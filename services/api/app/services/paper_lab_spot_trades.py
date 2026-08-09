"""Development-only tracking for dual-test pair-method spot proxies."""

from __future__ import annotations

import asyncio
import io
import logging
import math
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session_factory
from app.models import PaperLabSpotTrade, PaperLabSpotTradeMark
from app.schemas.pair_method_lab import PairMethodLabCandidate
from app.services.nse.client import get_nse_client
from app.services.pair_method_lab import (
    FORMATION_DAYS,
    KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL,
    MAX_RESULTS_TO_CACHE,
    _engle_granger,
    get_pair_method_lab,
)
from app.services.pair_suggestions import FNO_INDEXES
from app.services.yahoo_live import LiveQuote, get_yahoo_live_stream

INDIA_TZ = ZoneInfo("Asia/Kolkata")
MINIMUM_MARK_INTERVAL = timedelta(seconds=45)
MIN_TRACKING_EXPECTED_RETURN_PERCENT = 1.0
ENTRY_P_VALUE_CUTOFF = 0.0001
HARD_EXIT_P_VALUE_CUTOFF = 0.001
EXIT_ZSCORE_ABS_TARGET = 0.1
ENTRY_KSS_STATISTIC_CUTOFF = KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL
P_VALUE_HISTORY_CACHE_TTL = timedelta(minutes=15)
AUTOMATIC_ENTRY_CREATION_ENABLED = False
logger = logging.getLogger(__name__)

_daily_p_value_cache_at: datetime | None = None
_daily_p_value_cache_tickers: frozenset[str] = frozenset()
_daily_p_value_cache = pd.DataFrame()


def qualifies_for_tracking(
    *,
    p_value: float,
    kss_statistic: float,
    expected_return_percent: float,
) -> bool:
    """Return whether a scan observation qualifies as a new tracked entry."""

    return (
        p_value <= ENTRY_P_VALUE_CUTOFF
        and kss_statistic <= ENTRY_KSS_STATISTIC_CUTOFF
        and expected_return_percent > MIN_TRACKING_EXPECTED_RETURN_PERCENT
    )


def automatic_exit_reason(
    trade: PaperLabSpotTrade,
    *,
    p_value: float | None,
    zscore: float | None,
) -> str | None:
    """Apply the hard p-value stop before the ordinary mean-reversion exit."""

    if (
        p_value is not None
        and math.isfinite(p_value)
        and p_value > HARD_EXIT_P_VALUE_CUTOFF
    ):
        return "p_value_above_0_001"
    if zscore is None or not math.isfinite(zscore):
        return None
    if (trade.entry_zscore > 0 and zscore <= EXIT_ZSCORE_ABS_TARGET) or (
        trade.entry_zscore < 0 and zscore >= -EXIT_ZSCORE_ABS_TARGET
    ):
        return "zscore_target_0_1"
    return None


def estimated_zscore_at_prices(
    trade: PaperLabSpotTrade,
    *,
    long_price: float,
    short_price: float,
) -> float | None:
    """Estimate the paper Z-score from the saved rolling-mean target.

    Only the near-zero target crossing is used for exits. Scaling the supplied spread gap
    from the frozen scan-time gap and Z avoids needing to persist the rolling
    standard deviation separately.
    """

    return estimated_zscore_from_snapshot(
        trade.suggestion_snapshot or {},
        long_ticker=trade.long_ticker,
        short_ticker=trade.short_ticker,
        long_price=long_price,
        short_price=short_price,
        fallback_zscore=trade.entry_zscore,
    )


def estimated_zscore_from_snapshot(
    snapshot: dict[str, Any],
    *,
    long_ticker: str,
    short_ticker: str,
    long_price: float,
    short_price: float,
    fallback_zscore: float | None = None,
) -> float | None:
    """Estimate Z at supplied prices using the frozen scan-time spread model."""

    try:
        stock_a = str(snapshot["stock_a"])
        stock_b = str(snapshot["stock_b"])
        base_price_a = float(snapshot["latest_price_a"])
        base_price_b = float(snapshot["latest_price_b"])
        base_gap = float(snapshot["spread_gap_to_mean"])
        beta = float(snapshot["hedge_ratio"])
        base_zscore = float(snapshot.get("current_zscore", fallback_zscore))
    except (KeyError, TypeError, ValueError):
        return None
    prices = {
        long_ticker: long_price,
        short_ticker: short_price,
    }
    if stock_a not in prices or stock_b not in prices or abs(base_gap) < 1e-12:
        return None
    current_gap = (
        base_gap
        + (prices[stock_a] - base_price_a)
        - beta * (prices[stock_b] - base_price_b)
    )
    zscore = base_zscore * current_gap / base_gap
    return zscore if math.isfinite(zscore) else None


def has_reached_exit_target(
    trade: PaperLabSpotTrade,
    *,
    long_price: float,
    short_price: float,
) -> tuple[bool, float | None]:
    current_zscore = estimated_zscore_at_prices(
        trade,
        long_price=long_price,
        short_price=short_price,
    )
    if current_zscore is None:
        return False, None
    crossed = (
        trade.entry_zscore > 0 and current_zscore <= EXIT_ZSCORE_ABS_TARGET
    ) or (
        trade.entry_zscore < 0 and current_zscore >= -EXIT_ZSCORE_ABS_TARGET
    )
    return crossed, current_zscore


def _download_daily_p_value_history_sync(tickers: set[str]) -> pd.DataFrame:
    symbol_by_ticker = {
        ticker: FNO_INDEXES.get(ticker, ("", f"{ticker}.NS"))[1]
        for ticker in tickers
    }
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    if not symbols:
        return pd.DataFrame()
    frame = yf.download(
        symbols,
        period="2y",
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"]
    elif len(symbols) == 1:
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
    else:
        return pd.DataFrame()
    output = pd.DataFrame(index=closes.index)
    for ticker, symbol in symbol_by_ticker.items():
        if symbol in closes.columns:
            output[ticker] = pd.to_numeric(closes[symbol], errors="coerce")
    return output.replace([np.inf, -np.inf], np.nan)


async def _daily_p_value_history(tickers: set[str]) -> pd.DataFrame:
    global _daily_p_value_cache_at
    global _daily_p_value_cache_tickers
    global _daily_p_value_cache

    now = datetime.now(UTC)
    if (
        _daily_p_value_cache_at is not None
        and now - _daily_p_value_cache_at < P_VALUE_HISTORY_CACHE_TTL
        and tickers.issubset(_daily_p_value_cache_tickers)
    ):
        return _daily_p_value_cache
    history = await asyncio.to_thread(_download_daily_p_value_history_sync, tickers)
    if not history.empty:
        _daily_p_value_cache_at = now
        _daily_p_value_cache_tickers = frozenset(tickers)
        _daily_p_value_cache = history
    return history


def _cached_daily_p_value_history(tickers: set[str]) -> pd.DataFrame | None:
    if (
        _daily_p_value_cache_at is None
        or datetime.now(UTC) - _daily_p_value_cache_at >= P_VALUE_HISTORY_CACHE_TTL
        or not tickers.issubset(_daily_p_value_cache_tickers)
    ):
        return None
    return _daily_p_value_cache


def estimated_p_value_at_prices(
    trade: PaperLabSpotTrade,
    *,
    long_price: float,
    short_price: float,
    quote_timestamp: datetime,
    daily_closes: pd.DataFrame,
) -> float | None:
    """Refit Engle-Granger on 251 prior closes plus the current observation."""

    snapshot = trade.suggestion_snapshot or {}
    try:
        stock_a = str(snapshot["stock_a"])
        stock_b = str(snapshot["stock_b"])
    except (KeyError, TypeError, ValueError):
        return None
    if stock_a not in daily_closes.columns or stock_b not in daily_closes.columns:
        return None
    prices = {trade.long_ticker: long_price, trade.short_ticker: short_price}
    current_a = _positive_price(prices.get(stock_a))
    current_b = _positive_price(prices.get(stock_b))
    if current_a is None or current_b is None:
        return None
    quote_date = quote_timestamp.astimezone(INDIA_TZ).date()
    index_dates = pd.Index(pd.to_datetime(daily_closes.index).date)
    prior = daily_closes.loc[index_dates < quote_date, [stock_a, stock_b]].dropna()
    prior = prior[(prior[stock_a] > 0) & (prior[stock_b] > 0)].tail(
        FORMATION_DAYS - 1
    )
    if len(prior) < FORMATION_DAYS - 1:
        return None
    a = np.append(prior[stock_a].to_numpy(dtype=float), current_a)
    b = np.append(prior[stock_b].to_numpy(dtype=float), current_b)
    fitted = _engle_granger(a, b)
    return fitted[0] if fitted is not None else None


def _same_candidate_snapshot(
    trade: PaperLabSpotTrade,
    candidate: PairMethodLabCandidate,
) -> bool:
    snapshot = trade.suggestion_snapshot or {}
    try:
        return (
            float(snapshot["current_zscore"]) == candidate.current_zscore
            and float(snapshot["spread_gap_to_mean"])
            == candidate.spread_gap_to_mean
            and float(snapshot["latest_price_a"]) == candidate.latest_price_a
            and float(snapshot["latest_price_b"]) == candidate.latest_price_b
        )
    except (KeyError, TypeError, ValueError):
        return False


def _positive_price(value: object) -> float | None:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def calculate_spot_proxy_mark(
    trade: PaperLabSpotTrade,
    *,
    long_price: float,
    short_price: float,
    quote_timestamp: datetime,
    price_source: str,
    estimated_p_value: float | None = None,
) -> dict[str, Any]:
    long_pnl = trade.long_units * (long_price - trade.entry_long_price)
    short_pnl = trade.short_units * (trade.entry_short_price - short_price)
    total_pnl = long_pnl + short_pnl
    return_percent = (
        total_pnl / trade.entry_combined_notional * 100
        if trade.entry_combined_notional > 0
        else 0.0
    )
    current_long_notional = trade.long_units * long_price
    current_short_notional = trade.short_units * short_price
    return {
        "long_price": round(long_price, 4),
        "short_price": round(short_price, 4),
        "long_pnl": round(long_pnl, 4),
        "short_pnl": round(short_pnl, 4),
        "total_pnl": round(total_pnl, 4),
        "return_percent": round(return_percent, 6),
        "current_long_notional": round(current_long_notional, 4),
        "current_short_notional": round(current_short_notional, 4),
        "current_gross_notional": round(
            current_long_notional + current_short_notional,
            4,
        ),
        "estimated_p_value": estimated_p_value,
        "quote_timestamp": quote_timestamp,
        "price_source": price_source,
    }


def _download_recent_session_prices_sync(
    tickers: set[str],
) -> dict[str, dict[date, tuple[float, float]]]:
    symbol_by_ticker = {
        ticker: FNO_INDEXES.get(ticker, ("", f"{ticker}.NS"))[1]
        for ticker in tickers
    }
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    if not symbols:
        return {}
    frame = yf.download(
        symbols,
        period="10d",
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return {}
    if isinstance(frame.columns, pd.MultiIndex):
        opens = frame["Open"]
        closes = frame["Close"]
    elif len(symbols) == 1:
        opens = frame[["Open"]].rename(columns={"Open": symbols[0]})
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
    else:
        return {}

    prices: dict[str, dict[date, tuple[float, float]]] = {}
    for ticker, symbol in symbol_by_ticker.items():
        if symbol not in opens.columns or symbol not in closes.columns:
            continue
        sessions: dict[date, tuple[float, float]] = {}
        for index in opens.index:
            try:
                open_price = float(opens.at[index, symbol])
                close_price = float(closes.at[index, symbol])
            except (TypeError, ValueError):
                continue
            if (
                math.isfinite(open_price)
                and open_price > 0
                and math.isfinite(close_price)
                and close_price > 0
            ):
                sessions[pd.Timestamp(index).date()] = (open_price, close_price)
        if sessions:
            prices[ticker] = sessions
    return prices


def _download_intraday_closes_sync(
    tickers: set[str],
) -> dict[str, dict[datetime, float]]:
    symbol_by_ticker = {
        ticker: FNO_INDEXES.get(ticker, ("", f"{ticker}.NS"))[1]
        for ticker in tickers
    }
    symbols = list(dict.fromkeys(symbol_by_ticker.values()))
    if not symbols:
        return {}
    frame = yf.download(
        symbols,
        period="5d",
        interval="15m",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return {}
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"]
    elif len(symbols) == 1:
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
    else:
        return {}

    output: dict[str, dict[datetime, float]] = {}
    for ticker, symbol in symbol_by_ticker.items():
        if symbol not in closes.columns:
            continue
        bars: dict[datetime, float] = {}
        for index in closes.index:
            close_price = _positive_price(closes.at[index, symbol])
            if close_price is None:
                continue
            timestamp = pd.Timestamp(index).to_pydatetime()
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=INDIA_TZ)
            else:
                timestamp = timestamp.astimezone(INDIA_TZ)
            bars[timestamp] = close_price
        if bars:
            output[ticker] = bars
    return output


def latest_common_session_prices(
    ticker_a: str,
    ticker_b: str,
    prices: dict[str, dict[date, tuple[float, float]]],
) -> tuple[date, float, float, float, float] | None:
    sessions_a = prices.get(ticker_a, {})
    sessions_b = prices.get(ticker_b, {})
    common_dates = sorted(set(sessions_a) & set(sessions_b))
    if not common_dates:
        return None
    session_date = common_dates[-1]
    open_a, close_a = sessions_a[session_date]
    open_b, close_b = sessions_b[session_date]
    return session_date, open_a, open_b, close_a, close_b


async def _latest_official_nse_session_prices(
    tickers: set[str],
) -> tuple[date | None, dict[str, tuple[float, float]]]:
    client = get_nse_client()
    today = datetime.now(INDIA_TZ).date()
    for days_back in range(10):
        report_date = today - timedelta(days=days_back)
        if report_date.weekday() >= 5:
            continue
        url = (
            "https://nsearchives.nseindia.com/content/cm/"
            f"BhavCopy_NSE_CM_0_0_0_{report_date:%Y%m%d}_F_0000.csv.zip"
        )
        try:
            response = await client._get(url)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                if not names:
                    continue
                frame = pd.read_csv(archive.open(names[0]))
        except (httpx.HTTPError, zipfile.BadZipFile, ValueError, KeyError):
            continue
        required = {"TckrSymb", "SctySrs", "OpnPric", "ClsPric"}
        if not required.issubset(frame.columns):
            continue
        rows = frame[
            frame["TckrSymb"].astype(str).str.upper().isin(tickers)
            & (frame["SctySrs"].astype(str).str.upper() == "EQ")
        ]
        prices: dict[str, tuple[float, float]] = {}
        for _, row in rows.iterrows():
            ticker = str(row["TckrSymb"]).strip().upper()
            open_price = _positive_price(row["OpnPric"])
            close_price = _positive_price(row["ClsPric"])
            if open_price is not None and close_price is not None:
                prices[ticker] = (open_price, close_price)
        if prices:
            return report_date, prices
    return None, {}


def _entry_source(
    session_date: date,
    ticker_a: str,
    ticker_b: str,
    official_date: date | None,
    official_tickers: set[str],
) -> str:
    if (
        session_date == official_date
        and ticker_a in official_tickers
        and ticker_b in official_tickers
    ):
        return "NSE official cash bhavcopy session open (spot proxy)"
    return "Yahoo Finance NSE session open (spot proxy fallback)"


def _candidate_entry(
    candidate: PairMethodLabCandidate,
    session_prices: tuple[date, float, float, float, float],
    price_source: str,
) -> tuple[dict[str, Any], float, float]:
    # One theoretical hedge unit is 1 share of A against beta shares of B. Using
    # fractional units keeps the tracked percentage faithful to the fitted spread.
    units_a = 1.0
    units_b = candidate.hedge_ratio
    session_date, price_a, price_b, current_a, current_b = session_prices
    price_timestamp = datetime.combine(
        session_date,
        time(hour=9, minute=15),
        tzinfo=INDIA_TZ,
    )
    if candidate.current_zscore <= 0:
        long_ticker, short_ticker = candidate.stock_a, candidate.stock_b
        long_units, short_units = units_a, units_b
        long_price, short_price = price_a, price_b
        current_long_price, current_short_price = current_a, current_b
    else:
        long_ticker, short_ticker = candidate.stock_b, candidate.stock_a
        long_units, short_units = units_b, units_a
        long_price, short_price = price_b, price_a
        current_long_price, current_short_price = current_b, current_a

    snapshot = candidate.model_dump(mode="json")
    entry_zscore = estimated_zscore_from_snapshot(
        snapshot,
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        long_price=long_price,
        short_price=short_price,
        fallback_zscore=candidate.current_zscore,
    )
    if entry_zscore is None:
        entry_zscore = candidate.current_zscore

    return {
        "pair_id": candidate.pair_id,
        "status": "open",
        "long_ticker": long_ticker,
        "short_ticker": short_ticker,
        "long_units": long_units,
        "short_units": short_units,
        "entry_long_price": long_price,
        "entry_short_price": short_price,
        "entry_long_notional": long_units * long_price,
        "entry_short_notional": short_units * short_price,
        "entry_combined_notional": long_units * long_price + short_units * short_price,
        "hedge_ratio": candidate.hedge_ratio,
        "entry_zscore": entry_zscore,
        "entry_p_value": candidate.engle_granger_p_value,
        "entry_kss_statistic": candidate.kss_statistic,
        "entry_q_value": candidate.fdr_q_value,
        "entry_expected_return_percent": (
            candidate.potential_convergence_return_percent
        ),
        "formal_entry_signal": abs(candidate.current_zscore) >= 2,
        "entry_price_timestamp": price_timestamp,
        "entry_price_source": price_source,
        "suggestion_snapshot": snapshot,
        "exit_reason": None,
        "exit_zscore": None,
        "exit_p_value": None,
    }, current_long_price, current_short_price


async def _add_session_close_mark(
    db: AsyncSession,
    trade: PaperLabSpotTrade,
    *,
    long_price: float,
    short_price: float,
    price_source: str,
) -> None:
    session_date = trade.entry_price_timestamp.astimezone(INDIA_TZ).date()
    session_close = datetime.combine(
        session_date, time(hour=15, minute=30), tzinfo=INDIA_TZ
    )
    now = datetime.now(INDIA_TZ)
    quote_timestamp = now if session_date == now.date() and now < session_close else session_close
    db.add(
        PaperLabSpotTradeMark(
            trade_id=trade.id,
            **calculate_spot_proxy_mark(
                trade,
                long_price=long_price,
                short_price=short_price,
                quote_timestamp=quote_timestamp,
                price_source=price_source,
                estimated_p_value=trade.entry_p_value,
            ),
        )
    )


def _live_quotes(tickers: set[str]) -> dict[str, LiveQuote]:
    stream = get_yahoo_live_stream()
    return {
        ticker: quote
        for ticker in tickers
        if (quote := stream.latest(ticker)) is not None
    }


async def sync_dual_test_spot_trades(
    db: AsyncSession,
    portfolio_id: UUID,
) -> tuple[int, int]:
    if not AUTOMATIC_ENTRY_CREATION_ENABLED:
        current_trades = await list_spot_trades(db, portfolio_id)
        open_trades = [trade for trade in current_trades if trade.status == "open"]
        await backfill_intraday_spot_marks(db, open_trades)
        await close_zero_crossed_live_trades(
            db,
            [trade for trade in open_trades if trade.status == "open"],
        )
        return 0, 0

    lab = await get_pair_method_lab(db, limit=MAX_RESULTS_TO_CACHE, refresh=False)
    eligible = [
        candidate
        for candidate in lab.results
        if qualifies_for_tracking(
            p_value=candidate.engle_granger_p_value,
            kss_statistic=candidate.kss_statistic,
            expected_return_percent=(
                candidate.potential_convergence_return_percent
            ),
        )
    ]
    existing_trades = list(
        (
            await db.execute(
                select(PaperLabSpotTrade).where(
                    PaperLabSpotTrade.portfolio_id == portfolio_id
                )
            )
        )
        .scalars()
        .all()
    )
    open_trades = [trade for trade in existing_trades if trade.status == "open"]
    existing_by_pair = {trade.pair_id: trade for trade in open_trades}
    all_tickers = {
        ticker
        for candidate in eligible
        for ticker in (candidate.stock_a, candidate.stock_b)
    } | {
        ticker
        for trade in open_trades
        for ticker in (trade.long_ticker, trade.short_ticker)
    }
    recent_prices = await asyncio.to_thread(
        _download_recent_session_prices_sync,
        all_tickers,
    )
    official_date, official_prices = await _latest_official_nse_session_prices(
        all_tickers
    )
    if official_date is not None:
        for ticker, prices in official_prices.items():
            recent_prices.setdefault(ticker, {})[official_date] = prices
    official_tickers = set(official_prices)
    rebased = False
    for trade in open_trades:
        session = latest_common_session_prices(
            trade.long_ticker,
            trade.short_ticker,
            recent_prices,
        )
        if session is None:
            continue
        session_date, open_long, open_short, current_long, current_short = session
        source = _entry_source(
            session_date,
            trade.long_ticker,
            trade.short_ticker,
            official_date,
            official_tickers,
        )
        already_official_open = trade.entry_price_source.startswith(
            "NSE official cash bhavcopy session open"
        )
        same_open = (
            trade.entry_price_timestamp.astimezone(INDIA_TZ).date() == session_date
            and trade.entry_price_source == source
        )
        if already_official_open or same_open:
            continue
        await db.execute(
            delete(PaperLabSpotTradeMark).where(
                PaperLabSpotTradeMark.trade_id == trade.id
            )
        )
        trade.entry_long_price = open_long
        trade.entry_short_price = open_short
        trade.entry_long_notional = trade.long_units * open_long
        trade.entry_short_notional = trade.short_units * open_short
        trade.entry_combined_notional = (
            trade.entry_long_notional + trade.entry_short_notional
        )
        trade.entry_price_timestamp = datetime.combine(
            session_date,
            time(hour=9, minute=15),
            tzinfo=INDIA_TZ,
        )
        trade.entry_price_source = source
        trade.status = "open"
        trade.closed_at = None
        trade.realized_pnl = None
        await db.flush()
        await _add_session_close_mark(
            db,
            trade,
            long_price=current_long,
            short_price=current_short,
            price_source=(
                "NSE official cash bhavcopy close"
                if source.startswith("NSE official")
                else "Yahoo Finance daily close/current spot fallback"
            ),
        )
        rebased = True

    missing = [
        candidate
        for candidate in eligible
        if candidate.pair_id not in existing_by_pair
        and not any(
            trade.pair_id == candidate.pair_id
            and _same_candidate_snapshot(trade, candidate)
            for trade in existing_trades
        )
    ]
    created = 0
    for candidate in missing:
        session = latest_common_session_prices(
            candidate.stock_a,
            candidate.stock_b,
            recent_prices,
        )
        if session is None:
            continue
        source = _entry_source(
            session[0],
            candidate.stock_a,
            candidate.stock_b,
            official_date,
            official_tickers,
        )
        entry, current_long, current_short = _candidate_entry(
            candidate,
            session,
            source,
        )
        trade = PaperLabSpotTrade(portfolio_id=portfolio_id, **entry)
        db.add(trade)
        await db.flush()
        await _add_session_close_mark(
            db,
            trade,
            long_price=current_long,
            short_price=current_short,
            price_source=(
                "NSE official cash bhavcopy close"
                if source.startswith("NSE official")
                else "Yahoo Finance daily close/current spot fallback"
            ),
        )
        created += 1
    if created or rebased:
        await db.commit()
    current_trades = await list_spot_trades(db, portfolio_id)
    await backfill_intraday_spot_marks(
        db,
        [trade for trade in current_trades if trade.status == "open"],
    )
    await close_zero_crossed_live_trades(
        db,
        [trade for trade in current_trades if trade.status == "open"],
    )
    return len(eligible), created


async def backfill_intraday_spot_marks(
    db: AsyncSession,
    trades: list[PaperLabSpotTrade],
) -> int:
    if not trades:
        return 0
    tickers = {
        ticker
        for trade in trades
        for ticker in (trade.long_ticker, trade.short_ticker)
    }
    closes = await asyncio.to_thread(_download_intraday_closes_sync, tickers)
    daily_closes = await _daily_p_value_history(tickers)
    persisted = 0
    closed = 0
    for trade in trades:
        long_bars = closes.get(trade.long_ticker, {})
        short_bars = closes.get(trade.short_ticker, {})
        existing_marks = list(
            (
                await db.execute(
                    select(PaperLabSpotTradeMark)
                    .where(PaperLabSpotTradeMark.trade_id == trade.id)
                    .order_by(PaperLabSpotTradeMark.quote_timestamp)
                )
            )
            .scalars()
            .all()
        )
        for mark in existing_marks:
            p_value = mark.estimated_p_value
            if p_value is None:
                p_value = estimated_p_value_at_prices(
                    trade,
                    long_price=mark.long_price,
                    short_price=mark.short_price,
                    quote_timestamp=mark.quote_timestamp,
                    daily_closes=daily_closes,
                )
                if p_value is not None:
                    mark.estimated_p_value = p_value
                    persisted += 1
            exit_zscore = estimated_zscore_at_prices(
                trade,
                long_price=mark.long_price,
                short_price=mark.short_price,
            )
            reason = automatic_exit_reason(
                trade,
                p_value=p_value,
                zscore=exit_zscore,
            )
            if reason is not None:
                trade.status = "closed"
                trade.closed_at = mark.quote_timestamp
                trade.realized_pnl = mark.total_pnl
                trade.exit_reason = reason
                trade.exit_zscore = exit_zscore
                trade.exit_p_value = p_value
                closed += 1
                break
        if trade.status == "closed":
            continue
        existing_timestamps = {mark.quote_timestamp for mark in existing_marks}
        for bar_start in sorted(set(long_bars) & set(short_bars)):
            bar_end = bar_start + timedelta(minutes=15)
            if bar_end <= trade.entry_price_timestamp or bar_end in existing_timestamps:
                continue
            p_value = estimated_p_value_at_prices(
                trade,
                long_price=long_bars[bar_start],
                short_price=short_bars[bar_start],
                quote_timestamp=bar_end,
                daily_closes=daily_closes,
            )
            values = calculate_spot_proxy_mark(
                trade,
                long_price=long_bars[bar_start],
                short_price=short_bars[bar_start],
                quote_timestamp=bar_end,
                price_source="Yahoo Finance 15-minute spot bar",
                estimated_p_value=p_value,
            )
            db.add(PaperLabSpotTradeMark(trade_id=trade.id, **values))
            persisted += 1
            exit_zscore = estimated_zscore_at_prices(
                trade,
                long_price=long_bars[bar_start],
                short_price=short_bars[bar_start],
            )
            reason = automatic_exit_reason(
                trade,
                p_value=p_value,
                zscore=exit_zscore,
            )
            if reason is not None:
                trade.status = "closed"
                trade.closed_at = bar_end
                trade.realized_pnl = values["total_pnl"]
                trade.exit_reason = reason
                trade.exit_zscore = exit_zscore
                trade.exit_p_value = p_value
                closed += 1
                break
    if persisted or closed:
        await db.commit()
    return persisted


async def close_zero_crossed_live_trades(
    db: AsyncSession,
    trades: list[PaperLabSpotTrade],
) -> int:
    """Apply the live p-value stop and near-zero Z exit about once per minute."""

    closed = 0
    tickers = {
        ticker
        for trade in trades
        for ticker in (trade.long_ticker, trade.short_ticker)
    }
    daily_closes = await _daily_p_value_history(tickers)
    for trade in trades:
        if trade.status != "open":
            continue
        values, _ = _live_mark(trade, daily_closes=daily_closes)
        if values is None:
            continue
        exit_zscore = estimated_zscore_at_prices(
            trade,
            long_price=values["long_price"],
            short_price=values["short_price"],
        )
        reason = automatic_exit_reason(
            trade,
            p_value=values["estimated_p_value"],
            zscore=exit_zscore,
        )
        if reason is None:
            continue
        db.add(PaperLabSpotTradeMark(trade_id=trade.id, **values))
        trade.status = "closed"
        trade.closed_at = values["quote_timestamp"]
        trade.realized_pnl = values["total_pnl"]
        trade.exit_reason = reason
        trade.exit_zscore = exit_zscore
        trade.exit_p_value = values["estimated_p_value"]
        closed += 1
    if closed:
        await db.commit()
    return closed


def _live_mark(
    trade: PaperLabSpotTrade,
    *,
    daily_closes: pd.DataFrame | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    quotes = _live_quotes({trade.long_ticker, trade.short_ticker})
    long_quote = quotes.get(trade.long_ticker)
    short_quote = quotes.get(trade.short_ticker)
    if long_quote is None or short_quote is None:
        return None, "A live Yahoo spot quote is unavailable for one or both legs."
    quote_timestamp = max(long_quote.event_time, short_quote.event_time)
    p_value = (
        estimated_p_value_at_prices(
            trade,
            long_price=long_quote.price,
            short_price=short_quote.price,
            quote_timestamp=quote_timestamp,
            daily_closes=daily_closes,
        )
        if daily_closes is not None and not daily_closes.empty
        else None
    )
    return (
        calculate_spot_proxy_mark(
            trade,
            long_price=long_quote.price,
            short_price=short_quote.price,
            quote_timestamp=quote_timestamp,
            price_source="Yahoo Finance WebSocket spot proxy",
            estimated_p_value=p_value,
        ),
        None,
    )


async def persist_current_spot_marks(
    db: AsyncSession,
    trades: list[PaperLabSpotTrade],
) -> int:
    persisted = 0
    tickers = {
        ticker
        for trade in trades
        for ticker in (trade.long_ticker, trade.short_ticker)
    }
    daily_closes = await _daily_p_value_history(tickers)
    for trade in trades:
        values, _ = _live_mark(trade, daily_closes=daily_closes)
        if values is None:
            continue
        latest = (
            await db.execute(
                select(PaperLabSpotTradeMark)
                .where(PaperLabSpotTradeMark.trade_id == trade.id)
                .order_by(PaperLabSpotTradeMark.quote_timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is not None and (
            values["quote_timestamp"] - latest.quote_timestamp
        ) < MINIMUM_MARK_INTERVAL:
            continue
        db.add(PaperLabSpotTradeMark(trade_id=trade.id, **values))
        persisted += 1
    if persisted:
        await db.commit()
    return persisted


async def list_spot_trades(
    db: AsyncSession,
    portfolio_id: UUID,
) -> list[PaperLabSpotTrade]:
    return list(
        (
            await db.execute(
                select(PaperLabSpotTrade)
                .where(PaperLabSpotTrade.portfolio_id == portfolio_id)
                .order_by(PaperLabSpotTrade.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def trade_marks(
    db: AsyncSession,
    trade_id: UUID,
) -> list[PaperLabSpotTradeMark]:
    return list(
        (
            await db.execute(
                select(PaperLabSpotTradeMark)
                .where(PaperLabSpotTradeMark.trade_id == trade_id)
                .order_by(PaperLabSpotTradeMark.quote_timestamp)
            )
        )
        .scalars()
        .all()
    )


def spot_trade_response(
    trade: PaperLabSpotTrade,
    marks: list[PaperLabSpotTradeMark],
) -> dict[str, Any]:
    def serialized_mark(mark: PaperLabSpotTradeMark) -> dict[str, Any]:
        return {
            "id": mark.id,
            "long_price": mark.long_price,
            "short_price": mark.short_price,
            "long_pnl": mark.long_pnl,
            "short_pnl": mark.short_pnl,
            "total_pnl": mark.total_pnl,
            "return_percent": mark.return_percent,
            "current_long_notional": mark.current_long_notional,
            "current_short_notional": mark.current_short_notional,
            "current_gross_notional": mark.current_gross_notional,
            "estimated_zscore": estimated_zscore_at_prices(
                trade,
                long_price=mark.long_price,
                short_price=mark.short_price,
            ),
            "estimated_p_value": mark.estimated_p_value,
            "quote_timestamp": mark.quote_timestamp,
            "price_source": mark.price_source,
            "is_live": False,
            "created_at": mark.created_at,
        }

    serialized_marks = [serialized_mark(mark) for mark in marks]
    trade_tickers = {trade.long_ticker, trade.short_ticker}
    cached_history = _cached_daily_p_value_history(trade_tickers)
    live_values, limitation = (
        _live_mark(trade, daily_closes=cached_history)
        if trade.status == "open"
        else (None, None)
    )
    live_mark = None
    if live_values is not None:
        live_mark = {
            "id": None,
            **live_values,
            "estimated_zscore": estimated_zscore_at_prices(
                trade,
                long_price=live_values["long_price"],
                short_price=live_values["short_price"],
            ),
            "estimated_p_value": (
                live_values["estimated_p_value"]
                if live_values["estimated_p_value"] is not None
                else (
                    serialized_marks[-1]["estimated_p_value"]
                    if serialized_marks
                    else trade.entry_p_value
                )
            ),
            "is_live": True,
            "created_at": datetime.now(UTC),
        }
    return {
        "id": trade.id,
        "portfolio_id": trade.portfolio_id,
        "pair_id": trade.pair_id,
        "status": trade.status,
        "long_ticker": trade.long_ticker,
        "short_ticker": trade.short_ticker,
        "long_units": trade.long_units,
        "short_units": trade.short_units,
        "entry_long_price": trade.entry_long_price,
        "entry_short_price": trade.entry_short_price,
        "entry_long_notional": trade.entry_long_notional,
        "entry_short_notional": trade.entry_short_notional,
        "entry_combined_notional": trade.entry_combined_notional,
        "hedge_ratio": trade.hedge_ratio,
        "entry_zscore": trade.entry_zscore,
        "entry_p_value": trade.entry_p_value,
        "entry_kss_statistic": trade.entry_kss_statistic,
        "entry_q_value": trade.entry_q_value,
        "entry_expected_return_percent": trade.entry_expected_return_percent,
        "formal_entry_signal": trade.formal_entry_signal,
        "entry_price_timestamp": trade.entry_price_timestamp,
        "entry_price_source": trade.entry_price_source,
        "created_at": trade.created_at,
        "closed_at": trade.closed_at,
        "realized_pnl": trade.realized_pnl,
        "exit_reason": trade.exit_reason,
        "exit_zscore": trade.exit_zscore,
        "exit_p_value": trade.exit_p_value,
        "latest_mark": serialized_marks[-1] if serialized_marks else None,
        "live_mark": live_mark,
        "marks": serialized_marks,
        "valuation_limitation": limitation,
    }


async def close_spot_trade(
    db: AsyncSession,
    trade: PaperLabSpotTrade,
) -> None:
    daily_closes = await _daily_p_value_history(
        {trade.long_ticker, trade.short_ticker}
    )
    values, limitation = _live_mark(trade, daily_closes=daily_closes)
    if values is not None:
        mark = PaperLabSpotTradeMark(trade_id=trade.id, **values)
        db.add(mark)
        await db.flush()
        trade.realized_pnl = mark.total_pnl
    else:
        latest = (
            await db.execute(
                select(PaperLabSpotTradeMark)
                .where(PaperLabSpotTradeMark.trade_id == trade.id)
                .order_by(PaperLabSpotTradeMark.quote_timestamp.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest is None:
            raise ValueError(limitation or "No mark is available for this position.")
        trade.realized_pnl = latest.total_pnl
    trade.status = "closed"
    trade.closed_at = datetime.now(UTC)
    trade.exit_reason = "manual"
    if values is not None:
        trade.exit_zscore = estimated_zscore_at_prices(
            trade,
            long_price=values["long_price"],
            short_price=values["short_price"],
        )
        trade.exit_p_value = values["estimated_p_value"]
    elif latest is not None:
        trade.exit_p_value = latest.estimated_p_value
    await db.commit()


async def run_spot_mark_recorder() -> None:
    """Backfill each completed 15-minute bar while the API is running."""

    last_backfill_bucket: datetime | None = None
    while True:
        try:
            async with get_session_factory()() as db:
                trades = list(
                    (
                        await db.execute(
                            select(PaperLabSpotTrade).where(
                                PaperLabSpotTrade.status == "open"
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                if trades:
                    now = datetime.now(INDIA_TZ)
                    bucket = now.replace(
                        minute=now.minute // 15 * 15,
                        second=0,
                        microsecond=0,
                    )
                    if bucket != last_backfill_bucket:
                        await backfill_intraday_spot_marks(db, trades)
                        last_backfill_bucket = bucket
                    await close_zero_crossed_live_trades(db, trades)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Paper-lab spot mark recorder failed", exc_info=True)
        await asyncio.sleep(60)
