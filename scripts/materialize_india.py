"""Resumably materialize verified semantic coverage for the NSE main board.

The job has two checkpointed stages:

1. Store official annual-report metadata for companies that do not have it.
2. Fetch reports transiently, generate and verify cards, and embed them locally.

PDF bytes are never written to disk. Both stages derive their pending work from
PostgreSQL, so rerunning this command safely resumes after an interruption.

Usage:
  services/api/.venv/bin/python -u scripts/materialize_india.py
  services/api/.venv/bin/python -u scripts/materialize_india.py --cards-only
"""

import argparse
import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))


def progress(stage: str, message: str) -> None:
    elapsed = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{elapsed}] [{stage}] {message}", flush=True)


async def run_workers(
    items: list[tuple[UUID, str]],
    *,
    concurrency: int,
    stage: str,
    operation: Callable[[UUID, str], Awaitable[str]],
) -> tuple[int, int]:
    queue: asyncio.Queue[tuple[UUID, str]] = asyncio.Queue()
    for item in items:
        queue.put_nowait(item)

    completed = 0
    failed = 0
    lock = asyncio.Lock()
    started = time.monotonic()

    async def worker() -> None:
        nonlocal completed, failed
        while True:
            try:
                company_id, ticker = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                detail = await operation(company_id, ticker)
                outcome = "ok"
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                outcome = "failed"
            finally:
                queue.task_done()

            async with lock:
                completed += 1
                if outcome == "failed":
                    failed += 1
                rate = completed / max(time.monotonic() - started, 0.001) * 3600
                progress(
                    stage,
                    f"{completed}/{len(items)} {ticker} {outcome}: {detail} "
                    f"({rate:.1f} companies/hour)",
                )

    await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    return completed - failed, failed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--cards-only", action="store_true")
    parser.add_argument("--metadata-concurrency", type=int, default=2)
    parser.add_argument("--card-concurrency", type=int, default=2)
    parser.add_argument(
        "--minimum-cards",
        type=int,
        default=10,
        help="Companies at or above this verified-card count are already complete",
    )
    args = parser.parse_args()
    if args.metadata_only and args.cards_only:
        parser.error("--metadata-only and --cards-only cannot be combined")

    from sqlalchemy import func, select

    from app.core.db import get_engine, get_session_factory
    from app.core.llm import get_provider
    from app.core.logging import setup_logging
    from app.models import Company, CompanyCard, SecFiling
    from app.services.ingestion import ensure_universe, sync_india_annual_reports
    from app.services.nse.client import get_nse_client
    from app.services.semantic_search.cards import build_cards_for_company

    setup_logging("INFO")
    factory = get_session_factory()
    nse = get_nse_client()

    try:
        async with factory() as db:
            universe_size = await ensure_universe(db)
        progress("setup", f"NSE main-board universe contains {universe_size} companies")

        if not args.cards_only:
            async with factory() as db:
                metadata_query = (
                    select(Company.id, Company.ticker)
                    .where(
                        Company.universe == "NSE_MAINBOARD",
                        ~select(SecFiling.id)
                        .where(
                            SecFiling.company_id == Company.id,
                            SecFiling.form == "ANNUAL_REPORT",
                        )
                        .exists(),
                    )
                    .order_by(Company.ticker)
                )
                metadata_targets = list((await db.execute(metadata_query)).all())

            progress(
                "metadata",
                f"{len(metadata_targets)} companies need annual-report metadata",
            )

            async def sync_metadata(company_id: UUID, ticker: str) -> str:
                async with factory() as db:
                    company = (
                        await db.execute(select(Company).where(Company.id == company_id))
                    ).scalar_one()
                    added = await sync_india_annual_reports(db, company, nse)
                    has_report = (
                        await db.execute(
                            select(func.count(SecFiling.id)).where(
                                SecFiling.company_id == company_id,
                                SecFiling.form == "ANNUAL_REPORT",
                            )
                        )
                    ).scalar_one()
                    return f"reports_added={added}, reports_available={has_report}"

            metadata_ok, metadata_failed = await run_workers(
                metadata_targets,
                concurrency=args.metadata_concurrency,
                stage="metadata",
                operation=sync_metadata,
            )
            progress(
                "metadata",
                f"stage complete: {metadata_ok} succeeded, {metadata_failed} failed",
            )

        if not args.metadata_only:
            async with factory() as db:
                companies = list(
                    (
                        await db.execute(
                            select(Company)
                            .where(Company.universe == "NSE_MAINBOARD")
                            .order_by(Company.ticker)
                        )
                    )
                    .scalars()
                    .all()
                )
                card_counts = dict(
                    (
                        await db.execute(
                            select(CompanyCard.company_id, func.count(CompanyCard.id)).group_by(
                                CompanyCard.company_id
                            )
                        )
                    ).all()
                )
            card_targets = [
                (company.id, company.ticker)
                for company in companies
                if card_counts.get(company.id, 0) < args.minimum_cards
            ]
            progress(
                "cards",
                f"{len(card_targets)} companies need verified semantic cards",
            )

            async def build_cards(company_id: UUID, ticker: str) -> str:
                async with factory() as db:
                    company = (
                        await db.execute(select(Company).where(Company.id == company_id))
                    ).scalar_one()
                    count = await build_cards_for_company(db, company)
                    if count == 0:
                        raise RuntimeError("no verified cards produced")
                    return f"cards={count}"

            cards_ok, cards_failed = await run_workers(
                card_targets,
                concurrency=args.card_concurrency,
                stage="cards",
                operation=build_cards,
            )
            progress("cards", f"stage complete: {cards_ok} succeeded, {cards_failed} failed")
    finally:
        await nse.aclose()
        await get_provider().aclose()
        await get_engine().dispose()


if __name__ == "__main__":
    asyncio.run(main())
