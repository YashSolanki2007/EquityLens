from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import (
    Company,
    CompanyCard,
    CompanyMarketSnapshot,
    FinancialFact,
    ResearchCandidate,
    ResearchSession,
    SecFiling,
)
from app.schemas.api import CardOut, CompanyOut, FilingOut, MarketSnapshotOut
from app.schemas.company import (
    CompanyAnalysisOut,
    CompanyChatRequest,
    CompanyChatResponse,
    CompanyOutlookOut,
    FinancialOverviewOut,
    FinancialStatementsOut,
    PeerComparisonOut,
)
from app.schemas.trading import (
    IVSurfaceForecastOut,
    OptionsChainOut,
    PaperIVTradeClose,
    PaperIVTradeCreate,
    PaperIVTradeOut,
    PriceForecastOut,
    PriceHistoryOut,
    TradingRatiosOut,
)
from app.services.company_analysis import analyze_company
from app.services.company_chat import answer_company_question
from app.services.company_financials import get_financial_overview
from app.services.company_outlook import get_company_outlook
from app.services.company_peers import build_peer_comparison
from app.services.financial_statements import (
    StatementFrequency,
    StatementType,
    build_statement_csv,
    build_statement_workbook,
    get_full_financial_statements,
)
from app.services.ingestion import refresh_india_financial_facts
from app.services.market_data.forecasting import get_price_forecast
from app.services.market_data.india_trading import (
    HistoryRange,
    get_options_chain,
    get_price_history,
    get_trading_ratios,
)
from app.services.market_data.iv_surface import get_iv_surface_forecast
from app.services.market_data.path_dependent_ssvi import (
    get_path_dependent_iv_surface_forecast,
)
from app.services.market_data.paper_iv_trades import (
    NSE_DATE_FORMAT,
    paper_trade_response,
    refresh_trade_mark,
    trade_marks,
)

router = APIRouter()


async def _get_company(db: AsyncSession, ticker: str) -> Company:
    company = (
        await db.execute(select(Company).where(Company.ticker == ticker.upper()))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker {ticker}")
    return company


def _india_market_identifiers(company: Company) -> tuple[str, str]:
    if company.country != "IN":
        raise HTTPException(
            status_code=404,
            detail="Trading workspace is currently available only for Indian equities.",
        )
    market_data_ticker = company.market_data_ticker or f"{company.ticker}.NS"
    nse_symbol = market_data_ticker.removesuffix(".NS")
    return market_data_ticker, nse_symbol


@router.get("", response_model=list[CompanyOut])
async def list_companies(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Company).order_by(Company.ticker))).scalars().all()
    return rows


@router.get("/{ticker}")
async def get_company(ticker: str, db: AsyncSession = Depends(get_db)):
    company = await _get_company(db, ticker)
    snapshot = (
        await db.execute(
            select(CompanyMarketSnapshot)
            .where(CompanyMarketSnapshot.company_id == company.id)
            .order_by(desc(CompanyMarketSnapshot.retrieved_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    card_count = len(
        (await db.execute(select(CompanyCard.id).where(CompanyCard.company_id == company.id)))
        .scalars()
        .all()
    )
    facts = (
        (
            await db.execute(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id)
                .order_by(desc(FinancialFact.end_date))
                .limit(24)
            )
        )
        .scalars()
        .all()
    )
    appearances = (
        await db.execute(
            select(ResearchSession.id, ResearchSession.original_query, ResearchSession.created_at)
            .join(ResearchCandidate, ResearchCandidate.session_id == ResearchSession.id)
            .where(ResearchCandidate.company_id == company.id)
            .order_by(desc(ResearchSession.created_at))
            .limit(10)
        )
    ).all()
    return {
        "company": CompanyOut.model_validate(company),
        "market_snapshot": MarketSnapshotOut.model_validate(snapshot) if snapshot else None,
        "card_count": card_count,
        "financial_facts": [
            {
                "concept": f.concept,
                "unit": f.unit,
                "value": f.value,
                "start_date": f.start_date,
                "end_date": f.end_date,
                "fiscal_year": f.fiscal_year,
                "fiscal_period": f.fiscal_period,
                "form": f.form,
            }
            for f in facts
        ],
        "search_appearances": [
            {"session_id": str(sid), "query": q, "created_at": c} for sid, q, c in appearances
        ],
    }


@router.get("/{ticker}/cards", response_model=list[CardOut])
async def get_company_cards(ticker: str, db: AsyncSession = Depends(get_db)):
    company = await _get_company(db, ticker)
    cards = (
        (
            await db.execute(
                select(CompanyCard)
                .where(CompanyCard.company_id == company.id)
                .order_by(CompanyCard.card_type, desc(CompanyCard.confidence))
            )
        )
        .scalars()
        .all()
    )
    return cards


@router.get("/{ticker}/financial-overview", response_model=FinancialOverviewOut)
async def get_company_financial_overview(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    overview = await get_financial_overview(
        db,
        ticker=company.ticker,
        cik=company.cik,
        company_id=company.id,
        country=company.country,
        currency=company.reporting_currency,
        market_data_ticker=company.market_data_ticker,
    )
    # The NSE report/card materialization pipeline predates the yfinance facts
    # adapter, so some otherwise-complete Indian companies have no cached
    # financial rows. Repair those gaps on first view and cache the result.
    if company.country == "IN" and not overview.annual and not overview.quarterly:
        refreshed = await refresh_india_financial_facts(db, company)
        if refreshed:
            overview = await get_financial_overview(
                db,
                ticker=company.ticker,
                cik=company.cik,
                company_id=company.id,
                country=company.country,
                currency=company.reporting_currency,
                market_data_ticker=company.market_data_ticker,
            )
    return overview


@router.get("/{ticker}/trading-ratios", response_model=TradingRatiosOut)
async def get_company_trading_ratios(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    market_data_ticker, _ = _india_market_identifiers(company)
    return await get_trading_ratios(company.ticker, market_data_ticker)


@router.get("/{ticker}/peer-comparison", response_model=PeerComparisonOut)
async def get_company_peer_comparison(
    ticker: str,
    symbols: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=5, ge=1, le=7),
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    _india_market_identifiers(company)
    peer_symbols = None
    if symbols is not None:
        peer_symbols = [symbol for symbol in symbols.split(",") if symbol.strip()]
    return await build_peer_comparison(
        db,
        company,
        peer_symbols=peer_symbols,
        limit=limit,
    )


@router.get("/{ticker}/financial-statements", response_model=FinancialStatementsOut)
async def get_company_financial_statements(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    market_data_ticker, _ = _india_market_identifiers(company)
    return await get_full_financial_statements(company.ticker, market_data_ticker)


@router.get("/{ticker}/financial-statements/export")
async def export_company_financial_statements(
    ticker: str,
    format: Literal["csv", "xlsx"] = Query(default="xlsx"),
    statement: StatementType = Query(default="income"),
    frequency: StatementFrequency = Query(default="annual"),
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    market_data_ticker, _ = _india_market_identifiers(company)
    payload = await get_full_financial_statements(company.ticker, market_data_ticker)
    safe_ticker = company.ticker.replace("/", "-")
    if format == "csv":
        content = build_statement_csv(payload, statement, frequency)
        filename = f"{safe_ticker}_{frequency}_{statement}.csv"
        media_type = "text/csv; charset=utf-8"
    else:
        content = build_statement_workbook(payload)
        filename = f"{safe_ticker}_financial_statements.xlsx"
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{ticker}/price-history", response_model=PriceHistoryOut)
async def get_company_price_history(
    ticker: str,
    range: HistoryRange = "1Y",
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    market_data_ticker, _ = _india_market_identifiers(company)
    return await get_price_history(company.ticker, market_data_ticker, range)


@router.get("/{ticker}/price-forecast", response_model=PriceForecastOut)
async def get_company_price_forecast(
    ticker: str,
    horizon_days: int = Query(default=15, ge=5, le=15),
    simulations: int = Query(default=2500, ge=500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    market_data_ticker = company.market_data_ticker or company.ticker
    return await get_price_forecast(
        company.ticker,
        market_data_ticker,
        horizon_days=horizon_days,
        simulations=simulations,
    )


@router.get("/{ticker}/options-chain", response_model=OptionsChainOut)
async def get_company_options_chain(
    ticker: str,
    expiry: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    return await get_options_chain(company.ticker, nse_symbol, expiry)


@router.get("/{ticker}/iv-surface-forecast", response_model=IVSurfaceForecastOut)
async def get_company_iv_surface_forecast(
    ticker: str,
    expiry: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    return await get_iv_surface_forecast(company.ticker, nse_symbol, expiry)


@router.get(
    "/{ticker}/path-dependent-iv-surface-forecast",
    response_model=IVSurfaceForecastOut,
)
async def get_company_path_dependent_iv_surface_forecast(
    ticker: str,
    expiry: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    return await get_path_dependent_iv_surface_forecast(
        company.ticker,
        nse_symbol,
        expiry,
    )


@router.post(
    "/{ticker}/paper-iv-trades",
    response_model=PaperIVTradeOut,
    status_code=201,
)
async def create_company_paper_iv_trade(
    ticker: str,
    body: PaperIVTradeCreate,
    db: AsyncSession = Depends(get_db),
):
    from app.models import PaperIVTrade

    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    forecast = (
        await get_path_dependent_iv_surface_forecast(
            company.ticker,
            nse_symbol,
            body.expiry,
        )
        if body.model_family == "path_dependent_ssvi"
        else await get_iv_surface_forecast(
            company.ticker,
            nse_symbol,
            body.expiry,
        )
    )
    available_strategies = list(forecast.get("strategies") or [])
    if body.strategy_id:
        strategy = next(
            (
                dict(item)
                for item in available_strategies
                if item.get("strategy_id") == body.strategy_id
            ),
            {},
        )
    else:
        strategy = dict(forecast.get("strategy") or {})
    if not forecast.get("available") or not strategy.get("available"):
        raise HTTPException(
            status_code=409,
            detail=(
                (
                    "That strategy is no longer available for this expiry."
                    if body.strategy_id
                    else strategy.get("rationale")
                )
                or forecast.get("limitation")
                or "There is no trackable strategy for this expiry."
            ),
        )
    if strategy.get("expiry") != body.expiry:
        raise HTTPException(
            status_code=409,
            detail="The requested expiry no longer matches the suggested strategy.",
        )
    try:
        expiry_date = datetime.strptime(body.expiry, NSE_DATE_FORMAT).date()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid NSE expiry date.") from exc

    chain = await get_options_chain(company.ticker, nse_symbol, body.expiry)
    trade = PaperIVTrade(
        portfolio_id=body.portfolio_id,
        company_id=company.id,
        ticker=company.ticker,
        symbol=nse_symbol,
        strategy_name=str(strategy["strategy_name"]),
        signal=str(strategy["signal"]),
        status="open",
        expiry=expiry_date,
        lot_size=int(strategy["lot_size"]),
        quantity_lots=body.quantity_lots,
        entry_underlying_value=strategy.get("underlying_value"),
        entry_market_iv_percent=(
            strategy.get("market_iv_percent") or strategy.get("atm_market_iv_percent")
        ),
        entry_predicted_iv_percent=(
            strategy.get("predicted_iv_percent") or strategy.get("atm_predicted_iv_percent")
        ),
        entry_premium_type=str(strategy["entry_premium_type"]),
        entry_cash_flow_per_lot=float(strategy["entry_cash_flow_per_lot"]),
        capital_at_risk_per_lot=float(strategy["capital_at_risk_per_lot"]),
        legs=list(strategy.get("legs") or []),
        forecast_snapshot={
            "generated_at": str(forecast.get("generated_at") or ""),
            "model": forecast.get("model"),
            "model_version": forecast.get("model_version"),
            "selected_expiry": forecast.get("selected_expiry"),
            "forecast_for_date": forecast.get("forecast_for_date"),
            "summary": forecast.get("summary"),
            "comparisons": forecast.get("comparisons") or [],
            "strategy": strategy,
        },
    )
    db.add(trade)
    await db.flush()
    mark, limitation = await refresh_trade_mark(db, trade, chain)
    if mark is not None:
        trade.entry_exchange_timestamp = mark.source_timestamp
    await db.commit()
    marks = await trade_marks(db, trade.id)
    return paper_trade_response(
        trade,
        marks,
        valuation_limitation=limitation,
    )


@router.get(
    "/{ticker}/paper-iv-trades",
    response_model=list[PaperIVTradeOut],
)
async def list_company_paper_iv_trades(
    ticker: str,
    portfolio_id: UUID,
    include_closed: bool = True,
    db: AsyncSession = Depends(get_db),
):
    from app.models import PaperIVTrade

    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    query = (
        select(PaperIVTrade)
        .where(
            PaperIVTrade.company_id == company.id,
            PaperIVTrade.portfolio_id == portfolio_id,
        )
        .order_by(desc(PaperIVTrade.created_at))
    )
    if not include_closed:
        query = query.where(PaperIVTrade.status == "open")
    trades = list((await db.execute(query)).scalars().all())
    limitations: dict[UUID, str | None] = {}
    chains: dict[str, dict] = {}
    for trade in trades:
        if trade.status != "open":
            continue
        expiry = trade.expiry.strftime(NSE_DATE_FORMAT)
        if expiry not in chains:
            chains[expiry] = await get_options_chain(
                company.ticker,
                nse_symbol,
                expiry,
            )
        _, limitation = await refresh_trade_mark(db, trade, chains[expiry])
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


@router.post(
    "/{ticker}/paper-iv-trades/{trade_id}/close",
    response_model=PaperIVTradeOut,
)
async def close_company_paper_iv_trade(
    ticker: str,
    trade_id: UUID,
    body: PaperIVTradeClose,
    db: AsyncSession = Depends(get_db),
):
    from app.models import PaperIVTrade

    company = await _get_company(db, ticker)
    _, nse_symbol = _india_market_identifiers(company)
    trade = (
        await db.execute(
            select(PaperIVTrade).where(
                PaperIVTrade.id == trade_id,
                PaperIVTrade.company_id == company.id,
                PaperIVTrade.portfolio_id == body.portfolio_id,
            )
        )
    ).scalar_one_or_none()
    if trade is None:
        raise HTTPException(status_code=404, detail="Unknown paper trade.")
    if trade.status == "closed":
        return paper_trade_response(trade, await trade_marks(db, trade.id))

    expiry = trade.expiry.strftime(NSE_DATE_FORMAT)
    chain = await get_options_chain(company.ticker, nse_symbol, expiry)
    mark, limitation = await refresh_trade_mark(db, trade, chain)
    if mark is None or limitation is not None:
        raise HTTPException(
            status_code=409,
            detail=limitation or "The strategy cannot currently be marked for exit.",
        )
    trade.status = "closed"
    trade.closed_at = datetime.now(UTC)
    trade.realized_pnl = mark.pnl
    await db.commit()
    return paper_trade_response(trade, await trade_marks(db, trade.id))


@router.post("/{ticker}/analysis", response_model=CompanyAnalysisOut)
async def get_company_analysis(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    overview = await get_financial_overview(
        db,
        ticker=company.ticker,
        cik=company.cik,
        company_id=company.id,
        country=company.country,
        currency=company.reporting_currency,
        market_data_ticker=company.market_data_ticker,
    )
    return await analyze_company(db, company, overview)


@router.post("/{ticker}/chat", response_model=CompanyChatResponse)
async def chat_about_company(
    ticker: str,
    body: CompanyChatRequest,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    return await answer_company_question(db, company, body)


@router.get("/{ticker}/outlook", response_model=CompanyOutlookOut)
async def get_compact_company_outlook(
    ticker: str,
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, ticker)
    return await get_company_outlook(db, company)


@router.get("/{ticker}/filings", response_model=list[FilingOut])
async def get_company_filings(ticker: str, db: AsyncSession = Depends(get_db)):
    company = await _get_company(db, ticker)
    filings = (
        (
            await db.execute(
                select(SecFiling)
                .where(SecFiling.company_id == company.id)
                .order_by(desc(SecFiling.filing_date))
                .limit(40)
            )
        )
        .scalars()
        .all()
    )
    return filings
