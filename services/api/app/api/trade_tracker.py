"""Portfolio-wide paper option-trade tracker endpoints."""

import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import PaperIVTrade
from app.schemas.trading import PaperIVTradeOut
from app.services.market_data.india_trading import get_options_chain
from app.services.market_data.paper_iv_trades import (
    NSE_DATE_FORMAT,
    paper_trade_response,
    refresh_trade_mark,
    trade_marks,
)

router = APIRouter()


@router.get("/options", response_model=list[PaperIVTradeOut])
async def list_option_paper_trades(
    portfolio_id: UUID,
    include_closed: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Return every saved option strategy in one browser portfolio."""

    query = (
        select(PaperIVTrade)
        .where(PaperIVTrade.portfolio_id == portfolio_id)
        .order_by(desc(PaperIVTrade.created_at))
    )
    if not include_closed:
        query = query.where(PaperIVTrade.status == "open")
    trades = list((await db.execute(query)).scalars().all())

    open_keys = sorted(
        {
            (trade.ticker, trade.symbol, trade.expiry.strftime(NSE_DATE_FORMAT))
            for trade in trades
            if trade.status == "open"
        }
    )
    chain_values = await asyncio.gather(
        *(get_options_chain(ticker, symbol, expiry) for ticker, symbol, expiry in open_keys)
    )
    chains = dict(zip(open_keys, chain_values, strict=True))

    limitations: dict[UUID, str | None] = {}
    for trade in trades:
        if trade.status != "open":
            continue
        key = (trade.ticker, trade.symbol, trade.expiry.strftime(NSE_DATE_FORMAT))
        _, limitation = await refresh_trade_mark(db, trade, chains[key])
        limitations[trade.id] = limitation
    await db.commit()

    return [
        paper_trade_response(
            trade,
            await trade_marks(db, trade.id),
            valuation_limitation=limitations.get(trade.id),
        )
        for trade in trades
    ]
