"""Assemble API response objects from persisted search sessions."""

from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Citation as CitationRow,
)
from app.models import (
    Company,
    CompanyMarketSnapshot,
    ResearchCandidate,
    ResearchSession,
)
from app.models import (
    ConditionResult as ConditionResultRow,
)
from app.schemas.api import (
    CitationOut,
    ConditionResultOut,
    FunnelOut,
    ResultCandidateOut,
    SessionOut,
)
from app.schemas.search import SearchPlan

DIRECTNESS_ORDER = {"core": 0, "direct": 1, "indirect": 2, "prospective": 3}


def _directness_badge(semantic_matches: dict | None) -> str | None:
    if not semantic_matches:
        return None
    best = None
    for m in semantic_matches.values():
        for card in m.get("best_cards", [])[:1]:
            d = card.get("directness")
            if d and (best is None or DIRECTNESS_ORDER.get(d, 9) < DIRECTNESS_ORDER.get(best, 9)):
                best = d
    return "direct" if best == "core" else best


async def build_session_out(db: AsyncSession, session: ResearchSession) -> SessionOut:
    candidates = (
        (
            await db.execute(
                select(ResearchCandidate).where(ResearchCandidate.session_id == session.id)
            )
        )
        .scalars()
        .all()
    )
    company_ids = [c.company_id for c in candidates]
    companies: dict[UUID, Company] = {}
    snapshots: dict[UUID, CompanyMarketSnapshot] = {}
    if company_ids:
        for c in (
            (await db.execute(select(Company).where(Company.id.in_(company_ids)))).scalars().all()
        ):
            companies[c.id] = c
        rows = (
            (
                await db.execute(
                    select(CompanyMarketSnapshot)
                    .where(CompanyMarketSnapshot.company_id.in_(company_ids))
                    .order_by(
                        CompanyMarketSnapshot.company_id,
                        desc(CompanyMarketSnapshot.retrieved_at),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            snapshots.setdefault(row.company_id, row)

    results: list[ResultCandidateOut] = []
    for cand in candidates:
        cond_rows = (
            (
                await db.execute(
                    select(ConditionResultRow).where(ConditionResultRow.candidate_id == cand.id)
                )
            )
            .scalars()
            .all()
        )
        cond_outs = []
        for cond in cond_rows:
            citations = (
                (
                    await db.execute(
                        select(CitationRow).where(CitationRow.condition_result_id == cond.id)
                    )
                )
                .scalars()
                .all()
            )
            cond_outs.append(
                ConditionResultOut(
                    condition_id=cond.condition_id,
                    condition_type=cond.condition_type,
                    status=cond.status,
                    score=cond.score,
                    measured_value=cond.measured_value,
                    unit=cond.unit,
                    current_period=cond.current_period,
                    comparison_period=cond.comparison_period,
                    explanation=cond.explanation,
                    citations=[
                        CitationOut(
                            source_type=c.source_type,
                            url=c.url,
                            accession=c.accession,
                            description=c.description,
                            excerpt=c.excerpt,
                            filing_date=c.filing_date,
                        )
                        for c in citations
                    ],
                )
            )
        company = companies.get(cand.company_id)
        snapshot = snapshots.get(cand.company_id)
        results.append(
            ResultCandidateOut(
                company_id=cand.company_id,
                ticker=cand.ticker,
                name=company.name if company else None,
                country=company.country if company else None,
                exchange=company.exchange if company else None,
                currency=company.reporting_currency if company else None,
                stage=cand.stage,
                rank=cand.rank,
                eligible=cand.eligible,
                final_score=cand.final_score,
                match_percent=round(cand.final_score * 100, 1)
                if cand.final_score is not None
                else None,
                semantic_score=cand.semantic_score,
                semantic_matches=cand.semantic_matches,
                market_cap_usd=snapshot.market_cap_usd if snapshot else None,
                market_cap_native=snapshot.market_cap_native if snapshot else None,
                market_cap_retrieved_at=snapshot.retrieved_at if snapshot else None,
                completed=cand.completed,
                timed_out=cand.timed_out,
                overall_confidence=cand.overall_confidence,
                why_matched=cand.why_matched,
                limitations=list(cand.limitations or []),
                contradictions=list(cand.contradictions or []),
                condition_results=cond_outs,
                directness_badge=_directness_badge(cand.semantic_matches),
            )
        )

    results.sort(
        key=lambda r: (r.rank is None, r.rank if r.rank is not None else 0, -(r.final_score or 0))
    )

    plan = None
    if session.search_plan:
        plan = SearchPlan.model_validate(session.search_plan)
    funnel = FunnelOut(**(session.funnel or {})) if session.funnel else None
    return SessionOut(
        id=session.id,
        original_query=session.original_query,
        status=session.status,
        mode=session.mode,
        market=session.market,
        search_plan=plan,
        funnel=funnel,
        error=session.error,
        created_at=session.created_at,
        results=results,
    )
