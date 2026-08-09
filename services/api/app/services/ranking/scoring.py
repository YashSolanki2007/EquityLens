"""Deterministic final ranking (spec §11). The LLM never sets or alters this arithmetic.

    final_score = sum(condition_weight * condition_score) * evidence_multiplier
    evidence_multiplier = 0.70 + 0.30 * overall_confidence

All component scores are normalized to [0, 1]; weights are normalized to sum to 1.
Ranking reflects query fit only — never investment attractiveness.
"""

from dataclasses import dataclass

from app.schemas.search import (
    CandidateResearchResult,
    SearchPlan,
)


@dataclass
class RankedCandidate:
    company_id: str
    ticker: str
    eligible: bool
    final_score: float
    match_percent: float
    why_ineligible: list[str]


def evidence_multiplier(overall_confidence: float) -> float:
    return 0.70 + 0.30 * min(max(overall_confidence, 0.0), 1.0)


def compute_final_score(
    plan: SearchPlan,
    semantic_scores: dict[str, float],  # condition_id -> score in [0,1] for this company
    research: CandidateResearchResult,
    *,
    allow_partial_required: bool = True,
) -> RankedCandidate:
    """Combine semantic and research condition scores with plan weights."""
    why_ineligible: list[str] = []

    research_by_id = {c.condition_id: c for c in research.condition_results}

    # Eligibility: every required semantic condition needs evidence; every required
    # research condition must be pass (or partial when allowed).
    for cond in plan.base_semantic_conditions:
        if cond.required and cond.id not in semantic_scores:
            why_ineligible.append(f"missing evidence for required condition '{cond.id}'")
    for rcond in plan.research_conditions:
        res = research_by_id.get(rcond.id)
        status = res.status if res else "unknown"
        acceptable = ("pass", "partial") if allow_partial_required else ("pass",)
        if rcond.required and status not in acceptable:
            why_ineligible.append(f"required condition '{rcond.id}' is {status}")

    weighted = 0.0
    total_weight = 0.0
    for cond in plan.base_semantic_conditions:
        score = min(max(semantic_scores.get(cond.id, 0.0), 0.0), 1.0)
        weight = cond.weight if cond.weight > 0 else 0.01
        weighted += weight * score
        total_weight += weight
    for rcond in plan.research_conditions:
        res = research_by_id.get(rcond.id)
        score = min(max(res.score if res else 0.0, 0.0), 1.0)
        weight = rcond.weight if rcond.weight > 0 else 0.01
        weighted += weight * score
        total_weight += weight

    base = weighted / total_weight if total_weight > 0 else 0.0
    final = base * evidence_multiplier(research.overall_confidence)
    return RankedCandidate(
        company_id=str(research.company_id),
        ticker=research.ticker,
        eligible=not why_ineligible,
        final_score=round(final, 4),
        match_percent=round(final * 100, 1),
        why_ineligible=why_ineligible,
    )
