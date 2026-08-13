"""Endpoints for F&O pair-trade research suggestions."""

from datetime import UTC, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models import PaperIntradayCopulaTrade, PaperLabSpotTrade, PaperPairTrade
from app.schemas.copula_pair_signals import CopulaPairSignalsResponse
from app.schemas.intraday_copula_tracker import (
    IntradayCopulaTrackerResponse,
    IntradayCopulaTrackerSync,
    IntradayCopulaTradeOut,
)
from app.schemas.pair_method_lab import (
    PairMethodLabResponse,
    PaperLabSpotTradeClose,
    PaperLabSpotTradeOut,
    PaperLabSpotTradeSync,
    PaperLabSpotTradeSyncOut,
)
from app.schemas.pairs import (
    PairSuggestionsResponse,
    PaperPairPortfolioCreate,
    PaperPairPortfolioOut,
    PaperPairPortfolioRefresh,
    PaperPairTradeClose,
    PaperPairTradeCreate,
    PaperPairTradeOut,
)
from app.services.pair_suggestions import (
    _latest_futures_contracts,
    get_pair_suggestions,
)
from app.services.paper_pair_trades import (
    build_pair_paper_entry,
    live_pair_trade_marks,
    live_price_contracts,
    pair_trade_marks,
    paper_pair_trade_response,
    persist_live_pair_trade_mark,
    refresh_pair_trade_mark,
)

router = APIRouter()


@router.get("/method-lab", response_model=PairMethodLabResponse, include_in_schema=False)
async def pair_method_lab(
    limit: int = Query(default=24, ge=1, le=160),
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Development-only comparison with the method in arXiv:2109.10662."""

    if get_settings().app_environment.strip().lower() in {"prod", "production"}:
        raise HTTPException(status_code=404, detail="Not found")
    from app.services.pair_method_lab import get_pair_method_lab

    return await get_pair_method_lab(db, limit=limit, refresh=refresh)


@router.get(
    "/method-lab/copula-signals",
    response_model=CopulaPairSignalsResponse,
    include_in_schema=False,
)
async def copula_pair_signals(
    limit: int = Query(default=24, ge=1, le=160),
    refresh: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Development-only copula signals for strict dual-test pair candidates."""

    _require_development()
    from app.services.copula_pair_signals import get_copula_pair_signals

    return await get_copula_pair_signals(db, limit=limit, refresh=refresh)


@router.post(
    "/method-lab/intraday-copula/sync",
    response_model=IntradayCopulaTrackerResponse,
    include_in_schema=False,
)
async def sync_intraday_copula_tracker(
    body: IntradayCopulaTrackerSync,
    db: AsyncSession = Depends(get_db),
):
    """Scan the latest completed five-minute bars and advance paper trades."""

    _require_development()
    from app.services.intraday_copula_tracker import sync_intraday_copula_tracker

    return await sync_intraday_copula_tracker(
        db,
        body.portfolio_id,
        candidate_limit=body.candidate_limit,
    )


@router.post(
    "/method-lab/intraday-copula/trades/{trade_id}/close",
    response_model=IntradayCopulaTradeOut,
    include_in_schema=False,
)
async def close_intraday_copula_trade(
    trade_id: UUID,
    body: IntradayCopulaTrackerSync,
    db: AsyncSession = Depends(get_db),
):
    _require_development()
    from app.services.intraday_copula_tracker import (
        close_intraday_copula_trade,
        intraday_trade_marks,
        intraday_trade_response,
    )

    trade = (
        await db.execute(
            select(PaperIntradayCopulaTrade).where(
                PaperIntradayCopulaTrade.id == trade_id,
                PaperIntradayCopulaTrade.portfolio_id == body.portfolio_id,
            )
        )
    ).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Unknown intraday copula trade.")
    if trade.status == "open":
        await close_intraday_copula_trade(db, trade)
    return intraday_trade_response(trade, await intraday_trade_marks(db, trade.id))


def _require_development() -> None:
    if get_settings().app_environment.strip().lower() in {"prod", "production"}:
        raise HTTPException(status_code=404, detail="Not found")


@router.post(
    "/method-lab/paper-trades/sync",
    response_model=PaperLabSpotTradeSyncOut,
    include_in_schema=False,
)
async def sync_pair_method_lab_paper_trades(
    body: PaperLabSpotTradeSync,
    db: AsyncSession = Depends(get_db),
):
    _require_development()
    from app.services.paper_lab_spot_trades import (
        list_spot_trades,
        spot_trade_response,
        sync_dual_test_spot_trades,
        trade_marks,
    )

    eligible_pairs, created_trades = await sync_dual_test_spot_trades(
        db,
        body.portfolio_id,
    )
    trades = await list_spot_trades(db, body.portfolio_id)
    return {
        "eligible_pairs": eligible_pairs,
        "created_trades": created_trades,
        "trades": [
            spot_trade_response(trade, await trade_marks(db, trade.id))
            for trade in trades
        ],
    }


@router.get(
    "/method-lab/paper-trades",
    response_model=list[PaperLabSpotTradeOut],
    include_in_schema=False,
)
async def list_pair_method_lab_paper_trades(
    portfolio_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    _require_development()
    from app.services.paper_lab_spot_trades import (
        list_spot_trades,
        spot_trade_response,
        trade_marks,
    )

    trades = await list_spot_trades(db, portfolio_id)
    return [
        spot_trade_response(trade, await trade_marks(db, trade.id))
        for trade in trades
    ]


@router.post(
    "/method-lab/paper-trades/mark",
    response_model=list[PaperLabSpotTradeOut],
    include_in_schema=False,
)
async def mark_pair_method_lab_paper_trades(
    body: PaperLabSpotTradeSync,
    db: AsyncSession = Depends(get_db),
):
    _require_development()
    from app.services.paper_lab_spot_trades import (
        backfill_intraday_spot_marks,
        close_zero_crossed_live_trades,
        list_spot_trades,
        spot_trade_response,
        trade_marks,
    )

    trades = await list_spot_trades(db, body.portfolio_id)
    await backfill_intraday_spot_marks(
        db,
        [trade for trade in trades if trade.status == "open"],
    )
    await close_zero_crossed_live_trades(
        db,
        [trade for trade in trades if trade.status == "open"],
    )
    return [
        spot_trade_response(trade, await trade_marks(db, trade.id))
        for trade in trades
    ]


@router.post(
    "/method-lab/paper-trades/{trade_id}/close",
    response_model=PaperLabSpotTradeOut,
    include_in_schema=False,
)
async def close_pair_method_lab_paper_trade(
    trade_id: UUID,
    body: PaperLabSpotTradeClose,
    db: AsyncSession = Depends(get_db),
):
    _require_development()
    from app.services.paper_lab_spot_trades import (
        close_spot_trade,
        spot_trade_response,
        trade_marks,
    )

    trade = (
        await db.execute(
            select(PaperLabSpotTrade).where(
                PaperLabSpotTrade.id == trade_id,
                PaperLabSpotTrade.portfolio_id == body.portfolio_id,
            )
        )
    ).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Unknown lab spot-proxy trade.")
    if trade.status == "open":
        try:
            await close_spot_trade(db, trade)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    return spot_trade_response(trade, await trade_marks(db, trade.id))


@router.get("", response_model=PairSuggestionsResponse)
async def list_trade_suggestions(
    limit: int = Query(default=12, ge=1, le=30),
    refresh: bool = False,
    p_value_threshold: float = Query(default=0.001, ge=0.0001, le=0.05),
    db: AsyncSession = Depends(get_db),
):
    return await get_pair_suggestions(
        db,
        limit=limit,
        refresh=refresh,
        p_value_threshold=p_value_threshold,
    )


@router.get(
    "/pair-portfolios/current",
    response_model=PaperPairPortfolioOut | None,
)
async def get_current_pair_portfolio(
    owner_portfolio_id: UUID,
    refresh: bool = True,
    db: AsyncSession = Depends(get_db),
):
    from app.services.pair_portfolios import (
        current_portfolio,
        portfolio_response,
        refresh_portfolio_marks,
    )

    portfolio = await current_portfolio(db, owner_portfolio_id)
    if portfolio is None:
        return None
    if refresh:
        await refresh_portfolio_marks(portfolio)
        await db.commit()
    return portfolio_response(portfolio)


@router.post(
    "/pair-portfolios",
    response_model=PaperPairPortfolioOut,
    status_code=201,
)
async def construct_pair_portfolio(
    body: PaperPairPortfolioCreate,
    db: AsyncSession = Depends(get_db),
):
    from app.services.pair_portfolios import create_portfolio, portfolio_response

    scan = await get_pair_suggestions(
        db,
        limit=200,
        refresh=False,
        p_value_threshold=body.p_value_threshold,
    )
    try:
        portfolio = await create_portfolio(
            db,
            body.owner_portfolio_id,
            body.investment_amount_inr,
            body.p_value_threshold,
            scan.results,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return portfolio_response(portfolio)


@router.post(
    "/pair-portfolios/current/refresh",
    response_model=PaperPairPortfolioOut,
)
async def refresh_current_pair_portfolio(
    body: PaperPairPortfolioRefresh,
    db: AsyncSession = Depends(get_db),
):
    from app.services.pair_portfolios import (
        current_portfolio,
        portfolio_response,
        refresh_portfolio_marks,
    )

    portfolio = await current_portfolio(db, body.owner_portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="No pair portfolio has been built yet.")
    await refresh_portfolio_marks(portfolio)
    await db.commit()
    return portfolio_response(portfolio)


@router.post(
    "/paper-trades",
    response_model=PaperPairTradeOut,
    status_code=201,
)
async def create_pair_paper_trade(
    body: PaperPairTradeCreate,
    db: AsyncSession = Depends(get_db),
):
    suggestions = await get_pair_suggestions(
        db,
        limit=200,
        refresh=False,
        p_value_threshold=body.p_value_threshold,
    )
    suggestion = next(
        (item for item in suggestions.results if item.pair_id == body.pair_id),
        None,
    )
    if suggestion is None:
        raise HTTPException(
            status_code=404,
            detail="This pair is not present at the selected p-value cutoff.",
        )
    contracts, eod_price_date = await _latest_futures_contracts(
        {suggestion.stock_a, suggestion.stock_b}
    )
    live_contracts, live_timestamp, live_limitation = await live_price_contracts(
        contracts
    )
    using_live_entry = live_limitation is None and live_timestamp is not None
    entry_contracts = live_contracts if using_live_entry else contracts
    entry_price_date = (
        live_timestamp.astimezone(ZoneInfo("Asia/Kolkata")).date()
        if live_timestamp is not None
        else eod_price_date
    )
    entry, limitation = build_pair_paper_entry(
        suggestion,
        entry_contracts,
        entry_price_date,
        price_timestamp=live_timestamp if using_live_entry else None,
        price_source=(
            "Upstox V3 live futures LTP"
            if using_live_entry
            else "NSE official end-of-day futures bhavcopy fallback"
        ),
    )
    if entry is None:
        raise HTTPException(
            status_code=409,
            detail=limitation or "A common futures entry could not be built.",
        )

    trade = PaperPairTrade(
        portfolio_id=body.portfolio_id,
        status="open",
        **entry,
    )
    db.add(trade)
    await db.flush()
    await db.commit()
    return paper_pair_trade_response(
        trade,
        await pair_trade_marks(db, trade.id),
    )


@router.get(
    "/paper-trades",
    response_model=list[PaperPairTradeOut],
)
async def list_pair_paper_trades(
    portfolio_id: UUID,
    include_closed: bool = True,
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(PaperPairTrade)
        .where(PaperPairTrade.portfolio_id == portfolio_id)
        .order_by(PaperPairTrade.created_at.desc())
    )
    if not include_closed:
        query = query.where(PaperPairTrade.status == "open")
    trades = list((await db.execute(query)).scalars().all())
    open_trades = [trade for trade in trades if trade.status == "open"]
    limitations: dict[UUID, str | None] = {}
    live_marks: dict[UUID, dict] = {}
    if open_trades:
        live_marks, limitations = await live_pair_trade_marks(open_trades)
        fallback_trades = [
            trade for trade in open_trades if trade.id not in live_marks
        ]
        if fallback_trades:
            symbols = {
                ticker
                for trade in fallback_trades
                for ticker in (trade.long_ticker, trade.short_ticker)
            }
            contracts, price_date = await _latest_futures_contracts(symbols)
            for trade in fallback_trades:
                _, fallback_limitation = await refresh_pair_trade_mark(
                    db,
                    trade,
                    contracts,
                    price_date,
                )
                live_limitation = limitations.get(trade.id)
                if fallback_limitation is not None:
                    limitations[trade.id] = (
                        f"{live_limitation} {fallback_limitation}"
                        if live_limitation
                        else fallback_limitation
                    )
                else:
                    fallback_date = price_date.isoformat() if price_date else "unknown"
                    limitations[trade.id] = (
                        f"{live_limitation} Showing the official NSE futures close "
                        f"dated {fallback_date} as an EOD fallback."
                    )
            await db.commit()

    return [
        paper_pair_trade_response(
            trade,
            await pair_trade_marks(db, trade.id),
            valuation_limitation=limitations.get(trade.id),
            live_mark=live_marks.get(trade.id),
        )
        for trade in trades
    ]


@router.post(
    "/paper-trades/{trade_id}/close",
    response_model=PaperPairTradeOut,
)
async def close_pair_paper_trade(
    trade_id: UUID,
    body: PaperPairTradeClose,
    db: AsyncSession = Depends(get_db),
):
    trade = (
        await db.execute(
            select(PaperPairTrade).where(
                PaperPairTrade.id == trade_id,
                PaperPairTrade.portfolio_id == body.portfolio_id,
            )
        )
    ).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Unknown paper pair trade.")
    if trade.status == "closed":
        return paper_pair_trade_response(
            trade,
            await pair_trade_marks(db, trade.id),
        )

    live_marks, limitations = await live_pair_trade_marks([trade])
    live_mark = live_marks.get(trade.id)
    limitation = limitations.get(trade.id)
    if live_mark is not None and limitation is None:
        mark = await persist_live_pair_trade_mark(db, trade, live_mark)
    else:
        contracts, price_date = await _latest_futures_contracts(
            {trade.long_ticker, trade.short_ticker}
        )
        mark, fallback_limitation = await refresh_pair_trade_mark(
            db,
            trade,
            contracts,
            price_date,
        )
        if mark is None or fallback_limitation is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    fallback_limitation
                    or limitation
                    or "The pair cannot currently be marked for exit."
                ),
            )
    trade.status = "closed"
    trade.closed_at = datetime.now(UTC)
    trade.realized_pnl = mark.total_pnl
    await db.commit()
    return paper_pair_trade_response(
        trade,
        await pair_trade_marks(db, trade.id),
    )
