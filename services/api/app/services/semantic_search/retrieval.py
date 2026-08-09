"""Semantic retrieval over company cards (spec §7).

For each semantic condition: embed, pgvector cosine search, filter by card type and
directness, take the top 100 cards, group by company keeping the best three cards,
and compute the preliminary score:

    semantic_score = 0.70 * best_card_similarity
                   + 0.20 * directness_score
                   + 0.10 * source_confidence

Companies must have evidence for every required condition.
"""

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import LLMProvider, get_provider
from app.models import CompanyCard
from app.schemas.search import SemanticCondition

logger = logging.getLogger(__name__)

TOP_CARDS_PER_CONDITION = 100
BEST_CARDS_PER_COMPANY = 3

# A company only counts as evidence for a condition when its best card clears this
# cosine-similarity floor. Without it, top-K retrieval over a small card corpus lets
# semantically unrelated companies through on similarities in the 0.4s.
MIN_EVIDENCE_SIMILARITY = 0.55

DIRECTNESS_SCORE = {"core": 1.00, "direct": 0.85, "indirect": 0.55, "prospective": 0.30}

DIRECTNESS_FILTER = {
    "any": ("core", "direct", "indirect", "prospective"),
    "direct": ("core", "direct"),
    "core": ("core",),
}


@dataclass
class CardMatch:
    card_id: UUID
    ticker: str
    card_type: str
    text: str
    directness: str
    materiality: str
    similarity: float
    confidence: float
    source_url: str
    source_excerpt: str
    source_accession: str
    filing_date: str

    def to_dict(self) -> dict:
        return {
            "card_id": str(self.card_id),
            "ticker": self.ticker,
            "card_type": self.card_type,
            "text": self.text,
            "directness": self.directness,
            "materiality": self.materiality,
            "similarity": round(self.similarity, 4),
            "confidence": self.confidence,
            "source_url": self.source_url,
            "source_excerpt": self.source_excerpt[:600],
            "source_accession": self.source_accession,
            "filing_date": self.filing_date,
        }


@dataclass
class CompanyConditionMatch:
    condition_id: str
    score: float
    best_cards: list[CardMatch] = field(default_factory=list)


@dataclass
class CompanySemanticResult:
    company_id: UUID
    ticker: str
    combined_score: float
    per_condition: dict[str, CompanyConditionMatch] = field(default_factory=dict)


def passes_evidence_floor(match: "CompanyConditionMatch") -> bool:
    return bool(match.best_cards) and match.best_cards[0].similarity >= MIN_EVIDENCE_SIMILARITY


def condition_company_score(best: CardMatch) -> float:
    directness = DIRECTNESS_SCORE.get(best.directness, 0.3)
    return 0.70 * best.similarity + 0.20 * directness + 0.10 * best.confidence


async def retrieve_condition_matches(
    db: AsyncSession,
    condition: SemanticCondition,
    *,
    provider: LLMProvider | None = None,
    company_ids: list[UUID] | None = None,
) -> dict[UUID, CompanyConditionMatch]:
    """Run pgvector retrieval for one semantic condition, grouped by company."""
    provider = provider or get_provider()
    [embedding] = await provider.embed([condition.concept])

    allowed_directness = DIRECTNESS_FILTER[condition.directness_required]
    card_types = list(condition.card_types) or None

    distance = CompanyCard.embedding.cosine_distance(embedding)
    query = (
        select(CompanyCard, distance.label("distance"))
        .where(CompanyCard.embedding.is_not(None))
        .where(CompanyCard.directness.in_(allowed_directness))
        .order_by(distance)
        .limit(TOP_CARDS_PER_CONDITION)
    )
    if card_types:
        query = query.where(CompanyCard.card_type.in_(card_types))
    if company_ids is not None:
        if not company_ids:
            return {}
        query = query.where(CompanyCard.company_id.in_(company_ids))

    rows = (await db.execute(query)).all()

    grouped: dict[UUID, CompanyConditionMatch] = {}
    for card, dist in rows:
        similarity = 1.0 - float(dist)
        match = CardMatch(
            card_id=card.id,
            ticker=card.ticker,
            card_type=card.card_type,
            text=card.text,
            directness=card.directness,
            materiality=card.materiality,
            similarity=similarity,
            confidence=card.confidence,
            source_url=card.source_url,
            source_excerpt=card.source_excerpt,
            source_accession=card.source_filing_accession,
            filing_date=card.filing_date.isoformat(),
        )
        entry = grouped.setdefault(
            card.company_id, CompanyConditionMatch(condition_id=condition.id, score=0.0)
        )
        if len(entry.best_cards) < BEST_CARDS_PER_COMPANY:
            entry.best_cards.append(match)

    grouped = {
        company_id: entry
        for company_id, entry in grouped.items()
        if passes_evidence_floor(entry)
    }
    for entry in grouped.values():
        entry.score = condition_company_score(entry.best_cards[0])
    return grouped


def combine_condition_matches(
    conditions: list[SemanticCondition],
    per_condition: dict[str, dict[UUID, CompanyConditionMatch]],
    ticker_by_company: dict[UUID, str],
) -> list[CompanySemanticResult]:
    """Merge per-condition matches. Companies missing any required condition are dropped.
    The combined score is the weight-normalized average of condition scores."""
    required_ids = [c.id for c in conditions if c.required]
    all_companies: set[UUID] = set()
    for matches in per_condition.values():
        all_companies.update(matches.keys())

    results: list[CompanySemanticResult] = []
    for company_id in all_companies:
        if any(company_id not in per_condition.get(cid, {}) for cid in required_ids):
            continue
        total_weight = 0.0
        weighted = 0.0
        matched: dict[str, CompanyConditionMatch] = {}
        for cond in conditions:
            match = per_condition.get(cond.id, {}).get(company_id)
            if match is None:
                continue
            weight = cond.weight if cond.weight > 0 else 1.0
            weighted += weight * match.score
            total_weight += weight
            matched[cond.id] = match
        if not matched or total_weight == 0:
            continue
        results.append(
            CompanySemanticResult(
                company_id=company_id,
                ticker=ticker_by_company.get(company_id, "?"),
                combined_score=weighted / total_weight,
                per_condition=matched,
            )
        )
    results.sort(key=lambda r: r.combined_score, reverse=True)
    return results


async def semantic_retrieval(
    db: AsyncSession,
    conditions: list[SemanticCondition],
    ticker_by_company: dict[UUID, str],
    *,
    provider: LLMProvider | None = None,
    company_ids: list[UUID] | None = None,
) -> list[CompanySemanticResult]:
    per_condition: dict[str, dict[UUID, CompanyConditionMatch]] = {}
    for condition in conditions:
        per_condition[condition.id] = await retrieve_condition_matches(
            db, condition, provider=provider, company_ids=company_ids
        )
    return combine_condition_matches(conditions, per_condition, ticker_by_company)
