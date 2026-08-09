"""Persistence and live marking for paper futures pair trades."""

from dataclasses import replace
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaperPairTrade, PaperPairTradeMark
from app.schemas.pairs import PairSuggestion
from app.services.live_futures import LiveFuturesQuote, get_live_futures_quotes
from app.services.pair_suggestions import FuturesContract, _futures_contract_counts

INDIA_TZ = ZoneInfo("Asia/Kolkata")


def build_pair_paper_entry(
    suggestion: PairSuggestion,
    contracts_by_ticker: dict[str, list[FuturesContract]],
    price_date: date | None,
    *,
    price_timestamp: datetime | None = None,
    price_source: str = "NSE official end-of-day futures bhavcopy",
) -> tuple[dict[str, Any] | None, str | None]:
    """Build the nearest-common-expiry futures entry at supplied contract prices."""

    if price_date is None:
        return None, "No official NSE futures price date is available."
    contracts_a = {
        contract.expiry: contract
        for contract in contracts_by_ticker.get(suggestion.stock_a, [])
    }
    contracts_b = {
        contract.expiry: contract
        for contract in contracts_by_ticker.get(suggestion.stock_b, [])
    }
    common_expiries = sorted(set(contracts_a) & set(contracts_b))
    if not common_expiries:
        return None, "The two underlyings do not currently have a common futures expiry."

    expiry = common_expiries[0]
    contract_a = contracts_a[expiry]
    contract_b = contracts_b[expiry]
    count_a, count_b, hedge_fit = _futures_contract_counts(
        suggestion.hedge_ratio,
        contract_a.price * contract_a.lot_size,
        contract_b.price * contract_b.lot_size,
    )
    if suggestion.long_ticker == suggestion.stock_a:
        long_contract, short_contract = contract_a, contract_b
        long_count, short_count = count_a, count_b
    else:
        long_contract, short_contract = contract_b, contract_a
        long_count, short_count = count_b, count_a

    long_units = long_count * long_contract.lot_size
    short_units = short_count * short_contract.lot_size
    long_notional = long_units * long_contract.price
    short_notional = short_units * short_contract.price
    reversion_date = (
        date.fromisoformat(suggestion.estimated_reversion_date)
        if suggestion.estimated_reversion_date
        else None
    )
    return (
        {
            "pair_id": suggestion.pair_id,
            "long_ticker": suggestion.long_ticker,
            "short_ticker": suggestion.short_ticker,
            "expiry": expiry,
            "estimated_reversion_date": reversion_date,
            "requires_rollover": bool(
                reversion_date is not None and expiry < reversion_date
            ),
            "long_contract_name": long_contract.contract_name,
            "short_contract_name": short_contract.contract_name,
            "long_contracts": long_count,
            "short_contracts": short_count,
            "long_lot_size": long_contract.lot_size,
            "short_lot_size": short_contract.lot_size,
            "long_units": long_units,
            "short_units": short_units,
            "entry_long_price": long_contract.price,
            "entry_short_price": short_contract.price,
            "entry_long_notional": long_notional,
            "entry_short_notional": short_notional,
            "entry_combined_notional": long_notional + short_notional,
            "hedge_ratio": suggestion.hedge_ratio,
            "hedge_fit_percent": hedge_fit,
            "entry_zscore": suggestion.current_zscore,
            "entry_q_value": suggestion.fdr_q_value,
            "entry_price_date": price_date,
            "suggestion_snapshot": {
                **suggestion.model_dump(mode="json"),
                "paper_entry_price_source": price_source,
                "paper_entry_price_timestamp": (
                    price_timestamp.isoformat() if price_timestamp else None
                ),
            },
        },
        None,
    )


def calculate_pair_mark(
    *,
    entry_long_price: float,
    entry_short_price: float,
    long_units: int,
    short_units: int,
    entry_combined_notional: float,
    long_price: float,
    short_price: float,
    price_date: date,
) -> dict[str, Any]:
    long_pnl = long_units * (long_price - entry_long_price)
    short_pnl = short_units * (entry_short_price - short_price)
    total_pnl = long_pnl + short_pnl
    return_percent = (
        total_pnl / entry_combined_notional * 100
        if entry_combined_notional > 0
        else 0.0
    )
    return {
        "price_date": price_date,
        "long_price": round(long_price, 2),
        "short_price": round(short_price, 2),
        "long_pnl": round(long_pnl, 2),
        "short_pnl": round(short_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "return_percent": round(return_percent, 2),
        "current_gross_notional": round(
            long_units * long_price + short_units * short_price,
            2,
        ),
    }


async def live_price_contracts(
    contracts_by_ticker: dict[str, list[FuturesContract]],
) -> tuple[dict[str, list[FuturesContract]], datetime | None, str | None]:
    """Replace bhavcopy prices with authenticated LTPs for exact contracts."""

    requested = {
        (contract.ticker.upper(), contract.expiry)
        for contracts in contracts_by_ticker.values()
        for contract in contracts
    }
    quotes, limitation = await get_live_futures_quotes(requested)
    if limitation is not None:
        return contracts_by_ticker, None, limitation
    updated = {
        ticker: [
            replace(
                contract,
                price=quotes[(contract.ticker.upper(), contract.expiry)].price,
            )
            for contract in contracts
        ]
        for ticker, contracts in contracts_by_ticker.items()
    }
    timestamp = max(quote.received_at for quote in quotes.values())
    return updated, timestamp, None


def live_pair_trade_mark(
    trade: PaperPairTrade,
    quotes: dict[tuple[str, date], LiveFuturesQuote],
) -> tuple[dict[str, Any] | None, str | None]:
    """Calculate an unpersisted current mark from exact saved futures LTPs."""

    long_quote = quotes.get((trade.long_ticker.upper(), trade.expiry))
    short_quote = quotes.get((trade.short_ticker.upper(), trade.expiry))
    if long_quote is None or short_quote is None:
        return None, "A live LTP was unavailable for one or both saved futures contracts."
    quote_timestamp = max(long_quote.received_at, short_quote.received_at)
    values = calculate_pair_mark(
        entry_long_price=trade.entry_long_price,
        entry_short_price=trade.entry_short_price,
        long_units=trade.long_units,
        short_units=trade.short_units,
        entry_combined_notional=trade.entry_combined_notional,
        long_price=long_quote.price,
        short_price=short_quote.price,
        price_date=quote_timestamp.astimezone(INDIA_TZ).date(),
    )
    return (
        {
            "id": None,
            **values,
            "current_long_notional": round(trade.long_units * long_quote.price, 2),
            "current_short_notional": round(
                trade.short_units * short_quote.price,
                2,
            ),
            "quote_timestamp": quote_timestamp,
            "price_source": long_quote.source,
            "is_live": True,
            "created_at": quote_timestamp,
        },
        None,
    )


async def live_pair_trade_marks(
    trades: list[PaperPairTrade],
) -> tuple[dict[Any, dict[str, Any]], dict[Any, str | None]]:
    requested = {
        (ticker.upper(), trade.expiry)
        for trade in trades
        for ticker in (trade.long_ticker, trade.short_ticker)
    }
    quotes, provider_limitation = await get_live_futures_quotes(requested)
    marks: dict[Any, dict[str, Any]] = {}
    limitations: dict[Any, str | None] = {}
    for trade in trades:
        mark, trade_limitation = live_pair_trade_mark(trade, quotes)
        if mark is not None:
            marks[trade.id] = mark
        limitations[trade.id] = provider_limitation or trade_limitation
    return marks, limitations


async def persist_live_pair_trade_mark(
    db: AsyncSession,
    trade: PaperPairTrade,
    live_mark: dict[str, Any],
) -> PaperPairTradeMark:
    """Persist the exact live exit mark, replacing a same-day historical mark."""

    mark = (
        await db.execute(
            select(PaperPairTradeMark).where(
                PaperPairTradeMark.trade_id == trade.id,
                PaperPairTradeMark.price_date == live_mark["price_date"],
            )
        )
    ).scalar_one_or_none()
    values = {
        key: live_mark[key]
        for key in (
            "price_date",
            "long_price",
            "short_price",
            "long_pnl",
            "short_pnl",
            "total_pnl",
            "return_percent",
            "current_gross_notional",
        )
    }
    if mark is None:
        mark = PaperPairTradeMark(trade_id=trade.id, **values)
        db.add(mark)
    else:
        for key, value in values.items():
            setattr(mark, key, value)
        mark.created_at = live_mark["quote_timestamp"]
    await db.flush()
    return mark


def _contract_for(
    contracts_by_ticker: dict[str, list[FuturesContract]],
    ticker: str,
    expiry: date,
) -> FuturesContract | None:
    return next(
        (
            contract
            for contract in contracts_by_ticker.get(ticker, [])
            if contract.expiry == expiry
        ),
        None,
    )


async def refresh_pair_trade_mark(
    db: AsyncSession,
    trade: PaperPairTrade,
    contracts_by_ticker: dict[str, list[FuturesContract]],
    price_date: date | None,
) -> tuple[PaperPairTradeMark | None, str | None]:
    previous = (
        await db.execute(
            select(PaperPairTradeMark)
            .where(PaperPairTradeMark.trade_id == trade.id)
            .order_by(PaperPairTradeMark.price_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if price_date is None:
        return previous, "No current official NSE futures price is available."
    if previous is not None and previous.price_date == price_date:
        return previous, None

    long_contract = _contract_for(
        contracts_by_ticker,
        trade.long_ticker,
        trade.expiry,
    )
    short_contract = _contract_for(
        contracts_by_ticker,
        trade.short_ticker,
        trade.expiry,
    )
    if long_contract is None or short_contract is None:
        return (
            previous,
            "The saved futures expiry is no longer listed for both legs. The last "
            "available mark is retained.",
        )

    values = calculate_pair_mark(
        entry_long_price=trade.entry_long_price,
        entry_short_price=trade.entry_short_price,
        long_units=trade.long_units,
        short_units=trade.short_units,
        entry_combined_notional=trade.entry_combined_notional,
        long_price=long_contract.price,
        short_price=short_contract.price,
        price_date=price_date,
    )
    mark = PaperPairTradeMark(trade_id=trade.id, **values)
    db.add(mark)
    await db.flush()
    return mark, None


async def pair_trade_marks(
    db: AsyncSession,
    trade_id,
) -> list[PaperPairTradeMark]:
    return list(
        (
            await db.execute(
                select(PaperPairTradeMark)
                .where(PaperPairTradeMark.trade_id == trade_id)
                .order_by(PaperPairTradeMark.price_date)
            )
        )
        .scalars()
        .all()
    )


def paper_pair_trade_response(
    trade: PaperPairTrade,
    marks: list[PaperPairTradeMark],
    *,
    valuation_limitation: str | None = None,
    live_mark: dict[str, Any] | None = None,
) -> dict[str, Any]:
    def serialize_mark(mark: PaperPairTradeMark) -> dict[str, Any]:
        return {
            "id": mark.id,
            "price_date": mark.price_date.isoformat(),
            "long_price": mark.long_price,
            "short_price": mark.short_price,
            "long_pnl": mark.long_pnl,
            "short_pnl": mark.short_pnl,
            "current_long_notional": round(
                trade.long_units * mark.long_price,
                2,
            ),
            "current_short_notional": round(
                trade.short_units * mark.short_price,
                2,
            ),
            "quote_timestamp": mark.created_at,
            "price_source": "NSE official end-of-day futures bhavcopy",
            "is_live": False,
            "total_pnl": mark.total_pnl,
            "return_percent": mark.return_percent,
            "current_gross_notional": mark.current_gross_notional,
            "created_at": mark.created_at,
        }

    serialized_marks = [serialize_mark(mark) for mark in marks]
    return {
        "id": trade.id,
        "portfolio_id": trade.portfolio_id,
        "pair_id": trade.pair_id,
        "status": trade.status,
        "entry_signal": (
            "watch"
            if trade.suggestion_snapshot.get("signal") == "watch"
            else "active"
        ),
        "long_ticker": trade.long_ticker,
        "short_ticker": trade.short_ticker,
        "expiry": trade.expiry.isoformat(),
        "estimated_reversion_date": (
            trade.estimated_reversion_date.isoformat()
            if trade.estimated_reversion_date
            else None
        ),
        "requires_rollover": trade.requires_rollover,
        "long_contract_name": trade.long_contract_name,
        "short_contract_name": trade.short_contract_name,
        "long_contracts": trade.long_contracts,
        "short_contracts": trade.short_contracts,
        "long_lot_size": trade.long_lot_size,
        "short_lot_size": trade.short_lot_size,
        "long_units": trade.long_units,
        "short_units": trade.short_units,
        "entry_long_price": trade.entry_long_price,
        "entry_short_price": trade.entry_short_price,
        "entry_long_notional": trade.entry_long_notional,
        "entry_short_notional": trade.entry_short_notional,
        "entry_combined_notional": trade.entry_combined_notional,
        "hedge_ratio": trade.hedge_ratio,
        "hedge_fit_percent": trade.hedge_fit_percent,
        "entry_zscore": trade.entry_zscore,
        "entry_q_value": trade.entry_q_value,
        "entry_price_date": trade.entry_price_date.isoformat(),
        "entry_price_source": trade.suggestion_snapshot.get(
            "paper_entry_price_source",
            "NSE official end-of-day futures bhavcopy",
        ),
        "entry_price_timestamp": trade.suggestion_snapshot.get(
            "paper_entry_price_timestamp"
        ),
        "created_at": trade.created_at,
        "closed_at": trade.closed_at,
        "realized_pnl": trade.realized_pnl,
        "latest_mark": serialized_marks[-1] if serialized_marks else None,
        "live_mark": live_mark,
        "marks": serialized_marks,
        "valuation_limitation": valuation_limitation,
    }
