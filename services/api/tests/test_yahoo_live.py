"""Unit coverage for Yahoo live quote and candle overlays."""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.yahoo_live import YahooLiveStream, interval_bucket, split_stream_symbols

IST = ZoneInfo("Asia/Kolkata")


def _message(price: float, time: datetime, day_volume: int) -> dict:
    return {
        "id": "RELIANCE.NS",
        "price": price,
        "time": str(int(time.timestamp() * 1000)),
        "day_volume": str(day_volume),
        "last_size": "10",
        "market_hours": 1,
    }


def test_interval_buckets_are_anchored_to_nse_open():
    value = datetime(2026, 7, 22, 10, 44, 12, tzinfo=IST)

    assert interval_bucket(value, "5m") == datetime(2026, 7, 22, 10, 40, tzinfo=IST)
    assert interval_bucket(value, "1h") == datetime(2026, 7, 22, 10, 15, tzinfo=IST)
    assert interval_bucket(value, "1d") == datetime(2026, 7, 22, 0, 0, tzinfo=IST)


def test_full_nse_universe_is_split_below_yahoo_connection_ceiling():
    symbols = {f"STOCK{index}.NS" for index in range(200)}
    shards = split_stream_symbols(symbols)

    assert len(shards) == 4
    assert all(len(shard) == 50 for shard in shards)
    assert {symbol for shard in shards for symbol in shard} == symbols


def test_stream_aggregates_ticks_and_cumulative_volume_into_live_candle():
    stream = YahooLiveStream()
    first = datetime(2026, 7, 22, 9, 16, 1, tzinfo=IST)
    second = datetime(2026, 7, 22, 9, 17, 2, tzinfo=IST)

    stream._handle_message(_message(100.0, first, 1_000))
    stream._handle_message(_message(102.0, second, 1_125))
    candle = stream.current_candle("RELIANCE.NS", "5m")

    assert candle is not None
    assert candle["time"] == datetime(2026, 7, 22, 9, 15, tzinfo=IST).isoformat()
    assert candle["open"] == 100.0
    assert candle["high"] == 102.0
    assert candle["low"] == 100.0
    assert candle["close"] == 102.0
    assert candle["volume"] == 125


def test_live_overlay_updates_existing_forming_candle_without_caching_it():
    stream = YahooLiveStream()
    first = datetime(2026, 7, 22, 9, 16, 1, tzinfo=IST)
    second = datetime(2026, 7, 22, 9, 17, 2, tzinfo=IST)
    stream._handle_message(_message(100.0, first, 1_000))
    stream._handle_message(_message(102.0, second, 1_125))
    historical = [
        {
            "time": datetime(2026, 7, 22, 9, 15, tzinfo=IST).isoformat(),
            "open": 99.0,
            "high": 101.0,
            "low": 98.0,
            "close": 100.5,
            "volume": 500,
        }
    ]

    overlaid = stream.overlay_current_candle(
        historical, "RELIANCE.NS", "5m", limit=70
    )

    assert historical[0]["close"] == 100.5
    assert overlaid[0]["open"] == 99.0
    assert overlaid[0]["high"] == 102.0
    assert overlaid[0]["low"] == 98.0
    assert overlaid[0]["close"] == 102.0
    assert overlaid[0]["volume"] == 500


async def test_dynamic_subscriptions_fill_existing_shard_and_respect_capacity():
    class FakeSocket:
        def __init__(self):
            self.subscriptions = []

        async def subscribe(self, symbols):
            self.subscriptions.append(list(symbols))

    stream = YahooLiveStream()
    blocker = asyncio.create_task(asyncio.Event().wait())
    socket = FakeSocket()
    stream._tasks = [blocker]
    stream._aliases = {"BASE": "BASE.NS"}
    stream._symbols = {"BASE.NS"}
    stream._base_symbols = {"BASE.NS"}
    stream._max_symbols = 3
    stream._shard_symbols = {0: ["BASE.NS"]}
    stream._sockets = {0: socket}
    stream._connected_shards = {0}

    additions = await stream.ensure_subscribed(
        {
            "RESULT1": "RESULT1.NS",
            "RESULT2": "RESULT2.NS",
            "RESULT3": "RESULT3.NS",
        }
    )

    blocker.cancel()
    await asyncio.gather(blocker, return_exceptions=True)
    assert additions == ["RESULT1.NS", "RESULT2.NS"]
    assert stream._shard_symbols[0] == ["BASE.NS", "RESULT1.NS", "RESULT2.NS"]
    assert socket.subscriptions == [["RESULT1.NS", "RESULT2.NS"]]
    assert stream.status()["base_symbols"] == 1
    assert stream.status()["dynamic_symbols"] == 2
