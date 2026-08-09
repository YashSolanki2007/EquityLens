from datetime import date
from types import SimpleNamespace

import pytest

from app.api import companies as companies_api
from app.schemas.company import RevenueExplanation
from app.services.company_analysis import _clean_explanations
from app.services.company_financials import (
    build_financial_overview,
    build_financial_series,
)


def fact(
    concept: str,
    value: float,
    start: str,
    end: str,
    *,
    form: str,
    fiscal_year: int,
    fiscal_period: str,
    filed: str,
    accession: str,
):
    return SimpleNamespace(
        concept=f"us-gaap:{concept}",
        unit="USD",
        value=value,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        form=form,
        fiscal_year=fiscal_year,
        fiscal_period=fiscal_period,
        filed_date=date.fromisoformat(filed),
        accession=accession,
    )


class TestFinancialSeries:
    def test_annual_series_dedupes_restatements_and_calculates_yoy(self):
        facts = [
            fact(
                "Revenues",
                100,
                "2023-01-01",
                "2023-12-31",
                form="10-K",
                fiscal_year=2023,
                fiscal_period="FY",
                filed="2024-02-01",
                accession="old",
            ),
            fact(
                "Revenues",
                105,
                "2023-01-01",
                "2023-12-31",
                form="10-K",
                fiscal_year=2024,
                fiscal_period="FY",
                filed="2025-02-01",
                accession="restated",
            ),
            fact(
                "NetIncomeLoss",
                10,
                "2023-01-01",
                "2023-12-31",
                form="10-K",
                fiscal_year=2023,
                fiscal_period="FY",
                filed="2025-02-01",
                accession="restated",
            ),
            fact(
                "Revenues",
                126,
                "2024-01-01",
                "2024-12-31",
                form="10-K",
                fiscal_year=2024,
                fiscal_period="FY",
                filed="2025-02-01",
                accession="current",
            ),
            fact(
                "NetIncomeLoss",
                18,
                "2024-01-01",
                "2024-12-31",
                form="10-K",
                fiscal_year=2024,
                fiscal_period="FY",
                filed="2025-02-01",
                accession="current",
            ),
        ]

        series = build_financial_series(facts, "annual")

        assert len(series) == 2
        assert series[0].revenue == 105
        assert series[1].revenue_yoy_percent == 20
        assert series[1].net_margin_percent == 14.29
        assert series[0].period == "Year ended Dec 2023"

    def test_quarterly_series_rejects_ytd_values(self):
        facts = [
            fact(
                "Revenues",
                40,
                "2024-01-01",
                "2024-03-31",
                form="10-Q",
                fiscal_year=2024,
                fiscal_period="Q1",
                filed="2024-05-01",
                accession="q1-old",
            ),
            fact(
                "Revenues",
                50,
                "2025-01-01",
                "2025-03-31",
                form="10-Q",
                fiscal_year=2025,
                fiscal_period="Q1",
                filed="2025-05-01",
                accession="q1-new",
            ),
            fact(
                "Revenues",
                120,
                "2025-01-01",
                "2025-09-30",
                form="10-Q",
                fiscal_year=2025,
                fiscal_period="Q3",
                filed="2025-11-01",
                accession="ytd",
            ),
        ]

        series = build_financial_series(facts, "quarterly")

        assert len(series) == 2
        assert series[-1].revenue_yoy_percent == 25

    def test_overview_prefers_latest_quarter_for_headline(self):
        facts = [
            fact(
                "Revenues",
                100,
                "2024-01-01",
                "2024-12-31",
                form="10-K",
                fiscal_year=2024,
                fiscal_period="FY",
                filed="2025-02-01",
                accession="annual",
            ),
            fact(
                "Revenues",
                30,
                "2025-01-01",
                "2025-03-31",
                form="10-Q",
                fiscal_year=2025,
                fiscal_period="Q1",
                filed="2025-05-01",
                accession="quarter",
            ),
        ]

        overview = build_financial_overview("TEST", "123", facts)

        assert overview.headline is not None
        assert overview.headline.period == "Quarter ended Mar 2025"
        assert overview.source_url.endswith("CIK0000000123.json")


class TestAnalysisCleaning:
    def test_unsupported_catalyst_is_downgraded(self):
        overview = build_financial_overview(
            "TEST",
            "123",
            [
                fact(
                    "Revenues",
                    100,
                    "2024-01-01",
                    "2024-12-31",
                    form="10-K",
                    fiscal_year=2024,
                    fiscal_period="FY",
                    filed="2025-02-01",
                    accession="old",
                ),
                fact(
                    "Revenues",
                    120,
                    "2025-01-01",
                    "2025-12-31",
                    form="10-K",
                    fiscal_year=2025,
                    fiscal_period="FY",
                    filed="2026-02-01",
                    accession="new",
                ),
            ],
        )
        explanation = RevenueExplanation(
            movement_id="annual:2025-12-31",
            period="wrong",
            change_percent=999,
            driver_type="company_reported_catalyst",
            explanation="Unsupported claim",
            evidence_card_ids=["not-a-real-card"],
            confidence="high",
        )

        cleaned = _clean_explanations([explanation], overview, set())

        assert cleaned[0].driver_type == "unexplained"
        assert cleaned[0].change_percent == 20
        assert cleaned[0].confidence == "low"


@pytest.mark.asyncio
async def test_india_overview_backfills_missing_yahoo_facts(monkeypatch):
    company = SimpleNamespace(
        ticker="KAUSHALYA",
        cik="0000000000",
        id="company-id",
        country="IN",
        reporting_currency="INR",
        market_data_ticker="KAUSHALYA.NS",
    )
    empty = SimpleNamespace(annual=[], quarterly=[])
    populated = SimpleNamespace(annual=[SimpleNamespace(revenue=1)], quarterly=[])
    overview_results = iter((empty, populated))
    refresh_calls = []

    async def fake_get_company(db, ticker):
        return company

    async def fake_get_overview(db, **kwargs):
        return next(overview_results)

    async def fake_refresh(db, target):
        refresh_calls.append(target)
        return 2

    monkeypatch.setattr(companies_api, "_get_company", fake_get_company)
    monkeypatch.setattr(companies_api, "get_financial_overview", fake_get_overview)
    monkeypatch.setattr(companies_api, "refresh_india_financial_facts", fake_refresh)

    result = await companies_api.get_company_financial_overview("KAUSHALYA", db=object())

    assert result is populated
    assert refresh_calls == [company]
