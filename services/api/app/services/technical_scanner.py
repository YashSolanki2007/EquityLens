"""Bounded, natural-language NSE scanner over a user-selected candle window."""

import asyncio
import csv
import io
import logging
import math
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import quote

import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.llm import LLMProvider, generate_structured, get_provider
from app.models import Company
from app.prompts.technical import TECHNICAL_PLANNER_SYSTEM
from app.schemas.search import SemanticCondition
from app.schemas.technical import (
    IntradayTechnicalSnapshot,
    TechnicalCondition,
    TechnicalScanPlan,
    TechnicalScanRequest,
    TechnicalScanResponse,
    TechnicalScanResult,
)
from app.services.market_data.india_trading import get_options_chain
from app.services.nse.client import get_nse_client
from app.services.semantic_search.retrieval import semantic_retrieval
from app.services.yahoo_live import get_yahoo_live_stream

logger = logging.getLogger(__name__)

UPSTOX_INTRADAY_DOCS = (
    "https://upstox.com/developer/api-documentation/v3/get-intra-day-candle-data/"
)
TECHNICAL_CARD_TYPES = [
    "business_activity",
    "product_service",
    "customer_exposure",
    "geographic_exposure",
    "supply_chain_role",
    "macro_exposure",
]
OPTION_INDICATORS = {
    "call_oi_change_percent",
    "put_oi_change_percent",
    "put_call_oi_ratio",
    "call_delta",
    "put_delta",
}
FNO_UNIVERSE_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"
FNO_UNIVERSE_TTL_SECONDS = 24 * 60 * 60


async def get_fno_underlyings() -> set[str]:
    """Return the exchange's current derivatives underlyings from its lot-size file."""

    cache = FileCache(get_settings().cache_path, "technical_options")
    key = cache_key("nse_fno_underlyings_v2")
    cached = cache.get(key, FNO_UNIVERSE_TTL_SECONDS)
    if cached is not None:
        return {str(symbol).upper() for symbol in cached}
    response = await get_nse_client()._get(FNO_UNIVERSE_URL)
    reader = csv.reader(io.StringIO(response.text), skipinitialspace=True)
    headers = [header.strip().upper() for header in next(reader, [])]
    symbol_index = headers.index("SYMBOL")
    symbols = {
        str(row[symbol_index]).strip().upper()
        for row in reader
        if len(row) > symbol_index and str(row[symbol_index]).strip()
    }
    # NSE occasionally repeats the CSV header inside the file.
    symbols.discard("SYMBOL")
    cache.put(key, sorted(symbols), source=str(response.url))
    return symbols


@dataclass(frozen=True)
class CandleIntervalSpec:
    key: str
    label: str
    upstox_unit: str
    upstox_interval: int
    yahoo_interval: str
    approximate_candles_per_trading_day: int


CANDLE_INTERVALS = {
    "1m": CandleIntervalSpec("1m", "1 minute", "minutes", 1, "1m", 375),
    "5m": CandleIntervalSpec("5m", "5 minutes", "minutes", 5, "5m", 75),
    "15m": CandleIntervalSpec("15m", "15 minutes", "minutes", 15, "15m", 25),
    "30m": CandleIntervalSpec("30m", "30 minutes", "minutes", 30, "30m", 13),
    "1h": CandleIntervalSpec("1h", "1 hour", "hours", 1, "60m", 7),
    "1d": CandleIntervalSpec("1d", "1 day", "days", 1, "1d", 1),
}


def _bounded_candle_count(count: int) -> int:
    return min(max(count, 35), 70)


def _history_lookback_days(spec: CandleIntervalSpec, count: int) -> int:
    """Request enough calendar days for the selected number of trading candles."""
    trading_days = math.ceil(count / spec.approximate_candles_per_trading_day)
    return max(7, math.ceil(trading_days * 7 / 5) + 5)


class CandleFetcher(Protocol):
    source_name: str

    async def fetch(self, company: Company, interval: str, limit: int) -> list[dict]: ...


class AsyncWindowRateLimiter:
    """Simple one-second sliding-window limiter shared by all Upstox requests."""

    def __init__(self, max_calls_per_second: float):
        self.max_calls = max(1, int(max_calls_per_second))
        self.calls: deque[float] = deque()
        self.lock = asyncio.Lock()

    async def wait(self) -> None:
        while True:
            async with self.lock:
                now = time.monotonic()
                while self.calls and now - self.calls[0] >= 1.0:
                    self.calls.popleft()
                if len(self.calls) < self.max_calls:
                    self.calls.append(now)
                    return
                delay = max(0.005, 1.0 - (now - self.calls[0]))
            await asyncio.sleep(delay)


def _normalize_candles(candles: list[dict], limit: int) -> list[dict]:
    normalized: dict[str, dict] = {}
    for candle in candles:
        try:
            timestamp = pd.Timestamp(candle["time"])
            values = {
                "time": timestamp.isoformat(),
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": max(float(candle.get("volume") or 0), 0.0),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(values[key]) for key in ("open", "high", "low", "close")):
            continue
        if values["close"] <= 0:
            continue
        normalized[values["time"]] = values
    return sorted(normalized.values(), key=lambda row: row["time"])[-limit:]


def _upstox_rows(payload: dict) -> list[dict]:
    rows = payload.get("data", {}).get("candles") or []
    candles = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 6:
            continue
        candles.append(
            {
                "time": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            }
        )
    return candles


class UpstoxCandleFetcher:
    source_name = "Upstox V3"

    def __init__(self, token: str):
        settings = get_settings()
        self.base_url = settings.upstox_base_url.rstrip("/")
        self.token = token
        self.cache = FileCache(settings.cache_path, "technical_candles")
        self.ttl = settings.technical_scan_cache_ttl_seconds
        self.limiter = AsyncWindowRateLimiter(settings.technical_scan_max_rps)
        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=12.0,
        )

    async def _get(self, path: str) -> dict:
        await self.limiter.wait()
        response = await self.client.get(f"{self.base_url}{path}")
        response.raise_for_status()
        return response.json()

    async def fetch(self, company: Company, interval: str, limit: int) -> list[dict]:
        if not company.isin:
            raise ValueError(f"{company.ticker} has no ISIN for Upstox instrument mapping")
        spec = CANDLE_INTERVALS[interval]
        limit = _bounded_candle_count(limit)
        instrument_key = f"NSE_EQ|{company.isin}"
        key = cache_key(
            "upstox-v3",
            instrument_key,
            spec.upstox_unit,
            str(spec.upstox_interval),
            str(limit),
        )
        cached = self.cache.get(key, self.ttl)
        if cached is not None:
            return cached

        encoded = quote(instrument_key, safe="")
        intraday = _upstox_rows(
            await self._get(
                f"/historical-candle/intraday/{encoded}/{spec.upstox_unit}/{spec.upstox_interval}"
            )
        )
        candles = intraday
        if len(candles) < limit:
            today = datetime.now(UTC).astimezone().date()
            from_date = today - timedelta(days=_history_lookback_days(spec, limit))
            historical = _upstox_rows(
                await self._get(
                    f"/historical-candle/{encoded}/{spec.upstox_unit}/"
                    f"{spec.upstox_interval}/{today.isoformat()}/"
                    f"{from_date.isoformat()}"
                )
            )
            candles = [*historical, *intraday]
        normalized = _normalize_candles(candles, limit)
        if len(normalized) < 35:
            raise ValueError(f"only {len(normalized)} valid {spec.label} candles returned")
        self.cache.put(key, normalized, source="upstox_v3")
        return normalized

    async def aclose(self) -> None:
        await self.client.aclose()


def _fetch_yahoo_sync(symbol: str, spec: CandleIntervalSpec, limit: int) -> list[dict]:
    end = datetime.now(UTC) + timedelta(days=1)
    start = end - timedelta(days=_history_lookback_days(spec, limit))
    frame = yf.Ticker(symbol).history(
        start=start,
        end=end,
        interval=spec.yahoo_interval,
        auto_adjust=False,
        actions=False,
        prepost=False,
    )
    if frame is None or frame.empty:
        return []
    candles = []
    for timestamp, row in frame.tail(limit).iterrows():
        candles.append(
            {
                "time": pd.Timestamp(timestamp).isoformat(),
                "open": row.get("Open"),
                "high": row.get("High"),
                "low": row.get("Low"),
                "close": row.get("Close"),
                "volume": row.get("Volume", 0),
            }
        )
    return _normalize_candles(candles, limit)


class YahooCandleFetcher:
    source_name = "Yahoo history + live WebSocket"

    def __init__(self):
        settings = get_settings()
        self.cache = FileCache(settings.cache_path, "technical_candles")
        self.ttl = max(settings.technical_scan_cache_ttl_seconds, 120)

    async def fetch(self, company: Company, interval: str, limit: int) -> list[dict]:
        spec = CANDLE_INTERVALS[interval]
        limit = _bounded_candle_count(limit)
        symbol = company.market_data_ticker or f"{company.ticker}.NS"
        key = cache_key("yfinance", symbol, spec.yahoo_interval, str(limit))
        cached = self.cache.get(key, self.ttl)
        if cached is not None:
            return get_yahoo_live_stream().overlay_current_candle(cached, symbol, interval, limit)
        historical = await asyncio.to_thread(_fetch_yahoo_sync, symbol, spec, limit)
        candles = get_yahoo_live_stream().overlay_current_candle(
            historical, symbol, interval, limit
        )
        if len(candles) < 35:
            raise ValueError(f"only {len(candles)} valid {spec.label} candles returned")
        # Cache only the REST backfill. A live forming candle must never become a
        # stale cache entry; it is merged afresh on every scan.
        self.cache.put(key, historical, source="yfinance")
        return candles


def get_candle_fetcher() -> CandleFetcher:
    settings = get_settings()
    if settings.upstox_access_token.strip():
        return UpstoxCandleFetcher(settings.upstox_access_token.strip())
    return YahooCandleFetcher()


def _finite(value: float | np.floating | None, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def calculate_technical_snapshot(
    company: Company,
    candles: list[dict],
    source: str,
    *,
    interval: str = "1m",
    limit: int = 70,
) -> dict:
    """Calculate vectorized indicators over the selected bounded candle window."""
    limit = _bounded_candle_count(limit)
    candles = _normalize_candles(candles, limit)
    if len(candles) < 35:
        raise ValueError("at least 35 valid candles are required")

    frame = pd.DataFrame(candles)
    close = frame["close"].astype(float)
    high = frame["high"].astype(float)
    low = frame["low"].astype(float)
    volume = frame["volume"].astype(float)

    delta = close.diff()
    average_gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    average_loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + relative_strength))
    if average_loss.iloc[-1] == 0:
        rsi.iloc[-1] = 100.0

    ema_9 = close.ewm(span=9, adjust=False).mean()
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_21 = close.ewm(span=21, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema_12 - ema_26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_histogram = macd_line - macd_signal

    typical_price = (high + low + close) / 3
    volume_sum = float(volume.sum())
    vwap = (
        float((typical_price * volume).sum() / volume_sum)
        if volume_sum > 0
        else float(close.mean())
    )

    previous_close = close.shift(1)
    true_range = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()

    bollinger_middle = close.rolling(20).mean()
    bollinger_std = close.rolling(20).std(ddof=0)
    bollinger_lower = bollinger_middle - 2 * bollinger_std
    bollinger_upper = bollinger_middle + 2 * bollinger_std
    band_width = float(bollinger_upper.iloc[-1] - bollinger_lower.iloc[-1])

    latest = float(close.iloc[-1])

    def period_return(candles_back: int) -> float | None:
        if len(close) <= candles_back:
            return None
        prior = float(close.iloc[-(candles_back + 1)])
        return (latest / prior - 1) * 100 if prior > 0 else None

    prior_volume = volume.iloc[-21:-1] if len(volume) >= 21 else volume.iloc[:-1]
    mean_prior_volume = float(prior_volume.mean()) if len(prior_volume) else 0.0
    relative_volume = float(volume.iloc[-1]) / mean_prior_volume if mean_prior_volume > 0 else 0.0
    bollinger_position = (
        (latest - float(bollinger_lower.iloc[-1])) / band_width * 100
        if band_width > 1e-12
        else 50.0
    )

    return {
        "ticker": company.ticker,
        "name": company.name,
        "sector": company.sector,
        "industry": company.industry,
        "price": round(latest, 4),
        "candle_time": pd.Timestamp(frame["time"].iloc[-1]).to_pydatetime(),
        "candle_interval": interval,
        "candles_used": len(frame),
        "rsi_14": round(_finite(rsi.iloc[-1], 50.0), 4),
        "macd_histogram": round(_finite(macd_histogram.iloc[-1]), 6),
        "price_vs_vwap_percent": round((latest / vwap - 1) * 100, 4),
        "ema_9_vs_ema_21_percent": round(
            (float(ema_9.iloc[-1]) / float(ema_21.iloc[-1]) - 1) * 100, 4
        ),
        "return_5c_percent": (round(value, 4) if (value := period_return(5)) is not None else None),
        "return_15c_percent": (
            round(value, 4) if (value := period_return(15)) is not None else None
        ),
        "return_60c_percent": (
            round(value, 4) if (value := period_return(60)) is not None else None
        ),
        "relative_volume": round(_finite(relative_volume), 4),
        "atr_percent": round(_finite(float(atr.iloc[-1]) / latest * 100), 4),
        "bollinger_position_percent": round(_finite(bollinger_position, 50.0), 4),
        "source": source,
        "source_url": (
            UPSTOX_INTRADAY_DOCS
            if source == "Upstox V3"
            else f"https://finance.yahoo.com/quote/{company.market_data_ticker or company.ticker + '.NS'}"
        ),
        "is_delayed_or_unverified": source != "Upstox V3",
    }


def _fallback_conditions(query: str) -> list[TechnicalCondition]:
    text = query.lower()
    conditions: list[TechnicalCondition] = []

    def add(indicator: str, operator: str, value: float | list[float]) -> None:
        candidate = TechnicalCondition(indicator=indicator, operator=operator, value=value)
        if candidate not in conditions:
            conditions.append(candidate)

    if "oversold" in text:
        add("rsi_14", "lt", 30)
    if "overbought" in text:
        add("rsi_14", "gt", 70)
    rsi_match = re.search(
        r"rsi(?:\s*\(?14\)?)?\s*(?:is\s*)?(below|under|less than|above|over|greater than|[<>])\s*(\d+(?:\.\d+)?)",
        text,
    )
    if rsi_match:
        operator = "lt" if rsi_match.group(1) in {"below", "under", "less than", "<"} else "gt"
        add("rsi_14", operator, float(rsi_match.group(2)))
    if "bullish macd" in text or "macd bullish" in text:
        add("macd_histogram", "gt", 0)
    if "bearish macd" in text or "macd bearish" in text:
        add("macd_histogram", "lt", 0)
    if re.search(r"(?:price\s+)?above\s+(?:the\s+)?vwap", text):
        add("price_vs_vwap_percent", "gt", 0)
    if re.search(r"(?:price\s+)?below\s+(?:the\s+)?vwap", text):
        add("price_vs_vwap_percent", "lt", 0)
    if re.search(r"ema\s*9\s+(?:is\s+)?above\s+ema\s*21", text):
        add("ema_9_vs_ema_21_percent", "gt", 0)
    if re.search(r"ema\s*9\s+(?:is\s+)?below\s+ema\s*21", text):
        add("ema_9_vs_ema_21_percent", "lt", 0)
    volume_match = re.search(r"(?:relative\s+volume|volume\s+spike).*?(\d+(?:\.\d+)?)\s*x", text)
    if volume_match:
        add("relative_volume", "gte", float(volume_match.group(1)))
    elif "volume spike" in text or "high relative volume" in text:
        add("relative_volume", "gte", 1.5)
    for candles in (5, 15, 60):
        if re.search(rf"positive\s+{candles}(?:-|\s*)(?:candle|period)\s+momentum", text):
            add(f"return_{candles}c_percent", "gt", 0)
        if re.search(rf"negative\s+{candles}(?:-|\s*)(?:candle|period)\s+momentum", text):
            add(f"return_{candles}c_percent", "lt", 0)

    comparator = r"(below|under|less than|above|over|greater than|at least|[<>])"
    for side in ("call", "put"):
        oi_match = re.search(
            rf"{side}\s+(?:change\s+in\s+)?(?:open\s+interest|oi)(?:\s+change)?"
            rf".*?{comparator}\s*(-?\d+(?:\.\d+)?)\s*%?",
            text,
        )
        if oi_match:
            operator = (
                "lt"
                if oi_match.group(1) in {"below", "under", "less than", "<"}
                else "gte"
                if oi_match.group(1) == "at least"
                else "gt"
            )
            add(
                f"{side}_oi_change_percent",
                operator,
                float(oi_match.group(2)),
            )
        elif re.search(
            rf"{side}\s+(?:change\s+in\s+)?(?:open\s+interest|oi)"
            r"(?:\s+change)?.*?\bpositive\b",
            text,
        ):
            add(f"{side}_oi_change_percent", "gt", 0)
        elif re.search(
            rf"{side}\s+(?:change\s+in\s+)?(?:open\s+interest|oi)"
            r"(?:\s+change)?.*?\bnegative\b",
            text,
        ):
            add(f"{side}_oi_change_percent", "lt", 0)

        delta_between = re.search(
            rf"{side}\s+(?:option\s+)?delta.*?between\s+"
            r"(-?\d+(?:\.\d+)?)\s+(?:and|to|-)\s+(-?\d+(?:\.\d+)?)",
            text,
        )
        delta_around = re.search(
            rf"{side}\s+(?:option\s+)?delta.*?(?:around|near|approximately|about)\s+"
            r"(-?\d+(?:\.\d+)?)",
            text,
        )
        delta_exact = re.search(
            rf"{side}\s+(?:option\s+)?delta\s*(?:of|is|=)?\s*"
            r"(-?\d+(?:\.\d+)?)",
            text,
        )
        if delta_between:
            values = [
                min(1.0, max(0.0, abs(float(delta_between.group(1))))),
                min(1.0, max(0.0, abs(float(delta_between.group(2))))),
            ]
            add(f"{side}_delta", "between", values)
        elif delta_around:
            target = min(1.0, max(0.0, abs(float(delta_around.group(1)))))
            add(
                f"{side}_delta",
                "between",
                [max(0.0, target - 0.05), min(1.0, target + 0.05)],
            )
        elif delta_exact:
            target = min(1.0, max(0.0, abs(float(delta_exact.group(1)))))
            add(
                f"{side}_delta",
                "between",
                [max(0.0, target - 0.05), min(1.0, target + 0.05)],
            )

    pcr_match = re.search(
        rf"(?:pcr|put[- ]call(?:\s+oi)?\s+ratio).*?{comparator}\s*(\d+(?:\.\d+)?)",
        text,
    )
    if pcr_match:
        operator = (
            "lt"
            if pcr_match.group(1) in {"below", "under", "less than", "<"}
            else "gte"
            if pcr_match.group(1) == "at least"
            else "gt"
        )
        add("put_call_oi_ratio", operator, float(pcr_match.group(2)))
    return conditions


def _fallback_sort(
    query: str,
) -> tuple[str | None, str]:
    text = query.lower()
    ranking = re.search(
        r"\b(greatest|highest|largest|most|lowest|smallest|least)\b",
        text,
    )
    if not ranking:
        return None, "desc"
    direction = "asc" if ranking.group(1) in {"lowest", "smallest", "least"} else "desc"
    ranked_text = text[ranking.start() :]
    if re.search(r"\bcall\b.*?\b(?:open\s+interest|oi)\b", ranked_text):
        return "call_oi_change_percent", direction
    if re.search(r"\bput\b.*?\b(?:open\s+interest|oi)\b", ranked_text):
        return "put_oi_change_percent", direction
    if re.search(r"\b(?:pcr|put[- ]call(?:\s+oi)?\s+ratio)\b", ranked_text):
        return "put_call_oi_ratio", direction
    if re.search(r"\brsi\b", ranked_text):
        return "rsi_14", direction
    if re.search(r"\brelative\s+volume\b|\bvolume\s+spike\b", ranked_text):
        return "relative_volume", direction
    return None, direction


def _explicit_option_indicators(query: str) -> set[str]:
    text = query.lower()
    indicators: set[str] = set()
    for side in ("call", "put"):
        if re.search(
            rf"\b{side}\s+(?:change\s+in\s+)?(?:open\s+interest|oi)\b",
            text,
        ):
            indicators.add(f"{side}_oi_change_percent")
        if re.search(rf"\b{side}\s+(?:option\s+)?delta\b", text):
            indicators.add(f"{side}_delta")
    if re.search(r"\b(?:pcr|put[- ]call(?:\s+oi)?\s+ratio)\b", text):
        indicators.add("put_call_oi_ratio")
    return indicators


def _normalize_business_concept(value: str | None) -> str | None:
    """Remove market-universe scaffolding while preserving real industries."""

    if not value:
        return None
    concept = value
    concept = re.sub(
        r"\b(?:nse(?:[- ]listed)?|main[- ]board|f\s*(?:&|and)\s*o|"
        r"futures?\s*(?:&|and)\s*options?|derivatives?|optionable|listed)\b",
        " ",
        concept,
        flags=re.IGNORECASE,
    )
    concept = re.sub(
        r"\b(?:stocks?|shares?|securities|companies|company|universe|market|"
        r"sectors?|industr(?:y|ies))\b\s*$",
        " ",
        concept,
        flags=re.IGNORECASE,
    )
    concept = re.sub(
        r"^(?:find|show|scan for|search for)\s+",
        "",
        concept,
        flags=re.IGNORECASE,
    )
    concept = re.sub(
        r"\b(?:with|that have|having|where)\b\s*$",
        "",
        concept,
        flags=re.IGNORECASE,
    )
    concept = re.sub(r"\s+", " ", concept).strip(" ,:-&")
    return concept or None


def _fallback_semantic_concept(query: str) -> str | None:
    first_technical = re.search(
        r"\b(rsi|oversold|overbought|macd|vwap|ema\s*9|volume spike|relative volume|"
        r"(?:a\s+)?(?:nearest[- ]expiry\s+)?call\s+(?:open interest|oi|delta)|"
        r"(?:a\s+)?(?:nearest[- ]expiry\s+)?put\s+(?:open interest|oi|delta)|"
        r"pcr|put[- ]call(?:\s+oi)?\s+ratio|"
        r"positive\s+(?:5|15|60)[- ](?:candle|period)|"
        r"negative\s+(?:5|15|60)[- ](?:candle|period))",
        query,
        re.IGNORECASE,
    )
    if not first_technical:
        return None
    prefix = query[: first_technical.start()].strip(" ,:-")
    prefix = re.sub(r"^(find|show|scan for|search for)\s+", "", prefix, flags=re.IGNORECASE)
    prefix = re.sub(r"\b(?:nse|nifty\s*200)\b", "", prefix, flags=re.IGNORECASE)
    prefix = re.sub(
        r"\b(?:the\s+)?(?:greatest|highest|largest|most|lowest|smallest|least)\s*$",
        "",
        prefix,
        flags=re.IGNORECASE,
    )
    prefix = re.sub(r"\b(?:stocks|companies)\s+(?:with|that have)\s*$", "", prefix, flags=re.I)
    prefix = re.sub(r"\s+", " ", prefix).strip(" ,:-")
    return _normalize_business_concept(prefix)


async def plan_technical_scan(
    query: str,
    *,
    provider: LLMProvider | None = None,
) -> TechnicalScanPlan:
    provider = provider or get_provider()
    messages = [
        {"role": "system", "content": TECHNICAL_PLANNER_SYSTEM},
        {"role": "user", "content": query},
    ]
    try:
        plan = await generate_structured(
            TechnicalScanPlan,
            messages,
            provider=provider,
            temperature=0.0,
        )
    except Exception as exc:
        logger.warning("Technical planner unavailable; using deterministic parser: %s", exc)
        plan = TechnicalScanPlan(
            original_query=query,
            semantic_concept=_fallback_semantic_concept(query),
            conditions=_fallback_conditions(query),
        )
    plan.original_query = query
    deterministic_conditions = _fallback_conditions(query)
    deterministic_sort_by, deterministic_sort_direction = _fallback_sort(query)
    deterministic_semantic = _fallback_semantic_concept(query)
    explicit_option_indicators = _explicit_option_indicators(query)
    plan.semantic_concept = _normalize_business_concept(plan.semantic_concept)
    plan.conditions = [
        condition
        for condition in plan.conditions
        if condition.indicator not in OPTION_INDICATORS
        or condition.indicator in explicit_option_indicators
    ]
    if deterministic_semantic:
        if not plan.semantic_concept:
            plan.semantic_concept = deterministic_semantic
    elif deterministic_conditions or deterministic_sort_by:
        plan.semantic_concept = None
    for deterministic_condition in deterministic_conditions:
        existing_index = next(
            (
                index
                for index, condition in enumerate(plan.conditions)
                if condition.indicator == deterministic_condition.indicator
            ),
            None,
        )
        if existing_index is None:
            plan.conditions.append(deterministic_condition)
        else:
            plan.conditions[existing_index] = deterministic_condition
    if deterministic_sort_by:
        plan.sort_by = deterministic_sort_by
        plan.sort_direction = deterministic_sort_direction
    plan.result_limit = min(max(plan.result_limit, 1), 50)
    return plan


def _condition_passes(value: float | None, condition: TechnicalCondition) -> bool:
    if value is None or not math.isfinite(value):
        return False
    if condition.operator == "between":
        low, high = condition.value
        return float(low) <= value <= float(high)
    target = float(condition.value)
    return {
        "gt": value > target,
        "gte": value >= target,
        "lt": value < target,
        "lte": value <= target,
    }[condition.operator]


def _condition_strength(value: float, condition: TechnicalCondition) -> float:
    if condition.operator == "between":
        low, high = (float(item) for item in condition.value)
        half_width = max((high - low) / 2, 1e-9)
        midpoint = (low + high) / 2
        return max(0.5, 1 - 0.5 * abs(value - midpoint) / half_width)
    target = float(condition.value)
    scale = max(abs(target), 1.0)
    margin = value - target if condition.operator in {"gt", "gte"} else target - value
    return min(1.0, max(0.5, 0.5 + 0.5 * margin / scale))


def _condition_description(condition: TechnicalCondition, value: float) -> str:
    operator = {
        "gt": ">",
        "gte": "≥",
        "lt": "<",
        "lte": "≤",
        "between": "between",
    }[condition.operator]
    target = (
        f"{condition.value[0]:g}–{condition.value[1]:g}"
        if isinstance(condition.value, list)
        else f"{condition.value:g}"
    )
    return f"{condition.indicator} {value:.3f} ({operator} {target})"


def _closest_delta_contract(
    contracts: list[dict],
    condition: TechnicalCondition | None,
) -> dict | None:
    usable = []
    for contract in contracts:
        delta = _finite(contract.get("delta"), default=float("nan"))
        if math.isfinite(delta):
            usable.append(contract)
    if not usable:
        return None
    if condition is None:
        target = 0.5
    elif isinstance(condition.value, list):
        target = (float(condition.value[0]) + float(condition.value[1])) / 2
    else:
        target = float(condition.value)
    passing = [
        contract
        for contract in usable
        if condition is None or _condition_passes(abs(float(contract["delta"])), condition)
    ]
    if not passing:
        return None
    return min(
        passing,
        key=lambda contract: abs(abs(float(contract["delta"])) - target),
    )


def _evaluate_option_conditions(
    chain: dict,
    conditions: list[TechnicalCondition],
) -> tuple[bool, dict, list[str], list[float]]:
    summary = dict(chain.get("scanner_summary") or {})
    updates = {
        "options_available": bool(chain.get("available")),
        "option_expiry": chain.get("selected_expiry"),
        "call_open_interest": summary.get("call_open_interest"),
        "put_open_interest": summary.get("put_open_interest"),
        "call_oi_change_percent": summary.get("call_oi_change_percent"),
        "put_oi_change_percent": summary.get("put_oi_change_percent"),
        "put_call_oi_ratio": summary.get("put_call_oi_ratio"),
        "option_source_url": chain.get("source_url"),
    }
    underlying = _finite(chain.get("underlying_value"), default=0.0)
    if underlying > 0:
        updates["price"] = underlying
    retrieved_at = chain.get("retrieved_at")
    if isinstance(retrieved_at, str):
        try:
            updates["candle_time"] = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
        except ValueError:
            pass
    matched: list[str] = []
    strengths: list[float] = []
    eligible = bool(chain.get("available"))

    for side in ("call", "put"):
        condition = next(
            (item for item in conditions if item.indicator == f"{side}_delta"),
            None,
        )
        contract = _closest_delta_contract(
            list(summary.get(f"{side}_delta_contracts") or []),
            condition,
        )
        updates[f"{side}_delta"] = abs(float(contract["delta"])) if contract is not None else None
        updates[f"{side}_delta_strike"] = (
            float(contract["strike_price"]) if contract is not None else None
        )

    for condition in conditions:
        value = updates.get(condition.indicator)
        passed = _condition_passes(value, condition)
        if condition.required and not passed:
            eligible = False
        if passed and value is not None:
            description = _condition_description(condition, value)
            if condition.indicator in {"call_delta", "put_delta"}:
                strike = updates.get(f"{condition.indicator}_strike")
                description += f" at ₹{strike:g}" if strike is not None else ""
            matched.append(description)
            strengths.append(_condition_strength(value, condition))
    return eligible, updates, matched, strengths


def _option_only_snapshot(
    company: Company,
    request: TechnicalScanRequest,
) -> IntradayTechnicalSnapshot:
    """Create a result shell without pretending candle indicators were calculated."""

    return IntradayTechnicalSnapshot(
        ticker=company.ticker,
        name=company.name,
        sector=company.sector,
        industry=company.industry,
        price=None,
        candle_time=datetime.now(UTC),
        candle_interval=request.candle_interval,
        candles_used=0,
        source="NSE India option chain",
        source_url=f"https://www.nseindia.com/option-chain?symbol={quote(company.ticker)}",
        is_delayed_or_unverified=True,
    )


async def run_technical_scan(
    db: AsyncSession,
    request: TechnicalScanRequest,
    *,
    provider: LLMProvider | None = None,
    candle_fetcher: CandleFetcher | None = None,
    options_fetcher: Callable[[str, str], Awaitable[dict]] | None = None,
    fno_symbols: set[str] | None = None,
) -> TechnicalScanResponse:
    settings = get_settings()
    provider = provider or get_provider()
    plan = await plan_technical_scan(request.query, provider=provider)
    plan.result_limit = request.result_limit
    companies = (
        (
            await db.execute(
                select(Company).where(Company.universe == "NSE_MAINBOARD").order_by(Company.ticker)
            )
        )
        .scalars()
        .all()
    )
    ticker_by_company = {company.id: company.ticker for company in companies}
    semantic_scores: dict = {}
    semantic_evidence: dict = {}
    candidates = companies
    limitations: list[str] = []

    if plan.semantic_concept:
        semantic_condition = SemanticCondition(
            id="business_concept",
            concept=plan.semantic_concept,
            card_types=TECHNICAL_CARD_TYPES,
            directness_required="any",
            required=True,
            weight=1.0,
        )
        semantic_results = await semantic_retrieval(
            db,
            [semantic_condition],
            ticker_by_company,
            provider=provider,
            company_ids=list(ticker_by_company),
        )
        semantic_scores = {result.company_id: result.combined_score for result in semantic_results}
        for result in semantic_results:
            match = result.per_condition.get("business_concept")
            if match and match.best_cards:
                semantic_evidence[result.company_id] = match.best_cards[0].text
        allowed = set(semantic_scores)
        candidates = [company for company in companies if company.id in allowed]

    option_conditions = [
        condition for condition in plan.conditions if condition.indicator in OPTION_INDICATORS
    ]
    technical_conditions = [
        condition for condition in plan.conditions if condition.indicator not in OPTION_INDICATORS
    ]
    if option_conditions:
        try:
            current_fno_symbols = (
                fno_symbols if fno_symbols is not None else await get_fno_underlyings()
            )
            candidates = [
                company for company in candidates if company.ticker.upper() in current_fno_symbols
            ]
        except Exception as exc:
            logger.warning("NSE F&O universe fetch failed: %s", exc)
            candidates = []
            limitations.append(
                "The official NSE F&O-underlying list was temporarily unavailable, so option filters could not be evaluated."
            )

    candle_scan_skipped = bool(option_conditions and not technical_conditions)
    fetcher: CandleFetcher | None = None
    snapshots: list[tuple[Company, IntradayTechnicalSnapshot]] = []
    if candle_scan_skipped:
        snapshots = [(company, _option_only_snapshot(company, request)) for company in candidates]
    else:
        fetcher = candle_fetcher or get_candle_fetcher()
        semaphore = asyncio.Semaphore(max(1, min(settings.technical_scan_concurrency, 20)))

        async def fetch_one(company: Company):
            async with semaphore:
                candles = await fetcher.fetch(
                    company, request.candle_interval, request.candle_count
                )
                payload = calculate_technical_snapshot(
                    company,
                    candles,
                    fetcher.source_name,
                    interval=request.candle_interval,
                    limit=request.candle_count,
                )
                return company, IntradayTechnicalSnapshot.model_validate(payload)

        tasks = [asyncio.create_task(fetch_one(company)) for company in candidates]
        done, pending = await asyncio.wait(
            tasks,
            timeout=max(5, settings.technical_scan_deadline_seconds),
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            try:
                snapshots.append(task.result())
            except Exception as exc:
                logger.debug("Technical candle fetch failed: %s", exc)

        closer = getattr(fetcher, "aclose", None)
        if closer:
            await closer()

    preliminaries: list[tuple[Company, IntradayTechnicalSnapshot, list[str], list[float]]] = []
    for company, snapshot in snapshots:
        matched: list[str] = []
        strengths: list[float] = []
        eligible = True
        for condition in technical_conditions:
            value = getattr(snapshot, condition.indicator)
            passed = _condition_passes(value, condition)
            if condition.required and not passed:
                eligible = False
                break
            if passed and value is not None:
                matched.append(_condition_description(condition, value))
                strengths.append(_condition_strength(value, condition))
        if not eligible:
            continue
        preliminaries.append((company, snapshot, matched, strengths))

    option_candidates = len(preliminaries) if option_conditions else 0
    options_scanned = 0
    options_available = 0
    options_failed = 0
    if option_conditions:
        # Per-symbol NSE option chains are intentionally bounded. Rank the
        # prefiltered set by technical fit and current relative-volume activity.
        preliminaries.sort(
            key=lambda item: (
                -(sum(item[3]) / len(item[3]) if item[3] else 0.5),
                -(item[1].relative_volume or 0),
                item[0].ticker,
            )
        )
        option_limit = max(1, settings.technical_option_scan_limit)
        preliminaries = preliminaries[:option_limit]
        chain_fetcher = options_fetcher or (
            lambda ticker, symbol: get_options_chain(ticker, symbol)
        )
        option_semaphore = asyncio.Semaphore(8)

        async def fetch_chain(
            item: tuple[Company, IntradayTechnicalSnapshot, list[str], list[float]],
        ):
            async with option_semaphore:
                company = item[0]
                chain = await chain_fetcher(company.ticker, company.ticker)
                return item, chain

        option_tasks = [asyncio.create_task(fetch_chain(item)) for item in preliminaries]
        if option_tasks:
            option_done, option_pending = await asyncio.wait(
                option_tasks,
                timeout=max(10, settings.technical_option_deadline_seconds),
            )
        else:
            option_done, option_pending = set(), set()
        for task in option_pending:
            task.cancel()
        if option_pending:
            await asyncio.gather(*option_pending, return_exceptions=True)

        enriched = []
        options_scanned = len(option_done)
        for task in option_done:
            try:
                item, chain = task.result()
            except Exception as exc:
                logger.debug("Option-chain fetch failed: %s", exc)
                options_failed += 1
                continue
            if chain.get("available"):
                options_available += 1
            else:
                options_failed += 1
            eligible, updates, matched, strengths = _evaluate_option_conditions(
                chain,
                option_conditions,
            )
            if eligible:
                company, snapshot, prior_matched, prior_strengths = item
                enriched.append(
                    (
                        company,
                        snapshot.model_copy(update=updates),
                        [*prior_matched, *matched],
                        [*prior_strengths, *strengths],
                    )
                )
        preliminaries = enriched

    results: list[TechnicalScanResult] = []
    for company, snapshot, matched, strengths in preliminaries:
        technical_score = sum(strengths) / len(strengths) if strengths else 0.5
        semantic_score = semantic_scores.get(company.id)
        combined_score = (
            0.55 * technical_score + 0.45 * semantic_score
            if semantic_score is not None
            else technical_score
        )
        results.append(
            TechnicalScanResult(
                **snapshot.model_dump(),
                technical_score=round(technical_score, 4),
                semantic_score=(round(semantic_score, 4) if semantic_score is not None else None),
                combined_score=round(combined_score, 4),
                matched_conditions=matched,
                semantic_evidence=semantic_evidence.get(company.id),
            )
        )

    if plan.sort_by:

        def ranking_key(result: TechnicalScanResult):
            value = getattr(result, plan.sort_by)
            if value is None or not math.isfinite(value):
                return (1, 0.0, result.ticker)
            ranked_value = value if plan.sort_direction == "asc" else -value
            return (0, ranked_value, result.ticker)

        results.sort(key=ranking_key)
    else:
        results.sort(key=lambda result: (-result.combined_score, result.ticker))
    results = results[: plan.result_limit]
    candle_scanned = 0 if candle_scan_skipped else len(snapshots)
    failed = 0 if candle_scan_skipped else len(candidates) - len(snapshots)
    if isinstance(fetcher, YahooCandleFetcher):
        limitations.append(
            "Yahoo's unofficial WebSocket updates the forming candle during NSE market hours; historical candles still come from yfinance and have no exchange-grade SLA."
        )
    if failed:
        limitations.append(
            f"{failed} candidate(s) did not return enough candles before the scan deadline."
        )
    if option_conditions:
        candidate_label = (
            "eligible F&O candidate(s)"
            if candle_scan_skipped
            else "technically eligible F&O candidate(s)"
        )
        limitations.extend(
            [
                (
                    f"Option filters checked {options_scanned} of {option_candidates} "
                    f"{candidate_label}, capped at "
                    f"{settings.technical_option_scan_limit} per scan."
                ),
                "Option metrics use the nearest listed expiry. Put delta is shown as an absolute magnitude; Greeks are Black-Scholes estimates, not exchange-supplied values.",
                "An increase in open interest does not by itself prove call/put writing or buying; price and premium context are still required.",
            ]
        )
        if plan.sort_by in OPTION_INDICATORS and option_candidates > options_scanned:
            limitations.append(
                f"The requested ranking is among the {options_scanned} option chains checked, not every F&O stock."
            )
    if candle_scan_skipped:
        limitations.append(
            "Candle retrieval was skipped because the parsed query contained only option-chain conditions."
        )
    else:
        limitations.append(
            f"Indicators use the latest {request.candle_count} {CANDLE_INTERVALS[request.candle_interval].label} candles; market-closed scans use the latest available session.",
        )
    limitations.append(
        "Scanner metrics are descriptive, not a trading recommendation or execution signal."
    )
    if results and settings.yahoo_live_stream_enabled and not settings.upstox_access_token.strip():
        company_by_ticker = {company.ticker: company for company in companies}
        aliases = {
            result.ticker: (
                company_by_ticker[result.ticker].market_data_ticker or f"{result.ticker}.NS"
            )
            for result in results
            if result.ticker in company_by_ticker
        }
        try:
            await get_yahoo_live_stream().ensure_subscribed(aliases)
        except Exception:
            logger.warning(
                "Could not add scan results to the Yahoo live stream",
                exc_info=True,
            )
    return TechnicalScanResponse(
        query=request.query,
        plan=plan,
        universe_size=len(companies),
        semantic_candidates=len(candidates),
        scanned=candle_scanned,
        failed=failed,
        candle_scan_skipped=candle_scan_skipped,
        option_candidates=option_candidates,
        options_scanned=options_scanned,
        options_available=options_available,
        options_failed=options_failed,
        returned=len(results),
        candle_interval=request.candle_interval,
        candle_limit=request.candle_count,
        generated_at=datetime.now(UTC),
        data_source=("NSE India option chain" if candle_scan_skipped else fetcher.source_name),
        results=results,
        limitations=limitations,
    )
