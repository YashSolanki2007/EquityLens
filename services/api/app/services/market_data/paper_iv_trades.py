"""Persistence and executable-price marking for paper IV strategies."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session_factory
from app.models import PaperIVTrade, PaperIVTradeMark
from app.services.market_data.iv_surface import implied_volatility_percent

NSE_DATE_FORMAT = "%d-%b-%Y"
NSE_TIMESTAMP_FORMAT = "%d-%b-%Y %H:%M:%S"
logger = logging.getLogger(__name__)


def _parse_exchange_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return (
            datetime.strptime(value, NSE_TIMESTAMP_FORMAT)
            .replace(tzinfo=ZoneInfo("Asia/Kolkata"))
            .astimezone(UTC)
        )
    except ValueError:
        return None


def _exit_price(
    option: dict[str, Any] | None,
    close_action: str,
) -> tuple[float | None, str | None]:
    if not option:
        return None, None
    preferred_field = "ask_price" if close_action == "buy" else "bid_price"
    preferred = option.get(preferred_field)
    if preferred is not None and float(preferred) > 0:
        return float(preferred), "ask" if close_action == "buy" else "bid"
    last = option.get("last_price")
    if last is not None and float(last) > 0:
        return float(last), "last traded"
    return None, None


def _current_option_iv(
    *,
    option: dict[str, Any],
    option_type: str,
    option_price: float,
    strike: float,
    chain: dict[str, Any],
) -> tuple[float | None, str | None]:
    reported = option.get("implied_volatility")
    if reported is not None:
        try:
            reported_value = float(reported)
        except (TypeError, ValueError):
            reported_value = 0.0
        if reported_value > 0:
            return reported_value, "exchange reported"
    try:
        spot = float(chain["underlying_value"])
        expiry = datetime.strptime(str(chain["selected_expiry"]), NSE_DATE_FORMAT).date()
    except (KeyError, TypeError, ValueError):
        return None, None
    exchange_timestamp = _parse_exchange_timestamp(chain.get("exchange_timestamp"))
    as_of = (
        exchange_timestamp.astimezone(ZoneInfo("Asia/Kolkata")).date()
        if exchange_timestamp is not None
        else datetime.now(ZoneInfo("Asia/Kolkata")).date()
    )
    days_to_expiry = (expiry - as_of).days
    if days_to_expiry <= 0:
        return None, None
    derived = implied_volatility_percent(
        option_type,
        option_price,
        spot,
        strike,
        days_to_expiry / 365.25,
    )
    return derived, "derived from close quote" if derived is not None else None


def reconstruct_historical_leg_ivs(
    *,
    leg_marks: list[dict[str, Any]],
    underlying_value: float | None,
    expiry,
    source_timestamp: datetime | None,
    created_at: datetime,
) -> list[dict[str, Any]]:
    """Fill IVs missing from marks saved before IV follow-through existed.

    The reconstruction uses the exact close-out quote and underlying value that
    were saved with the paper mark. It therefore preserves the original
    observation instead of substituting today's option chain.
    """

    reconstructed = [dict(leg) for leg in leg_marks]
    if underlying_value is None or float(underlying_value) <= 0:
        return reconstructed
    observed_at = source_timestamp or created_at
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=UTC)
    as_of = observed_at.astimezone(ZoneInfo("Asia/Kolkata")).date()
    days_to_expiry = (expiry - as_of).days
    if days_to_expiry <= 0:
        return reconstructed

    for leg in reconstructed:
        if leg.get("current_iv_percent") is not None:
            leg.setdefault("iv_source", "saved observation")
            continue
        try:
            derived = implied_volatility_percent(
                str(leg["option_type"]),
                float(leg["close_price_per_unit"]),
                float(underlying_value),
                float(leg["strike_price"]),
                days_to_expiry / 365.25,
            )
        except (KeyError, TypeError, ValueError):
            derived = None
        if derived is not None:
            leg["current_iv_percent"] = round(derived, 4)
            leg["iv_source"] = "reconstructed from saved close quote"
    return reconstructed


def calculate_paper_iv_mark(
    *,
    legs: list[dict[str, Any]],
    lot_size: int,
    quantity_lots: int,
    entry_premium_type: str,
    entry_cash_flow_per_lot: float,
    capital_at_risk_per_lot: float,
    chain: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    """Value a saved strategy at the prices required to close it now."""

    if not chain.get("available"):
        return None, chain.get("limitation") or "The option chain is unavailable."

    rows = list(chain.get("strikes") or [])
    row_by_strike = {
        round(float(row["strike_price"]), 4): row
        for row in rows
        if row.get("strike_price") is not None
    }
    leg_marks: list[dict[str, Any]] = []
    close_cash_flow = 0.0
    estimated = False

    for leg in legs:
        strike = float(leg["strike_price"])
        row = row_by_strike.get(round(strike, 4))
        option_type = str(leg["option_type"])
        option = (row or {}).get(option_type)
        original_action = str(leg["action"])
        close_action = "sell" if original_action == "buy" else "buy"
        close_price, price_source = _exit_price(option, close_action)
        if close_price is None or price_source is None:
            return (
                None,
                f"No usable {close_action} price is available for the "
                f"₹{strike:g} {option_type}.",
            )

        leg_quantity_lots = int(leg.get("quantity_lots") or 1) * quantity_lots
        current_iv, current_iv_source = _current_option_iv(
            option=option,
            option_type=option_type,
            option_price=close_price,
            strike=strike,
            chain=chain,
        )
        quantity_units = leg_quantity_lots * lot_size
        leg_cash_flow = close_price * quantity_units
        if close_action == "buy":
            leg_cash_flow *= -1
        close_cash_flow += leg_cash_flow
        estimated = estimated or price_source == "last traded"
        leg_marks.append(
            {
                "original_action": original_action,
                "close_action": close_action,
                "option_type": option_type,
                "strike_price": round(strike, 2),
                "quantity_lots": leg_quantity_lots,
                "quantity_units": quantity_units,
                "entry_price_per_unit": round(float(leg["premium_per_unit"]), 2),
                "close_price_per_unit": round(close_price, 2),
                "close_price_source": price_source,
                "close_cash_flow": round(leg_cash_flow, 2),
                "current_iv_percent": (
                    round(current_iv, 4) if current_iv is not None else None
                ),
                "iv_source": current_iv_source,
            }
        )

    entry_amount = float(entry_cash_flow_per_lot) * quantity_lots
    entry_cash_flow = -entry_amount if entry_premium_type == "debit" else entry_amount
    pnl = entry_cash_flow + close_cash_flow
    capital_at_risk = float(capital_at_risk_per_lot) * quantity_lots
    pnl_percent = pnl / capital_at_risk * 100 if capital_at_risk > 0 else 0.0
    return (
        {
            "underlying_value": chain.get("underlying_value"),
            "close_cash_flow": round(close_cash_flow, 2),
            "pnl": round(pnl, 2),
            "pnl_percent": round(pnl_percent, 2),
            "leg_marks": leg_marks,
            "source_timestamp": _parse_exchange_timestamp(
                chain.get("exchange_timestamp")
            ),
            "price_quality": "estimated" if estimated else "executable",
        },
        None,
    )


async def latest_trade_mark(
    db: AsyncSession,
    trade_id,
) -> PaperIVTradeMark | None:
    return (
        await db.execute(
            select(PaperIVTradeMark)
            .where(PaperIVTradeMark.trade_id == trade_id)
            .order_by(desc(PaperIVTradeMark.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()


async def refresh_trade_mark(
    db: AsyncSession,
    trade: PaperIVTrade,
    chain: dict[str, Any],
) -> tuple[PaperIVTradeMark | None, str | None]:
    if chain.get("selected_expiry") != trade.expiry.strftime(NSE_DATE_FORMAT):
        return (
            await latest_trade_mark(db, trade.id),
            "The saved expiry is no longer present in the current NSE option chain.",
        )

    values, limitation = calculate_paper_iv_mark(
        legs=list(trade.legs),
        lot_size=trade.lot_size,
        quantity_lots=trade.quantity_lots,
        entry_premium_type=trade.entry_premium_type,
        entry_cash_flow_per_lot=trade.entry_cash_flow_per_lot,
        capital_at_risk_per_lot=trade.capital_at_risk_per_lot,
        chain=chain,
    )
    if values is None:
        return await latest_trade_mark(db, trade.id), limitation

    previous = await latest_trade_mark(db, trade.id)
    if (
        previous is not None
        and values["source_timestamp"] is not None
        and previous.source_timestamp == values["source_timestamp"]
    ):
        if not any(
            leg.get("current_iv_percent") is not None
            for leg in list(previous.leg_marks or [])
        ):
            previous.leg_marks = values["leg_marks"]
            previous.underlying_value = values["underlying_value"]
            previous.close_cash_flow = values["close_cash_flow"]
            previous.pnl = values["pnl"]
            previous.pnl_percent = values["pnl_percent"]
            previous.price_quality = values["price_quality"]
        return previous, limitation

    mark = PaperIVTradeMark(trade_id=trade.id, **values)
    db.add(mark)
    await db.flush()
    return mark, limitation


async def trade_marks(
    db: AsyncSession,
    trade_id,
) -> list[PaperIVTradeMark]:
    return list(
        (
            await db.execute(
                select(PaperIVTradeMark)
                .where(PaperIVTradeMark.trade_id == trade_id)
                .order_by(PaperIVTradeMark.created_at)
            )
        )
        .scalars()
        .all()
    )


def paper_trade_response(
    trade: PaperIVTrade,
    marks: list[PaperIVTradeMark],
    *,
    valuation_limitation: str | None = None,
) -> dict[str, Any]:
    entry_amount = trade.entry_cash_flow_per_lot * trade.quantity_lots
    entry_cash_flow = (
        -entry_amount if trade.entry_premium_type == "debit" else entry_amount
    )

    def serialize_mark(mark: PaperIVTradeMark) -> dict[str, Any]:
        leg_marks = reconstruct_historical_leg_ivs(
            leg_marks=list(mark.leg_marks or []),
            underlying_value=mark.underlying_value,
            expiry=trade.expiry,
            source_timestamp=mark.source_timestamp,
            created_at=mark.created_at,
        )
        current_ivs = [
            float(leg["current_iv_percent"])
            for leg in leg_marks
            if leg.get("current_iv_percent") is not None
        ]
        return {
            "id": mark.id,
            "underlying_value": mark.underlying_value,
            "close_cash_flow": mark.close_cash_flow,
            "pnl": mark.pnl,
            "pnl_percent": mark.pnl_percent,
            "leg_marks": leg_marks,
            "source_timestamp": mark.source_timestamp,
            "price_quality": mark.price_quality,
            "current_market_iv_percent": (
                round(sum(current_ivs) / len(current_ivs), 4)
                if current_ivs
                else None
            ),
            "created_at": mark.created_at,
        }

    serialized_marks = [serialize_mark(mark) for mark in marks]
    return {
        "id": trade.id,
        "portfolio_id": trade.portfolio_id,
        "ticker": trade.ticker,
        "symbol": trade.symbol,
        "strategy_name": trade.strategy_name,
        "signal": trade.signal,
        "status": trade.status,
        "expiry": trade.expiry.strftime(NSE_DATE_FORMAT),
        "lot_size": trade.lot_size,
        "quantity_lots": trade.quantity_lots,
        "entry_underlying_value": trade.entry_underlying_value,
        "entry_market_iv_percent": trade.entry_market_iv_percent,
        "entry_predicted_iv_percent": trade.entry_predicted_iv_percent,
        "forecast_generated_at": (trade.forecast_snapshot or {}).get("generated_at"),
        "forecast_for_date": (trade.forecast_snapshot or {}).get("forecast_for_date"),
        "entry_premium_type": trade.entry_premium_type,
        "entry_cash_flow": round(entry_cash_flow, 2),
        "capital_at_risk": round(
            trade.capital_at_risk_per_lot * trade.quantity_lots,
            2,
        ),
        "legs": trade.legs,
        "created_at": trade.created_at,
        "closed_at": trade.closed_at,
        "realized_pnl": trade.realized_pnl,
        "latest_mark": serialized_marks[-1] if serialized_marks else None,
        "marks": serialized_marks,
        "valuation_limitation": valuation_limitation,
    }


async def record_open_paper_iv_marks() -> int:
    """Record one current mark per exchange timestamp for every open option trade."""

    from app.services.market_data.india_trading import get_options_chain

    async with get_session_factory()() as db:
        trades = list(
            (
                await db.execute(
                    select(PaperIVTrade).where(PaperIVTrade.status == "open")
                )
            )
            .scalars()
            .all()
        )
        keys = sorted(
            {
                (trade.ticker, trade.symbol, trade.expiry.strftime(NSE_DATE_FORMAT))
                for trade in trades
            }
        )
        chain_values = await asyncio.gather(
            *(
                get_options_chain(ticker, symbol, expiry)
                for ticker, symbol, expiry in keys
            )
        )
        chains = dict(zip(keys, chain_values, strict=True))
        recorded = 0
        for trade in trades:
            key = (
                trade.ticker,
                trade.symbol,
                trade.expiry.strftime(NSE_DATE_FORMAT),
            )
            previous = await latest_trade_mark(db, trade.id)
            mark, _ = await refresh_trade_mark(db, trade, chains[key])
            if mark is not None and (previous is None or mark.id != previous.id):
                recorded += 1
        await db.commit()
        return recorded


async def run_paper_iv_mark_recorder() -> None:
    """Capture open option trades once per 15-minute NSE market bucket."""

    india_tz = ZoneInfo("Asia/Kolkata")
    last_bucket: datetime | None = None
    while True:
        try:
            now = datetime.now(india_tz)
            minute_of_day = now.hour * 60 + now.minute
            market_is_open = (
                now.weekday() < 5 and 9 * 60 + 15 <= minute_of_day <= 15 * 60 + 45
            )
            bucket = now.replace(
                minute=now.minute // 15 * 15,
                second=0,
                microsecond=0,
            )
            if market_is_open and bucket != last_bucket:
                await record_open_paper_iv_marks()
                last_bucket = bucket
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Paper IV mark recorder failed", exc_info=True)
        await asyncio.sleep(60)
