"""Unit tests for bounded follow-up deep research."""

import json
from datetime import date

import httpx
import pytest

from app.models import Company
from app.schemas.search import Citation
from app.services.research.deep_research import (
    DeepResearchSynthesis,
    EvidenceClaim,
    EvidenceRecord,
    _format_report,
    _summarize_price_window,
    is_price_move_research_question,
    requested_lookback_days,
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


def test_exact_recent_window_and_price_move_question_are_detected():
    question = "In the past five days, what caused the decline in the stock price?"

    assert requested_lookback_days(question) == 5
    assert is_price_move_research_question(question)
    assert requested_lookback_days("Why has it fallen over the past few days?") == 7


def test_price_window_summary_confirms_observed_move(monkeypatch):
    monkeypatch.setattr("app.services.research.deep_research.date", _FixedDate)
    history = {
        "currency": "INR",
        "source_url": "https://example.com/history",
        "retrieved_at": "2026-08-13T10:00:00Z",
        "is_delayed_or_unverified": True,
        "candles": [
            {"time": "2026-08-07", "close": 110, "volume": 90},
            {"time": "2026-08-10", "close": 108, "volume": 100},
            {"time": "2026-08-11", "close": 104, "volume": 120},
            {"time": "2026-08-12", "close": 103, "volume": 110},
            {"time": "2026-08-13", "close": 100, "volume": 150},
        ],
    }

    result = _summarize_price_window(history, 5)

    assert result is not None
    text, citation = result
    payload = json.loads(text)
    assert payload["requested_calendar_window"]["start"] == "2026-08-08"
    assert payload["available_trading_window"]["trading_sessions"] == 4
    assert payload["observed_direction"] == "decline"
    assert payload["available_trading_window"]["reference_close_date"] == "2026-08-07"
    assert payload["observed_change_percent"] == pytest.approx(-9.0909)
    assert citation.source_type == "market_data"


class _FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 8, 13)

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


def test_price_move_report_always_states_measured_move_and_attaches_source():
    company = Company(
        ticker="TEST",
        name="Test Limited",
        cik="0000000001",
        exchange="NSE",
        sector="Industrials",
        industry="Machinery",
    )
    price_payload = {
        "observed_change_percent": -9.0909,
        "available_trading_window": {
            "reference_close_date": "2026-08-07",
            "first_session": "2026-08-10",
            "last_session": "2026-08-13",
            "trading_sessions": 4,
        },
    }
    evidence = [
        EvidenceRecord(
            index=1,
            source_type="market_data",
            title="Observed share-price move over the requested 5-day window",
            text=json.dumps(price_payload),
            citation=Citation(
                source_type="market_data",
                url="https://example.com/history",
                description="Historical closes",
            ),
        )
    ]
    synthesis = DeepResearchSynthesis(
        direction="unclear",
        magnitude="unclear",
        confidence="low",
        executive_summary="No single cause was established.",
        impact_mechanisms=[],
        counterevidence=[],
        watch_items=[],
        evidence_boundary="Price data was available, but causal evidence was limited.",
    )

    answer, citations = _format_report(
        company,
        "What caused the stock-price decline over the past five days?",
        synthesis,
        evidence,
    )

    assert "Observed move: -9.09%" in answer
    assert "[1]" in answer
    assert [citation.url for citation in citations] == ["https://example.com/history"]
