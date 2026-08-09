"""Unit tests for final ranking arithmetic (spec §11, §20)."""

from uuid import uuid4

from app.schemas.search import (
    CandidateResearchResult,
    ConditionResult,
    ResearchCondition,
    SearchPlan,
    SemanticCondition,
)
from app.services.ranking.scoring import compute_final_score, evidence_multiplier


def make_plan() -> SearchPlan:
    return SearchPlan(
        original_query="q",
        base_semantic_conditions=[
            SemanticCondition(
                id="sem", concept="c", card_types=["business_activity"], required=True, weight=0.5
            )
        ],
        research_conditions=[
            ResearchCondition(
                id="growth",
                type="revenue_yoy_growth",
                operator="gte",
                threshold=10,
                required=True,
                weight=0.5,
            )
        ],
    )


def make_result(status="pass", score=1.0, confidence=1.0) -> CandidateResearchResult:
    return CandidateResearchResult(
        company_id=uuid4(),
        ticker="TST",
        condition_results=[
            ConditionResult(condition_id="growth", status=status, score=score, explanation="")
        ],
        completed=True,
        overall_confidence=confidence,
    )


class TestEvidenceMultiplier:
    def test_full_confidence(self):
        assert evidence_multiplier(1.0) == 1.0

    def test_zero_confidence(self):
        assert abs(evidence_multiplier(0.0) - 0.70) < 1e-9

    def test_clamped(self):
        assert evidence_multiplier(2.0) == 1.0


class TestFinalScore:
    def test_perfect_candidate(self):
        ranked = compute_final_score(make_plan(), {"sem": 1.0}, make_result())
        assert ranked.eligible
        assert ranked.final_score == 1.0
        assert ranked.match_percent == 100.0

    def test_weighted_average(self):
        # sem 0.8 * 0.5 + growth 1.0 * 0.5 = 0.9, confidence 1.0
        ranked = compute_final_score(make_plan(), {"sem": 0.8}, make_result())
        assert ranked.final_score == 0.9

    def test_confidence_discounts_score(self):
        ranked = compute_final_score(make_plan(), {"sem": 1.0}, make_result(confidence=0.5))
        assert ranked.final_score == round(1.0 * (0.70 + 0.15), 4)

    def test_missing_required_semantic_evidence_ineligible(self):
        ranked = compute_final_score(make_plan(), {}, make_result())
        assert not ranked.eligible
        assert "sem" in ranked.why_ineligible[0]

    def test_failed_required_research_condition_ineligible(self):
        ranked = compute_final_score(
            make_plan(), {"sem": 1.0}, make_result(status="fail", score=0.0)
        )
        assert not ranked.eligible

    def test_partial_allowed_by_default(self):
        ranked = compute_final_score(
            make_plan(), {"sem": 1.0}, make_result(status="partial", score=0.5)
        )
        assert ranked.eligible

    def test_partial_rejected_when_strict(self):
        ranked = compute_final_score(
            make_plan(),
            {"sem": 1.0},
            make_result(status="partial", score=0.5),
            allow_partial_required=False,
        )
        assert not ranked.eligible

    def test_scores_clamped_to_unit_interval(self):
        ranked = compute_final_score(make_plan(), {"sem": 5.0}, make_result(score=9.0))
        assert ranked.final_score <= 1.0
