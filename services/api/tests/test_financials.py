"""Unit tests for deterministic YoY verification (spec §9, §20)."""

from datetime import date

import pytest

from app.services.research.financials import (
    FactValue,
    calculate_yoy,
    is_quarterly,
    select_yoy_pair,
)

REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(
    value: float,
    start: str,
    end: str,
    *,
    concept: str = REV,
    fy: int | None = None,
    fp: str | None = None,
    form: str = "10-Q",
    filed: str | None = None,
) -> FactValue:
    return FactValue(
        concept=concept,
        unit="USD",
        value=value,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        form=form,
        fiscal_year=fy,
        fiscal_period=fp,
        accession=None,
        filed_date=date.fromisoformat(filed) if filed else None,
    )


class TestGrowthFormula:
    def test_basic_growth(self):
        assert calculate_yoy(120, 100) == 20.0

    def test_decline(self):
        assert calculate_yoy(80, 100) == -20.0

    def test_zero_previous_returns_none(self):
        assert calculate_yoy(50, 0) is None

    def test_negative_previous_uses_abs(self):
        # ((10 - -100) / 100) * 100 = 110
        assert calculate_yoy(10, -100) == pytest.approx(110.0)


class TestQuarterDetection:
    def test_quarterly_duration(self):
        assert is_quarterly(fact(1, "2025-01-01", "2025-03-31"))

    def test_annual_duration_rejected(self):
        assert not is_quarterly(fact(1, "2024-01-01", "2024-12-31"))

    def test_ytd_six_months_rejected(self):
        assert not is_quarterly(fact(1, "2025-01-01", "2025-06-30"))


class TestYoYPairSelection:
    def test_matches_same_quarter_one_year_earlier(self):
        facts = [
            fact(110, "2026-01-01", "2026-03-31", fy=2026, fp="Q1"),
            fact(100, "2025-01-01", "2025-03-31", fy=2025, fp="Q1"),
            fact(95, "2025-10-01", "2025-12-31", fy=2025, fp="Q4"),
        ]
        r = select_yoy_pair(facts, (REV,))
        assert r.status == "ok"
        assert r.growth_percent == 10.0
        assert r.current.end_date == date(2026, 3, 31)
        assert r.previous.end_date == date(2025, 3, 31)

    def test_missing_comparable_period_is_unknown(self):
        facts = [fact(110, "2026-01-01", "2026-03-31", fy=2026, fp="Q1")]
        r = select_yoy_pair(facts, (REV,))
        assert r.status == "unknown"
        assert r.growth_percent is None

    def test_zero_previous_is_unknown(self):
        facts = [
            fact(110, "2026-01-01", "2026-03-31", fp="Q1"),
            fact(0, "2025-01-01", "2025-03-31", fp="Q1"),
        ]
        r = select_yoy_pair(facts, (REV,))
        assert r.status == "unknown"

    def test_negative_previous_not_directly_comparable(self):
        ni = "us-gaap:NetIncomeLoss"
        facts = [
            fact(50, "2026-01-01", "2026-03-31", concept=ni, fp="Q1"),
            fact(-100, "2025-01-01", "2025-03-31", concept=ni, fp="Q1"),
        ]
        r = select_yoy_pair(facts, (ni,))
        assert r.status == "not_directly_comparable"
        assert r.growth_percent == 150.0

    def test_annualized_facts_never_selected(self):
        facts = [
            fact(400, "2025-01-01", "2025-12-31"),  # annual
            fact(420, "2026-01-01", "2026-12-31"),  # annual
        ]
        r = select_yoy_pair(facts, (REV,))
        assert r.status == "unknown"

    def test_restated_value_preferred(self):
        facts = [
            fact(110, "2026-01-01", "2026-03-31", fp="Q1", filed="2026-05-01"),
            fact(100, "2025-01-01", "2025-03-31", fp="Q1", filed="2025-05-01"),
            # restatement of the prior-year quarter filed later
            fact(105, "2025-01-01", "2025-03-31", fp="Q1", filed="2026-05-01"),
        ]
        r = select_yoy_pair(facts, (REV,))
        assert r.status == "ok"
        assert r.previous.value == 105

    def test_concept_fallback_to_revenues(self):
        facts = [
            fact(110, "2026-01-01", "2026-03-31", concept="us-gaap:Revenues", fp="Q1"),
            fact(100, "2025-01-01", "2025-03-31", concept="us-gaap:Revenues", fp="Q1"),
        ]
        r = select_yoy_pair(facts, (REV, "us-gaap:Revenues"))
        assert r.status == "ok"
        assert r.concept_used == "us-gaap:Revenues"
