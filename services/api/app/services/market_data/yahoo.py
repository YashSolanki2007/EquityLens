"""Replaceable market-data adapter backed by yfinance (prototype snapshots only).

All values are labeled with source / retrieved_at / as_of / is_delayed_or_unverified=true
per spec §3. Snapshots are cached for 12 hours. Failures return None so the app keeps
working; dependent filters must then be marked "not verified".
"""

import asyncio
import logging
from datetime import UTC, datetime
from functools import lru_cache

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings

logger = logging.getLogger(__name__)

SNAPSHOT_TTL = 12 * 3600


@lru_cache(maxsize=8)
def _usd_inr_rate() -> float | None:
    import yfinance as yf

    try:
        rate = getattr(yf.Ticker("INR=X").fast_info, "last_price", None)
        return float(rate) if rate else None
    except Exception:
        return None


def _fetch_snapshot_sync(ticker: str) -> dict | None:
    import yfinance as yf

    try:
        t = yf.Ticker(ticker)
        info: dict = {}
        try:
            info = t.info or {}
        except Exception:  # yfinance .info is fragile; fall back to fast_info
            info = {}
        fast = t.fast_info
        price = info.get("regularMarketPrice") or getattr(fast, "last_price", None)
        market_cap = info.get("marketCap") or getattr(fast, "market_cap", None)
        if price is None and market_cap is None:
            return None
        currency = info.get("currency") or getattr(fast, "currency", None)
        market_cap_native = float(market_cap) if market_cap is not None else None
        market_cap_usd = market_cap_native
        if currency == "INR" and market_cap_native is not None:
            rate = _usd_inr_rate()
            market_cap_usd = market_cap_native / rate if rate else None
        elif currency not in (None, "USD"):
            market_cap_usd = None
        return {
            "ticker": ticker,
            "price": float(price) if price is not None else None,
            "market_cap_usd": market_cap_usd,
            "market_cap_native": market_cap_native,
            "currency": currency,
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "summary": (info.get("longBusinessSummary") or "")[:4000] or None,
            "source": "yfinance",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "as_of": datetime.now(UTC).isoformat(),
            "is_delayed_or_unverified": True,
        }
    except Exception as exc:
        logger.warning("yfinance snapshot failed for %s: %s", ticker, exc)
        return None


async def get_market_snapshot(ticker: str, *, force_refresh: bool = False) -> dict | None:
    cache = FileCache(get_settings().cache_path, "market_snapshots")
    key = cache_key("snapshot", ticker.upper())
    if not force_refresh:
        cached = cache.get(key, SNAPSHOT_TTL)
        if cached is not None:
            return cached
    snapshot = await asyncio.to_thread(_fetch_snapshot_sync, ticker.upper())
    if snapshot is not None:
        cache.put(key, snapshot, source="yfinance")
    return snapshot
