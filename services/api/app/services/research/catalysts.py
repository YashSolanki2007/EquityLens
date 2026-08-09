"""Catalyst research over recent official filings (spec §10).

Workflow: retrieve recent U.S. regulatory filings or an Indian annual report, parse and chunk once
(cached in filing_chunks), embed chunks, retrieve the most relevant ones for the
question, and ask the configured model to classify the evidence.
"""

import logging
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import (
    InvalidModelOutputError,
    LLMProvider,
    generate_structured,
    get_provider,
)
from app.models import Company, FilingChunk, SecFiling
from app.prompts.catalyst import CATALYST_SYSTEM, CATALYST_USER
from app.schemas.search import CatalystFinding, Citation
from app.services.ingestion import download_filing, download_india_filing
from app.services.nse.client import get_nse_client
from app.services.nse.parser import pdf_to_pages
from app.services.sec.client import get_sec_client
from app.services.sec.parser import chunk_text, html_to_text

logger = logging.getLogger(__name__)

MAX_8K = 6  # most recent 8-Ks parsed per candidate
MAX_CHUNK_EMBED_BATCH = 64


class CatalystModelOutput(BaseModel):
    status: Literal["pass", "partial", "fail", "unknown"]
    category: Literal[
        "capacity_expansion",
        "facility_opening",
        "capital_investment",
        "acquisition",
        "major_contract",
        "product_launch",
        "partnership",
        "regulatory_development",
        "other",
    ] = "other"
    event_date: date | None = None
    summary: str = ""
    state: Literal[
        "announced", "approved", "under_construction", "completed", "cancelled", "unknown"
    ] = "unknown"
    relevance_to_query: float = Field(default=0.0, ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)
    evidence_indices: list[int] = Field(default_factory=list)


async def ensure_filing_chunks(
    db: AsyncSession, company: Company, filing: SecFiling, *, provider: LLMProvider
) -> list[FilingChunk]:
    """Parse + chunk + embed a filing once; cached in filing_chunks by filing id."""
    existing = (
        (
            await db.execute(
                select(FilingChunk)
                .where(FilingChunk.filing_id == filing.id)
                .order_by(FilingChunk.chunk_index)
            )
        )
        .scalars()
        .all()
    )
    if existing and all(c.embedding is not None for c in existing):
        return list(existing)

    if company.country == "IN":
        content = await download_india_filing(db, filing, get_nse_client())
        text = "\n\n".join(pdf_to_pages(content))
    else:
        html = await download_filing(db, company, filing, get_sec_client())
        text = html_to_text(html)
    texts = chunk_text(text, target_chars=1500, overlap_chars=150, max_chunks=200)
    if not texts:
        return []

    rows: list[FilingChunk] = []
    if not existing:
        for i, chunk in enumerate(texts):
            row = FilingChunk(filing_id=filing.id, chunk_index=i, section=filing.form, text=chunk)
            db.add(row)
            rows.append(row)
    else:
        rows = list(existing)

    for start in range(0, len(rows), MAX_CHUNK_EMBED_BATCH):
        batch = rows[start : start + MAX_CHUNK_EMBED_BATCH]
        embeddings = await provider.embed([r.text for r in batch])
        for row, emb in zip(batch, embeddings, strict=True):
            row.embedding = emb
            row.embed_model = provider.embed_model_name
    await db.commit()
    return rows


async def collect_recent_filings(
    db: AsyncSession, company: Company, lookback_days: int
) -> list[SecFiling]:
    """Recent annual/regulatory filings available for the company's home market."""
    if company.country == "IN":
        latest_report = (
            await db.execute(
                select(SecFiling)
                .where(
                    SecFiling.company_id == company.id,
                    SecFiling.form == "ANNUAL_REPORT",
                )
                .order_by(SecFiling.filing_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return [latest_report] if latest_report is not None else []
    cutoff = date.today() - timedelta(days=lookback_days)
    eight_ks = (
        (
            await db.execute(
                select(SecFiling)
                .where(
                    SecFiling.company_id == company.id,
                    SecFiling.form == "8-K",
                    SecFiling.filing_date >= cutoff,
                )
                .order_by(SecFiling.filing_date.desc())
                .limit(MAX_8K)
            )
        )
        .scalars()
        .all()
    )
    latest: list[SecFiling] = []
    for form in ("10-Q", "10-K"):
        row = (
            await db.execute(
                select(SecFiling)
                .where(SecFiling.company_id == company.id, SecFiling.form == form)
                .order_by(SecFiling.filing_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            latest.append(row)
    return list(eight_ks) + latest


async def find_catalyst(
    db: AsyncSession,
    company: Company,
    question: str,
    *,
    lookback_days: int = 365,
    max_downloads: int = 4,
    max_chunks: int = 12,
    provider: LLMProvider | None = None,
) -> CatalystFinding:
    """Retrieve relevant chunks from recent filings and classify them."""
    provider = provider or get_provider()
    filings = await collect_recent_filings(db, company, lookback_days)
    if not filings:
        return CatalystFinding(
            status="unknown",
            summary="No recent filings available for catalyst research.",
            limitations=[
                (
                    "No annual report is on record for this Indian company."
                    if company.country == "IN"
                    else "No 8-K/10-Q/10-K filings are on record within the lookback window."
                )
            ],
        )

    # Respect the worker's download budget: prefer recent 8-Ks, then 10-Q/10-K.
    filings_by_id: dict = {}
    downloads = 0
    all_chunks: list[FilingChunk] = []
    for filing in filings:
        if downloads >= max_downloads:
            break
        if not filing.primary_document:
            continue
        try:
            chunks = await ensure_filing_chunks(db, company, filing, provider=provider)
        except Exception as exc:
            logger.warning(
                "Chunking failed for %s %s: %s", company.ticker, filing.accession_number, exc
            )
            continue
        downloads += 1
        filings_by_id[filing.id] = filing
        all_chunks.extend(chunks)

    if not all_chunks:
        return CatalystFinding(
            status="unknown",
            summary="Filings could not be parsed for catalyst research.",
            limitations=["Filing downloads or parsing failed."],
        )

    [q_emb] = await provider.embed([question])
    chunk_ids = [c.id for c in all_chunks]
    distance = FilingChunk.embedding.cosine_distance(q_emb)
    top_chunks = (
        (
            await db.execute(
                select(FilingChunk)
                .where(FilingChunk.id.in_(chunk_ids), FilingChunk.embedding.is_not(None))
                .order_by(distance)
                .limit(max_chunks)
            )
        )
        .scalars()
        .all()
    )

    excerpts = []
    for i, chunk in enumerate(top_chunks):
        src = filings_by_id.get(chunk.filing_id)
        form = src.form if src else chunk.section or "filing"
        fdate = src.filing_date.isoformat() if src else "unknown date"
        excerpts.append(f"[{i}] ({form}, filed {fdate})\n{chunk.text}")

    messages = [
        {"role": "system", "content": CATALYST_SYSTEM},
        {
            "role": "user",
            "content": CATALYST_USER.format(
                name=company.name,
                ticker=company.ticker,
                question=question,
                excerpts="\n\n".join(excerpts),
            ),
        },
    ]
    try:
        out = await generate_structured(CatalystModelOutput, messages, provider=provider)
    except InvalidModelOutputError:
        return CatalystFinding(
            status="unknown",
            summary="The configured model could not produce a valid classification.",
            limitations=["Model output failed validation; no catalyst judgment available."],
        )

    citations: list[Citation] = []
    for idx in out.evidence_indices:
        if 0 <= idx < len(top_chunks):
            chunk = top_chunks[idx]
            src = filings_by_id.get(chunk.filing_id)
            if src is None:
                continue
            citations.append(
                Citation(
                    source_type=(
                        "exchange_filing" if company.country == "IN" else "sec_filing"
                    ),
                    url=src.primary_doc_url or "",
                    accession=src.accession_number,
                    description=f"{src.form} filed {src.filing_date.isoformat()}",
                    excerpt=chunk.text[:600],
                    filing_date=src.filing_date,
                )
            )
    if not citations and top_chunks and out.status in ("pass", "partial"):
        # A pass without usable citations is not trustworthy evidence.
        out.status = "unknown"
        out.limitations.append("Model did not identify which excerpts support the finding.")

    return CatalystFinding(
        status=out.status,
        category=out.category,
        event_date=out.event_date,
        summary=out.summary,
        state=out.state,
        relevance_to_query=out.relevance_to_query,
        citations=citations,
        limitations=out.limitations,
    )
