"""System endpoints for genuine forward IV-model validation."""

from fastapi import APIRouter, Query

from app.services.iv_model_evaluation import (
    collect_forward_forecasts,
    evaluation_report,
    path_dependent_historical_backtest,
    score_pending_forecasts,
)

router = APIRouter()


@router.get("")
async def get_iv_model_evaluation():
    return await evaluation_report()


@router.post("/run")
async def run_iv_model_evaluation(limit: int = Query(default=30, ge=1, le=30)):
    scoring = await score_pending_forecasts()
    collection = await collect_forward_forecasts(limit=limit)
    path_dependent_backtest = await path_dependent_historical_backtest(
        force_refresh=True
    )
    return {
        "scoring": scoring,
        "collection": collection,
        "path_dependent_backtest": path_dependent_backtest,
    }
