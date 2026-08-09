"""Normalized NSE block-deal disclosures for the market workspace."""

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.services.nse.client import get_nse_client

logger = logging.getLogger(__name__)

NSE_LARGE_DEALS_URL = "https://www.nseindia.com/market-data/large-deals"
INDIA_TZ = ZoneInfo("Asia/Kolkata")


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    raw = str(value).strip()
    for pattern in ("%d-%b-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.title(), pattern).date()
        except ValueError:
            continue
    return None


def normalize_block_deal(row: dict) -> dict | None:
    """Normalize either the historical or latest-snapshot NSE response shape."""

    trade_date = _parse_date(row.get("BD_DT_DATE") or row.get("date"))
    symbol = str(row.get("BD_SYMBOL") or row.get("symbol") or "").strip().upper()
    client_name = str(row.get("BD_CLIENT_NAME") or row.get("clientName") or "").strip()
    side = str(row.get("BD_BUY_SELL") or row.get("buySell") or "").strip().upper()
    quantity = _number(row.get("BD_QTY_TRD") or row.get("qty"))
    price = _number(row.get("BD_TP_WATP") or row.get("watp"))
    if (
        trade_date is None
        or not symbol
        or not client_name
        or side not in {"BUY", "SELL"}
        or quantity is None
        or price is None
    ):
        return None
    return {
        "trade_date": trade_date,
        "symbol": symbol,
        "company_name": str(
            row.get("BD_SCRIP_NAME") or row.get("name") or symbol
        ).strip(),
        "client_name": client_name,
        "side": side,
        "quantity": quantity,
        "weighted_average_price": price,
        "trade_value_inr": round(quantity * price, 2),
    }


async def get_block_deals(days: int = 30, *, today: date | None = None) -> dict:
    """Return recent NSE block deals, falling back to the latest public snapshot."""

    as_of = today or datetime.now(INDIA_TZ).date()
    from_date = as_of - timedelta(days=days - 1)
    client = get_nse_client()
    used_latest_snapshot = False
    limitation = (
        "NSE block-deal disclosures are published after market hours and do not "
        "represent a live institutional order feed."
    )
    try:
        # NSE can silently cap large date-range responses. Weekly chunks keep each
        # response bounded while requiring only a handful of cached requests.
        raw_rows: list[dict] = []
        chunk_start = from_date
        while chunk_start <= as_of:
            chunk_end = min(chunk_start + timedelta(days=6), as_of)
            raw_rows.extend(
                await client.get_historical_deals("block_deals", chunk_start, chunk_end)
            )
            chunk_start = chunk_end + timedelta(days=1)
    except Exception as exc:
        logger.warning("NSE block-deal history failed; using latest snapshot: %s", exc)
        snapshot = await client.get_large_deals_snapshot()
        raw_rows = list(snapshot.get("BLOCK_DEALS_DATA") or [])
        used_latest_snapshot = True
        limitation += " Historical data was unavailable, so only the latest snapshot is shown."

    deals = [deal for row in raw_rows if (deal := normalize_block_deal(row)) is not None]
    unique: dict[tuple, dict] = {}
    for deal in deals:
        identity = (
            deal["trade_date"],
            deal["symbol"],
            deal["client_name"],
            deal["side"],
            deal["quantity"],
            deal["weighted_average_price"],
        )
        unique[identity] = deal
    sorted_deals = sorted(
        unique.values(),
        key=lambda deal: (deal["trade_date"], deal["trade_value_inr"]),
        reverse=True,
    )
    return {
        "market": "IN",
        "exchange": "NSE",
        "from_date": from_date,
        "to_date": as_of,
        "retrieved_at": datetime.now(UTC),
        "source": "NSE India",
        "source_url": NSE_LARGE_DEALS_URL,
        "used_latest_snapshot": used_latest_snapshot,
        "limitation": limitation,
        "deals": sorted_deals,
    }
