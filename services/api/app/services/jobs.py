"""Background ingestion jobs tracked in the ingestion_jobs table.

Jobs run as plain asyncio tasks in the API process (no Celery/queues per spec §2).
"""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.db import get_session_factory
from app.models import IngestionJob

logger = logging.getLogger(__name__)

_running_tasks: set[asyncio.Task] = set()


async def create_job(job_type: str, ticker: str | None = None) -> UUID:
    async with get_session_factory()() as db:
        job = IngestionJob(job_type=job_type, ticker=ticker, status="pending")
        db.add(job)
        await db.commit()
        return job.id


async def _set_job(job_id: UUID, **fields) -> None:
    async with get_session_factory()() as db:
        job = (await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))).scalar_one()
        for k, v in fields.items():
            setattr(job, k, v)
        await db.commit()


def start_job(job_id: UUID, coro_factory) -> None:
    """Run `await coro_factory()` in the background, recording status transitions."""

    async def runner():
        await _set_job(job_id, status="running", started_at=datetime.now(UTC))
        try:
            detail = await coro_factory()
            await _set_job(job_id, status="done", detail=detail, finished_at=datetime.now(UTC))
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            await _set_job(job_id, status="failed", error=str(exc), finished_at=datetime.now(UTC))

    task = asyncio.create_task(runner())
    _running_tasks.add(task)
    task.add_done_callback(_running_tasks.discard)
