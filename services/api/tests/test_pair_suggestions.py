from datetime import UTC, date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd

from app.schemas.pairs import PairSuggestion
from app.services.pair_suggestions import (
    FuturesContract,
    PAIR_FORMATION_DAYS,
    PairUniverseMember,
    _attach_futures_plans,
    _filter_cached_payload,
    _futures_contract_counts,
    benjamini_hochberg,
    scan_pair_matrix,
)
from app.services.live_futures import LiveFuturesQuote, futures_instrument_map
from app.services.paper_pair_trades import (
    build_pair_paper_entry,
    calculate_pair_mark,
    live_pair_trade_mark,
)


def _member(ticker: str, instrument_type: str = "stock") -> PairUniverseMember:
    return PairUniverseMember(
        ticker=ticker,
        name=f"{ticker} Limited",
        sector="Financial Services",
        market_data_ticker=f"{ticker}.NS",
        market_cap_native=(10_000_000_000 if instrument_type == "stock" else None),
        instrument_type=instrument_type,
    )


def test_benjamini_hochberg_returns_monotonic_adjusted_values():
    adjusted = benjamini_hochberg([0.01, 0.04, 0.03])

    assert adjusted.tolist() == [0.03, 0.04, 0.04]


def test_upstox_instrument_map_selects_exact_nse_future_and_expiry():
    rows = [
        {
            "segment": "NSE_FO",
            "instrument_type": "FUT",
            "underlying_symbol": "SHREECEM",
            "expiry": "2026-08-25",
            "instrument_key": "NSE_FO|58383",
        },
        {
            "segment": "NSE_EQ",
            "instrument_type": "EQ",
            "underlying_symbol": "SHREECEM",
            "instrument_key": "NSE_EQ|INE070A01015",
        },
    ]

    assert futures_instrument_map(rows) == {
        ("SHREECEM", date(2026, 8, 25)): "NSE_FO|58383"
    }


def test_live_pair_mark_uses_exact_futures_ltps_for_both_legs():
    expiry = date(2026, 8, 25)
    received_at = datetime(2026, 8, 4, 5, 30, tzinfo=UTC)
    trade = SimpleNamespace(
        long_ticker="SHREECEM",
        short_ticker="BAJAJHLDNG",
        expiry=expiry,
        entry_long_price=25_560,
        entry_short_price=11_406,
        long_units=75,
        short_units=150,
        entry_combined_notional=3_627_900,
    )
    quotes = {
        ("SHREECEM", expiry): LiveFuturesQuote(
            "SHREECEM", expiry, "NSE_FO|58383", 26_760, received_at
        ),
        ("BAJAJHLDNG", expiry): LiveFuturesQuote(
            "BAJAJHLDNG", expiry, "NSE_FO|58120", 11_450, received_at
        ),
    }

    mark, limitation = live_pair_trade_mark(trade, quotes)

    assert limitation is None
    assert mark is not None
    assert mark["long_price"] == 26_760
    assert mark["short_price"] == 11_450
    assert mark["long_pnl"] == 90_000
    assert mark["short_pnl"] == -6_600
    assert mark["is_live"] is True


def test_scan_pair_matrix_finds_cointegrated_pair_and_builds_chart():
    rng = np.random.default_rng(42)
    observations = 520
    dates = pd.bdate_range("2024-01-01", periods=observations)
    common_walk = 4.5 + np.cumsum(rng.normal(0, 0.008, observations))
    spread = np.zeros(observations)
    for index in range(1, observations):
        spread[index] = 0.72 * spread[index - 1] + rng.normal(0, 0.006)
    log_a = 0.35 + 1.08 * common_walk + spread
    unrelated = 4.2 + np.cumsum(rng.normal(0, 0.014, observations))
    closes = pd.DataFrame(
        {
            "AAA": np.exp(log_a),
            "BBB": np.exp(common_walk),
            "CCC": np.exp(unrelated),
        },
        index=dates,
    )
    volumes = pd.DataFrame(
        {
            "AAA": np.full(observations, 1_000_000),
            "BBB": np.full(observations, 1_200_000),
            "CCC": np.full(observations, 800_000),
        },
        index=dates,
    )

    (
        suggestions,
        pairs_tested,
        threshold_counts,
        price_eligible,
    ) = scan_pair_matrix(
        [_member("AAA"), _member("BBB"), _member("CCC")],
        closes,
        volumes,
    )

    assert pairs_tested == 3
    assert price_eligible == 3
    standard_counts = next(item for item in threshold_counts if item["threshold"] == 0.05)
    assert standard_counts["p_significant_pairs"] >= 1
    assert suggestions
    expected = next(item for item in suggestions if item.pair_id == "AAA-BBB")
    assert expected.observations == PAIR_FORMATION_DAYS == 250
    assert len(expected.chart) == 126
    assert expected.stock_a_market_cap_crore == 1000
    assert expected.example_long_quantity >= 1
    assert expected.example_short_quantity >= 1
    assert expected.example_long_value_inr > 0
    assert expected.example_short_value_inr > 0
    assert expected.example_target_long_price > 0
    assert expected.example_target_short_price > 0
    assert expected.example_gross_return_percent >= 0

    expiry = date(2027, 1, 26)
    enriched = _attach_futures_plans(
        [expected],
        {
            "AAA": [
                FuturesContract(
                    ticker="AAA",
                    contract_name="AAA27JANFUT",
                    expiry=expiry,
                    price=100,
                    lot_size=500,
                    traded_volume=100,
                )
            ],
            "BBB": [
                FuturesContract(
                    ticker="BBB",
                    contract_name="BBB27JANFUT",
                    expiry=expiry,
                    price=90,
                    lot_size=500,
                    traded_volume=100,
                )
            ],
        },
        date(2026, 7, 30),
    )[0]

    assert enriched.futures_plan_available is True
    assert enriched.futures_expiry == expiry.isoformat()
    assert enriched.long_futures_contracts is not None
    assert enriched.short_futures_contracts is not None
    assert enriched.long_futures_notional_inr is not None
    assert enriched.short_futures_notional_inr is not None
    assert enriched.example_gross_return_percent >= 0


def test_futures_contract_counts_prefers_small_acceptable_whole_lot_plan():
    contracts_a, contracts_b, fit = _futures_contract_counts(
        hedge_ratio=0.42,
        stock_a_contract_notional=532_000,
        stock_b_contract_notional=603_000,
    )

    assert (contracts_a, contracts_b) == (3, 1)
    assert fit >= 85


def test_cached_results_are_selected_by_raw_p_value_while_q_remains_in_payload():
    payload = {
        "threshold_counts": [
            {"threshold": 0.05, "p_significant_pairs": 1},
        ],
        "results": [
            {
                "pair_id": "LOW-P-HIGH-Q",
                "cointegration_p_value": 0.001,
                "fdr_q_value": 0.73,
            },
            {
                "pair_id": "HIGH-P-LOW-Q",
                "cointegration_p_value": 0.08,
                "fdr_q_value": 0.04,
            },
        ],
    }

    filtered = _filter_cached_payload(
        payload,
        p_value_threshold=0.05,
        limit=12,
        cached=True,
    )

    assert filtered["p_value_threshold"] == 0.05
    assert filtered["p_significant_pairs"] == 1
    assert [result["pair_id"] for result in filtered["results"]] == [
        "LOW-P-HIGH-Q"
    ]
    assert filtered["results"][0]["fdr_q_value"] == 0.73


def test_cached_results_rank_trade_opportunity_after_q_value_filter():
    payload = {
        "threshold_counts": [
            {"threshold": 0.05, "p_significant_pairs": 3},
        ],
        "results": [
            {
                "pair_id": "LOWEST-Q-WATCH",
                "signal": "watch",
                "current_zscore": 0.3,
                "half_life_days": 4,
                "return_correlation": 0.9,
                "cointegration_p_value": 0.001,
                "fdr_q_value": 0.001,
            },
            {
                "pair_id": "SMALLER-ACTIVE-GAP",
                "signal": "long_a_short_b",
                "current_zscore": -1.7,
                "half_life_days": 5,
                "return_correlation": 0.8,
                "cointegration_p_value": 0.002,
                "fdr_q_value": 0.002,
            },
            {
                "pair_id": "LARGER-ACTIVE-GAP",
                "signal": "short_a_long_b",
                "current_zscore": 2.4,
                "half_life_days": 12,
                "return_correlation": 0.7,
                "cointegration_p_value": 0.04,
                "fdr_q_value": 0.04,
            },
        ],
    }

    filtered = _filter_cached_payload(
        payload,
        p_value_threshold=0.05,
        limit=3,
        cached=True,
    )

    assert [result["pair_id"] for result in filtered["results"]] == [
        "LARGER-ACTIVE-GAP",
        "SMALLER-ACTIVE-GAP",
        "LOWEST-Q-WATCH",
    ]


def test_nearest_common_futures_expiry_is_used_and_rollover_is_flagged():
    suggestion = PairSuggestion.model_construct(
        pair_id="AAA-BBB",
        stock_a="AAA",
        stock_b="BBB",
        signal="long_a_short_b",
        long_ticker="AAA",
        short_ticker="BBB",
        hedge_ratio=0.42,
        half_life_days=12,
        example_long_price=100,
        example_short_price=90,
        example_target_long_price=104,
        example_target_short_price=88,
        current_zscore=-2.2,
        fdr_q_value=0.03,
    )
    nearest = date(2026, 8, 6)
    farther = date(2026, 9, 24)
    contracts = {
        ticker: [
            FuturesContract(
                ticker=ticker,
                contract_name=f"{ticker}26AUGFUT",
                expiry=nearest,
                price=price,
                lot_size=500,
                traded_volume=100,
            ),
            FuturesContract(
                ticker=ticker,
                contract_name=f"{ticker}26SEPFUT",
                expiry=farther,
                price=price + 1,
                lot_size=500,
                traded_volume=100,
            ),
        ]
        for ticker, price in (("AAA", 100), ("BBB", 90))
    }

    enriched = _attach_futures_plans(
        [suggestion],
        contracts,
        date(2026, 7, 30),
    )[0]

    assert enriched.futures_expiry == nearest.isoformat()
    assert enriched.futures_requires_rollover is True
    assert "nearest common" in str(enriched.futures_plan_note).lower()


def test_pair_paper_entry_and_mark_use_whole_contract_units():
    suggestion = PairSuggestion.model_construct(
        pair_id="AAA-BBB",
        stock_a="AAA",
        stock_b="BBB",
        signal="long_a_short_b",
        long_ticker="AAA",
        short_ticker="BBB",
        hedge_ratio=0.42,
        half_life_days=5,
        estimated_reversion_date="2026-08-05",
        current_zscore=-2.4,
        fdr_q_value=0.02,
    )
    expiry = date(2026, 8, 27)
    contracts = {
        "AAA": [
            FuturesContract("AAA", "AAA26AUGFUT", expiry, 100, 500, 100)
        ],
        "BBB": [
            FuturesContract("BBB", "BBB26AUGFUT", expiry, 90, 500, 100)
        ],
    }

    entry, limitation = build_pair_paper_entry(
        suggestion,
        contracts,
        date(2026, 7, 31),
    )

    assert limitation is None
    assert entry is not None
    assert entry["long_contracts"] >= 1
    assert entry["short_contracts"] >= 1
    assert entry["long_units"] == entry["long_contracts"] * 500
    mark = calculate_pair_mark(
        entry_long_price=entry["entry_long_price"],
        entry_short_price=entry["entry_short_price"],
        long_units=entry["long_units"],
        short_units=entry["short_units"],
        entry_combined_notional=entry["entry_combined_notional"],
        long_price=104,
        short_price=88,
        price_date=date(2026, 8, 1),
    )

    assert mark["long_pnl"] > 0
    assert mark["short_pnl"] > 0
    assert mark["total_pnl"] == mark["long_pnl"] + mark["short_pnl"]
    assert mark["return_percent"] > 0
