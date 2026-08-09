"""Unit tests: citation serialization, cache invalidation, filing parsing (spec §20)."""

import time
from datetime import date

from app.core.cache import FileCache, cache_key
from app.schemas.search import Citation
from app.services.sec.facts import extract_facts
from app.services.sec.parser import chunk_text, extract_10k_business_sections, html_to_text


class TestCitationSerialization:
    def test_round_trip(self):
        c = Citation(
            source_type="sec_filing",
            url="https://www.sec.gov/Archives/edgar/data/1/doc.htm",
            accession="0000000000-26-000001",
            description="10-K filed 2026-02-01",
            excerpt="The company operates data centers.",
            filing_date=date(2026, 2, 1),
        )
        data = c.model_dump(mode="json")
        assert data["filing_date"] == "2026-02-01"
        restored = Citation.model_validate(data)
        assert restored == c

    def test_defaults(self):
        c = Citation(url="https://data.sec.gov/x.json", source_type="sec_xbrl")
        assert c.accession is None and c.excerpt is None


class TestFileCache:
    def test_put_get_and_metadata(self, tmp_path):
        cache = FileCache(tmp_path, "test")
        cache.put("k", {"a": 1}, source="unit-test", model_name="m", prompt_version="v1")
        assert cache.get("k", ttl_seconds=None) == {"a": 1}
        wrapper = cache.get_wrapper("k", ttl_seconds=None)
        assert wrapper["source"] == "unit-test"
        assert wrapper["model_name"] == "m"
        assert "retrieved_at" in wrapper and "data_version" in wrapper

    def test_ttl_expiry(self, tmp_path, monkeypatch):
        cache = FileCache(tmp_path, "test")
        cache.put("k", 1, source="s")
        assert cache.get("k", ttl_seconds=3600) == 1
        future = time.time() + 7200
        monkeypatch.setattr("app.core.cache.time.time", lambda: future)
        assert cache.get("k", ttl_seconds=3600) is None

    def test_invalidate(self, tmp_path):
        cache = FileCache(tmp_path, "test")
        cache.put("k", 1, source="s")
        cache.invalidate("k")
        assert cache.get("k", ttl_seconds=None) is None

    def test_key_stability(self):
        assert cache_key("a", "b") == cache_key("a", "b")
        assert cache_key("a", "b") != cache_key("a", "c")


SAMPLE_10K = """
<html><head><script>alert('x')</script></head><body>
<p>TABLE OF CONTENTS</p>
<p>Item 1. Business</p>
<p>Item 1A. Risk Factors</p>
<p>Item 1. Business</p>
<p>{business}</p>
<p>Item 1A. Risk Factors</p>
<p>{risk}</p>
<p>Item 2. Properties</p>
<p>{properties}</p>
</body></html>
""".format(
    business="We operate interconnected data centers worldwide. " * 20,
    risk="Our business faces risks from power costs. " * 20,
    properties="We own facilities in 30 metropolitan areas. " * 20,
)


class TestFilingParser:
    def test_scripts_stripped(self):
        text = html_to_text(SAMPLE_10K)
        assert "alert" not in text

    def test_section_extraction_skips_toc(self):
        sections = extract_10k_business_sections(html_to_text(SAMPLE_10K))
        assert "Item 1 - Business" in sections
        assert "data centers" in sections["Item 1 - Business"]
        assert "Item 2 - Properties" in sections

    def test_chunking_bounds(self):
        chunks = chunk_text("word " * 5000, target_chars=1000, overlap_chars=100)
        assert all(len(c) <= 1200 for c in chunks)
        assert len(chunks) > 3

    def test_combined_item_headings(self):
        # FCX-style: "Items 1. and 2." keyed under item 1.
        html = "<html><body><p>Items 1. and 2. Business and Properties</p><p>{b}</p><p>Item 1A. Risk Factors</p><p>{r}</p></body></html>".format(
            b="We mine copper in the Americas and Indonesia. " * 20,
            r="Commodity prices fluctuate. " * 20,
        )
        sections = extract_10k_business_sections(html_to_text(html))
        assert "Item 1 - Business" in sections
        assert "copper" in sections["Item 1 - Business"]

    def test_late_cross_reference_does_not_steal_section(self):
        # CVX-style: a line-start cross-reference to "Item 1." late in the filing
        # must not displace the real Item 1 body (largest-body occurrence wins).
        html = "<html><body><p>Item 1. Business</p><p>{b}</p><p>Item 1A. Risk Factors</p><p>{r}</p><p>Item 1. through Item 4. are incorporated by reference.</p><p>signatures</p></body></html>".format(
            b="We produce crude oil and natural gas. " * 30,
            r="Oil prices are volatile. " * 30,
        )
        sections = extract_10k_business_sections(html_to_text(html))
        assert "crude oil" in sections.get("Item 1 - Business", "")


class TestXbrlExtraction:
    def test_usd_quarterly_facts_extracted(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {
                                    "start": "2026-01-01",
                                    "end": "2026-03-31",
                                    "val": 100,
                                    "fy": 2026,
                                    "fp": "Q1",
                                    "form": "10-Q",
                                    "accn": "acc-1",
                                    "filed": "2026-05-01",
                                }
                            ],
                            "EUR": [{"start": "2026-01-01", "end": "2026-03-31", "val": 90}],
                        }
                    }
                }
            }
        }
        facts = extract_facts(payload)
        assert len(facts) == 1
        assert facts[0]["concept"] == "us-gaap:Revenues"
        assert facts[0]["unit"] == "USD"

    def test_missing_concepts_ignored(self):
        assert extract_facts({"facts": {"us-gaap": {}}}) == []
