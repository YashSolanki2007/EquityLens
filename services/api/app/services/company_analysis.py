"""Cached, evidence-grounded Llama analysis for the company detail page."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.llm import generate_structured, get_provider
from app.models import Company, CompanyCard, SecFiling
from app.prompts.company_analysis import (
    BUSINESS_ANALYSIS_SYSTEM,
    BUSINESS_ANALYSIS_USER,
    PROMPT_VERSION,
    REVENUE_ANALYSIS_SYSTEM,
    REVENUE_ANALYSIS_USER,
)
from app.schemas.company import (
    BusinessAnalysisPoint,
    CompanyAnalysisOut,
    FinancialOverviewOut,
    RevenueEvidence,
    RevenueExplanation,
)
from app.services.ingestion import download_filing, download_india_filing
from app.services.nse.client import get_nse_client
from app.services.nse.parser import pdf_to_pages
from app.services.sec.client import get_sec_client
from app.services.sec.parser import chunk_text, html_to_text


class BusinessAnalysisModel(BaseModel):
    strengths: list[BusinessAnalysisPoint] = Field(default_factory=list, max_length=4)
    weaknesses: list[BusinessAnalysisPoint] = Field(default_factory=list, max_length=4)


class RevenueAnalysisModel(BaseModel):
    revenue_explanations: list[RevenueExplanation] = Field(default_factory=list, max_length=4)


def _render_cards(cards: list[CompanyCard]) -> str:
    records = []
    for card in cards:
        records.append(
            {
                "id": str(card.id),
                "type": card.card_type,
                "text": card.text,
                "directness": card.directness,
                "materiality": card.materiality,
                "source_section": card.source_section,
                "source_excerpt": card.source_excerpt[:700],
            }
        )
    return json.dumps(records, indent=2)


ADVERSE_TERMS = re.compile(
    r"\b(depend|dependency|concentrat|constraint|risk|reliance|rely|expos|shortage|"
    r"competition|fluctuat|advers|sensitive|subject to|limited|uncertain|declin)\w*",
    re.IGNORECASE,
)

REVENUE_TERMS = {
    "revenue": 5,
    "sales": 4,
    "rental": 2,
    "increase": 2,
    "decrease": 2,
    "growth": 2,
    "decline": 2,
    "primarily": 2,
    "due to": 4,
    "driven by": 4,
    "attributable": 4,
    "acquisition": 2,
    "pricing": 2,
    "volume": 2,
    "foreign currency": 2,
}

CAUSAL_LANGUAGE = re.compile(
    r"\b(due to|driven by|because|attributable to|resulted from|reflecting)\b",
    re.IGNORECASE,
)


def _clean_points(
    points: list[BusinessAnalysisPoint],
    cards_by_id: dict[str, CompanyCard],
    *,
    require_adverse_evidence: bool = False,
) -> list[BusinessAnalysisPoint]:
    cleaned: list[BusinessAnalysisPoint] = []
    valid_card_ids = set(cards_by_id)
    for point in points:
        point.evidence_card_ids = list(
            dict.fromkeys(card_id for card_id in point.evidence_card_ids if card_id in valid_card_ids)
        )
        evidence_text = " ".join(
            f"{cards_by_id[card_id].text} {cards_by_id[card_id].source_excerpt}"
            for card_id in point.evidence_card_ids
        )
        if point.evidence_card_ids and (
            not require_adverse_evidence or ADVERSE_TERMS.search(evidence_text)
        ):
            cleaned.append(point)
    return cleaned[:4]


def _clean_explanations(
    explanations: list[RevenueExplanation],
    overview: FinancialOverviewOut,
    valid_card_ids: set[str],
    valid_evidence_ids: set[str] | None = None,
) -> list[RevenueExplanation]:
    movements = {movement.id: movement for movement in overview.notable_movements}
    valid_evidence_ids = valid_evidence_ids or set()
    cleaned: list[RevenueExplanation] = []
    seen: set[str] = set()
    for explanation in explanations:
        movement = movements.get(explanation.movement_id)
        if movement is None or movement.id in seen:
            continue
        seen.add(movement.id)
        explanation.period = movement.period
        explanation.change_percent = movement.change_percent
        explanation.evidence_card_ids = list(
            dict.fromkeys(
                card_id
                for card_id in explanation.evidence_card_ids
                if card_id in valid_card_ids
            )
        )
        explanation.evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for evidence_id in explanation.evidence_ids
                if evidence_id in valid_evidence_ids
            )
        )
        if (
            explanation.driver_type == "company_reported_catalyst"
            and (
                not explanation.evidence_ids
                or not CAUSAL_LANGUAGE.search(explanation.explanation)
            )
        ):
            explanation.driver_type = "unexplained"
            explanation.confidence = "low"
            explanation.explanation = (
                "The available filing evidence does not identify a supported cause "
                "for this revenue movement."
            )
        elif (
            explanation.driver_type == "business_context"
            and not explanation.evidence_card_ids
            and not explanation.evidence_ids
        ):
            explanation.driver_type = "unexplained"
            explanation.confidence = "low"
            explanation.explanation = (
                "The available verified company cards do not identify a supported cause "
                "for this revenue movement."
            )
        cleaned.append(explanation)

    for movement_id, movement in movements.items():
        if movement_id in seen:
            continue
        cleaned.append(
            RevenueExplanation(
                movement_id=movement.id,
                period=movement.period,
                change_percent=movement.change_percent,
                driver_type="unexplained",
                explanation=(
                    "The available verified company cards do not identify a supported cause "
                    "for this revenue movement."
                ),
                confidence="low",
            )
        )
    return cleaned[:4]


def _score_revenue_chunk(text: str, direction: str) -> int:
    lowered = text.lower()
    if "revenue" not in lowered and "sales" not in lowered:
        return 0
    score = sum(weight * lowered.count(term) for term, weight in REVENUE_TERMS.items())
    if direction == "increase":
        score += 3 * (lowered.count("increased") + lowered.count("growth"))
    elif direction == "decline":
        score += 3 * (lowered.count("decreased") + lowered.count("decline"))
    return score


async def _collect_revenue_evidence(
    db: AsyncSession,
    company: Company,
    overview: FinancialOverviewOut,
) -> list[RevenueEvidence]:
    if company.country == "IN":
        filing = (
            await db.execute(
                select(SecFiling)
                .where(
                    SecFiling.company_id == company.id,
                    SecFiling.form == "ANNUAL_REPORT",
                )
                .order_by(desc(SecFiling.filing_date))
                .limit(1)
            )
        ).scalar_one_or_none()
        if filing is None:
            return []
        try:
            content = await download_india_filing(db, filing, get_nse_client())
            chunks = chunk_text(
                "\n\n".join(pdf_to_pages(content)),
                target_chars=1700,
                overlap_chars=120,
                max_chunks=250,
            )
        except Exception:
            return []
        evidence: list[RevenueEvidence] = []
        for movement in overview.notable_movements:
            scored = sorted(
                (
                    (_score_revenue_chunk(chunk, movement.direction), index, chunk)
                    for index, chunk in enumerate(chunks)
                ),
                reverse=True,
            )
            for score, index, chunk in scored[:2]:
                if score <= 0:
                    continue
                evidence.append(
                    RevenueEvidence(
                        id=f"{movement.id}:E{len(evidence) + 1}",
                        movement_id=movement.id,
                        url=filing.primary_doc_url or "",
                        description=(
                            f"Annual report filed {filing.filing_date.isoformat()} "
                            f"(revenue discussion excerpt {index + 1})"
                        ),
                        excerpt=chunk[:1600],
                    )
                )
        return evidence

    point_by_end = {
        point.end_date: point for point in overview.annual + overview.quarterly
    }
    accessions: set[str] = set()
    for movement in overview.notable_movements:
        point = point_by_end.get(movement.end_date)
        if point is not None:
            accessions.update(point.accessions)
    if not accessions:
        return []
    filings = (
        (
            await db.execute(
                select(SecFiling).where(
                    SecFiling.company_id == company.id,
                    SecFiling.accession_number.in_(accessions),
                )
            )
        )
        .scalars()
        .all()
    )
    filing_by_accession = {filing.accession_number: filing for filing in filings}
    evidence: list[RevenueEvidence] = []
    downloaded: dict[str, list[str]] = {}
    for movement in overview.notable_movements:
        point = point_by_end.get(movement.end_date)
        if point is None:
            continue
        for accession in point.accessions:
            filing = filing_by_accession.get(accession)
            if filing is None or not filing.primary_document:
                continue
            if accession not in downloaded:
                try:
                    html = await download_filing(db, company, filing, get_sec_client())
                    downloaded[accession] = chunk_text(
                        html_to_text(html),
                        target_chars=1700,
                        overlap_chars=120,
                        max_chunks=250,
                    )
                except Exception:
                    downloaded[accession] = []
            scored = sorted(
                (
                    (_score_revenue_chunk(chunk, movement.direction), index, chunk)
                    for index, chunk in enumerate(downloaded[accession])
                ),
                reverse=True,
            )
            for score, index, chunk in scored[:2]:
                if score <= 0:
                    continue
                evidence.append(
                    RevenueEvidence(
                        id=f"{movement.id}:E{len(evidence) + 1}",
                        movement_id=movement.id,
                        url=filing.primary_doc_url or "",
                        description=(
                            f"{filing.form} filed {filing.filing_date.isoformat()} "
                            f"(revenue discussion excerpt {index + 1})"
                        ),
                        excerpt=chunk[:1600],
                    )
                )
            break
    return evidence


async def analyze_company(
    db: AsyncSession,
    company: Company,
    overview: FinancialOverviewOut,
) -> CompanyAnalysisOut:
    cards = (
        (
            await db.execute(
                select(CompanyCard)
                .where(CompanyCard.company_id == company.id)
                .order_by(desc(CompanyCard.confidence))
            )
        )
        .scalars()
        .all()
    )
    provider = get_provider()
    latest_accession = max(
        (accession for point in overview.annual + overview.quarterly for accession in point.accessions),
        default="no-financial-accession",
    )
    latest_card_version = max(
        (
            f"{card.source_filing_accession}:{card.prompt_version or ''}"
            for card in cards
        ),
        default="no-cards",
    )
    key = cache_key(
        company.ticker,
        PROMPT_VERSION,
        provider.model_name,
        latest_accession,
        latest_card_version,
    )
    cache = FileCache(get_settings().cache_path, "company_analysis")
    cached = cache.get(key, ttl_seconds=None)
    if cached:
        result = CompanyAnalysisOut.model_validate(cached)
        result.cached = True
        return result

    if not cards:
        return CompanyAnalysisOut(
            ticker=company.ticker,
            model_name=provider.model_name,
            generated_at=datetime.now(UTC),
            limitations=["No verified company cards are available for grounded AI analysis."],
        )

    movements = [movement.model_dump(mode="json") for movement in overview.notable_movements]
    revenue_evidence = await _collect_revenue_evidence(db, company, overview)
    async def generate_business() -> BusinessAnalysisModel:
        return await generate_structured(
            BusinessAnalysisModel,
            [
                {"role": "system", "content": BUSINESS_ANALYSIS_SYSTEM},
                {
                    "role": "user",
                    "content": BUSINESS_ANALYSIS_USER.format(
                        company_name=company.name,
                        ticker=company.ticker,
                        sector=company.sector,
                        industry=company.industry,
                        cards=_render_cards(list(cards)),
                    ),
                },
            ],
        )

    async def generate_revenue() -> RevenueAnalysisModel:
        return await generate_structured(
            RevenueAnalysisModel,
            [
                {"role": "system", "content": REVENUE_ANALYSIS_SYSTEM},
                {
                    "role": "user",
                    "content": REVENUE_ANALYSIS_USER.format(
                        company_name=company.name,
                        ticker=company.ticker,
                        movements=json.dumps(movements, indent=2),
                        revenue_evidence=json.dumps(
                            [item.model_dump(mode="json") for item in revenue_evidence],
                            indent=2,
                        ),
                        cards=_render_cards(list(cards)[:12]),
                    ),
                },
            ],
        )

    generation_results = await asyncio.gather(
        generate_business(),
        generate_revenue(),
        return_exceptions=True,
    )
    business_output = generation_results[0]
    revenue_output = generation_results[1]
    limitations: list[str] = []
    if isinstance(business_output, BaseException):
        business_output = BusinessAnalysisModel()
        limitations.append("The model could not produce a valid strengths-and-weaknesses analysis.")
    if isinstance(revenue_output, BaseException):
        revenue_output = RevenueAnalysisModel()
        limitations.append("The model could not produce valid revenue explanations.")
    if not isinstance(business_output, BusinessAnalysisModel) or not isinstance(
        revenue_output, RevenueAnalysisModel
    ):
        raise RuntimeError("Unexpected company-analysis model output")

    cards_by_id = {str(card.id): card for card in cards}
    valid_card_ids = set(cards_by_id)
    valid_evidence_ids = {item.id for item in revenue_evidence}
    result = CompanyAnalysisOut(
        ticker=company.ticker,
        strengths=_clean_points(business_output.strengths, cards_by_id),
        weaknesses=_clean_points(
            business_output.weaknesses,
            cards_by_id,
            require_adverse_evidence=True,
        ),
        revenue_explanations=_clean_explanations(
            revenue_output.revenue_explanations,
            overview,
            valid_card_ids,
            valid_evidence_ids,
        ),
        revenue_evidence=revenue_evidence,
        limitations=limitations,
        model_name=provider.model_name,
        generated_at=datetime.now(UTC),
    )
    cache.put(
        key,
        result.model_dump(mode="json"),
        source="verified_company_cards_and_normalized_financials",
        model_name=provider.model_name,
        prompt_version=PROMPT_VERSION,
    )
    return result
