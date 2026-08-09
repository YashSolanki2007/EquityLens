"""Follow-up intent router and handlers (spec §12)."""

import logging
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm import InvalidModelOutputError, generate_structured
from app.models import ChatMessage, ResearchCandidate, ResearchSession
from app.models import ConditionResult as ConditionResultRow
from app.prompts.chat import INTENT_SYSTEM, INTENT_USER
from app.schemas.api import PlanPatchRequest
from app.schemas.search import (
    CandidateResearchRequest,
    ResearchCondition,
    SearchPlan,
)
from app.services.chat.grounded import answer_grounded
from app.services.chat.plan_editor import apply_plan_patch
from app.workers.candidate_worker import research_candidate

logger = logging.getLogger(__name__)

Intent = Literal[
    "explain_result",
    "compare_results",
    "show_evidence",
    "clarify_metric",
    "modify_filter",
    "exclude_company",
    "expand_candidate_limit",
    "research_new_condition",
    "deep_research",
    "general_financial_explanation",
]

EXISTING_DATA_INTENTS = {
    "explain_result",
    "compare_results",
    "show_evidence",
    "clarify_metric",
    "general_financial_explanation",
}


class IntentClassification(BaseModel):
    intent: Intent
    target_tickers: list[str] = Field(default_factory=list)
    instruction: str | None = None
    question: str | None = None


async def _save_message(
    db: AsyncSession,
    session_id,
    role: str,
    content: str,
    *,
    intent: str | None = None,
    citations: list | None = None,
    limitations: list | None = None,
) -> ChatMessage:
    row = ChatMessage(
        session_id=session_id,
        role=role,
        content=content,
        intent=intent,
        citations=citations or [],
        limitations=limitations or [],
    )
    db.add(row)
    await db.commit()
    return row


async def classify_intent(
    session: ResearchSession, message: str, tickers: list[str]
) -> IntentClassification:
    messages = [
        {"role": "system", "content": INTENT_SYSTEM},
        {
            "role": "user",
            "content": INTENT_USER.format(
                query=session.original_query,
                tickers=", ".join(tickers) or "(none yet)",
                message=message,
            ),
        },
    ]
    try:
        return await generate_structured(IntentClassification, messages)
    except InvalidModelOutputError:
        return IntentClassification(intent="explain_result")


async def _handle_exclude(db: AsyncSession, session: ResearchSession, tickers: list[str]) -> str:
    if not tickers:
        return "No tickers to exclude were identified in your message."
    rows = (
        (
            await db.execute(
                select(ResearchCandidate).where(
                    ResearchCandidate.session_id == session.id,
                    ResearchCandidate.ticker.in_([t.upper() for t in tickers]),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.eligible = False
        row.rank = None
        limitations = list(row.limitations or [])
        limitations.append("Excluded by user request.")
        row.limitations = limitations

    # Re-rank the remaining eligible candidates deterministically.
    plan = SearchPlan.model_validate(session.search_plan)
    remaining = (
        (
            await db.execute(
                select(ResearchCandidate)
                .where(
                    ResearchCandidate.session_id == session.id,
                    ResearchCandidate.eligible.is_(True),
                )
                .order_by(ResearchCandidate.final_score.desc())
            )
        )
        .scalars()
        .all()
    )
    for i, row in enumerate(remaining):
        row.rank = i + 1 if i < plan.final_limit else None

    if session.search_plan is not None:
        plan.exclusions = list({*plan.exclusions, *[t.upper() for t in tickers]})
        session.search_plan = plan.model_dump(mode="json")
    await db.commit()
    excluded = ", ".join(t.upper() for t in tickers)
    return f"Excluded {excluded} from the results and re-ranked the remaining companies."


async def _handle_new_research(
    db: AsyncSession, session: ResearchSession, classification: IntentClassification, message: str
) -> tuple[str, list, list]:
    """Research a new question against the current result companies only."""
    question = classification.question or message
    condition = ResearchCondition(
        id=f"followup_{abs(hash(question)) % 10_000}",
        type="custom_filing_question",
        operator="semantic_match",
        question=question,
        lookback_days=365,
        required=False,
        weight=0.1,
    )
    targets = (
        (
            await db.execute(
                select(ResearchCandidate).where(
                    ResearchCandidate.session_id == session.id,
                    ResearchCandidate.stage.in_(["researched", "qualified"]),
                )
            )
        )
        .scalars()
        .all()
    )
    if classification.target_tickers:
        wanted = {t.upper() for t in classification.target_tickers}
        targets = [t for t in targets if t.ticker in wanted]
    if not targets:
        return "There are no researched companies in this workspace to investigate.", [], []

    citations_all = []
    lines = []
    for row in targets:
        request = CandidateResearchRequest(
            search_id=session.id,
            company_id=row.company_id,
            ticker=row.ticker,
            research_conditions=[condition],
        )
        result = await research_candidate(db, request)
        for cond in result.condition_results:
            cond_row = ConditionResultRow(
                candidate_id=row.id,
                condition_id=cond.condition_id,
                condition_type="custom_filing_question",
                status=cond.status,
                score=cond.score,
                explanation=cond.explanation,
            )
            db.add(cond_row)
            await db.flush()
            from app.models import Citation as CitationRow

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
                citations_all.append(citation.model_dump(mode="json"))
            lines.append(f"{row.ticker} [{cond.status}]: {cond.explanation}")
    await db.commit()
    answer = "Findings from recent company filings:\n" + "\n".join(
        f"- {line}" for line in lines
    )
    return answer, citations_all, []


async def handle_follow_up(db: AsyncSession, session: ResearchSession, message: str) -> dict:
    await _save_message(db, session.id, "user", message)

    ranked = (
        (
            await db.execute(
                select(ResearchCandidate.ticker)
                .where(ResearchCandidate.session_id == session.id)
                .order_by(ResearchCandidate.rank.nulls_last())
            )
        )
        .scalars()
        .all()
    )
    classification = await classify_intent(session, message, list(ranked))
    intent = classification.intent
    citations: list = []
    limitations: list = []

    if intent in EXISTING_DATA_INTENTS:
        answer, cited, limitations = await answer_grounded(
            db, session, message, classification.target_tickers or None
        )
        citations = [c.model_dump(mode="json") for c in cited]
    elif intent == "exclude_company":
        answer = await _handle_exclude(db, session, classification.target_tickers)
    elif intent in ("modify_filter", "expand_candidate_limit"):
        instruction = classification.instruction or message
        patch = await apply_plan_patch(
            db, session, PlanPatchRequest(instruction=instruction, rerun=True)
        )
        if "error" in patch:
            answer = f"Could not modify the search: {patch['error']}"
        else:
            answer = (
                "Updated the search plan and re-running the affected stages "
                "(structured filters, research for newly admitted candidates, ranking). "
                "Results will refresh shortly."
            )
    elif intent == "research_new_condition":
        answer, citations, limitations = await _handle_new_research(
            db, session, classification, message
        )
    elif intent == "deep_research":
        from app.services.research.deep_research import (
            resolve_target_tickers,
            run_deep_research,
        )

        settings = get_settings()
        targets = resolve_target_tickers(
            message,
            classification.target_tickers,
            list(ranked),
            max_companies=settings.deep_research_max_companies,
        )
        result = await run_deep_research(db, session.id, classification.question or message, targets)
        answer = result.answer
        citations = [citation.model_dump(mode="json") for citation in result.citations]
        limitations = result.limitations
    else:
        answer, cited, limitations = await answer_grounded(db, session, message, None)
        citations = [c.model_dump(mode="json") for c in cited]

    row = await _save_message(
        db,
        session.id,
        "assistant",
        answer,
        intent=intent,
        citations=citations,
        limitations=limitations,
    )
    return {
        "message_id": str(row.id),
        "intent": intent,
        "answer": answer,
        "citations": citations,
        "limitations": limitations,
    }
