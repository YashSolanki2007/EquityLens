"""Best-effort Yahoo quote stream and current-candle aggregation.

Yahoo's stream supplies trades/quotes, not historical bars.  This service keeps
the most recent quote and builds minute bars in memory; the technical scanner
merges the current live bar into its yfinance historical backfill.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import yfinance as yf

logger = logging.getLogger(__name__)

INDIA_TZ = ZoneInfo("Asia/Kolkata")
REGULAR_MARKET_HOURS = 1
STREAM_SHARD_SIZE = 50
INTERVAL_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
}


@dataclass(frozen=True)
class LiveQuote:
    symbol: str
    price: float
    event_time: datetime
    received_at: datetime
    day_volume: int | None
    last_size: int | None
    market_hours: int | None

    def public_dict(self, ticker: str) -> dict:
        return {
            "ticker": ticker,
            "symbol": self.symbol,
            "price": self.price,
            "event_time": self.event_time.isoformat(),
            "received_at": self.received_at.isoformat(),
            "market_hours": self.market_hours,
        }


@dataclass
class MinuteBar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _event_datetime(value: object) -> datetime:
    milliseconds = _as_int(value)
    if milliseconds is None:
        return datetime.now(UTC)
    try:
        return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return datetime.now(UTC)


def interval_bucket(value: datetime, interval: str) -> datetime:
    """Return the NSE candle start, anchored to the 09:15 IST open."""
    local = value.astimezone(INDIA_TZ)
    if interval == "1d":
        return local.replace(hour=0, minute=0, second=0, microsecond=0)

    width = INTERVAL_MINUTES[interval]
    open_minute = 9 * 60 + 15
    minute_of_day = local.hour * 60 + local.minute
    offset = minute_of_day - open_minute
    bucket_offset = math.floor(offset / width) * width
    bucket_minute = open_minute + bucket_offset
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + timedelta(minutes=bucket_minute)


def split_stream_symbols(symbols: set[str], size: int = STREAM_SHARD_SIZE) -> list[list[str]]:
    """Split a universe below Yahoo's observed per-connection delivery ceiling."""
    ordered = sorted(symbols)
    return [ordered[index : index + size] for index in range(0, len(ordered), size)]


class YahooLiveStream:
    """One shared, sharded Yahoo stream pool for the Indian universe."""

    def __init__(self) -> None:
        self._aliases: dict[str, str] = {}
        self._symbols: set[str] = set()
        self._base_symbols: set[str] = set()
        self._base_label = "configured universe"
        self._max_symbols = 500
        self._quotes: dict[str, LiveQuote] = {}
        self._minute_bars: dict[str, dict[datetime, MinuteBar]] = {}
        self._last_day_volume: dict[str, tuple[datetime.date, int]] = {}
        self._tasks: list[asyncio.Task] = []
        self._sockets: dict[int, yf.AsyncWebSocket] = {}
        self._shard_symbols: dict[int, list[str]] = {}
        self._connected_shards: set[int] = set()
        self._shard_errors: dict[int, str] = {}
        self._subscription_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self.started_at: datetime | None = None
        self.last_message_at: datetime | None = None

    @property
    def connected(self) -> bool:
        return bool(self._tasks) and len(self._connected_shards) == len(self._tasks)

    @property
    def last_error(self) -> str | None:
        if not self._shard_errors:
            return None
        return "; ".join(
            f"shard {index + 1}: {error}"
            for index, error in sorted(self._shard_errors.items())
        )

    async def start(
        self,
        aliases: dict[str, str],
        *,
        base_label: str = "configured universe",
        max_symbols: int = 500,
    ) -> None:
        if any(not task.done() for task in self._tasks):
            return
        normalized_aliases = {
            ticker.upper(): symbol.upper()
            for ticker, symbol in aliases.items()
            if ticker and symbol
        }
        self._max_symbols = max(1, max_symbols)
        self._aliases = dict(
            list(sorted(normalized_aliases.items()))[: self._max_symbols]
        )
        self._symbols = set(self._aliases.values())
        self._base_symbols = set(self._symbols)
        self._base_label = base_label
        if not self._symbols:
            logger.warning("Yahoo live stream was not started because no symbols were loaded")
            return
        self._stop.clear()
        self.started_at = datetime.now(UTC)
        self._quotes.clear()
        self._minute_bars.clear()
        self._last_day_volume.clear()
        self._connected_shards.clear()
        self._shard_errors.clear()
        shards = split_stream_symbols(self._symbols)
        self._shard_symbols = {
            index: list(shard) for index, shard in enumerate(shards)
        }
        self._tasks = [
            asyncio.create_task(
                self._run_shard(index),
                name=f"yahoo-live-stream-{index + 1}",
            )
            for index in self._shard_symbols
        ]

    async def ensure_subscribed(self, aliases: dict[str, str]) -> list[str]:
        """Add scan-result symbols without allowing unbounded socket growth."""

        if not any(not task.done() for task in self._tasks):
            return []
        async with self._subscription_lock:
            candidates: list[str] = []
            for raw_ticker, raw_symbol in sorted(aliases.items()):
                ticker = raw_ticker.strip().upper()
                symbol = raw_symbol.strip().upper()
                if not ticker or not symbol:
                    continue
                self._aliases[ticker] = symbol
                if symbol not in self._symbols and symbol not in candidates:
                    candidates.append(symbol)
            room = max(0, self._max_symbols - len(self._symbols))
            additions = candidates[:room]
            if not additions:
                return []
            self._symbols.update(additions)

            remaining = list(additions)
            for shard_index in sorted(self._shard_symbols):
                shard = self._shard_symbols[shard_index]
                take = min(STREAM_SHARD_SIZE - len(shard), len(remaining))
                if take <= 0:
                    continue
                shard_additions = remaining[:take]
                del remaining[:take]
                shard.extend(shard_additions)
                socket = self._sockets.get(shard_index)
                if socket is not None and shard_index in self._connected_shards:
                    try:
                        await socket.subscribe(shard_additions)
                    except Exception:
                        logger.warning(
                            "Yahoo dynamic subscription failed on shard %s; reconnecting",
                            shard_index + 1,
                            exc_info=True,
                        )
                        await socket.close()
                if not remaining:
                    break

            while remaining:
                shard_index = max(self._shard_symbols, default=-1) + 1
                shard = remaining[:STREAM_SHARD_SIZE]
                del remaining[:STREAM_SHARD_SIZE]
                self._shard_symbols[shard_index] = shard
                self._tasks.append(
                    asyncio.create_task(
                        self._run_shard(shard_index),
                        name=f"yahoo-live-stream-{shard_index + 1}",
                    )
                )
            return additions

    async def stop(self) -> None:
        self._stop.set()
        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            task.cancel()
        for socket in list(self._sockets.values()):
            try:
                await socket.close()
            except Exception:
                logger.debug("Yahoo socket close failed", exc_info=True)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._sockets.clear()
        self._shard_symbols.clear()
        self._connected_shards.clear()
        self._shard_errors.clear()

    async def _run_shard(self, shard_index: int) -> None:
        backoff = 2
        while not self._stop.is_set():
            socket = yf.AsyncWebSocket(verbose=False)
            self._sockets[shard_index] = socket
            try:
                await socket.subscribe(list(self._shard_symbols[shard_index]))
                self._connected_shards.add(shard_index)
                self._shard_errors.pop(shard_index, None)
                backoff = 2
                # yfinance's public listener retries internally but can retain a
                # closed transport. Reading the transport here lets this outer loop
                # recreate the client with bounded exponential backoff.
                transport = socket._ws
                if transport is None:
                    raise ConnectionError("Yahoo WebSocket transport was not created")
                async for raw_message in transport:
                    envelope = json.loads(raw_message)
                    decoded = socket._decode_message(envelope.get("message", ""))
                    self._handle_message(decoded)
                raise ConnectionError("Yahoo WebSocket closed")
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._shard_errors[shard_index] = str(exc)
                logger.warning(
                    "Yahoo live stream shard %s disconnected: %s",
                    shard_index + 1,
                    exc,
                )
            finally:
                self._connected_shards.discard(shard_index)
                try:
                    await socket.close()
                except Exception:
                    logger.debug("Yahoo socket cleanup failed", exc_info=True)
                if self._sockets.get(shard_index) is socket:
                    del self._sockets[shard_index]
            if not self._stop.is_set():
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    def _handle_message(self, message: dict) -> None:
        symbol = str(message.get("id") or "").upper()
        if not symbol:
            return
        try:
            price = float(message["price"])
        except (KeyError, TypeError, ValueError):
            return
        if not math.isfinite(price) or price <= 0:
            return

        now = datetime.now(UTC)
        event_time = _event_datetime(message.get("time"))
        day_volume = _as_int(message.get("day_volume"))
        last_size = _as_int(message.get("last_size"))
        market_hours = _as_int(message.get("market_hours"))
        quote = LiveQuote(
            symbol=symbol,
            price=price,
            event_time=event_time,
            received_at=now,
            day_volume=day_volume,
            last_size=last_size,
            market_hours=market_hours,
        )
        self._quotes[symbol] = quote
        self.last_message_at = now

        if market_hours != REGULAR_MARKET_HOURS:
            return
        volume_delta = 0
        event_date = event_time.astimezone(INDIA_TZ).date()
        previous = self._last_day_volume.get(symbol)
        if day_volume is not None:
            if previous and previous[0] == event_date and day_volume >= previous[1]:
                volume_delta = day_volume - previous[1]
            self._last_day_volume[symbol] = (event_date, day_volume)
        elif last_size is not None and last_size > 0:
            volume_delta = last_size

        minute = interval_bucket(event_time, "1m")
        bars = self._minute_bars.setdefault(symbol, {})
        bar = bars.get(minute)
        if bar is None:
            bars[minute] = MinuteBar(minute, price, price, price, price, volume_delta)
        else:
            bar.high = max(bar.high, price)
            bar.low = min(bar.low, price)
            bar.close = price
            bar.volume += volume_delta

        # Only the current and previous session are useful for live overlays.
        cutoff = minute - timedelta(days=2)
        for old_minute in [key for key in bars if key < cutoff]:
            del bars[old_minute]

    def resolve_symbol(self, ticker: str) -> str:
        return self._aliases.get(ticker.upper(), ticker.upper())

    def latest(self, ticker_or_symbol: str) -> LiveQuote | None:
        return self._quotes.get(self.resolve_symbol(ticker_or_symbol))

    def public_quotes(self, tickers: list[str]) -> list[dict]:
        quotes = []
        for ticker in tickers:
            quote = self.latest(ticker)
            if quote:
                quotes.append(quote.public_dict(ticker.upper()))
        return quotes

    def current_candle(self, symbol: str, interval: str) -> dict | None:
        quote = self.latest(symbol)
        if quote is None or quote.market_hours != REGULAR_MARKET_HOURS:
            return None
        target = interval_bucket(quote.event_time, interval)
        minute_bars = self._minute_bars.get(quote.symbol, {})
        relevant = sorted(
            (bar for bar in minute_bars.values() if interval_bucket(bar.time, interval) == target),
            key=lambda bar: bar.time,
        )
        if not relevant:
            return None
        return {
            "time": target.isoformat(),
            "open": relevant[0].open,
            "high": max(bar.high for bar in relevant),
            "low": min(bar.low for bar in relevant),
            "close": relevant[-1].close,
            "volume": sum(bar.volume for bar in relevant),
        }

    def overlay_current_candle(
        self, candles: list[dict], symbol: str, interval: str, limit: int
    ) -> list[dict]:
        live = self.current_candle(symbol, interval)
        if live is None:
            return [dict(candle) for candle in candles]
        output = [dict(candle) for candle in candles]
        live_bucket = interval_bucket(datetime.fromisoformat(live["time"]), interval)
        if output:
            latest_time = datetime.fromisoformat(str(output[-1]["time"]))
            latest_bucket = interval_bucket(latest_time, interval)
            if latest_bucket == live_bucket:
                latest = output[-1]
                latest["high"] = max(float(latest["high"]), float(live["high"]))
                latest["low"] = min(float(latest["low"]), float(live["low"]))
                latest["close"] = live["close"]
                latest["volume"] = max(
                    float(latest.get("volume") or 0), float(live.get("volume") or 0)
                )
                return output[-limit:]
            if latest_bucket > live_bucket:
                return output[-limit:]
        output.append(live)
        return output[-limit:]

    def status(self) -> dict:
        return {
            "enabled": bool(self._symbols),
            "connected": self.connected,
            "connected_shards": len(self._connected_shards),
            "total_shards": len(self._tasks),
            "subscribed_symbols": len(self._symbols),
            "base_symbols": len(self._base_symbols),
            "dynamic_symbols": len(self._symbols - self._base_symbols),
            "max_symbols": self._max_symbols,
            "base_label": self._base_label,
            "quotes_received": len(self._quotes),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_message_at": (self.last_message_at.isoformat() if self.last_message_at else None),
            "last_error": self.last_error,
        }


_stream = YahooLiveStream()


def get_yahoo_live_stream() -> YahooLiveStream:
    return _stream
