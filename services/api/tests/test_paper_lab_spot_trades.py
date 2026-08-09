from datetime import UTC, date, datetime
from uuid import uuid4

import pandas as pd
import pytest

from app.models import PaperLabSpotTrade
from app.services import paper_lab_spot_trades
from app.services.paper_lab_spot_trades import (
    AUTOMATIC_ENTRY_CREATION_ENABLED,
    ENTRY_KSS_STATISTIC_CUTOFF,
    ENTRY_P_VALUE_CUTOFF,
    EXIT_ZSCORE_ABS_TARGET,
    HARD_EXIT_P_VALUE_CUTOFF,
    automatic_exit_reason,
    calculate_spot_proxy_mark,
    estimated_p_value_at_prices,
    estimated_zscore_at_prices,
    estimated_zscore_from_snapshot,
    has_reached_exit_target,
    latest_common_session_prices,
    qualifies_for_tracking,
)


def test_automatic_entry_creation_is_paused():
    assert AUTOMATIC_ENTRY_CREATION_ENABLED is False


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


@pytest.mark.parametrize(
    ("p_value", "kss_statistic", "expected_return_percent", "expected"),
    [
        (ENTRY_P_VALUE_CUTOFF, ENTRY_KSS_STATISTIC_CUTOFF, 1.0001, True),
        (ENTRY_P_VALUE_CUTOFF, ENTRY_KSS_STATISTIC_CUTOFF, 1.0, False),
        (ENTRY_P_VALUE_CUTOFF, ENTRY_KSS_STATISTIC_CUTOFF, 0.9999, False),
        (ENTRY_P_VALUE_CUTOFF + 0.000001, -6.0, 2.0, False),
        (0.00001, ENTRY_KSS_STATISTIC_CUTOFF + 0.01, 2.0, False),
    ],
)
def test_tracking_qualification_uses_strict_expected_return_threshold(
    p_value: float,
    kss_statistic: float,
    expected_return_percent: float,
    expected: bool,
):
    assert (
        qualifies_for_tracking(
            p_value=p_value,
            kss_statistic=kss_statistic,
            expected_return_percent=expected_return_percent,
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


def test_negative_entry_exits_at_minus_point_one_before_zero():
    trade = _trade()

    not_reached, outside_target = has_reached_exit_target(
        trade,
        long_price=109.4,
        short_price=80.0,
    )
    reached, at_target = has_reached_exit_target(
        trade,
        long_price=109.5,
        short_price=80.0,
    )

    assert EXIT_ZSCORE_ABS_TARGET == 0.1
    assert not_reached is False
    assert outside_target == pytest.approx(-0.12)
    assert reached is True
    assert at_target == pytest.approx(-0.1)
    assert automatic_exit_reason(trade, p_value=0.0001, zscore=-0.11) is None
    assert (
        automatic_exit_reason(trade, p_value=0.0001, zscore=-0.1)
        == "zscore_target_0_1"
    )


def test_positive_entry_exits_at_plus_point_one_before_zero():
    trade = _trade()
    trade.entry_zscore = 1.5

    assert automatic_exit_reason(trade, p_value=0.0001, zscore=0.11) is None
    assert (
        automatic_exit_reason(trade, p_value=0.0001, zscore=0.1)
        == "zscore_target_0_1"
    )


def test_p_value_hard_exit_takes_precedence_and_has_a_hold_buffer():
    trade = _trade()

    assert automatic_exit_reason(
        trade,
        p_value=ENTRY_P_VALUE_CUTOFF + 0.0001,
        zscore=-1.0,
    ) is None
    assert automatic_exit_reason(
        trade,
        p_value=HARD_EXIT_P_VALUE_CUTOFF,
        zscore=-1.0,
    ) is None
    assert automatic_exit_reason(
        trade,
        p_value=HARD_EXIT_P_VALUE_CUTOFF + 0.000001,
        zscore=-1.0,
    ) == "p_value_above_0_001"


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
