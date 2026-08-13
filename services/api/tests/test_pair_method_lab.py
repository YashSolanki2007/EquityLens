from datetime import date

import numpy as np
import pandas as pd

from app.schemas.pair_method_lab import PairMethodLabCandidate
from app.services.pair_method_lab import (
    KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL,
    adaptive_lookback_days,
    attach_futures_capital_plans,
    kss_test,
    potential_convergence_return_percent,
    scan_paper_method_matrix,
    tracker_entry_diagnostics,
)
from app.services.pair_suggestions import FuturesContract, PairUniverseMember


def _member(ticker: str) -> PairUniverseMember:
    return PairUniverseMember(
        ticker=ticker,
        name=f"{ticker} Limited",
        sector="Test sector",
        market_data_ticker=f"{ticker}.NS",
        market_cap_native=10_000_000_000,
    )


def test_adaptive_lookback_uses_paper_half_life_conversion():
    # N = 2 / (ln(2) / 10) - 1 = 27.85, rounded to 28.
    assert adaptive_lookback_days(10, available=252) == 28


def test_kss_uses_calibrated_point_zero_one_percent_residual_cutoff():
    assert KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL == -5.04


def test_potential_convergence_return_uses_both_legs_gross_notional():
    result = potential_convergence_return_percent(
        spread_gap=-6,
        beta=0.5,
        price_a=100,
        price_b=40,
    )

    assert result == 5.0


def test_tracker_direct_entry_uses_current_absolute_zscore() -> None:
    result = tracker_entry_diagnostics(
        engle_granger_pass=True,
        kss_pass=True,
        fdr_q_value=0.02,
        current_zscore=-1.7,
        potential_convergence_return_percent=2.0,
        zscore_history=[-1.2, -1.5, -1.7],
    )

    assert result["entry_type"] == "direct"
    assert result["recent_peak_abs_zscore"] == 1.7


def test_tracker_confirmed_entry_requires_recent_same_sign_contraction() -> None:
    result = tracker_entry_diagnostics(
        engle_granger_pass=True,
        kss_pass=True,
        fdr_q_value=0.02,
        current_zscore=1.0,
        potential_convergence_return_percent=2.0,
        zscore_history=[2.0, 1.8, 1.5, 1.2, 1.0],
    )

    assert result["entry_type"] == "confirmed_convergence"
    assert result["recent_peak_abs_zscore"] == 2.0
    assert result["remaining_return_percent"] == 1.6


def test_tracker_confirmed_entry_rejects_insufficient_remaining_return() -> None:
    result = tracker_entry_diagnostics(
        engle_granger_pass=True,
        kss_pass=True,
        fdr_q_value=0.02,
        current_zscore=-1.0,
        potential_convergence_return_percent=1.0,
        zscore_history=[-2.0, -1.8, -1.5, -1.2, -1.0],
    )

    assert result["entry_type"] is None
    assert result["remaining_return_percent"] == 0.8


def test_tracker_confirmed_entry_rejects_noisy_or_stale_peak() -> None:
    noisy = tracker_entry_diagnostics(
        engle_granger_pass=True,
        kss_pass=True,
        fdr_q_value=0.02,
        current_zscore=1.0,
        potential_convergence_return_percent=2.0,
        zscore_history=[2.0, 1.8, 1.1, 1.2, 1.0],
    )
    stale = tracker_entry_diagnostics(
        engle_granger_pass=True,
        kss_pass=True,
        fdr_q_value=0.02,
        current_zscore=1.0,
        potential_convergence_return_percent=2.0,
        zscore_history=[2.0, 1.6, 1.5, 1.4, 1.3, 1.2, 1.0],
    )

    assert noisy["entry_type"] is None
    assert stale["entry_type"] is None


def test_futures_capital_plan_reports_long_short_and_combined_notionals():
    candidate = PairMethodLabCandidate.model_construct(
        stock_a="AAA",
        stock_b="BBB",
        hedge_ratio=0.5,
        current_zscore=-2.1,
        paper_signal="long_a_short_b",
    )
    expiry = date(2026, 8, 27)
    enriched = attach_futures_capital_plans(
        [candidate],
        {
            "AAA": [FuturesContract("AAA", "AAAAUGFUT", expiry, 100, 500, 100)],
            "BBB": [FuturesContract("BBB", "BBBAUGFUT", expiry, 80, 250, 100)],
        },
        date(2026, 8, 6),
    )[0]

    assert enriched.capital_long_ticker == "AAA"
    assert enriched.capital_short_ticker == "BBB"
    assert enriched.long_futures_notional_inr == 50_000
    assert enriched.short_futures_notional_inr == 20_000
    assert enriched.combined_futures_notional_inr == 70_000
    assert enriched.futures_hedge_fit_percent == 100


def test_kss_distinguishes_stationary_series_from_random_walk():
    rng = np.random.default_rng(42)
    stationary = np.zeros(500)
    for index in range(1, len(stationary)):
        stationary[index] = 0.72 * stationary[index - 1] + rng.normal()
    random_walk = np.cumsum(rng.normal(size=500))

    stationary_result = kss_test(stationary)
    random_walk_result = kss_test(random_walk)

    assert stationary_result is not None
    assert stationary_result.passed is True
    assert random_walk_result is not None
    assert random_walk_result.passed is False


def test_paper_method_scan_finds_pair_and_compares_current_method():
    rng = np.random.default_rng(7)
    observations = 720
    dates = pd.bdate_range("2023-01-02", periods=observations)
    common_walk = 100 + np.cumsum(rng.normal(0, 0.8, observations))
    spread = np.zeros(observations)
    for index in range(1, observations):
        spread[index] = 0.50 * spread[index - 1] + rng.normal(0, 0.6)
    closes = pd.DataFrame(
        {
            "AAA": 35 + 1.08 * common_walk + spread,
            "BBB": common_walk,
            "CCC": 90 + np.cumsum(rng.normal(0, 1.4, observations)),
        },
        index=dates,
    )

    results, metrics = scan_paper_method_matrix(
        [_member("AAA"), _member("BBB"), _member("CCC")],
        closes,
    )

    assert metrics["price_eligible_universe"] == 3
    assert metrics["pairs_tested"] == 3
    pair = next(result for result in results if result.pair_id == "AAA-BBB")
    assert pair.engle_granger_pass is True
    assert pair.kss_pass is True
    assert pair.adaptive_lookback_days >= 10
    assert pair.rolling_windows == 6
    assert pair.stability_passed_windows == 6
    assert pair.stability_score_percent == 100
    assert pair.stability_band == "strong"
    assert pair.fdr_q_value >= pair.engle_granger_p_value
    assert pair.current_method_p_value is not None
    assert pair.potential_convergence_return_percent >= 0
    assert len(pair.chart) == 126
