"""Search orchestration (spec §4): plan -> semantic retrieval -> structured filters ->
parallel bounded research -> deterministic ranking -> persisted workspace.

Progress is published to the SSE event bus at every stage.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.llm import get_provider
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
from app.schemas.search import (
    CandidateResearchRequest,
    CandidateResearchResult,
    ConditionResult,
    SearchPlan,
)
from app.services.events import event_bus
from app.services.query_planner.planner import plan_query
from app.services.ranking.filters import (
    CompanyFilterInput,
    apply_structured_filters,
)
from app.services.ranking.scoring import compute_final_score
from app.services.semantic_search.retrieval import (
    CompanySemanticResult,
    semantic_retrieval,
)
from app.workers.candidate_worker import research_candidate

logger = logging.getLogger(__name__)

_running_searches: set[asyncio.Task] = set()


async def create_session(
    db: AsyncSession,
    query: str,
    mode: str,
    plan: SearchPlan | None,
    *,
    market: Literal["US", "IN"] = "US",
) -> ResearchSession:
    s = get_settings()
    provider = get_provider()
    if plan is not None and plan.universe in {"NIFTY_100", "NIFTY_200"}:
        plan = plan.model_copy(deep=True)
        plan.universe = "NSE_MAINBOARD"
    session = ResearchSession(
        original_query=query,
        market=market,
        mode=mode,
        status="created",
        search_plan=plan.model_dump(mode="json") if plan else None,
        data_versions={
            "universe": "NSE_MAINBOARD" if market == "IN" else "NYSE_100",
            "chat_model": provider.model_name,
            "embed_model": provider.embed_model_name,
            "prompt_version": s.prompt_version,
        },
    )
    db.add(session)
    await db.commit()
    return session


def start_search(session_id: UUID) -> None:
    task = asyncio.create_task(run_search(session_id))
    _running_searches.add(task)
    task.add_done_callback(_running_searches.discard)


def start_search_incremental(session_id: UUID) -> None:
    """Rerun after a plan edit: keeps researched candidates, researches only new ones."""
    event_bus.clear(session_id)
    task = asyncio.create_task(run_search(session_id, only_new_candidates=True))
    _running_searches.add(task)
    task.add_done_callback(_running_searches.discard)


async def _load_snapshots(
    db: AsyncSession, company_ids: list[UUID]
) -> dict[UUID, CompanyMarketSnapshot]:
    """Latest snapshot per company."""
    snapshots: dict[UUID, CompanyMarketSnapshot] = {}
    if not company_ids:
        return snapshots
    rows = (
        (
            await db.execute(
                select(CompanyMarketSnapshot)
                .where(CompanyMarketSnapshot.company_id.in_(company_ids))
                .order_by(
                    CompanyMarketSnapshot.company_id, desc(CompanyMarketSnapshot.retrieved_at)
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        snapshots.setdefault(row.company_id, row)
    return snapshots


def _why_matched(
    semantic: CompanySemanticResult | None,
    research: CandidateResearchResult,
) -> str:
    parts: list[str] = []
    if semantic:
        best_card = None
        best_sim = -1.0
        for match in semantic.per_condition.values():
            if match.best_cards and match.best_cards[0].similarity > best_sim:
                best_card = match.best_cards[0]
                best_sim = best_card.similarity
        if best_card:
            parts.append(f"Semantic evidence: {best_card.text}")
    for cond in research.condition_results:
        if cond.status == "pass":
            parts.append(cond.explanation)
    return " ".join(parts) if parts else "Matched the structured criteria of the query."


def _directness_badge(semantic: CompanySemanticResult | None) -> str | None:
    if not semantic:
        return None
    order = {"core": 0, "direct": 1, "indirect": 2, "prospective": 3}
    best: str | None = None
    for match in semantic.per_condition.values():
        for card in match.best_cards[:1]:
            if best is None or order.get(card.directness, 9) < order.get(best, 9):
                best = card.directness
    if best == "core":
        return "direct"  # user-facing badge groups core with direct
    return best


async def run_search(session_id: UUID, *, only_new_candidates: bool = False) -> None:
    factory = get_session_factory()
    try:
        async with factory() as db:
            session = (
                await db.execute(select(ResearchSession).where(ResearchSession.id == session_id))
            ).scalar_one()

            # --- Stage: planning ---
            if session.search_plan is None:
                event_bus.publish(session_id, "planning_query")
                session.status = "planning"
                await db.commit()
                plan = await plan_query(
                    session.original_query,
                    mode=session.mode,
                    market=cast(Literal["US", "IN"], session.market),
                )
                session.search_plan = plan.model_dump(mode="json")
                await db.commit()
            else:
                plan = SearchPlan.model_validate(session.search_plan)
            if plan.universe in {"NIFTY_100", "NIFTY_200"}:
                # Transparently migrate persisted pre-expansion sessions so a
                # follow-up rerun does not target an empty legacy universe.
                plan.universe = "NSE_MAINBOARD"
                session.search_plan = plan.model_dump(mode="json")
                await db.commit()
            event_bus.publish(session_id, "plan_ready", plan=plan.model_dump(mode="json"))

            companies = (
                (await db.execute(select(Company).where(Company.universe == plan.universe)))
                .scalars()
                .all()
            )
            ticker_by_company = {c.id: c.ticker for c in companies}
            company_by_id = {c.id: c for c in companies}
            funnel = {"indexed": len(companies)}

            # --- Stage: semantic retrieval ---
            event_bus.publish(session_id, "retrieving_semantic_candidates")
            session.status = "retrieving"
            await db.commit()
            if plan.base_semantic_conditions:
                semantic_results = await semantic_retrieval(
                    db,
                    plan.base_semantic_conditions,
                    ticker_by_company,
                    company_ids=list(company_by_id),
                )
            else:
                semantic_results = [
                    CompanySemanticResult(company_id=c.id, ticker=c.ticker, combined_score=0.5)
                    for c in companies
                ]
            funnel["semantic_matches"] = len(semantic_results)
            event_bus.publish(
                session_id,
                "retrieving_semantic_candidates",
                count=len(semantic_results),
                done=True,
            )

            # --- Stage: structured filters ---
            event_bus.publish(session_id, "applying_base_filters")
            snapshots = await _load_snapshots(db, [r.company_id for r in semantic_results])
            filtered: list[CompanySemanticResult] = []
            filter_details: dict[UUID, list] = {}
            for result in semantic_results:
                company = company_by_id[result.company_id]
                snapshot = snapshots.get(result.company_id)
                keep, details = apply_structured_filters(
                    CompanyFilterInput(
                        ticker=company.ticker,
                        sector=company.sector,
                        industry=company.industry,
                        market_cap_usd=snapshot.market_cap_usd if snapshot else None,
                        market_cap_native=(snapshot.market_cap_native if snapshot else None),
                    ),
                    plan.base_structured_conditions,
                )
                filter_details[result.company_id] = [
                    {
                        "field": d.field,
                        "status": d.status,
                        "required": d.required,
                        "detail": d.detail,
                    }
                    for d in details
                ]
                if keep:
                    filtered.append(result)
            funnel["passed_base_filters"] = len(filtered)
            event_bus.publish(session_id, "applying_base_filters", count=len(filtered), done=True)

            candidates = filtered[: plan.candidate_limit]

            # Persist candidate rows (replace unless doing an incremental rerun).
            if not only_new_candidates:
                old_candidate_ids = select(ResearchCandidate.id).where(
                    ResearchCandidate.session_id == session_id
                )
                old_result_ids = select(ConditionResultRow.id).where(
                    ConditionResultRow.candidate_id.in_(old_candidate_ids)
                )
                await db.execute(
                    delete(CitationRow).where(CitationRow.condition_result_id.in_(old_result_ids))
                )
                await db.execute(
                    delete(ConditionResultRow).where(
                        ConditionResultRow.candidate_id.in_(old_candidate_ids)
                    )
                )
                await db.execute(
                    delete(ResearchCandidate).where(ResearchCandidate.session_id == session_id)
                )
                await db.commit()

            existing_rows = (
                (
                    await db.execute(
                        select(ResearchCandidate).where(ResearchCandidate.session_id == session_id)
                    )
                )
                .scalars()
                .all()
            )

            # On an incremental rerun the edited structured filters must be re-applied
            # to candidates kept from the previous run — otherwise a tightened filter
            # never removes an already-researched company.
            if only_new_candidates:
                passing_ids = {r.company_id for r in filtered}
                for row in existing_rows:
                    row.structured_filter_results = {
                        "results": filter_details.get(row.company_id, [])
                    }
                    if row.company_id not in passing_ids:
                        row.stage = "filtered_out"
                        row.eligible = False
                        row.rank = None
                        limitations = list(row.limitations or [])
                        note = "Removed by updated structured filters."
                        if note not in limitations:
                            limitations.append(note)
                        row.limitations = limitations
                    elif row.stage == "filtered_out":
                        # Filter relaxed again: restore without redoing research.
                        row.stage = "researched" if row.completed else "filtered"
                await db.commit()

            already_researched = {
                r.company_id for r in existing_rows if r.stage in ("researched", "qualified")
            }

            candidate_rows: dict[UUID, ResearchCandidate] = {r.company_id: r for r in existing_rows}
            for result in candidates:
                if result.company_id in candidate_rows:
                    continue
                row = ResearchCandidate(
                    session_id=session_id,
                    company_id=result.company_id,
                    ticker=result.ticker,
                    stage="filtered",
                    semantic_score=result.combined_score,
                    semantic_matches={
                        cid: {
                            "score": m.score,
                            "best_cards": [c.to_dict() for c in m.best_cards],
                        }
                        for cid, m in result.per_condition.items()
                    },
                    structured_filter_results={
                        "results": filter_details.get(result.company_id, [])
                    },
                )
                db.add(row)
                candidate_rows[result.company_id] = row
            session.funnel = funnel
            await db.commit()

            to_research = [r for r in candidates if r.company_id not in already_researched]

        # --- Stage: parallel bounded research (own session per worker) ---
        event_bus.publish(session_id, "validating_financials")
        deadline = get_settings().worker_deadline_seconds
        research_results: dict[UUID, CandidateResearchResult] = {}

        async def worker(sem_result: CompanySemanticResult):
            event_bus.publish(session_id, "researching_candidate", ticker=sem_result.ticker)
            async with factory() as wdb:
                request = CandidateResearchRequest(
                    search_id=session_id,
                    company_id=sem_result.company_id,
                    ticker=sem_result.ticker,
                    research_conditions=plan.research_conditions,
                    deadline_seconds=deadline,
                )
                result = await research_candidate(wdb, request)
                research_results[sem_result.company_id] = result
                event_bus.publish(
                    session_id,
                    "researching_candidate",
                    ticker=sem_result.ticker,
                    done=True,
                    completed=result.completed,
                    timed_out=result.timed_out,
                )

        await asyncio.gather(*(worker(r) for r in to_research))

        # --- Stage: persist research + ranking ---
        async with factory() as db:
            session = (
                await db.execute(select(ResearchSession).where(ResearchSession.id == session_id))
            ).scalar_one()
            rows = (
                (
                    await db.execute(
                        select(ResearchCandidate).where(ResearchCandidate.session_id == session_id)
                    )
                )
                .scalars()
                .all()
            )
            rows_by_company = {r.company_id: r for r in rows}

            for company_id, research_out in research_results.items():
                candidate_row = rows_by_company.get(company_id)
                if candidate_row is None:
                    continue
                row = candidate_row
                row.stage = "researched"
                row.completed = research_out.completed
                row.timed_out = research_out.timed_out
                row.overall_confidence = research_out.overall_confidence
                row.limitations = research_out.limitations
                row.contradictions = research_out.contradictions
                for cond in research_out.condition_results:
                    cond_row = ConditionResultRow(
                        candidate_id=row.id,
                        condition_id=cond.condition_id,
                        condition_type=_condition_type(plan, cond),
                        status=cond.status,
                        score=cond.score,
                        measured_value=cond.measured_value,
                        unit=cond.unit,
                        current_period=cond.current_period,
                        comparison_period=cond.comparison_period,
                        explanation=cond.explanation,
                    )
                    db.add(cond_row)
                    await db.flush()
                    for citation in cond.citations:
                        db.add(
                            CitationRow(
                                condition_result_id=cond_row.id,
                                source_type=citation.source_type,
                                url=citation.url,
                                accession=citation.accession,
                                description=citation.description,
                                excerpt=citation.excerpt,
                                filing_date=citation.filing_date,
                            )
                        )
            await db.commit()

            event_bus.publish(session_id, "ranking_results")
            researched_rows = [r for r in rows if r.stage in ("researched", "qualified")]
            funnel = dict(session.funnel or {})
            funnel["researched"] = len(researched_rows)

            plan_obj = SearchPlan.model_validate(session.search_plan)
            ranked = []
            for row in researched_rows:
                sem_scores = {cid: m["score"] for cid, m in (row.semantic_matches or {}).items()}
                research = research_results.get(row.company_id)
                if research is None:
                    research = await _result_from_row(db, row)
                    research_results[row.company_id] = research
                ranked.append((row, compute_final_score(plan_obj, sem_scores, research)))

            ranked.sort(key=lambda pair: pair[1].final_score, reverse=True)
            eligible_rank = 0
            excluded_tickers = {e.upper() for e in plan_obj.exclusions}
            for row, scored in ranked:
                if row.ticker.upper() in excluded_tickers:
                    # User exclusions are sticky across reruns.
                    row.eligible = False
                    row.rank = None
                    limitations = list(row.limitations or [])
                    if "Excluded by user request." not in limitations:
                        limitations.append("Excluded by user request.")
                    row.limitations = limitations
                    continue
                row.final_score = scored.final_score
                row.eligible = scored.eligible
                sem_result = _semantic_from_row(row)
                research = research_results.get(row.company_id)
                if research is not None:
                    row.why_matched = _why_matched(sem_result, research)
                if scored.eligible and eligible_rank < plan_obj.final_limit:
                    eligible_rank += 1
                    row.rank = eligible_rank
                    row.stage = "qualified"
                else:
                    row.rank = None
                    if not scored.eligible and scored.why_ineligible:
                        limitations = list(row.limitations or [])
                        limitations.extend(scored.why_ineligible)
                        row.limitations = limitations

            funnel["fully_qualified"] = eligible_rank
            session.funnel = funnel
            session.status = "completed"
            session.updated_at = datetime.now(UTC)
            await db.commit()

        event_bus.publish(session_id, "completed", funnel=funnel)
    except Exception as exc:
        logger.exception("Search %s failed", session_id)
        try:
            async with factory() as db:
                session = (
                    await db.execute(
                        select(ResearchSession).where(ResearchSession.id == session_id)
                    )
                ).scalar_one()
                session.status = "failed"
                session.error = str(exc)
                await db.commit()
        finally:
            event_bus.publish(session_id, "failed", error=str(exc))


def _condition_type(plan: SearchPlan, cond: ConditionResult) -> str:
    for rc in plan.research_conditions:
        if rc.id == cond.condition_id:
            return rc.type
    return "unknown"


def _semantic_from_row(row: ResearchCandidate) -> CompanySemanticResult | None:
    if not row.semantic_matches:
        return None
    from app.services.semantic_search.retrieval import CardMatch, CompanyConditionMatch

    per_condition = {}
    for cid, m in row.semantic_matches.items():
        cards = [
            CardMatch(
                card_id=c.get("card_id"),
                ticker=c.get("ticker", row.ticker),
                card_type=c.get("card_type", ""),
                text=c.get("text", ""),
                directness=c.get("directness", "direct"),
                materiality=c.get("materiality", "unknown"),
                similarity=c.get("similarity", 0.0),
                confidence=c.get("confidence", 0.0),
                source_url=c.get("source_url", ""),
                source_excerpt=c.get("source_excerpt", ""),
                source_accession=c.get("source_accession", ""),
                filing_date=c.get("filing_date", ""),
            )
            for c in m.get("best_cards", [])
        ]
        per_condition[cid] = CompanyConditionMatch(
            condition_id=cid, score=m.get("score", 0.0), best_cards=cards
        )
    return CompanySemanticResult(
        company_id=row.company_id,
        ticker=row.ticker,
        combined_score=row.semantic_score or 0.0,
        per_condition=per_condition,
    )


async def _result_from_row(db: AsyncSession, row: ResearchCandidate) -> CandidateResearchResult:
    """Rebuild a CandidateResearchResult from persisted rows (for incremental reruns)."""
    cond_rows = (
        (
            await db.execute(
                select(ConditionResultRow).where(ConditionResultRow.candidate_id == row.id)
            )
        )
        .scalars()
        .all()
    )
    return CandidateResearchResult(
        company_id=row.company_id,
        ticker=row.ticker,
        condition_results=[
            ConditionResult(
                condition_id=c.condition_id,
                status=cast(Literal["pass", "partial", "fail", "unknown"], c.status),
                score=c.score,
                measured_value=c.measured_value,
                unit=c.unit,
                current_period=c.current_period,
                comparison_period=c.comparison_period,
                explanation=c.explanation,
            )
            for c in cond_rows
        ],
        limitations=list(row.limitations or []),
        contradictions=list(row.contradictions or []),
        completed=row.completed,
        timed_out=row.timed_out,
        overall_confidence=row.overall_confidence or 0.0,
    )
