"""Unit tests for card aggregation and preliminary semantic scoring (spec §7, §20)."""

from uuid import uuid4

from app.schemas.search import SemanticCondition
from app.services.semantic_search.retrieval import (
    CardMatch,
    CompanyConditionMatch,
    combine_condition_matches,
    condition_company_score,
)


def card(similarity: float, directness: str = "core", confidence: float = 0.9) -> CardMatch:
    return CardMatch(
        card_id=uuid4(),
        ticker="TST",
        card_type="business_activity",
        text="t",
        directness=directness,
        materiality="major",
        similarity=similarity,
        confidence=confidence,
        source_url="",
        source_excerpt="",
        source_accession="",
        filing_date="2026-01-01",
    )


def cond(id: str, required: bool = True, weight: float = 0.5) -> SemanticCondition:
    return SemanticCondition(
        id=id, concept="c", card_types=["business_activity"], required=required, weight=weight
    )


class TestConditionScore:
    def test_formula(self):
        # 0.70*0.8 + 0.20*1.0 (core) + 0.10*0.9 = 0.85
        assert abs(condition_company_score(card(0.8)) - 0.85) < 1e-9

    def test_directness_mapping(self):
        assert (
            condition_company_score(card(0.8, "prospective"))
            < condition_company_score(card(0.8, "indirect"))
            < condition_company_score(card(0.8, "direct"))
            < condition_company_score(card(0.8, "core"))
        )


class TestCombine:
    def test_company_missing_required_condition_dropped(self):
        c1, c2 = uuid4(), uuid4()
        per_condition = {
            "a": {
                c1: CompanyConditionMatch("a", 0.9, [card(0.9)]),
                c2: CompanyConditionMatch("a", 0.8, [card(0.8)]),
            },
            "b": {c1: CompanyConditionMatch("b", 0.7, [card(0.7)])},
        }
        results = combine_condition_matches(
            [cond("a"), cond("b")], per_condition, {c1: "AAA", c2: "BBB"}
        )
        assert [r.ticker for r in results] == ["AAA"]

    def test_optional_condition_missing_keeps_company(self):
        c1 = uuid4()
        per_condition = {
            "a": {c1: CompanyConditionMatch("a", 0.9, [card(0.9)])},
            "b": {},
        }
        results = combine_condition_matches(
            [cond("a"), cond("b", required=False)], per_condition, {c1: "AAA"}
        )
        assert len(results) == 1

    def test_weighted_combination_and_sorting(self):
        c1, c2 = uuid4(), uuid4()
        per_condition = {
            "a": {
                c1: CompanyConditionMatch("a", 1.0, [card(1.0)]),
                c2: CompanyConditionMatch("a", 0.5, [card(0.5)]),
            },
        }
        results = combine_condition_matches([cond("a")], per_condition, {c1: "HI", c2: "LO"})
        assert results[0].ticker == "HI"
        assert results[0].combined_score == 1.0
        assert results[1].combined_score == 0.5

    def test_best_cards_capped_at_three(self):
        match = CompanyConditionMatch("a", 0.9, [card(0.9), card(0.8), card(0.7)])
        assert len(match.best_cards) == 3


class TestEvidenceFloor:
    def test_weak_best_card_is_not_evidence(self):
        from app.services.semantic_search.retrieval import passes_evidence_floor

        weak = CompanyConditionMatch("a", 0.0, [card(0.45)])
        strong = CompanyConditionMatch("a", 0.0, [card(0.62)])
        empty = CompanyConditionMatch("a", 0.0, [])
        assert not passes_evidence_floor(weak)
        assert passes_evidence_floor(strong)
        assert not passes_evidence_floor(empty)
