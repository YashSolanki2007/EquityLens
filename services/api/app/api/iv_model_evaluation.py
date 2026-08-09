"""System endpoints for genuine forward IV-model validation."""

from fastapi import APIRouter, Query

from app.services.iv_model_evaluation import (
    collect_forward_forecasts,
    evaluation_report,
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
    return {"scoring": scoring, "collection": collection}
