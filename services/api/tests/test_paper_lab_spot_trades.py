from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import pytest

from app.models import PaperLabSpotTrade
from app.services import paper_lab_spot_trades
from app.services.paper_lab_spot_trades import (
    AUTOMATIC_ENTRY_CREATION_ENABLED,
    ENTRY_FDR_Q_CUTOFF,
    EXIT_PROFIT_TARGET_PERCENT,
    EXIT_ZSCORE_ABS_TARGET,
    _should_rebase_entry,
    automatic_exit_reason,
    calculate_spot_proxy_mark,
    estimated_p_value_at_prices,
    estimated_zscore_at_prices,
    estimated_zscore_from_snapshot,
    has_reached_exit_target,
    latest_common_session_prices,
    qualifies_for_tracking,
    remaining_return_to_exit_at_prices,
)


def test_automatic_entry_creation_is_enabled():
    assert AUTOMATIC_ENTRY_CREATION_ENABLED is True


def _trade() -> PaperLabSpotTrade:
    return PaperLabSpotTrade(
        id=uuid4(),
        portfolio_id=uuid4(),
        pair_id="AAA-BBB",
        status="open",
        long_ticker="AAA",
        short_ticker="BBB",
        long_units=1.0,
        short_units=0.5,
        entry_long_price=100.0,
        entry_short_price=80.0,
        entry_long_notional=100.0,
        entry_short_notional=40.0,
        entry_combined_notional=140.0,
        hedge_ratio=0.5,
        entry_zscore=-1.5,
        entry_p_value=0.0001,
        entry_kss_statistic=-5.1,
        entry_q_value=0.02,
        entry_expected_return_percent=2.0,
        formal_entry_signal=False,
        entry_price_timestamp=datetime.now(UTC),
        entry_price_source="test",
        suggestion_snapshot={
            "stock_a": "AAA",
            "stock_b": "BBB",
            "latest_price_a": 100.0,
            "latest_price_b": 80.0,
            "spread_gap_to_mean": -10.0,
            "hedge_ratio": 0.5,
            "current_zscore": -2.0,
        },
    )


def test_spot_proxy_mark_uses_long_and_short_hedge_units():
    mark = calculate_spot_proxy_mark(
        _trade(),
        long_price=110.0,
        short_price=70.0,
        quote_timestamp=datetime.now(UTC),
        price_source="test",
        estimated_p_value=0.0002,
    )

    assert mark["long_pnl"] == 10.0
    assert mark["short_pnl"] == 5.0
    assert mark["total_pnl"] == 15.0
    assert mark["return_percent"] == pytest.approx(10.714286)
    assert mark["current_gross_notional"] == 145.0
    assert mark["estimated_p_value"] == 0.0002


def test_latest_common_session_prices_uses_shared_open_and_close():
    result = latest_common_session_prices(
        "AAA",
        "BBB",
        {
            "AAA": {
                date(2026, 8, 4): (100.0, 102.0),
                date(2026, 8, 5): (103.0, 104.0),
            },
            "BBB": {
                date(2026, 8, 4): (80.0, 79.0),
                date(2026, 8, 5): (78.0, 77.0),
            },
        },
    )

    assert result == (date(2026, 8, 5), 103.0, 78.0, 104.0, 77.0)


def test_entry_rebase_only_accepts_a_better_source_for_the_same_session():
    trade = _trade()
    trade.entry_price_timestamp = datetime(2026, 8, 11, 3, 45, tzinfo=UTC)
    trade.entry_price_source = "Yahoo Finance NSE session open (spot proxy fallback)"

    assert not _should_rebase_entry(
        trade,
        session_date=date(2026, 8, 10),
        source="NSE official cash bhavcopy session open (spot proxy)",
    )
    assert not _should_rebase_entry(
        trade,
        session_date=date(2026, 8, 12),
        source="Yahoo Finance NSE session open (spot proxy fallback)",
    )
    assert not _should_rebase_entry(
        trade,
        session_date=date(2026, 8, 11),
        source=trade.entry_price_source,
    )
    assert _should_rebase_entry(
        trade,
        session_date=date(2026, 8, 11),
        source="NSE official cash bhavcopy session open (spot proxy)",
    )

    trade.entry_price_source = "NSE official cash bhavcopy session open (spot proxy)"
    assert not _should_rebase_entry(
        trade,
        session_date=date(2026, 8, 11),
        source="another source",
    )


@pytest.mark.parametrize(
    ("engle_granger_pass", "kss_pass", "q_value", "entry_type", "expected"),
    [
        (True, True, ENTRY_FDR_Q_CUTOFF, "direct", True),
        (True, True, ENTRY_FDR_Q_CUTOFF, "confirmed_convergence", True),
        (False, True, 0.01, "direct", False),
        (True, False, 0.01, "direct", False),
        (True, True, ENTRY_FDR_Q_CUTOFF + 0.0001, "direct", False),
        (True, True, 0.01, None, False),
    ],
)
def test_tracking_qualification_requires_both_tests_low_q_and_entry_zscore(
    engle_granger_pass: bool,
    kss_pass: bool,
    q_value: float,
    entry_type: str | None,
    expected: bool,
):
    assert (
        qualifies_for_tracking(
            engle_granger_pass=engle_granger_pass,
            kss_pass=kss_pass,
            fdr_q_value=q_value,
            tracker_entry_type=entry_type,
        )
        is expected
    )


def test_estimated_zscore_scales_the_saved_spread_gap():
    trade = _trade()

    assert estimated_zscore_at_prices(
        trade,
        long_price=105.0,
        short_price=80.0,
    ) == pytest.approx(-1.0)


def test_remaining_return_is_recomputed_from_actual_entry_prices():
    trade = _trade()

    result = remaining_return_to_exit_at_prices(
        trade.suggestion_snapshot,
        long_ticker=trade.long_ticker,
        short_ticker=trade.short_ticker,
        long_units=trade.long_units,
        short_units=trade.short_units,
        long_price=105.0,
        short_price=80.0,
        current_zscore=-1.0,
    )

    assert result == pytest.approx(4 / 145 * 100)


def test_entry_zscore_is_recomputed_at_actual_open_prices():
    snapshot = {
        "stock_a": "ALKEM",
        "stock_b": "PAYTM",
        "latest_price_a": 5670.0,
        "latest_price_b": 1443.8,
        "spread_gap_to_mean": -104.4155,
        "hedge_ratio": 0.9556,
        "current_zscore": -1.439,
    }

    result = estimated_zscore_from_snapshot(
        snapshot,
        long_ticker="ALKEM",
        short_ticker="PAYTM",
        long_price=5520.5,
        short_price=1425.300048828125,
    )

    assert result == pytest.approx(-3.255, abs=0.001)


def test_negative_entry_exits_at_minus_point_two_before_zero():
    trade = _trade()

    not_reached, outside_target = has_reached_exit_target(
        trade,
        long_price=108.9,
        short_price=80.0,
    )
    reached, at_target = has_reached_exit_target(
        trade,
        long_price=109.0,
        short_price=80.0,
    )

    assert EXIT_ZSCORE_ABS_TARGET == 0.2
    assert not_reached is False
    assert outside_target == pytest.approx(-0.22)
    assert reached is True
    assert at_target == pytest.approx(-0.2)
    assert automatic_exit_reason(trade, zscore=-0.21, return_percent=0.5) is None
    assert (
        automatic_exit_reason(trade, zscore=-0.2, return_percent=0.5)
        == "zscore_target_0_2"
    )


def test_positive_entry_exits_at_plus_point_two_before_zero():
    trade = _trade()
    trade.entry_zscore = 1.5

    assert automatic_exit_reason(trade, zscore=0.21, return_percent=-0.5) is None
    assert (
        automatic_exit_reason(trade, zscore=0.2, return_percent=-0.5)
        == "zscore_target_0_2"
    )


def test_profit_target_exits_without_waiting_for_zscore():
    trade = _trade()

    assert EXIT_PROFIT_TARGET_PERCENT == 1.25
    assert automatic_exit_reason(trade, zscore=-1.0, return_percent=1.249) is None
    assert (
        automatic_exit_reason(trade, zscore=-1.0, return_percent=1.25)
        == "profit_target_1_25"
    )


def test_current_p_value_refits_251_prior_closes_plus_live_prices(monkeypatch):
    trade = _trade()
    index = pd.date_range("2025-07-01", periods=260, freq="B", tz="UTC")
    history = pd.DataFrame(
        {
            "AAA": [100.0 + offset for offset in range(260)],
            "BBB": [80.0 + offset * 0.5 for offset in range(260)],
        },
        index=index,
    )
    observed: dict[str, int] = {}

    def fitted(a, b):
        observed["a"] = len(a)
        observed["b"] = len(b)
        return 0.0002, 1.0, 0.5

    monkeypatch.setattr(paper_lab_spot_trades, "_engle_granger", fitted)
    result = estimated_p_value_at_prices(
        trade,
        long_price=365.0,
        short_price=212.5,
        quote_timestamp=datetime(2026, 8, 6, 6, tzinfo=UTC),
        daily_closes=history,
    )

    assert result == 0.0002
    assert observed == {"a": 252, "b": 252}
