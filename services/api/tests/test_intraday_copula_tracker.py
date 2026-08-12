from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

from app.models import PaperIntradayCopulaPendingEntry, PaperIntradayCopulaTrade
from app.services.intraday_copula_tracker import (
    DAILY_REGRESSION_DAYS,
    PROFIT_TARGET_PERCENT,
    _entry_block_reason,
    _new_trade_from_pending,
    _should_queue_for_next_open,
    automatic_intraday_exit_reason,
    build_intraday_candidate,
    calculate_intraday_mark,
    completed_five_minute_bars,
)

INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _trade() -> PaperIntradayCopulaTrade:
    return PaperIntradayCopulaTrade(
        id=uuid4(),
        portfolio_id=uuid4(),
        pair_id="AAA-BBB",
        session_date=date(2026, 8, 11),
        status="open",
        stock_a="AAA",
        stock_b="BBB",
        long_ticker="AAA",
        short_ticker="BBB",
        long_units=500.0,
        short_units=625.0,
        entry_long_price=100.0,
        entry_short_price=80.0,
        entry_long_notional=50_000.0,
        entry_short_notional=50_000.0,
        entry_combined_notional=100_000.0,
        entry_h_a_given_b=0.95,
        entry_h_b_given_a=0.05,
        entry_q_value=0.01,
        entry_kss_statistic=-6.0,
        copula_family="Gaussian",
        profit_target_percent=PROFIT_TARGET_PERCENT,
        entry_price_timestamp=datetime(2026, 8, 11, 4, 30, tzinfo=UTC),
        entry_price_source="test",
        signal_snapshot={},
    )


def test_completed_bars_exclude_the_forming_five_minute_interval():
    index = pd.DatetimeIndex(
        [
            datetime(2026, 8, 11, 9, 15, tzinfo=INDIA_TZ),
            datetime(2026, 8, 11, 9, 20, tzinfo=INDIA_TZ),
        ]
    )
    frame = pd.DataFrame({"AAA": [100.0, 101.0]}, index=index)

    result = completed_five_minute_bars(
        frame,
        now=datetime(2026, 8, 11, 9, 23, tzinfo=INDIA_TZ),
    )

    assert len(result) == 1
    assert result.index[0].astimezone(INDIA_TZ).time() == time(9, 20)


def test_entry_gate_uses_completed_bar_and_intraday_cutoffs():
    now = datetime(2026, 8, 11, 10, 0, tzinfo=INDIA_TZ)

    assert (
        _entry_block_reason(
            signal="enter_long_a_short_b",
            latest_bar_end=datetime(2026, 8, 11, 9, 30, tzinfo=INDIA_TZ),
            now=now,
        )
        is None
    )
    assert "starts" in (
        _entry_block_reason(
            signal="enter_long_a_short_b",
            latest_bar_end=datetime(2026, 8, 11, 9, 25, tzinfo=INDIA_TZ),
            now=now,
        )
        or ""
    )
    assert "do not jointly" in (
        _entry_block_reason(
            signal="watch",
            latest_bar_end=datetime(2026, 8, 11, 10, 0, tzinfo=INDIA_TZ),
            now=now,
        )
        or ""
    )
    assert "market is closed" in (
        _entry_block_reason(
            signal="enter_long_a_short_b",
            latest_bar_end=datetime(2026, 8, 11, 14, 0, tzinfo=INDIA_TZ),
            now=datetime(2026, 8, 11, 17, 0, tzinfo=INDIA_TZ),
        )
        or ""
    )


def test_mark_and_half_percent_profit_exit_use_gross_entry_notional():
    trade = _trade()
    mark = calculate_intraday_mark(
        trade,
        long_price=100.5,
        short_price=80.0,
        h_a_given_b=0.8,
        h_b_given_a=0.2,
        quote_timestamp=datetime(2026, 8, 11, 5, 0, tzinfo=UTC),
    )

    assert mark["total_pnl"] == 250.0
    assert mark["return_percent"] == pytest.approx(0.25)
    assert PROFIT_TARGET_PERCENT == 0.5
    assert (
        automatic_intraday_exit_reason(
            trade,
            return_percent=0.5,
            h_a_given_b=0.8,
            h_b_given_a=0.2,
            quote_timestamp=datetime(2026, 8, 11, 5, 0, tzinfo=UTC),
        )
        == "profit_target_0_5"
    )


def test_copula_equilibrium_and_forced_square_off_are_exit_rules():
    trade = _trade()

    assert (
        automatic_intraday_exit_reason(
            trade,
            return_percent=-0.1,
            h_a_given_b=0.45,
            h_b_given_a=0.55,
            quote_timestamp=datetime(2026, 8, 11, 6, 0, tzinfo=UTC),
        )
        == "copula_equilibrium"
    )
    assert (
        automatic_intraday_exit_reason(
            trade,
            return_percent=-0.1,
            h_a_given_b=0.8,
            h_b_given_a=0.2,
            quote_timestamp=datetime(2026, 8, 11, 15, 10, tzinfo=INDIA_TZ),
        )
        == "mandatory_intraday_square_off"
    )


def test_intraday_candidate_uses_504_daily_regression_and_prior_session_bars():
    rng = np.random.default_rng(20260811)
    daily_dates = pd.bdate_range("2024-01-01", periods=540)
    reference = 22_000 + np.cumsum(rng.normal(scale=20, size=len(daily_dates)))
    daily = pd.DataFrame(
        {
            "NIFTY": reference,
            "AAA": (reference - rng.normal(scale=8, size=len(daily_dates))) / 10,
            "BBB": (reference - rng.normal(scale=10, size=len(daily_dates))) / 20,
        },
        index=daily_dates,
    )

    sessions = pd.bdate_range("2026-05-01", periods=16)
    intraday_index: list[datetime] = []
    for session in sessions:
        start = datetime.combine(session.date(), time(9, 15), tzinfo=INDIA_TZ)
        intraday_index.extend(start + timedelta(minutes=5 * offset) for offset in range(75))
    observations = len(intraday_index)
    intraday_reference = 24_000 + np.cumsum(rng.normal(scale=2, size=observations))
    common = rng.normal(scale=4, size=observations)
    intraday = pd.DataFrame(
        {
            "NIFTY": intraday_reference,
            "AAA": (intraday_reference - common - rng.normal(size=observations)) / 10,
            "BBB": (intraday_reference - common - rng.normal(size=observations)) / 20,
        },
        index=pd.DatetimeIndex(intraday_index).tz_convert(UTC) + timedelta(minutes=5),
    )
    intraday_opens = intraday.copy()
    first_current_index = intraday.index[15 * 75]
    intraday_opens.loc[first_current_index, "AAA"] = 2_345.0
    intraday_opens.loc[first_current_index, "BBB"] = 1_234.0
    candidate = SimpleNamespace(
        pair_id="AAA-BBB",
        stock_a="AAA",
        stock_a_name="AAA Limited",
        stock_b="BBB",
        stock_b_name="BBB Limited",
        sector="Test",
        engle_granger_p_value=0.00001,
        fdr_q_value=0.01,
        kss_statistic=-6.0,
    )
    now = intraday.index[-1].to_pydatetime() + timedelta(minutes=1)

    result = build_intraday_candidate(
        candidate,
        daily,
        intraday,
        intraday_opens,
        now=now,
    )

    assert result is not None
    assert result.regression_days == DAILY_REGRESSION_DAYS
    assert result.formation_bars == 15 * 75
    assert len(result.history) == 75
    assert 0 < result.h_a_given_b < 1
    assert 0 < result.h_b_given_a < 1
    assert result.session_open_a == 2_345.0
    assert result.session_open_b == 1_234.0
    assert result.session_open_timestamp == (
        first_current_index.to_pydatetime() - timedelta(minutes=5)
    )

    queued_candidate = result.model_copy(
        update={
            "signal": "enter_long_a_short_b",
            "long_ticker": "AAA",
            "short_ticker": "BBB",
            "long_weight": 10.0,
            "short_weight": 20.0,
        }
    )
    assert _should_queue_for_next_open(
        queued_candidate,
        now=result.latest_bar_end.astimezone(INDIA_TZ) + timedelta(hours=1),
    )

    pending = PaperIntradayCopulaPendingEntry(
        id=uuid4(),
        portfolio_id=uuid4(),
        pair_id="AAA-BBB",
        signal_session_date=(
            result.latest_bar_end.astimezone(INDIA_TZ).date() - timedelta(days=1)
        ),
        status="queued",
        stock_a="AAA",
        stock_b="BBB",
        long_ticker="AAA",
        short_ticker="BBB",
        long_weight=10.0,
        short_weight=20.0,
        observed_h_a_given_b=0.95,
        observed_h_b_given_a=0.05,
        entry_q_value=0.01,
        entry_kss_statistic=-6.0,
        copula_family="Gaussian",
        signal_observed_at=result.latest_bar_end - timedelta(days=1),
        signal_snapshot={},
    )
    trade = _new_trade_from_pending(pending.portfolio_id, pending, queued_candidate)
    assert trade.entry_long_price == 2_345.0
    assert trade.entry_short_price == 1_234.0
    assert trade.entry_price_timestamp == result.session_open_timestamp
    assert trade.entry_h_a_given_b == 0.95
    assert "first five-minute" in trade.entry_price_source
