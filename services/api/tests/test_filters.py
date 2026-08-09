"""Unit tests for structured filtering (spec §20: market-cap 'around' tolerance)."""

from app.schemas.search import StructuredCondition
from app.services.ranking.filters import (
    CompanyFilterInput,
    apply_structured_filters,
    market_cap_bounds,
)


def company(market_cap=3_000_000_000.0, sector="Information Technology", ticker="TST"):
    return CompanyFilterInput(
        ticker=ticker,
        sector=sector,
        industry="Data Center Equipment",
        market_cap_usd=market_cap,
        market_cap_native=market_cap,
    )


class TestMarketCapBounds:
    def test_around_default_tolerance(self):
        import pytest

        c = StructuredCondition(field="market_cap_usd", operator="around", value=3e9)
        low, high = market_cap_bounds(c)
        assert low == pytest.approx(3e9 * 0.6) and high == pytest.approx(3e9 * 1.4)

    def test_around_custom_tolerance(self):
        c = StructuredCondition(
            field="market_cap_usd", operator="around", value=1e9, tolerance_percent=70
        )
        low, high = market_cap_bounds(c)
        assert low == 3e8 and high == 1.7e9

    def test_between(self):
        c = StructuredCondition(field="market_cap_usd", operator="between", value=[1e9, 5e9])
        assert market_cap_bounds(c) == (1e9, 5e9)

    def test_gte(self):
        c = StructuredCondition(field="market_cap_usd", operator="gte", value=1e10)
        assert market_cap_bounds(c) == (1e10, None)


class TestApplyFilters:
    def test_market_cap_pass_and_fail(self):
        cond = StructuredCondition(field="market_cap_usd", operator="around", value=3e9)
        keep, results = apply_structured_filters(company(3.5e9), [cond])
        assert keep and results[0].status == "pass"
        keep, results = apply_structured_filters(company(10e9), [cond])
        assert not keep and results[0].status == "fail"

    def test_missing_market_data_is_not_verified_but_kept(self):
        cond = StructuredCondition(field="market_cap_usd", operator="around", value=3e9)
        keep, results = apply_structured_filters(company(None), [cond])
        assert keep
        assert results[0].status == "not_verified"

    def test_native_inr_market_cap_is_compared_without_usd_conversion(self):
        cond = StructuredCondition(
            field="market_cap_native",
            operator="gte",
            value=3_000_000_000_000,
        )
        keep, results = apply_structured_filters(
            company(3_500_000_000_000),
            [cond],
        )
        assert keep and results[0].status == "pass"
        assert "market_cap_inr=3500000000000" in results[0].detail

    def test_optional_condition_failure_keeps_company(self):
        cond = StructuredCondition(field="sector", operator="eq", value="Energy", required=False)
        keep, results = apply_structured_filters(company(), [cond])
        assert keep and results[0].status == "fail"

    def test_sector_substring_match(self):
        cond = StructuredCondition(field="sector", operator="eq", value="technology")
        keep, results = apply_structured_filters(company(), [cond])
        assert keep and results[0].status == "pass"

    def test_ticker_in(self):
        cond = StructuredCondition(field="ticker", operator="in", value=["TST", "OTH"])
        keep, _ = apply_structured_filters(company(), [cond])
        assert keep
