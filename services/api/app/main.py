import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import setup_logging
from app.models import Company
from app.services.yahoo_live import get_yahoo_live_stream

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    yahoo_stream = get_yahoo_live_stream()
    lab_mark_task = None
    intraday_copula_task = None
    iv_mark_task = None
    iv_evaluation_task = None
    if settings.yahoo_live_stream_enabled and not settings.upstox_access_token.strip():
        try:
            from app.services.technical_scanner import get_fno_underlyings

            fno_symbols = await get_fno_underlyings()
            async with get_session_factory()() as db:
                companies = (
                    (
                        await db.execute(
                            select(Company)
                            .where(
                                Company.universe == "NSE_MAINBOARD",
                                Company.ticker.in_(fno_symbols),
                            )
                            .order_by(Company.ticker)
                        )
                    )
                    .scalars()
                    .all()
                )
            aliases = {
                company.ticker: company.market_data_ticker or f"{company.ticker}.NS"
                for company in companies
            }
            await yahoo_stream.start(
                aliases,
                base_label="NSE F&O",
                max_symbols=settings.yahoo_live_max_symbols,
            )
        except Exception as exc:
            # Live data is an enhancement. A database or Yahoo outage must not stop
            # historical scans or the rest of the application from starting.
            logger.warning("Yahoo live stream startup was skipped: %s", exc)
    if settings.app_environment.strip().lower() not in {"prod", "production"}:
        from app.services.intraday_copula_tracker import run_intraday_copula_recorder
        from app.services.iv_model_evaluation import run_iv_model_evaluation_recorder
        from app.services.market_data.paper_iv_trades import run_paper_iv_mark_recorder
        from app.services.paper_lab_spot_trades import run_spot_mark_recorder

        lab_mark_task = asyncio.create_task(
            run_spot_mark_recorder(),
            name="paper-lab-spot-mark-recorder",
        )
        intraday_copula_task = asyncio.create_task(
            run_intraday_copula_recorder(),
            name="intraday-copula-paper-recorder",
        )
        iv_mark_task = asyncio.create_task(
            run_paper_iv_mark_recorder(),
            name="paper-iv-mark-recorder",
        )
        iv_evaluation_task = asyncio.create_task(
            run_iv_model_evaluation_recorder(),
            name="iv-model-evaluation-recorder",
        )
    yield
    if lab_mark_task is not None:
        lab_mark_task.cancel()
        await asyncio.gather(lab_mark_task, return_exceptions=True)
    if intraday_copula_task is not None:
        intraday_copula_task.cancel()
        await asyncio.gather(intraday_copula_task, return_exceptions=True)
    if iv_mark_task is not None:
        iv_mark_task.cancel()
        await asyncio.gather(iv_mark_task, return_exceptions=True)
    if iv_evaluation_task is not None:
        iv_evaluation_task.cancel()
        await asyncio.gather(iv_evaluation_task, return_exceptions=True)
    await yahoo_stream.stop()
    from app.core.llm import get_provider

    provider = get_provider()
    aclose = getattr(provider, "aclose", None)
    if aclose:
        await aclose()


app = FastAPI(title="Equity Research Prototype", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


def _include_routers() -> None:
    from app.api import (
        admin,
        companies,
        iv_model_evaluation,
        market,
        search,
        technical,
        trade_suggestions,
        trade_tracker,
    )

    app.include_router(search.router, prefix="/api/search", tags=["search"])
    app.include_router(companies.router, prefix="/api/companies", tags=["companies"])
    app.include_router(market.router, prefix="/api/market", tags=["market"])
    app.include_router(technical.router, prefix="/api/technical", tags=["technical"])
    app.include_router(
        trade_suggestions.router,
        prefix="/api/trade-suggestions",
        tags=["trade-suggestions"],
    )
    app.include_router(
        trade_tracker.router,
        prefix="/api/trade-tracker",
        tags=["trade-tracker"],
    )
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
    app.include_router(
        iv_model_evaluation.router,
        prefix="/api/iv-model-evaluation",
        tags=["iv-model-evaluation"],
    )


_include_routers()
