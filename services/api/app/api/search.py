import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models import ChatMessage as ChatMessageRow
from app.models import ResearchSession
from app.schemas.api import (
    FollowUpRequest,
    PlanPatchRequest,
    PlanRequest,
    RunRequest,
    SessionOut,
    SessionSummaryOut,
)
from app.schemas.search import SearchPlan
from app.services import search_service
from app.services.events import event_bus
from app.services.query_planner.planner import plan_query
from app.services.serializers import build_session_out

router = APIRouter()


@router.post("/plan", response_model=SearchPlan)
async def create_plan(body: PlanRequest):
    """Parse a natural-language query into an editable SearchPlan without executing it."""
    return await plan_query(body.query, mode=body.mode, market=body.market)


@router.post("/run")
async def run_search(body: RunRequest, db: AsyncSession = Depends(get_db)):
    if body.plan is None and not body.query:
        raise HTTPException(422, "Provide either a query or a plan")
    query = body.query or (body.plan.original_query if body.plan else "")
    market = (
        "IN"
        if body.plan is not None
        and body.plan.universe in {"NIFTY_100", "NIFTY_200", "NSE_MAINBOARD"}
        else body.market
    )
    session = await search_service.create_session(db, query, body.mode, body.plan, market=market)
    search_service.start_search(session.id)
    return {"search_id": str(session.id), "status": session.status}


@router.get("/sessions", response_model=list[SessionSummaryOut])
async def list_sessions(db: AsyncSession = Depends(get_db), limit: int = 20):
    rows = (
        (
            await db.execute(
                select(ResearchSession)
                .where(ResearchSession.market == "IN")
                .order_by(desc(ResearchSession.created_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        SessionSummaryOut(
            id=r.id,
            original_query=r.original_query,
            status=r.status,
            mode=r.mode,
            market=r.market,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def _get_session(db: AsyncSession, search_id: UUID) -> ResearchSession:
    session = (
        await db.execute(select(ResearchSession).where(ResearchSession.id == search_id))
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(404, "Unknown search session")
    return session


@router.get("/{search_id}", response_model=SessionOut)
async def get_search(search_id: UUID, db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, search_id)
    return await build_session_out(db, session)


@router.get("/{search_id}/stream")
async def stream_search(search_id: UUID, db: AsyncSession = Depends(get_db)):
    await _get_session(db, search_id)

    async def event_stream():
        async for event in event_bus.subscribe(search_id):
            yield f"data: {json.dumps(event, default=str)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{search_id}/messages")
async def get_messages(search_id: UUID, db: AsyncSession = Depends(get_db)):
    await _get_session(db, search_id)
    rows = (
        (
            await db.execute(
                select(ChatMessageRow)
                .where(ChatMessageRow.session_id == search_id)
                .order_by(ChatMessageRow.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(r.id),
            "role": r.role,
            "content": r.content,
            "intent": r.intent,
            "citations": r.citations or [],
            "limitations": r.limitations or [],
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/{search_id}/follow-up")
async def follow_up(search_id: UUID, body: FollowUpRequest, db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, search_id)
    from app.services.chat.router import handle_follow_up

    return await handle_follow_up(db, session, body.message)


@router.patch("/{search_id}/plan")
async def patch_plan(search_id: UUID, body: PlanPatchRequest, db: AsyncSession = Depends(get_db)):
    session = await _get_session(db, search_id)
    from app.services.chat.plan_editor import apply_plan_patch

    return await apply_plan_patch(db, session, body)
