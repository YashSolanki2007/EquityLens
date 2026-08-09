from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db, get_session_factory
from app.models import Company, CompanyCard, IngestionJob, SecFiling
from app.schemas.api import JobOut
from app.services import jobs as jobs_service
from app.services.ingestion import ensure_universe, ingest_company
from app.services.materialization_status import parse_materialization_log

router = APIRouter()


@router.post("/bootstrap")
async def bootstrap(db: AsyncSession = Depends(get_db)):
    """Load the NSE main-board universe, then ingest it in the background."""
    count = await ensure_universe(db)
    job_id = await jobs_service.create_job("bootstrap")

    async def run():
        import asyncio

        from sqlalchemy import select as sa_select

        factory = get_session_factory()
        async with factory() as jdb:
            companies = (await jdb.execute(sa_select(Company))).scalars().all()
        sem = asyncio.Semaphore(4)
        ok, failed = 0, []

        async def one(company_id):
            nonlocal ok
            async with sem:
                async with factory() as jdb:
                    company = (
                        await jdb.execute(sa_select(Company).where(Company.id == company_id))
                    ).scalar_one()
                    try:
                        await ingest_company(jdb, company)
                        ok += 1
                    except Exception as exc:
                        failed.append({"ticker": company.ticker, "error": str(exc)})

        await asyncio.gather(*(one(c.id) for c in companies))
        return {"companies": count, "ingested": ok, "failed": failed}

    jobs_service.start_job(job_id, run)
    return {"job_id": str(job_id), "companies": count}


@router.post("/ingest/{ticker}")
async def ingest_one(ticker: str, db: AsyncSession = Depends(get_db)):
    company = (
        await db.execute(select(Company).where(Company.ticker == ticker.upper()))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(404, f"Unknown ticker {ticker}")
    job_id = await jobs_service.create_job("ingest_company", ticker=company.ticker)
    company_id = company.id

    async def run():
        async with get_session_factory()() as jdb:
            c = (await jdb.execute(select(Company).where(Company.id == company_id))).scalar_one()
            return await ingest_company(jdb, c)

    jobs_service.start_job(job_id, run)
    return {"job_id": str(job_id)}


@router.post("/rebuild-embeddings")
async def rebuild_embeddings():
    from app.services.semantic_search.indexer import rebuild_all_embeddings

    job_id = await jobs_service.create_job("rebuild_embeddings")

    async def run():
        return await rebuild_all_embeddings()

    jobs_service.start_job(job_id, run)
    return {"job_id": str(job_id)}


@router.get("/jobs/{job_id}", response_model=JobOut)
async def get_job(job_id: UUID, db: AsyncSession = Depends(get_db)):
    job = (
        await db.execute(select(IngestionJob).where(IngestionJob.id == job_id))
    ).scalar_one_or_none()
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job


@router.get("/status")
async def admin_status(db: AsyncSession = Depends(get_db)):
    """Universe/ingestion/card/embedding status for the /admin page."""
    companies = (await db.execute(select(Company).order_by(Company.ticker))).scalars().all()

    async def count_map(query) -> dict[UUID, int]:
        return {company_id: count for company_id, count in (await db.execute(query)).all()}

    filings = await count_map(
        select(SecFiling.company_id, func.count()).group_by(SecFiling.company_id)
    )
    downloaded_primary_filing = await count_map(
        select(SecFiling.company_id, func.count())
        .where(
            SecFiling.form.in_(("10-K", "ANNUAL_REPORT")),
            SecFiling.downloaded.is_(True),
        )
        .group_by(SecFiling.company_id)
    )
    cards = await count_map(
        select(CompanyCard.company_id, func.count()).group_by(CompanyCard.company_id)
    )
    embedded = await count_map(
        select(CompanyCard.company_id, func.count())
        .where(CompanyCard.embedding.is_not(None))
        .group_by(CompanyCard.company_id)
    )
    recent_jobs = (
        (await db.execute(select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(20)))
        .scalars()
        .all()
    )
    return {
        "universe_size": len(companies),
        "missing_identifiers": [
            c.ticker
            for c in companies
            if (c.country == "US" and not c.cik) or (c.country == "IN" and not c.isin)
        ],
        "companies": [
            {
                "ticker": c.ticker,
                "name": c.name,
                "country": c.country,
                "identifier": c.isin if c.country == "IN" else c.cik,
                "filings": filings.get(c.id, 0),
                "downloaded_primary_filing": downloaded_primary_filing.get(c.id, 0),
                "cards": cards.get(c.id, 0),
                "cards_embedded": embedded.get(c.id, 0),
            }
            for c in companies
        ],
        "recent_jobs": [JobOut.model_validate(j).model_dump(mode="json") for j in recent_jobs],
    }


@router.get("/materialization-status")
async def materialization_status(db: AsyncSession = Depends(get_db)):
    """Live NSE report/card materialization coverage, throughput, and ETA."""

    universe_filter = Company.universe == "NSE_MAINBOARD"
    universe_size = (
        await db.execute(select(func.count(Company.id)).where(universe_filter))
    ).scalar_one()
    companies_with_reports = (
        await db.execute(
            select(func.count(Company.id)).where(
                universe_filter,
                select(SecFiling.id)
                .where(
                    SecFiling.company_id == Company.id,
                    SecFiling.form == "ANNUAL_REPORT",
                )
                .exists(),
            )
        )
    ).scalar_one()
    completed_card_companies = (
        select(CompanyCard.company_id)
        .group_by(CompanyCard.company_id)
        .having(func.count(CompanyCard.id) >= 10)
    )
    companies_with_cards = (
        await db.execute(
            select(func.count(Company.id)).where(
                universe_filter,
                Company.id.in_(completed_card_companies),
            )
        )
    ).scalar_one()
    total_cards = (await db.execute(select(func.count(CompanyCard.id)))).scalar_one()
    embedded_cards = (
        await db.execute(
            select(func.count(CompanyCard.id)).where(CompanyCard.embedding.is_not(None))
        )
    ).scalar_one()

    progress = parse_materialization_log()
    return {
        **progress,
        "universe_size": universe_size,
        "companies_with_reports": companies_with_reports,
        "report_coverage_percent": round(
            companies_with_reports / universe_size * 100 if universe_size else 0.0, 1
        ),
        "companies_with_cards": companies_with_cards,
        "card_coverage_percent": round(
            companies_with_cards / universe_size * 100 if universe_size else 0.0, 1
        ),
        "total_cards": total_cards,
        "embedded_cards": embedded_cards,
    }
