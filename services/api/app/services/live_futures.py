"""Authenticated live NSE futures quotes for paper-pair valuation."""

from __future__ import annotations

import asyncio
import gzip
import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime

import httpx

from app.core.config import get_settings

UPSTOX_NSE_INSTRUMENTS_URL = (
    "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
)
INSTRUMENT_FILE_TIMEOUT_SECONDS = 45
QUOTE_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class LiveFuturesQuote:
    ticker: str
    expiry: date
    instrument_key: str
    price: float
    received_at: datetime
    source: str = "Upstox V3 live futures LTP"


_instrument_lock = asyncio.Lock()
_instrument_file_date: date | None = None
_futures_instruments: dict[tuple[str, date], str] = {}


def _instrument_expiry(value: object) -> date | None:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value) / 1000, tz=UTC).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def futures_instrument_map(rows: list[dict]) -> dict[tuple[str, date], str]:
    """Index current Upstox NSE stock/index futures by underlying and expiry."""

    resolved: dict[tuple[str, date], str] = {}
    for row in rows:
        if row.get("segment") != "NSE_FO" or row.get("instrument_type") != "FUT":
            continue
        ticker = str(row.get("underlying_symbol") or "").strip().upper()
        instrument_key = str(row.get("instrument_key") or "").strip()
        expiry = _instrument_expiry(row.get("expiry"))
        if ticker and instrument_key and expiry is not None:
            resolved[(ticker, expiry)] = instrument_key
    return resolved


async def _load_futures_instruments() -> dict[tuple[str, date], str]:
    global _instrument_file_date, _futures_instruments

    today = datetime.now(UTC).date()
    if _instrument_file_date == today and _futures_instruments:
        return _futures_instruments
    async with _instrument_lock:
        if _instrument_file_date == today and _futures_instruments:
            return _futures_instruments
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(INSTRUMENT_FILE_TIMEOUT_SECONDS),
            follow_redirects=True,
        ) as client:
            response = await client.get(UPSTOX_NSE_INSTRUMENTS_URL)
            response.raise_for_status()
        raw = response.content
        try:
            raw = gzip.decompress(raw)
        except gzip.BadGzipFile:
            # Some HTTP stacks transparently decompress a .gz response.
            pass
        rows = json.loads(raw)
        if not isinstance(rows, list):
            raise ValueError("Upstox NSE instrument file is not a JSON array")
        _futures_instruments = futures_instrument_map(rows)
        _instrument_file_date = today
        return _futures_instruments


async def get_live_futures_quotes(
    contracts: set[tuple[str, date]],
) -> tuple[dict[tuple[str, date], LiveFuturesQuote], str | None]:
    """Return bulk live LTPs for exact NSE futures contracts."""

    if not contracts:
        return {}, None
    settings = get_settings()
    token = settings.upstox_access_token.strip()
    if not token:
        return {}, (
            "Live futures prices are unavailable because UPSTOX_ACCESS_TOKEN is not "
            "configured."
        )
    try:
        instruments = await _load_futures_instruments()
    except (httpx.HTTPError, OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, f"The live futures instrument map could not be loaded: {exc}"

    requested_keys = {
        contract: instruments.get((contract[0].upper(), contract[1]))
        for contract in contracts
    }
    missing = [contract for contract, key in requested_keys.items() if not key]
    if missing:
        labels = ", ".join(f"{ticker} {expiry.isoformat()}" for ticker, expiry in missing)
        return {}, f"Live futures instrument keys were unavailable for: {labels}."

    instrument_keys = [key for key in requested_keys.values() if key]
    try:
        async with httpx.AsyncClient(
            base_url=settings.upstox_base_url.rstrip("/"),
            timeout=httpx.Timeout(QUOTE_TIMEOUT_SECONDS),
        ) as client:
            response = await client.get(
                "/market-quote/ltp",
                params={"instrument_key": ",".join(instrument_keys)},
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return {}, f"The authenticated live futures quote request failed: {exc}"

    rows_by_token = {
        str(row.get("instrument_token") or ""): row
        for row in (payload.get("data") or {}).values()
        if isinstance(row, dict)
    }
    received_at = datetime.now(UTC)
    quotes: dict[tuple[str, date], LiveFuturesQuote] = {}
    for (ticker, expiry), instrument_key in requested_keys.items():
        row = rows_by_token.get(str(instrument_key))
        try:
            price = float((row or {}).get("last_price"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        quotes[(ticker.upper(), expiry)] = LiveFuturesQuote(
            ticker=ticker.upper(),
            expiry=expiry,
            instrument_key=str(instrument_key),
            price=price,
            received_at=received_at,
        )
    if len(quotes) != len(contracts):
        return quotes, "At least one exact futures contract did not return a live LTP."
    return quotes, None
