"""Regression coverage for the bounded multi-timeframe technical scanner."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.schemas.technical import IntradayTechnicalSnapshot, TechnicalScanRequest
from app.services.technical_scanner import (
    CANDLE_INTERVALS,
    _evaluate_option_conditions,
    _fallback_conditions,
    _fallback_semantic_concept,
    _fallback_sort,
    _history_lookback_days,
    _normalize_business_concept,
    calculate_technical_snapshot,
    plan_technical_scan,
    run_technical_scan,
)

from .conftest import FakeProvider


def _company():
    return SimpleNamespace(
        id="test-company",
        ticker="TEST",
        name="Test Industries",
        sector="Industrials",
        industry="Electrical Equipment",
        market_data_ticker="TEST.NS",
    )


class _FailIfCalledCandleFetcher:
    source_name = "must not run"

    def __init__(self):
        self.calls = 0

    async def fetch(self, company, interval, limit):
        self.calls += 1
        raise AssertionError("option-only scans must not retrieve candles")


class _SingleCompanyDb:
    async def execute(self, statement):
        companies = SimpleNamespace(all=lambda: [_company()])
        return SimpleNamespace(scalars=lambda: companies)


def _rising_candles(count: int = 90) -> list[dict]:
    start = datetime(2026, 7, 20, 9, 15, tzinfo=UTC)
    candles = []
    for index in range(count):
        close = 100 + index * 0.2
        candles.append(
            {
                "time": (start + timedelta(minutes=index)).isoformat(),
                "open": close - 0.08,
                "high": close + 0.15,
                "low": close - 0.15,
                "close": close,
                "volume": 1_000 + index * 10,
            }
        )
    return candles


def test_indicator_engine_caps_input_and_calculates_vectorized_signals():
    payload = calculate_technical_snapshot(
        _company(), _rising_candles(), "yfinance development fallback"
    )
    snapshot = IntradayTechnicalSnapshot.model_validate(payload)

    assert snapshot.candles_used == 70
    assert snapshot.rsi_14 == 100
    assert snapshot.macd_histogram > 0
    assert snapshot.price_vs_vwap_percent > 0
    assert snapshot.ema_9_vs_ema_21_percent > 0
    assert snapshot.return_5c_percent > 0
    assert snapshot.return_15c_percent > snapshot.return_5c_percent
    assert snapshot.return_60c_percent > snapshot.return_15c_percent
    assert snapshot.atr_percent > 0


def test_indicator_engine_honors_selected_interval_and_count():
    payload = calculate_technical_snapshot(
        _company(),
        _rising_candles(),
        "Upstox V3",
        interval="1d",
        limit=42,
    )
    snapshot = IntradayTechnicalSnapshot.model_validate(payload)

    assert snapshot.candle_interval == "1d"
    assert snapshot.candles_used == 42


def test_scan_request_bounds_candle_selection():
    request = TechnicalScanRequest(
        query="NSE stocks above VWAP",
        candle_interval="15m",
        candle_count=55,
    )
    assert request.candle_interval == "15m"
    assert request.candle_count == 55

    with pytest.raises(ValidationError):
        TechnicalScanRequest(query="NSE stocks above VWAP", candle_count=71)


def test_daily_interval_requests_a_longer_history_window():
    assert _history_lookback_days(CANDLE_INTERVALS["1d"], 70) > 90
    assert _history_lookback_days(CANDLE_INTERVALS["1m"], 70) == 7


def test_deterministic_parser_understands_common_scanner_language():
    conditions = _fallback_conditions(
        "Oversold NSE stocks with bullish MACD, above VWAP and volume spike above 1.8x"
    )
    triples = {(condition.indicator, condition.operator, condition.value) for condition in conditions}

    assert ("rsi_14", "lt", 30.0) in triples
    assert ("macd_histogram", "gt", 0.0) in triples
    assert ("price_vs_vwap_percent", "gt", 0.0) in triples
    assert ("relative_volume", "gte", 1.8) in triples


def test_deterministic_parser_understands_option_chain_language():
    conditions = _fallback_conditions(
        "F&O stocks with call OI change above 10%, PCR above 1.2 "
        "and put delta around -0.30"
    )
    by_indicator = {condition.indicator: condition for condition in conditions}

    assert by_indicator["call_oi_change_percent"].operator == "gt"
    assert by_indicator["call_oi_change_percent"].value == 10
    assert by_indicator["put_call_oi_ratio"].value == 1.2
    assert by_indicator["put_delta"].operator == "between"
    assert by_indicator["put_delta"].value == pytest.approx([0.25, 0.35])


def test_ranking_language_is_not_misclassified_as_business_context():
    query = "companies with the greatest call Open interest positive change"
    conditions = _fallback_conditions(query)

    assert _fallback_semantic_concept(query) is None
    assert _fallback_sort(query) == ("call_oi_change_percent", "desc")
    assert len(conditions) == 1
    assert conditions[0].indicator == "call_oi_change_percent"
    assert conditions[0].operator == "gt"
    assert conditions[0].value == 0


def test_market_universe_words_are_not_business_concepts():
    query = "F&O stocks with call OI change above 10%, PCR above 1.2 and RSI below 45"

    assert _fallback_semantic_concept(query) is None
    assert _normalize_business_concept("F&O stocks") is None
    assert _normalize_business_concept("NSE-listed banking companies") == "banking"
    assert (
        _fallback_semantic_concept(
            "F&O banking stocks with call OI change above 10%"
        )
        == "banking"
    )


async def test_planner_removes_fno_from_business_filter():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "original_query": "ignored",
                    "semantic_concept": "F&O",
                    "conditions": [
                        {
                            "indicator": "call_oi_change_percent",
                            "operator": "gt",
                            "value": 10,
                            "required": True,
                        },
                        {
                            "indicator": "put_call_oi_ratio",
                            "operator": "gt",
                            "value": 1.2,
                            "required": True,
                        },
                        {
                            "indicator": "rsi_14",
                            "operator": "lt",
                            "value": 45,
                            "required": True,
                        },
                    ],
                    "sort_by": None,
                    "sort_direction": "desc",
                    "result_limit": 20,
                }
            )
        ]
    )
    plan = await plan_technical_scan(
        "F&O stocks with call OI change above 10%, PCR above 1.2 and RSI below 45",
        provider=provider,
    )

    assert plan.semantic_concept is None
    assert [condition.indicator for condition in plan.conditions] == [
        "call_oi_change_percent",
        "put_call_oi_ratio",
        "rsi_14",
    ]


async def test_planner_overrides_incorrect_ranking_business_concept():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "original_query": "ignored",
                    "semantic_concept": "companies with the greatest",
                    "conditions": [
                        {
                            "indicator": "put_oi_change_percent",
                            "operator": "gt",
                            "value": 0,
                            "required": True,
                        },
                        {
                            "indicator": "call_oi_change_percent",
                            "operator": "gt",
                            "value": 0,
                            "required": True,
                        }
                    ],
                    "sort_by": None,
                    "sort_direction": "desc",
                    "result_limit": 20,
                }
            )
        ]
    )
    plan = await plan_technical_scan(
        "companies with the greatest call Open interest positive change",
        provider=provider,
    )

    assert plan.semantic_concept is None
    assert plan.sort_by == "call_oi_change_percent"
    assert plan.sort_direction == "desc"
    assert [condition.indicator for condition in plan.conditions] == [
        "call_oi_change_percent"
    ]


async def test_option_only_scan_skips_candle_retrieval():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "original_query": "ignored",
                    "semantic_concept": None,
                    "conditions": [
                        {
                            "indicator": "call_oi_change_percent",
                            "operator": "gt",
                            "value": 0,
                            "required": True,
                        }
                    ],
                    "sort_by": "call_oi_change_percent",
                    "sort_direction": "desc",
                    "result_limit": 20,
                }
            )
        ]
    )
    candles = _FailIfCalledCandleFetcher()

    async def options_fetcher(ticker: str, symbol: str):
        return {
            "available": True,
            "selected_expiry": "28-Jul-2026",
            "underlying_value": 123.45,
            "retrieved_at": "2026-07-25T06:00:00+00:00",
            "source_url": "https://www.nseindia.com/option-chain?symbol=TEST",
            "scanner_summary": {
                "call_open_interest": 1000,
                "put_open_interest": 800,
                "call_oi_change_percent": 12.5,
                "put_oi_change_percent": 5,
                "put_call_oi_ratio": 0.8,
                "call_delta_contracts": [],
                "put_delta_contracts": [],
            },
        }

    response = await run_technical_scan(
        _SingleCompanyDb(),
        TechnicalScanRequest(
            query="companies with the greatest call open interest positive change"
        ),
        provider=provider,
        candle_fetcher=candles,
        options_fetcher=options_fetcher,
        fno_symbols={"TEST"},
    )

    assert candles.calls == 0
    assert response.candle_scan_skipped is True
    assert response.scanned == 0
    assert response.options_scanned == 1
    assert response.results[0].price == pytest.approx(123.45)
    assert response.results[0].rsi_14 is None


def test_option_conditions_use_full_chain_aggregates_and_matching_delta_strike():
    conditions = _fallback_conditions(
        "Call OI change above 10%, PCR above 1.2 and put delta between 0.25 and 0.35"
    )
    chain = {
        "available": True,
        "selected_expiry": "30-Jul-2026",
        "source_url": "https://www.nseindia.com/option-chain?symbol=TEST",
        "scanner_summary": {
            "call_open_interest": 1000,
            "put_open_interest": 1400,
            "call_oi_change_percent": 12.5,
            "put_oi_change_percent": 8.0,
            "put_call_oi_ratio": 1.4,
            "call_delta_contracts": [
                {"strike_price": 100, "delta": 0.51},
            ],
            "put_delta_contracts": [
                {"strike_price": 95, "delta": 0.22},
                {"strike_price": 100, "delta": 0.31},
            ],
        },
    }

    eligible, updates, matched, strengths = _evaluate_option_conditions(
        chain, conditions
    )

    assert eligible is True
    assert updates["put_delta"] == pytest.approx(0.31)
    assert updates["put_delta_strike"] == 100
    assert len(matched) == len(strengths) == 3


async def test_model_planner_separates_semantics_from_technical_conditions():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "original_query": "ignored by service",
                    "semantic_concept": "companies operating renewable power assets",
                    "conditions": [
                        {
                            "indicator": "rsi_14",
                            "operator": "lt",
                            "value": 35,
                            "required": True,
                        },
                        {
                            "indicator": "price_vs_vwap_percent",
                            "operator": "gt",
                            "value": 0,
                            "required": True,
                        },
                    ],
                    "result_limit": 20,
                }
            )
        ]
    )
    query = "Renewable power companies with RSI below 35 and price above VWAP"
    plan = await plan_technical_scan(query, provider=provider)

    assert plan.original_query == query
    assert plan.semantic_concept == "companies operating renewable power assets"
    assert [condition.indicator for condition in plan.conditions] == [
        "rsi_14",
        "price_vs_vwap_percent",
    ]


async def test_planner_deterministically_recovers_missed_business_prefix():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "original_query": "ignored",
                    "semantic_concept": None,
                    "conditions": [
                        {
                            "indicator": "rsi_14",
                            "operator": "lt",
                            "value": 35,
                            "required": True,
                        }
                    ],
                    "result_limit": 20,
                }
            )
        ]
    )
    plan = await plan_technical_scan(
        "Renewable power companies with RSI below 35", provider=provider
    )

    assert plan.semantic_concept == "Renewable power"
