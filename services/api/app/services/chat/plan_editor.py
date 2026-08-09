"""Conversational search-plan modification (spec §12).

The plan is edited (directly or via the LLM), then only the affected stages rerun:
structured filtering, research for newly admitted candidates, and ranking.
Existing research results are reused — unchanged work is not repeated.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import generate_structured
from app.models import ResearchSession
from app.prompts.chat import PLAN_EDIT_SYSTEM, PLAN_EDIT_USER
from app.schemas.api import PlanPatchRequest
from app.schemas.search import SearchPlan
from app.services import search_service
from app.services.query_planner.planner import enforce_india_market_cap

logger = logging.getLogger(__name__)


async def edit_plan_with_instruction(plan: SearchPlan, instruction: str) -> SearchPlan:
    import json

    messages = [
        {"role": "system", "content": PLAN_EDIT_SYSTEM},
        {
            "role": "user",
            "content": PLAN_EDIT_USER.format(
                plan_json=json.dumps(plan.model_dump(mode="json"), indent=2),
                instruction=instruction,
            ),
        },
    ]
    new_plan = await generate_structured(SearchPlan, messages)
    new_plan.original_query = plan.original_query
    new_plan.universe = plan.universe
    if plan.universe in {"NIFTY_100", "NIFTY_200", "NSE_MAINBOARD"}:
        new_plan = enforce_india_market_cap(new_plan, instruction)
    new_plan.candidate_limit = min(max(new_plan.candidate_limit, 1), 15)
    new_plan.final_limit = min(max(new_plan.final_limit, 1), new_plan.candidate_limit)
    return new_plan


async def apply_plan_patch(
    db: AsyncSession, session: ResearchSession, body: PlanPatchRequest
) -> dict:
    if session.search_plan is None:
        return {"error": "Session has no plan yet"}
    current = SearchPlan.model_validate(session.search_plan)
    if current.universe in {"NIFTY_100", "NIFTY_200"}:
        current.universe = "NSE_MAINBOARD"

    if body.plan is not None:
        new_plan = body.plan
        new_plan.original_query = current.original_query
        new_plan.universe = current.universe
    elif body.instruction:
        new_plan = await edit_plan_with_instruction(current, body.instruction)
    else:
        return {"error": "Provide an instruction or an edited plan"}

    session.search_plan = new_plan.model_dump(mode="json")
    session.status = "created"
    await db.commit()

    if body.rerun:
        # Rerun structured filtering + research for newly admitted candidates + ranking.
        # Candidates already researched are kept and reused (see run_search).
        search_service.start_search_incremental(session.id)
    return {
        "search_id": str(session.id),
        "plan": new_plan.model_dump(mode="json"),
        "rerun": body.rerun,
    }
