"""Bounded per-candidate research worker (spec §8).

One identical worker per candidate, run with asyncio.gather. No autonomous
multi-agent frameworks: a worker is a plain function over allowlisted tools with
hard limits (downloads, model calls, deadline). A timeout marks the candidate
incomplete instead of failing the search.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Company
from app.schemas.search import (
    CandidateResearchRequest,
    CandidateResearchResult,
    Citation,
    ConditionResult,
    ResearchCondition,
)
from app.services.research.catalysts import find_catalyst
from app.services.research.financials import YoYResult, compute_yoy_metric

logger = logging.getLogger(__name__)


class WorkerBudget:
    """Tracks the hard limits of spec §8."""

    def __init__(self):
        s = get_settings()
        self.max_downloads = s.worker_max_filing_downloads
        self.max_model_calls = s.worker_max_model_calls
        self.max_chunks = s.worker_max_chunks_per_call
        self.downloads_used = 0
        self.model_calls_used = 0

    def can_model_call(self) -> bool:
        return self.model_calls_used < self.max_model_calls

    def remaining_downloads(self) -> int:
        return max(0, self.max_downloads - self.downloads_used)


def _financial_citation(company: Company, concept: str) -> Citation:
    if company.country == "IN":
        symbol = company.market_data_ticker or f"{company.ticker}.NS"
        return Citation(
            source_type="market_data",
            url=f"https://finance.yahoo.com/quote/{symbol}/financials/",
            description=f"Delayed structured financial data, concept {concept}",
        )
    slug = (concept or "").replace("us-gaap:", "")
    return Citation(
        source_type="sec_xbrl",
        url=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(company.cik).zfill(10)}.json",
        description=f"SEC Company Facts XBRL data, concept {slug}",
    )


def _growth_condition_result(
    condition: ResearchCondition, yoy: YoYResult, company: Company
) -> ConditionResult:
    metric_label = "revenue" if condition.type == "revenue_yoy_growth" else "net income"
    citations = [_financial_citation(company, yoy.concept_used or "")]
    current_label = yoy.current.period_label() if yoy.current else None
    previous_label = yoy.previous.period_label() if yoy.previous else None

    if yoy.status == "unknown" or yoy.growth_percent is None:
        return ConditionResult(
            condition_id=condition.id,
            status="unknown",
            score=0.0,
            measured_value=None,
            unit="percent",
            current_period=current_label,
            comparison_period=previous_label,
            explanation=f"Latest-quarter {metric_label} YoY growth could not be verified: {yoy.note}",
            citations=citations,
        )

    growth = yoy.growth_percent
    threshold = condition.threshold
    if yoy.status == "not_directly_comparable":
        return ConditionResult(
            condition_id=condition.id,
            status="partial",
            score=0.5,
            measured_value=round(growth, 2),
            unit="percent",
            current_period=current_label,
            comparison_period=previous_label,
            explanation=(
                f"Latest-quarter {metric_label} changed {growth:.1f}% YoY, but {yoy.note} "
                "The threshold was therefore not applied automatically."
            ),
            citations=citations,
        )

    passed = True
    if threshold is not None:
        if condition.operator == "gte":
            passed = growth >= threshold
        elif condition.operator == "lte":
            passed = growth <= threshold
        elif condition.operator == "eq":
            passed = abs(growth - threshold) < 0.5

    explanation = (
        f"Latest-quarter {metric_label} grew {growth:.1f}% YoY "
        f"({current_label} vs {previous_label}), verified from structured financial facts"
    )
    if threshold is not None:
        explanation += f"; requirement: {condition.operator} {threshold}%"
    explanation += "."

    return ConditionResult(
        condition_id=condition.id,
        status="pass" if passed else "fail",
        score=1.0 if passed else 0.0,
        measured_value=round(growth, 2),
        unit="percent",
        current_period=current_label,
        comparison_period=previous_label,
        explanation=explanation,
        citations=citations,
    )


async def _research_conditions(
    db: AsyncSession,
    company: Company,
    request: CandidateResearchRequest,
    result: CandidateResearchResult,
) -> None:
    budget = WorkerBudget()
    for condition in request.research_conditions:
        if condition.type in ("revenue_yoy_growth", "net_income_yoy_growth"):
            yoy = await compute_yoy_metric(db, company.id, condition.type)
            result.condition_results.append(_growth_condition_result(condition, yoy, company))
            if yoy.status == "unknown":
                result.limitations.append(
                    f"{condition.id}: {yoy.note or 'no comparable XBRL data.'}"
                )
        elif condition.type in ("recent_sec_catalyst", "custom_filing_question"):
            if not budget.can_model_call():
                result.condition_results.append(
                    ConditionResult(
                        condition_id=condition.id,
                        status="unknown",
                        score=0.0,
                        explanation="Worker model-call budget exhausted before this condition.",
                    )
                )
                result.limitations.append(f"{condition.id}: model-call budget exhausted.")
                continue
            question = condition.question or "Has the company reported a notable recent event?"
            budget.model_calls_used += 1
            finding = await find_catalyst(
                db,
                company,
                question,
                lookback_days=condition.lookback_days or 365,
                max_downloads=budget.remaining_downloads(),
                max_chunks=budget.max_chunks,
            )
            budget.downloads_used = budget.max_downloads  # catalyst pass consumes the budget
            score = (
                finding.relevance_to_query
                if finding.status == "pass"
                else (0.5 * finding.relevance_to_query if finding.status == "partial" else 0.0)
            )
            summary = finding.summary
            if finding.state != "unknown":
                summary += f" (state: {finding.state})"
            result.condition_results.append(
                ConditionResult(
                    condition_id=condition.id,
                    status=finding.status,
                    score=score,
                    explanation=summary or "No catalyst evidence found.",
                    citations=finding.citations,
                )
            )
            result.limitations.extend(f"{condition.id}: {lim}" for lim in finding.limitations)
        else:
            result.condition_results.append(
                ConditionResult(
                    condition_id=condition.id,
                    status="unknown",
                    score=0.0,
                    explanation=f"Unsupported research condition type {condition.type}.",
                )
            )


def _overall_confidence(result: CandidateResearchResult, n_conditions: int) -> float:
    if n_conditions == 0:
        return 1.0
    definitive = sum(1 for c in result.condition_results if c.status != "unknown")
    confidence = definitive / n_conditions
    if result.timed_out:
        confidence *= 0.7
    return round(confidence, 3)


async def research_candidate(
    db: AsyncSession, request: CandidateResearchRequest
) -> CandidateResearchResult:
    result = CandidateResearchResult(company_id=request.company_id, ticker=request.ticker)
    company = (
        await db.execute(select(Company).where(Company.id == request.company_id))
    ).scalar_one()
    try:
        async with asyncio.timeout(request.deadline_seconds):
            await _research_conditions(db, company, request, result)
        result.completed = True
    except TimeoutError:
        result.timed_out = True
        result.limitations.append(
            f"Research timed out after {request.deadline_seconds}s; findings are partial."
        )
        answered = {c.condition_id for c in result.condition_results}
        for condition in request.research_conditions:
            if condition.id not in answered:
                result.condition_results.append(
                    ConditionResult(
                        condition_id=condition.id,
                        status="unknown",
                        score=0.0,
                        explanation="Not evaluated before the worker deadline.",
                    )
                )
    except Exception as exc:
        logger.exception("Worker failed for %s", request.ticker)
        result.limitations.append(f"Research failed: {exc}")
        answered = {c.condition_id for c in result.condition_results}
        for condition in request.research_conditions:
            if condition.id not in answered:
                result.condition_results.append(
                    ConditionResult(
                        condition_id=condition.id,
                        status="unknown",
                        score=0.0,
                        explanation="Not evaluated due to a worker error.",
                    )
                )

    result.overall_confidence = _overall_confidence(result, len(request.research_conditions))
    return result
