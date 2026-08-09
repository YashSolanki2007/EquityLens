"""Unit tests for bounded follow-up deep research."""

import json
from datetime import date

import httpx

from app.models import Company
from app.schemas.search import Citation
from app.services.research.deep_research import (
    DeepResearchSynthesis,
    EvidenceClaim,
    EvidenceRecord,
    _format_report,
    resolve_target_tickers,
)
from app.services.research.news import TavilyNewsClient, parse_tavily_results


class TestTargetResolution:
    def test_explicit_ticker_wins(self):
        assert resolve_target_tickers(
            "Could DELL be affected?",
            ["DELL"],
            ["VRT", "DELL", "HPE"],
            max_companies=3,
        ) == ["DELL"]

    def test_hallucinated_explicit_ticker_does_not_override_ordinal(self):
        assert resolve_target_tickers(
            "Could the first result be affected?",
            ["VRTX", "DELL"],
            ["VRT", "DELL", "HPE"],
            max_companies=3,
        ) == ["VRT"]

    def test_ordinal_result_reference(self):
        assert resolve_target_tickers(
            "Deep research the second result.",
            [],
            ["VRT", "DELL", "HPE"],
            max_companies=3,
        ) == ["DELL"]

    def test_last_company_reference(self):
        assert resolve_target_tickers(
            "Could the last company be insulated?",
            [],
            ["VRT", "DELL", "HPE"],
            max_companies=3,
        ) == ["HPE"]

    def test_unresolved_defaults_to_top_result(self):
        assert resolve_target_tickers(
            "How would this geopolitical development affect the company?",
            [],
            ["VRT", "DELL"],
            max_companies=3,
        ) == ["VRT"]


def test_tavily_results_are_bounded_and_normalized():
    sources = parse_tavily_results(
        {
            "results": [
                {
                    "title": "Recent supply-chain development",
                    "url": "https://example.com/story",
                    "content": "A source-backed excerpt.",
                    "published_date": "2026-07-18T10:00:00Z",
                    "score": 0.9,
                },
                {
                    "title": "Unsafe URL",
                    "url": "file:///etc/passwd",
                    "content": "must be rejected",
                },
                {
                    "title": "RFC-dated report",
                    "url": "https://example.com/rfc-date",
                    "content": "Another source-backed excerpt.",
                    "published_date": "Fri, 17 Jul 2026 21:30:57 GMT",
                },
                {"title": "No content", "url": "https://example.com/empty"},
            ]
        }
    )
    assert len(sources) == 2
    assert sources[0].published_date == date(2026, 7, 18)
    assert sources[0].excerpt == "A source-backed excerpt."
    assert sources[0].search_excerpt == "A source-backed excerpt."
    assert sources[1].published_date == date(2026, 7, 17)


async def test_tavily_search_accepts_numeric_cache_dimensions():
    request_payload = {}

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Current report",
                        "url": "https://example.com/report",
                        "content": "Current source text.",
                        "score": 0.8,
                    }
                ]
            },
        )

    class EmptyCache:
        def get(self, *_args):
            return None

        def put(self, *_args, **_kwargs):
            return None

    client = TavilyNewsClient(api_key="test-key", base_url="https://api.example")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="https://api.example",
        transport=httpx.MockTransport(handler),
    )
    client._cache = EmptyCache()
    try:
        rows = await client.search("current event", lookback_days=30, max_results=3)
    finally:
        await client.aclose()

    assert len(rows) == 1
    assert request_payload["max_results"] == 3
    assert request_payload["topic"] == "news"


def test_evidence_claim_accepts_common_small_model_field_alias():
    claim = EvidenceClaim.model_validate(
        {"mechanism": "Higher component costs could compress margins.", "evidence_indices": [2]}
    )
    assert claim.statement == "Higher component costs could compress margins."


def test_report_only_returns_citations_used_by_synthesis():
    company = Company(
        ticker="VRT",
        name="Vertiv",
        cik="0000000001",
        exchange="NYSE",
        sector="Industrials",
        industry="Electrical Equipment",
    )
    evidence = [
        EvidenceRecord(
            index=1,
            source_type="news",
            title="Used source",
            text="Used evidence",
            citation=Citation(
                source_type="news",
                url="https://example.com/used",
                description="Used source",
            ),
        ),
        EvidenceRecord(
            index=2,
            source_type="news",
            title="Unused source",
            text="Unused evidence",
            citation=Citation(
                source_type="news",
                url="https://example.com/unused",
                description="Unused source",
            ),
        ),
    ]
    synthesis = DeepResearchSynthesis(
        direction="negative",
        magnitude="marginal",
        confidence="medium",
        executive_summary="A bounded impact is plausible.",
        impact_mechanisms=[
            EvidenceClaim(statement="Input costs could rise.", evidence_indices=[1, 99])
        ],
        counterevidence=[],
        watch_items=["Supplier lead times"],
        evidence_boundary="Based on current-news evidence.",
    )

    answer, citations = _format_report(company, "Could shortages matter?", synthesis, evidence)

    assert "Input costs could rise. [1]" in answer
    assert "[99]" not in answer
    assert [citation.url for citation in citations] == ["https://example.com/used"]
