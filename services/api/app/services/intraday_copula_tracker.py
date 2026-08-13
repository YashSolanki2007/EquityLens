"""Five-minute paper tracking for strict daily pairs using copula signals."""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.models import (
    PaperIntradayCopulaPendingEntry,
    PaperIntradayCopulaTrackerSubscription,
    PaperIntradayCopulaTrade,
    PaperIntradayCopulaTradeMark,
)
from app.schemas.intraday_copula_tracker import (
    IntradayCopulaCandidate,
    IntradayCopulaHistoryPoint,
    IntradayCopulaTrackerResponse,
)
from app.services.copula_pair_signals import (
    ENTRY_THRESHOLD,
    EXIT_THRESHOLD,
    REFERENCE_TICKER,
    _clip_pit,
    _reference_spread,
    classify_signal,
    conditional_probabilities,
    fit_best_copula,
    fit_best_marginal,
)
from app.services.pair_method_lab import (
    MAX_RESULTS_TO_CACHE,
    TRACKER_FDR_Q_CUTOFF,
    _download_history_sync,
    get_pair_method_lab,
)
from app.services.pair_suggestions import PairUniverseMember, _eligible_fno_members

INDIA_TZ = ZoneInfo("Asia/Kolkata")
BAR_MINUTES = 5
DAILY_REGRESSION_DAYS = 504
MINIMUM_DAILY_REGRESSION_DAYS = 440
INTRADAY_HISTORY_PERIOD = "60d"
MINIMUM_INTRADAY_BARS = 750
ENTRY_START_IST = time(9, 30)
LAST_ENTRY_IST = time(14, 30)
FORCED_EXIT_IST = time(15, 10)
MARKET_OPEN_IST = time(9, 15)
MARKET_CLOSE_IST = time(15, 30)
PROFIT_TARGET_PERCENT = 0.5
STOP_LOSS_PERCENT = 0.1
TRACKED_GROSS_NOTIONAL_INR = 100_000.0
PRICE_SOURCE = "Yahoo Finance completed five-minute adjusted spot bars"
NEXT_OPEN_PRICE_SOURCE = "Yahoo Finance first five-minute adjusted cash bar open"
SNAPSHOT_CACHE_VERSION = "intraday-copula-snapshot-v2"
SNAPSHOT_CACHE_NAMESPACE = "intraday_copula_tracker"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntradayCandidateSnapshot:
    slot: str
    generated_at: datetime
    snapshot_bar_end: datetime | None
    candidates: list[IntradayCopulaCandidate]
    cached: bool
    current: bool


_snapshot_refresh_lock = asyncio.Lock()
_snapshot_refresh_task: asyncio.Task[None] | None = None


def _as_ist_index(index: pd.Index) -> pd.DatetimeIndex:
    timestamps = pd.DatetimeIndex(pd.to_datetime(index))
    if timestamps.tz is None:
        return timestamps.tz_localize(INDIA_TZ)
    return timestamps.tz_convert(INDIA_TZ)


def completed_five_minute_bars(
    closes: pd.DataFrame,
    *,
    now: datetime,
) -> pd.DataFrame:
    """Return only bars whose five-minute interval has already ended."""

    if closes.empty:
        return closes.copy()
    now_ist = now.astimezone(INDIA_TZ)
    starts = _as_ist_index(closes.index)
    ends = starts + timedelta(minutes=BAR_MINUTES)
    output = closes.loc[ends <= now_ist].copy()
    output.index = ends[ends <= now_ist].tz_convert(UTC)
    return output


def _download_intraday_prices_sync(
    members: list[PairUniverseMember],
    *,
    now: datetime,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbol_by_ticker = {member.ticker: member.market_data_ticker for member in members}
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    if not symbols:
        return pd.DataFrame(), pd.DataFrame()
    frame = yf.download(
        symbols,
        period=INTRADAY_HISTORY_PERIOD,
        interval=f"{BAR_MINUTES}m",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
        prepost=False,
    )
    if frame is None or frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"]
        opens = frame["Open"]
    elif len(symbols) == 1:
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
        opens = frame[["Open"]].rename(columns={"Open": symbols[0]})
    else:
        return pd.DataFrame(), pd.DataFrame()
    close_output = pd.DataFrame(index=closes.index)
    open_output = pd.DataFrame(index=opens.index)
    for ticker, symbol in symbol_by_ticker.items():
        if symbol in closes.columns:
            close_output[ticker] = pd.to_numeric(closes[symbol], errors="coerce")
        if symbol in opens.columns:
            open_output[ticker] = pd.to_numeric(opens[symbol], errors="coerce")
    close_output = close_output.replace([np.inf, -np.inf], np.nan)
    open_output = open_output.replace([np.inf, -np.inf], np.nan)
    return (
        completed_five_minute_bars(close_output, now=now),
        completed_five_minute_bars(open_output, now=now),
    )


def _entry_block_reason(
    *,
    signal: str,
    latest_bar_end: datetime,
    now: datetime,
) -> str | None:
    latest_ist = latest_bar_end.astimezone(INDIA_TZ)
    now_ist = now.astimezone(INDIA_TZ)
    if latest_ist.date() != now_ist.date():
        return "Latest common five-minute bar is not from today's NSE session."
    if latest_ist.time() < ENTRY_START_IST:
        return "Entry window starts at 09:30 IST after the opening-price discovery period."
    if latest_ist.time() > LAST_ENTRY_IST:
        return "The final new-entry cutoff of 14:30 IST has passed."
    if (
        now_ist.weekday() >= 5
        or now_ist.time() < MARKET_OPEN_IST
        or now_ist.time() > MARKET_CLOSE_IST
    ):
        return "The NSE cash market is closed; this signal will queue for the next open."
    if not signal.startswith("enter_"):
        return "Copula conditional probabilities do not jointly satisfy an entry rule."
    return None


def build_intraday_candidate(
    candidate: Any,
    daily_closes: pd.DataFrame,
    intraday_closes: pd.DataFrame,
    intraday_opens: pd.DataFrame | None = None,
    *,
    now: datetime,
) -> IntradayCopulaCandidate | None:
    columns = [REFERENCE_TICKER, candidate.stock_a, candidate.stock_b]
    if not set(columns).issubset(daily_closes.columns) or not set(columns).issubset(
        intraday_closes.columns
    ):
        return None

    intraday = intraday_closes[columns].dropna()
    intraday = intraday[(intraday > 0).all(axis=1)]
    if intraday.empty:
        return None
    latest_bar_end = pd.Timestamp(intraday.index[-1]).to_pydatetime()
    session_date = latest_bar_end.astimezone(INDIA_TZ).date()

    daily = daily_closes[columns].replace([np.inf, -np.inf], np.nan).dropna()
    daily = daily[(daily > 0).all(axis=1)]
    daily_dates = pd.Index(pd.to_datetime(daily.index).date)
    daily = daily.loc[daily_dates < session_date].tail(DAILY_REGRESSION_DAYS)
    if len(daily) < MINIMUM_DAILY_REGRESSION_DAYS:
        return None

    reference_daily = daily[REFERENCE_TICKER].to_numpy(dtype=float)
    beta_a, _ = _reference_spread(
        reference_daily,
        daily[candidate.stock_a].to_numpy(dtype=float),
    )
    beta_b, _ = _reference_spread(
        reference_daily,
        daily[candidate.stock_b].to_numpy(dtype=float),
    )

    intraday_ist = _as_ist_index(intraday.index)
    formation_mask = np.asarray(intraday_ist.date < session_date)
    formation = intraday.loc[formation_mask]
    if len(formation) < MINIMUM_INTRADAY_BARS:
        return None
    reference_formation = formation[REFERENCE_TICKER].to_numpy(dtype=float)
    spread_a = reference_formation - beta_a * formation[candidate.stock_a].to_numpy(
        dtype=float
    )
    spread_b = reference_formation - beta_b * formation[candidate.stock_b].to_numpy(
        dtype=float
    )
    marginal_a = fit_best_marginal(spread_a)
    marginal_b = fit_best_marginal(spread_b)
    copula = fit_best_copula(
        _clip_pit(marginal_a.cdf(spread_a)),
        _clip_pit(marginal_b.cdf(spread_b)),
    )

    current = intraday.loc[~formation_mask]
    if current.empty:
        return None
    if intraday_opens is None:
        current_opens = current.copy()
    else:
        if not set(columns).issubset(intraday_opens.columns):
            return None
        current_opens = intraday_opens.reindex(current.index)[columns].dropna()
        current_opens = current_opens[(current_opens > 0).all(axis=1)]
        if current_opens.empty or current.index[0] not in current_opens.index:
            return None
    current_reference = current[REFERENCE_TICKER].to_numpy(dtype=float)
    current_spread_a = current_reference - beta_a * current[candidate.stock_a].to_numpy(
        dtype=float
    )
    current_spread_b = current_reference - beta_b * current[candidate.stock_b].to_numpy(
        dtype=float
    )
    current_h_a, current_h_b = conditional_probabilities(
        copula,
        _clip_pit(marginal_a.cdf(current_spread_a)),
        _clip_pit(marginal_b.cdf(current_spread_b)),
    )
    h_a, h_b = float(current_h_a[-1]), float(current_h_b[-1])
    signal = classify_signal(h_a, h_b)
    long_ticker = short_ticker = None
    long_weight = short_weight = None
    if signal == "enter_long_a_short_b":
        long_ticker, short_ticker = candidate.stock_a, candidate.stock_b
        long_weight, short_weight = beta_a, beta_b
    elif signal == "enter_short_a_long_b":
        long_ticker, short_ticker = candidate.stock_b, candidate.stock_a
        long_weight, short_weight = beta_b, beta_a

    history = [
        IntradayCopulaHistoryPoint(
            timestamp=pd.Timestamp(index).to_pydatetime(),
            h_a_given_b=round(float(current_h_a[position]), 6),
            h_b_given_a=round(float(current_h_b[position]), 6),
            stock_a_price=round(float(current[candidate.stock_a].iloc[position]), 4),
            stock_b_price=round(float(current[candidate.stock_b].iloc[position]), 4),
        )
        for position, index in enumerate(current.index)
    ]
    block_reason = _entry_block_reason(
        signal=signal,
        latest_bar_end=latest_bar_end,
        now=now,
    )
    intraday_sessions = len(set(_as_ist_index(formation.index).date))
    return IntradayCopulaCandidate(
        pair_id=candidate.pair_id,
        stock_a=candidate.stock_a,
        stock_a_name=candidate.stock_a_name,
        stock_b=candidate.stock_b,
        stock_b_name=candidate.stock_b_name,
        sector=candidate.sector,
        engle_granger_p_value=candidate.engle_granger_p_value,
        fdr_q_value=candidate.fdr_q_value,
        kss_statistic=candidate.kss_statistic,
        regression_days=len(daily),
        intraday_sessions=intraday_sessions,
        formation_bars=len(formation),
        reference_beta_a=round(beta_a, 8),
        reference_beta_b=round(beta_b, 8),
        marginal_a=marginal_a.name,
        marginal_b=marginal_b.name,
        copula_family=copula.family,
        copula_parameter=round(copula.parameter, 8),
        copula_degrees_of_freedom=(
            round(copula.degrees_of_freedom, 4)
            if copula.degrees_of_freedom is not None
            else None
        ),
        copula_aic=round(copula.aic, 2),
        h_a_given_b=round(h_a, 6),
        h_b_given_a=round(h_b, 6),
        signal=signal,
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        long_weight=round(long_weight, 8) if long_weight is not None else None,
        short_weight=round(short_weight, 8) if short_weight is not None else None,
        stock_a_price=round(float(current[candidate.stock_a].iloc[-1]), 4),
        stock_b_price=round(float(current[candidate.stock_b].iloc[-1]), 4),
        session_open_a=round(float(current_opens[candidate.stock_a].iloc[0]), 4),
        session_open_b=round(float(current_opens[candidate.stock_b].iloc[0]), 4),
        session_open_timestamp=(
            pd.Timestamp(current.index[0]).to_pydatetime()
            - timedelta(minutes=BAR_MINUTES)
        ),
        latest_bar_end=latest_bar_end,
        can_enter=block_reason is None,
        entry_block_reason=block_reason,
        history=history,
    )


def intraday_snapshot_slot(now: datetime) -> str:
    """Return the completed NSE five-minute slot that should back the UI.

    The key stops advancing after the cash close and over weekends, so simply
    reopening the page cannot invalidate an otherwise current snapshot.
    """

    now_ist = now.astimezone(INDIA_TZ)
    session_date = now_ist.date()
    session_time = now_ist.time().replace(tzinfo=None)
    if now_ist.weekday() >= 5 or session_time < time(9, 20):
        session_date -= timedelta(days=1)
        while session_date.weekday() >= 5:
            session_date -= timedelta(days=1)
        slot_time = MARKET_CLOSE_IST
    elif session_time >= MARKET_CLOSE_IST:
        slot_time = MARKET_CLOSE_IST
    else:
        slot_time = time(
            now_ist.hour,
            now_ist.minute // BAR_MINUTES * BAR_MINUTES,
        )
    return datetime.combine(session_date, slot_time, tzinfo=INDIA_TZ).isoformat()


def _snapshot_cache() -> FileCache:
    return FileCache(get_settings().cache_path, SNAPSHOT_CACHE_NAMESPACE)


def _snapshot_key(slot: str) -> str:
    return cache_key(SNAPSHOT_CACHE_VERSION, slot)


def _load_candidate_snapshot(
    *,
    slot: str,
    latest: bool = False,
) -> IntradayCandidateSnapshot | None:
    key = _snapshot_key("latest" if latest else slot)
    payload = _snapshot_cache().get(key, ttl_seconds=None)
    if not isinstance(payload, dict):
        return None
    try:
        candidates = [
            IntradayCopulaCandidate.model_validate(candidate)
            for candidate in payload.get("candidates", [])
        ]
        snapshot_slot = str(payload["slot"])
        generated_at = datetime.fromisoformat(str(payload["generated_at"]))
        raw_bar_end = payload.get("snapshot_bar_end")
        snapshot_bar_end = (
            datetime.fromisoformat(str(raw_bar_end)) if raw_bar_end else None
        )
    except (KeyError, TypeError, ValueError):
        return None
    return IntradayCandidateSnapshot(
        slot=snapshot_slot,
        generated_at=generated_at,
        snapshot_bar_end=snapshot_bar_end,
        candidates=candidates,
        cached=True,
        current=snapshot_slot == slot,
    )


def _store_candidate_snapshot(snapshot: IntradayCandidateSnapshot) -> None:
    payload = {
        "slot": snapshot.slot,
        "generated_at": snapshot.generated_at.isoformat(),
        "snapshot_bar_end": (
            snapshot.snapshot_bar_end.isoformat()
            if snapshot.snapshot_bar_end is not None
            else None
        ),
        "candidates": [
            candidate.model_dump(mode="json") for candidate in snapshot.candidates
        ],
    }
    cache = _snapshot_cache()
    source = "Yahoo Finance completed five-minute adjusted spot bars"
    cache.put(_snapshot_key(snapshot.slot), payload, source=source)
    cache.put(_snapshot_key("latest"), payload, source=source)


async def _scan_intraday_candidates_uncached(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[IntradayCopulaCandidate]:
    resolved_now = now or datetime.now(UTC)
    lab = await get_pair_method_lab(db, limit=MAX_RESULTS_TO_CACHE, refresh=False)
    candidates = [
        candidate
        for candidate in lab.results
        if candidate.engle_granger_pass
        and candidate.kss_pass
        and candidate.fdr_q_value <= TRACKER_FDR_Q_CUTOFF
        and REFERENCE_TICKER not in {candidate.stock_a, candidate.stock_b}
    ]
    if not candidates:
        return []
    members, _ = await _eligible_fno_members(db)
    needed = {REFERENCE_TICKER} | {
        ticker
        for candidate in candidates
        for ticker in (candidate.stock_a, candidate.stock_b)
    }
    selected_members = [member for member in members if member.ticker in needed]
    daily_closes, _ = await asyncio.to_thread(_download_history_sync, selected_members)
    intraday_closes, intraday_opens = await asyncio.to_thread(
        _download_intraday_prices_sync,
        selected_members,
        now=resolved_now,
    )
    results: list[IntradayCopulaCandidate] = []
    for candidate in candidates:
        try:
            result = await asyncio.to_thread(
                build_intraday_candidate,
                candidate,
                daily_closes,
                intraday_closes,
                intraday_opens,
                now=resolved_now,
            )
        except (ValueError, FloatingPointError, OverflowError, np.linalg.LinAlgError):
            logger.info("Intraday copula fit skipped for %s", candidate.pair_id, exc_info=True)
            result = None
        if result is not None:
            results.append(result)
    order = {
        "enter_long_a_short_b": 0,
        "enter_short_a_long_b": 0,
        "exit": 1,
        "watch": 2,
    }
    results.sort(key=lambda item: (order[item.signal], item.fdr_q_value, item.pair_id))
    return results


async def refresh_intraday_candidate_snapshot(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    force: bool = False,
) -> IntradayCandidateSnapshot:
    """Compute at most one shared candidate matrix per completed five-minute bar."""

    resolved_now = now or datetime.now(UTC)
    slot = intraday_snapshot_slot(resolved_now)
    if not force:
        cached = _load_candidate_snapshot(slot=slot)
        if cached is not None:
            return cached
    async with _snapshot_refresh_lock:
        if not force:
            cached = _load_candidate_snapshot(slot=slot)
            if cached is not None:
                return cached
        candidates = await _scan_intraday_candidates_uncached(db, now=resolved_now)
        snapshot_bar_end = max(
            (candidate.latest_bar_end for candidate in candidates),
            default=None,
        )
        snapshot = IntradayCandidateSnapshot(
            slot=slot,
            generated_at=datetime.now(UTC),
            snapshot_bar_end=snapshot_bar_end,
            candidates=candidates,
            cached=False,
            current=True,
        )
        _store_candidate_snapshot(snapshot)
        return snapshot


async def scan_intraday_candidates(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> list[IntradayCopulaCandidate]:
    """Compatibility wrapper returning the cached per-bar candidate list."""

    snapshot = await refresh_intraday_candidate_snapshot(db, now=now)
    return snapshot.candidates


def calculate_intraday_mark(
    trade: PaperIntradayCopulaTrade,
    *,
    long_price: float,
    short_price: float,
    h_a_given_b: float,
    h_b_given_a: float,
    quote_timestamp: datetime,
) -> dict[str, Any]:
    long_pnl = trade.long_units * (long_price - trade.entry_long_price)
    short_pnl = trade.short_units * (trade.entry_short_price - short_price)
    total_pnl = long_pnl + short_pnl
    return_percent = (
        total_pnl / trade.entry_combined_notional * 100
        if trade.entry_combined_notional > 0
        else 0.0
    )
    return {
        "long_price": round(long_price, 4),
        "short_price": round(short_price, 4),
        "long_pnl": round(long_pnl, 4),
        "short_pnl": round(short_pnl, 4),
        "total_pnl": round(total_pnl, 4),
        "return_percent": round(return_percent, 6),
        "current_gross_notional": round(
            trade.long_units * long_price + trade.short_units * short_price,
            4,
        ),
        "h_a_given_b": round(h_a_given_b, 6),
        "h_b_given_a": round(h_b_given_a, 6),
        "quote_timestamp": quote_timestamp,
        "price_source": PRICE_SOURCE,
    }


def automatic_intraday_exit_reason(
    trade: PaperIntradayCopulaTrade,
    *,
    return_percent: float,
    h_a_given_b: float,
    h_b_given_a: float,
    quote_timestamp: datetime,
) -> str | None:
    if math.isfinite(return_percent) and return_percent >= trade.profit_target_percent:
        return "profit_target_0_5"
    if math.isfinite(return_percent) and return_percent <= -STOP_LOSS_PERCENT:
        return "stop_loss_0_1"
    if (
        0.5 - EXIT_THRESHOLD <= h_a_given_b <= 0.5 + EXIT_THRESHOLD
        and 0.5 - EXIT_THRESHOLD <= h_b_given_a <= 0.5 + EXIT_THRESHOLD
    ):
        return "copula_equilibrium"
    quote_ist = quote_timestamp.astimezone(INDIA_TZ)
    if quote_ist.date() > trade.session_date or (
        quote_ist.date() == trade.session_date and quote_ist.time() >= FORCED_EXIT_IST
    ):
        return "mandatory_intraday_square_off"
    return None


def _candidate_prices(
    candidate: IntradayCopulaCandidate,
    point: IntradayCopulaHistoryPoint,
    *,
    long_ticker: str,
    short_ticker: str,
) -> tuple[float, float]:
    prices = {
        candidate.stock_a: point.stock_a_price,
        candidate.stock_b: point.stock_b_price,
    }
    return prices[long_ticker], prices[short_ticker]


def _new_trade(
    portfolio_id: UUID,
    candidate: IntradayCopulaCandidate,
) -> PaperIntradayCopulaTrade:
    if not candidate.long_ticker or not candidate.short_ticker:
        raise ValueError("An entry candidate must identify both trade legs.")
    long_weight = float(candidate.long_weight or 0)
    short_weight = float(candidate.short_weight or 0)
    prices = {
        candidate.stock_a: candidate.stock_a_price,
        candidate.stock_b: candidate.stock_b_price,
    }
    long_price = prices[candidate.long_ticker]
    short_price = prices[candidate.short_ticker]
    weighted_notional = long_weight * long_price + short_weight * short_price
    if weighted_notional <= 0:
        raise ValueError("Copula hedge weights do not produce a positive gross notional.")
    scale = TRACKED_GROSS_NOTIONAL_INR / weighted_notional
    long_units = long_weight * scale
    short_units = short_weight * scale
    return PaperIntradayCopulaTrade(
        portfolio_id=portfolio_id,
        pair_id=candidate.pair_id,
        session_date=candidate.latest_bar_end.astimezone(INDIA_TZ).date(),
        status="open",
        stock_a=candidate.stock_a,
        stock_b=candidate.stock_b,
        long_ticker=candidate.long_ticker,
        short_ticker=candidate.short_ticker,
        long_units=long_units,
        short_units=short_units,
        entry_long_price=long_price,
        entry_short_price=short_price,
        entry_long_notional=long_units * long_price,
        entry_short_notional=short_units * short_price,
        entry_combined_notional=long_units * long_price + short_units * short_price,
        entry_h_a_given_b=candidate.h_a_given_b,
        entry_h_b_given_a=candidate.h_b_given_a,
        entry_q_value=candidate.fdr_q_value,
        entry_kss_statistic=candidate.kss_statistic,
        copula_family=candidate.copula_family,
        profit_target_percent=PROFIT_TARGET_PERCENT,
        entry_price_timestamp=candidate.latest_bar_end,
        entry_price_source=PRICE_SOURCE,
        signal_snapshot=candidate.model_dump(mode="json"),
    )


def _should_queue_for_next_open(
    candidate: IntradayCopulaCandidate,
    *,
    now: datetime,
) -> bool:
    if not candidate.signal.startswith("enter_"):
        return False
    latest_ist = candidate.latest_bar_end.astimezone(INDIA_TZ)
    now_ist = now.astimezone(INDIA_TZ)
    market_is_closed = (
        now_ist.weekday() >= 5
        or now_ist.time() < MARKET_OPEN_IST
        or now_ist.time() > MARKET_CLOSE_IST
    )
    return (
        latest_ist.date() < now_ist.date()
        or latest_ist.time() > LAST_ENTRY_IST
        or market_is_closed
    )


def _new_pending_entry(
    portfolio_id: UUID,
    candidate: IntradayCopulaCandidate,
) -> PaperIntradayCopulaPendingEntry:
    if (
        not candidate.long_ticker
        or not candidate.short_ticker
        or candidate.long_weight is None
        or candidate.short_weight is None
    ):
        raise ValueError("A queued entry candidate must identify both trade legs.")
    return PaperIntradayCopulaPendingEntry(
        portfolio_id=portfolio_id,
        pair_id=candidate.pair_id,
        signal_session_date=candidate.latest_bar_end.astimezone(INDIA_TZ).date(),
        status="queued",
        stock_a=candidate.stock_a,
        stock_b=candidate.stock_b,
        long_ticker=candidate.long_ticker,
        short_ticker=candidate.short_ticker,
        long_weight=candidate.long_weight,
        short_weight=candidate.short_weight,
        observed_h_a_given_b=candidate.h_a_given_b,
        observed_h_b_given_a=candidate.h_b_given_a,
        entry_q_value=candidate.fdr_q_value,
        entry_kss_statistic=candidate.kss_statistic,
        copula_family=candidate.copula_family,
        signal_observed_at=candidate.latest_bar_end,
        signal_snapshot=candidate.model_dump(mode="json"),
    )


def pending_can_execute(
    pending: PaperIntradayCopulaPendingEntry,
    candidate: IntradayCopulaCandidate,
) -> bool:
    session_date = candidate.latest_bar_end.astimezone(INDIA_TZ).date()
    return pending.status == "queued" and session_date > pending.signal_session_date


def _new_trade_from_pending(
    portfolio_id: UUID,
    pending: PaperIntradayCopulaPendingEntry,
    candidate: IntradayCopulaCandidate,
) -> PaperIntradayCopulaTrade:
    if not pending_can_execute(pending, candidate):
        raise ValueError("Queued entry cannot execute before a later NSE session opens.")
    prices = {
        candidate.stock_a: candidate.session_open_a,
        candidate.stock_b: candidate.session_open_b,
    }
    long_price = prices[pending.long_ticker]
    short_price = prices[pending.short_ticker]
    weighted_notional = (
        pending.long_weight * long_price + pending.short_weight * short_price
    )
    if weighted_notional <= 0:
        raise ValueError("Queued hedge weights do not produce a positive gross notional.")
    scale = TRACKED_GROSS_NOTIONAL_INR / weighted_notional
    long_units = pending.long_weight * scale
    short_units = pending.short_weight * scale
    session_date = candidate.latest_bar_end.astimezone(INDIA_TZ).date()
    snapshot = dict(pending.signal_snapshot)
    snapshot["queued_entry_id"] = str(pending.id)
    snapshot["next_session_open"] = {
        "timestamp": candidate.session_open_timestamp.isoformat(),
        candidate.stock_a: candidate.session_open_a,
        candidate.stock_b: candidate.session_open_b,
    }
    return PaperIntradayCopulaTrade(
        portfolio_id=portfolio_id,
        pair_id=pending.pair_id,
        session_date=session_date,
        status="open",
        stock_a=pending.stock_a,
        stock_b=pending.stock_b,
        long_ticker=pending.long_ticker,
        short_ticker=pending.short_ticker,
        long_units=long_units,
        short_units=short_units,
        entry_long_price=long_price,
        entry_short_price=short_price,
        entry_long_notional=long_units * long_price,
        entry_short_notional=short_units * short_price,
        entry_combined_notional=long_units * long_price + short_units * short_price,
        entry_h_a_given_b=pending.observed_h_a_given_b,
        entry_h_b_given_a=pending.observed_h_b_given_a,
        entry_q_value=pending.entry_q_value,
        entry_kss_statistic=pending.entry_kss_statistic,
        copula_family=pending.copula_family,
        profit_target_percent=PROFIT_TARGET_PERCENT,
        entry_price_timestamp=candidate.session_open_timestamp,
        entry_price_source=NEXT_OPEN_PRICE_SOURCE,
        signal_snapshot=snapshot,
    )


async def list_intraday_trades(
    db: AsyncSession,
    portfolio_id: UUID,
) -> list[PaperIntradayCopulaTrade]:
    return list(
        (
            await db.execute(
                select(PaperIntradayCopulaTrade)
                .where(PaperIntradayCopulaTrade.portfolio_id == portfolio_id)
                .order_by(
                    PaperIntradayCopulaTrade.session_date.desc(),
                    PaperIntradayCopulaTrade.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )


async def list_pending_entries(
    db: AsyncSession,
    portfolio_id: UUID,
) -> list[PaperIntradayCopulaPendingEntry]:
    return list(
        (
            await db.execute(
                select(PaperIntradayCopulaPendingEntry)
                .where(PaperIntradayCopulaPendingEntry.portfolio_id == portfolio_id)
                .order_by(
                    PaperIntradayCopulaPendingEntry.signal_session_date.desc(),
                    PaperIntradayCopulaPendingEntry.created_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )


def pending_entry_response(entry: PaperIntradayCopulaPendingEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "pair_id": entry.pair_id,
        "signal_session_date": entry.signal_session_date,
        "status": entry.status,
        "stock_a": entry.stock_a,
        "stock_b": entry.stock_b,
        "long_ticker": entry.long_ticker,
        "short_ticker": entry.short_ticker,
        "observed_h_a_given_b": entry.observed_h_a_given_b,
        "observed_h_b_given_a": entry.observed_h_b_given_a,
        "entry_q_value": entry.entry_q_value,
        "copula_family": entry.copula_family,
        "signal_observed_at": entry.signal_observed_at,
        "entered_trade_id": entry.entered_trade_id,
        "created_at": entry.created_at,
    }


async def intraday_trade_marks(
    db: AsyncSession,
    trade_id: UUID,
) -> list[PaperIntradayCopulaTradeMark]:
    return list(
        (
            await db.execute(
                select(PaperIntradayCopulaTradeMark)
                .where(PaperIntradayCopulaTradeMark.trade_id == trade_id)
                .order_by(PaperIntradayCopulaTradeMark.quote_timestamp)
            )
        )
        .scalars()
        .all()
    )


def intraday_trade_response(
    trade: PaperIntradayCopulaTrade,
    marks: list[PaperIntradayCopulaTradeMark],
) -> dict[str, Any]:
    serialized_marks = [
        {
            "id": mark.id,
            "long_price": mark.long_price,
            "short_price": mark.short_price,
            "long_pnl": mark.long_pnl,
            "short_pnl": mark.short_pnl,
            "total_pnl": mark.total_pnl,
            "return_percent": mark.return_percent,
            "current_gross_notional": mark.current_gross_notional,
            "h_a_given_b": mark.h_a_given_b,
            "h_b_given_a": mark.h_b_given_a,
            "quote_timestamp": mark.quote_timestamp,
            "price_source": mark.price_source,
            "created_at": mark.created_at,
        }
        for mark in marks
    ]
    return {
        "id": trade.id,
        "portfolio_id": trade.portfolio_id,
        "pair_id": trade.pair_id,
        "session_date": trade.session_date,
        "status": trade.status,
        "stock_a": trade.stock_a,
        "stock_b": trade.stock_b,
        "long_ticker": trade.long_ticker,
        "short_ticker": trade.short_ticker,
        "long_units": trade.long_units,
        "short_units": trade.short_units,
        "entry_long_price": trade.entry_long_price,
        "entry_short_price": trade.entry_short_price,
        "entry_long_notional": trade.entry_long_notional,
        "entry_short_notional": trade.entry_short_notional,
        "entry_combined_notional": trade.entry_combined_notional,
        "entry_h_a_given_b": trade.entry_h_a_given_b,
        "entry_h_b_given_a": trade.entry_h_b_given_a,
        "entry_q_value": trade.entry_q_value,
        "entry_kss_statistic": trade.entry_kss_statistic,
        "copula_family": trade.copula_family,
        "profit_target_percent": trade.profit_target_percent,
        "stop_loss_percent": STOP_LOSS_PERCENT,
        "entry_price_timestamp": trade.entry_price_timestamp,
        "entry_price_source": trade.entry_price_source,
        "created_at": trade.created_at,
        "closed_at": trade.closed_at,
        "realized_pnl": trade.realized_pnl,
        "exit_reason": trade.exit_reason,
        "exit_h_a_given_b": trade.exit_h_a_given_b,
        "exit_h_b_given_a": trade.exit_h_b_given_a,
        "latest_mark": serialized_marks[-1] if serialized_marks else None,
        "marks": serialized_marks,
    }


async def backfill_intraday_stop_loss(
    db: AsyncSession,
    session_date: date,
) -> dict[str, int]:
    """Re-evaluate a session causally under the current automatic exit rules."""

    trades = list(
        (
            await db.execute(
                select(PaperIntradayCopulaTrade)
                .where(PaperIntradayCopulaTrade.session_date == session_date)
                .order_by(PaperIntradayCopulaTrade.created_at)
            )
        )
        .scalars()
        .all()
    )
    updated = 0
    stop_losses = 0
    removed_marks = 0
    for trade in trades:
        marks = await intraday_trade_marks(db, trade.id)
        exit_mark: PaperIntradayCopulaTradeMark | None = None
        exit_reason: str | None = None
        for mark in marks:
            reason = automatic_intraday_exit_reason(
                trade,
                return_percent=mark.return_percent,
                h_a_given_b=mark.h_a_given_b,
                h_b_given_a=mark.h_b_given_a,
                quote_timestamp=mark.quote_timestamp,
            )
            if reason is not None:
                exit_mark = mark
                exit_reason = reason
                break
        if exit_mark is None or exit_reason is None:
            continue
        changed = (
            trade.status != "closed"
            or trade.closed_at != exit_mark.quote_timestamp
            or trade.exit_reason != exit_reason
            or trade.realized_pnl != exit_mark.total_pnl
        )
        if changed:
            trade.status = "closed"
            trade.closed_at = exit_mark.quote_timestamp
            trade.realized_pnl = exit_mark.total_pnl
            trade.exit_reason = exit_reason
            trade.exit_h_a_given_b = exit_mark.h_a_given_b
            trade.exit_h_b_given_a = exit_mark.h_b_given_a
            updated += 1
        if exit_reason == "stop_loss_0_1":
            stop_losses += 1
        later_mark_ids = [
            mark.id for mark in marks if mark.quote_timestamp > exit_mark.quote_timestamp
        ]
        if later_mark_ids:
            await db.execute(
                delete(PaperIntradayCopulaTradeMark).where(
                    PaperIntradayCopulaTradeMark.id.in_(later_mark_ids)
                )
            )
            removed_marks += len(later_mark_ids)
    await db.commit()
    return {
        "trades_scanned": len(trades),
        "trades_updated": updated,
        "stop_loss_exits": stop_losses,
        "later_marks_removed": removed_marks,
    }


async def _apply_candidate_marks(
    db: AsyncSession,
    trade: PaperIntradayCopulaTrade,
    candidate: IntradayCopulaCandidate,
) -> None:
    existing = await intraday_trade_marks(db, trade.id)
    latest_timestamp = existing[-1].quote_timestamp if existing else trade.entry_price_timestamp
    for point in candidate.history:
        if point.timestamp <= latest_timestamp or point.timestamp <= trade.entry_price_timestamp:
            continue
        long_price, short_price = _candidate_prices(
            candidate,
            point,
            long_ticker=trade.long_ticker,
            short_ticker=trade.short_ticker,
        )
        values = calculate_intraday_mark(
            trade,
            long_price=long_price,
            short_price=short_price,
            h_a_given_b=point.h_a_given_b,
            h_b_given_a=point.h_b_given_a,
            quote_timestamp=point.timestamp,
        )
        mark = PaperIntradayCopulaTradeMark(trade_id=trade.id, **values)
        db.add(mark)
        reason = automatic_intraday_exit_reason(
            trade,
            return_percent=values["return_percent"],
            h_a_given_b=point.h_a_given_b,
            h_b_given_a=point.h_b_given_a,
            quote_timestamp=point.timestamp,
        )
        if reason is not None:
            trade.status = "closed"
            trade.closed_at = point.timestamp
            trade.realized_pnl = values["total_pnl"]
            trade.exit_reason = reason
            trade.exit_h_a_given_b = point.h_a_given_b
            trade.exit_h_b_given_a = point.h_b_given_a
            break


async def sync_intraday_copula_tracker(
    db: AsyncSession,
    portfolio_id: UUID,
    *,
    now: datetime | None = None,
    wait_for_fresh: bool = False,
    snapshot: IntradayCandidateSnapshot | None = None,
    candidate_limit: int = 12,
) -> IntradayCopulaTrackerResponse:
    resolved_now = now or datetime.now(UTC)
    subscription = await db.get(PaperIntradayCopulaTrackerSubscription, portfolio_id)
    if subscription is None:
        subscription = PaperIntradayCopulaTrackerSubscription(portfolio_id=portfolio_id)
        db.add(subscription)
    subscription.last_synced_at = resolved_now
    # Persist the subscription before a detached refresh opens its own session.
    await db.commit()

    slot = intraday_snapshot_slot(resolved_now)
    if snapshot is None:
        snapshot = _load_candidate_snapshot(slot=slot)
    if snapshot is None and wait_for_fresh:
        snapshot = await refresh_intraday_candidate_snapshot(db, now=resolved_now)
    if snapshot is None:
        snapshot = _load_candidate_snapshot(slot=slot, latest=True)
    snapshot_is_current = snapshot is not None and snapshot.slot == slot
    refreshing = not snapshot_is_current
    if refreshing and not wait_for_fresh:
        _schedule_intraday_snapshot_refresh(resolved_now)

    candidates = snapshot.candidates if snapshot is not None else []
    can_advance_trades = snapshot_is_current
    by_pair = {candidate.pair_id: candidate for candidate in candidates}
    trades = await list_intraday_trades(db, portfolio_id)

    for trade in trades:
        if can_advance_trades and trade.status == "open" and trade.pair_id in by_pair:
            await _apply_candidate_marks(db, trade, by_pair[trade.pair_id])

    session_keys = {(trade.pair_id, trade.session_date) for trade in trades}
    pending_entries = await list_pending_entries(db, portfolio_id)
    created = 0
    for pending in pending_entries:
        if not can_advance_trades:
            break
        candidate = by_pair.get(pending.pair_id)
        if candidate is None or not pending_can_execute(pending, candidate):
            continue
        session_date = candidate.latest_bar_end.astimezone(INDIA_TZ).date()
        existing_trade = next(
            (
                trade
                for trade in trades
                if (trade.pair_id, trade.session_date)
                == (pending.pair_id, session_date)
            ),
            None,
        )
        if existing_trade is None:
            existing_trade = _new_trade_from_pending(portfolio_id, pending, candidate)
            db.add(existing_trade)
            await db.flush()
            trades.append(existing_trade)
            session_keys.add((pending.pair_id, session_date))
            created += 1
            await _apply_candidate_marks(db, existing_trade, candidate)
        pending.status = "entered"
        pending.entered_trade_id = existing_trade.id

    for candidate in candidates:
        if not can_advance_trades:
            break
        session_date = candidate.latest_bar_end.astimezone(INDIA_TZ).date()
        if not candidate.can_enter or (candidate.pair_id, session_date) in session_keys:
            continue
        trade = _new_trade(portfolio_id, candidate)
        db.add(trade)
        trades.append(trade)
        session_keys.add((candidate.pair_id, session_date))
        created += 1

    queued_created = 0
    pending_keys = {
        (entry.pair_id, entry.signal_session_date) for entry in pending_entries
    }
    actively_queued_pairs = {
        entry.pair_id for entry in pending_entries if entry.status == "queued"
    }
    for candidate in candidates:
        if not can_advance_trades:
            break
        signal_date = candidate.latest_bar_end.astimezone(INDIA_TZ).date()
        key = (candidate.pair_id, signal_date)
        if (
            not _should_queue_for_next_open(candidate, now=resolved_now)
            or candidate.pair_id in actively_queued_pairs
            or key in pending_keys
        ):
            continue
        pending = _new_pending_entry(portfolio_id, candidate)
        db.add(pending)
        pending_entries.append(pending)
        pending_keys.add(key)
        actively_queued_pairs.add(candidate.pair_id)
        queued_created += 1
    await db.commit()

    trades = await list_intraday_trades(db, portfolio_id)
    pending_entries = await list_pending_entries(db, portfolio_id)
    serialized_trades = [
        intraday_trade_response(trade, await intraday_trade_marks(db, trade.id))
        for trade in trades
    ]
    return IntradayCopulaTrackerResponse(
        bar_minutes=BAR_MINUTES,
        daily_regression_days=DAILY_REGRESSION_DAYS,
        intraday_history_period=INTRADAY_HISTORY_PERIOD,
        entry_threshold=ENTRY_THRESHOLD,
        exit_band_low=0.5 - EXIT_THRESHOLD,
        exit_band_high=0.5 + EXIT_THRESHOLD,
        profit_target_percent=PROFIT_TARGET_PERCENT,
        entry_start_ist=ENTRY_START_IST.strftime("%H:%M"),
        last_entry_ist=LAST_ENTRY_IST.strftime("%H:%M"),
        forced_exit_ist=FORCED_EXIT_IST.strftime("%H:%M"),
        eligible_pairs=len(candidates),
        returned_candidates=min(len(candidates), candidate_limit),
        entry_signals=sum(candidate.signal.startswith("enter_") for candidate in candidates),
        created_trades=created,
        queued_entries_created=queued_created,
        generated_at=(snapshot.generated_at if snapshot is not None else resolved_now),
        snapshot_bar_end=(
            snapshot.snapshot_bar_end if snapshot is not None else None
        ),
        cached=(snapshot.cached if snapshot is not None else False),
        refreshing=refreshing,
        data_source=(
            "Yahoo Finance adjusted daily closes for the 504-session regression; "
            "one shared persisted snapshot per completed five-minute bar"
        ),
        candidates=candidates[:candidate_limit],
        pending_entries=[pending_entry_response(entry) for entry in pending_entries],
        trades=serialized_trades,
        limitations=[
            "Development paper tracker only; it never places broker or exchange orders.",
            "Direct pair admission still uses the existing latest-252-session Engle-Granger, KSS and BH q <= 0.05 gate. The shared-NIFTY hedge regression is independently estimated from up to 504 completed daily sessions.",
            "Copula margins and dependence are fitted from prior-session five-minute bars only. The latest completed five-minute bar is evaluated out of sample for the current session.",
            "Yahoo intraday history is unofficial, delayed and limited to roughly 60 calendar days. Production research requires a licensed point-in-time source with bid/ask data and corporate-action QA.",
            "The percentage P&L uses a theoretical INR 100,000 gross fractional-share hedge. It excludes brokerage, taxes, bid/ask spread, slippage, margin and short-sale execution failures.",
            "The -0.10% stop loss is evaluated on completed five-minute bars. A gap or a move within the bar can therefore produce a realised paper loss worse than -0.10%.",
            "Only one entry per pair per session is permitted. Entry signals first observed after the 14:30 cutoff or while the market is closed are frozen, queued, and filled from the first five-minute bar Open of the next actual NSE session. Every remaining position is marked for closure at the first completed bar ending at or after 15:10 IST.",
        ],
    )


async def close_intraday_copula_trade(
    db: AsyncSession,
    trade: PaperIntradayCopulaTrade,
) -> None:
    marks = await intraday_trade_marks(db, trade.id)
    latest = marks[-1] if marks else None
    trade.status = "closed"
    trade.closed_at = latest.quote_timestamp if latest is not None else datetime.now(UTC)
    trade.realized_pnl = latest.total_pnl if latest is not None else 0.0
    trade.exit_reason = "manual"
    trade.exit_h_a_given_b = (
        latest.h_a_given_b if latest is not None else trade.entry_h_a_given_b
    )
    trade.exit_h_b_given_a = (
        latest.h_b_given_a if latest is not None else trade.entry_h_b_given_a
    )
    await db.commit()


async def _refresh_and_advance_intraday_subscribers(now: datetime) -> None:
    """Refresh once, then reuse the same immutable snapshot for every portfolio."""

    try:
        async with get_session_factory()() as db:
            snapshot = await refresh_intraday_candidate_snapshot(db, now=now)
            portfolio_ids = list(
                (
                    await db.execute(
                        select(PaperIntradayCopulaTrackerSubscription.portfolio_id)
                    )
                )
                .scalars()
                .all()
            )
            for portfolio_id in portfolio_ids:
                await sync_intraday_copula_tracker(
                    db,
                    portfolio_id,
                    now=now,
                    snapshot=snapshot,
                )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning("Intraday copula snapshot refresh failed", exc_info=True)


def _schedule_intraday_snapshot_refresh(now: datetime) -> None:
    global _snapshot_refresh_task

    if _snapshot_refresh_task is not None and not _snapshot_refresh_task.done():
        return
    _snapshot_refresh_task = asyncio.create_task(
        _refresh_and_advance_intraday_subscribers(now),
        name="intraday-copula-snapshot-refresh",
    )


async def run_intraday_copula_recorder() -> None:
    """Refresh intraday and once per closed-market period for queued entries."""

    last_slot: str | None = None
    while True:
        try:
            now = datetime.now(INDIA_TZ)
            slot = intraday_snapshot_slot(now)
            if slot != last_slot:
                await _refresh_and_advance_intraday_subscribers(now)
                last_slot = slot
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Intraday copula recorder failed", exc_info=True)
        await asyncio.sleep(30)
