from types import SimpleNamespace

import pytest

from app.api import companies as companies_api
from app.services.company_peers import (
    METRIC_DEFINITIONS,
    _business_label,
    _favourability_percentiles,
    _rank_candidates,
)


def _company(identifier: str, ticker: str, *, industry: str = "Unclassified"):
    return SimpleNamespace(
        id=identifier,
        ticker=ticker,
        name=f"{ticker} Limited",
        country="IN",
        sector="Unclassified",
        industry=industry,
    )


def test_peer_ranking_balances_business_similarity_and_company_scale():
    target = _company("target", "TARGET")
    close_size = _company("close", "CLOSE")
    huge = _company("huge", "HUGE")
    candidates = [
        {"company": close_size, "similarity": 0.82, "matched_text": "construction"},
        {"company": huge, "similarity": 0.90, "matched_text": "construction"},
    ]

    ranked = _rank_candidates(
        target,
        candidates,
        {"target": 100, "close": 110, "huge": 100_000},
        2,
    )

    assert [item["company"].ticker for item in ranked] == ["CLOSE", "HUGE"]
    assert "comparable reported revenue" in ranked[0]["selection_reason"]


def test_favourability_percentiles_respect_metric_direction():
    def comparison_company(pe: float, growth: float):
        metrics = {definition["key"]: None for definition in METRIC_DEFINITIONS}
        metrics["trailing_pe"] = pe
        metrics["revenue_growth_percent"] = growth
        return {"metrics": metrics, "percentiles": {}}

    companies = [
        comparison_company(10, 5),
        comparison_company(20, 10),
        comparison_company(30, 20),
    ]

    _favourability_percentiles(companies)

    assert companies[0]["percentiles"]["trailing_pe"] == 100
    assert companies[0]["percentiles"]["revenue_growth_percent"] == 0
    assert companies[1]["percentiles"]["trailing_pe"] == 50


def test_non_positive_valuation_multiples_are_not_ranked_as_favourable():
    def comparison_company(pe: float):
        metrics = {definition["key"]: None for definition in METRIC_DEFINITIONS}
        metrics["trailing_pe"] = pe
        return {"metrics": metrics, "percentiles": {}}

    companies = [
        comparison_company(-2),
        comparison_company(10),
        comparison_company(20),
        comparison_company(30),
    ]

    _favourability_percentiles(companies)

    assert companies[0]["percentiles"]["trailing_pe"] is None
    assert companies[1]["percentiles"]["trailing_pe"] == 100


def test_business_label_can_describe_multi_segment_company():
    label = _business_label(
        [
            "The company is engaged in infrastructure construction contracts.",
            "The company also operates a hotel.",
        ]
    )

    assert label == "Infrastructure & construction / Hotels & hospitality"


@pytest.mark.asyncio
async def test_peer_endpoint_distinguishes_automatic_and_empty_manual_selection(monkeypatch):
    company = _company("target", "TARGET")
    company.market_data_ticker = "TARGET.NS"
    captured = []

    async def fake_get_company(db, ticker):
        return company

    async def fake_build(db, target, **kwargs):
        captured.append(kwargs["peer_symbols"])
        return {"ticker": target.ticker}

    monkeypatch.setattr(companies_api, "_get_company", fake_get_company)
    monkeypatch.setattr(companies_api, "build_peer_comparison", fake_build)

    await companies_api.get_company_peer_comparison("TARGET", symbols=None, db=object())
    await companies_api.get_company_peer_comparison("TARGET", symbols="", db=object())

    assert captured == [None, []]
