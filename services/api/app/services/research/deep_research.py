"""Bounded multi-agent deep research for follow-up questions.

This module is intentionally isolated from initial semantic retrieval and ranking.
It resolves a current result company, searches recent news plus official filings, runs
three parallel Llama analysis agents, and synthesizes a citation-backed report.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm import InvalidModelOutputError, generate_structured
from app.models import Company, ResearchCandidate
from app.prompts.deep_research import (
    ANGLE_AGENT_SYSTEM,
    ANGLE_AGENT_USER,
    DEEP_RESEARCH_PLAN_SYSTEM,
    DEEP_RESEARCH_PLAN_USER,
    SYNTHESIS_SYSTEM,
    SYNTHESIS_USER,
)
from app.schemas.search import Citation
from app.services.research.catalysts import find_catalyst
from app.services.research.news import NewsSource, TavilyNewsClient

logger = logging.getLogger(__name__)

ImpactDirection = Literal["positive", "negative", "mixed", "neutral", "unclear"]
ImpactMagnitude = Literal["high", "moderate", "marginal", "none", "unclear"]
ConfidenceLevel = Literal["high", "medium", "low"]


class ResearchAngle(BaseModel):
    name: str
    objective: str
    news_query: str


class DeepResearchPlan(BaseModel):
    event_or_factor: str
    lookback_days: int = Field(default=90, ge=30, le=365)
    angles: list[ResearchAngle] = Field(min_length=3, max_length=3)


class EvidenceClaim(BaseModel):
    statement: str
    evidence_indices: list[int] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_statement_key(cls, value):
        """Small hosted models commonly choose a semantically equivalent field name."""
        if isinstance(value, dict) and not value.get("statement"):
            for key in ("mechanism", "finding", "claim", "summary"):
                if value.get(key):
                    return {**value, "statement": value[key]}
        return value


class AngleAssessment(BaseModel):
    angle: str
    direction: ImpactDirection = "unclear"
    magnitude: ImpactMagnitude = "unclear"
    confidence: ConfidenceLevel = "low"
    mechanism: str
    supporting_findings: list[EvidenceClaim] = Field(default_factory=list)
    limiting_findings: list[EvidenceClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class DeepResearchSynthesis(BaseModel):
    direction: ImpactDirection = "unclear"
    magnitude: ImpactMagnitude = "unclear"
    confidence: ConfidenceLevel = "low"
    executive_summary: str
    impact_mechanisms: list[EvidenceClaim] = Field(default_factory=list)
    counterevidence: list[EvidenceClaim] = Field(default_factory=list)
    watch_items: list[str] = Field(default_factory=list)
    evidence_boundary: str


@dataclass
class EvidenceRecord:
    index: int
    source_type: str
    title: str
    text: str
    citation: Citation

    def render(self) -> str:
        source_date = self.citation.filing_date.isoformat() if self.citation.filing_date else "n/a"
        return (
            f"[{self.index}] type={self.source_type}; date={source_date}; "
            f"title={self.title}; url={self.citation.url}\n{self.text}"
        )


@dataclass
class DeepResearchResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


ORDINAL_WORDS = {
    "first": 0,
    "top": 0,
    "second": 1,
    "third": 2,
    "fourth": 3,
    "fifth": 4,
}


def resolve_target_tickers(
    message: str,
    explicit_tickers: list[str],
    ranked_tickers: list[str],
    *,
    max_companies: int,
) -> list[str]:
    """Resolve ticker mentions and phrases such as “first result” or “last company”."""
    valid = [ticker.upper() for ticker in ranked_tickers]
    valid_set = set(valid)
    # The intent model occasionally copies or mutates tickers from the supplied result
    # list even when the user only said “first result.” Only trust a model-extracted
    # ticker when that token actually appears in the user's message.
    explicit = [
        ticker.upper()
        for ticker in explicit_tickers
        if ticker.upper() in valid_set
        and re.search(rf"\b{re.escape(ticker)}\b", message, flags=re.IGNORECASE)
    ]
    if explicit:
        return list(dict.fromkeys(explicit))[:max_companies]

    lowered = message.lower()
    if re.search(r"\blast\s+(?:result|company|stock)\b", lowered):
        return valid[-1:] if valid else []
    for word, index in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\s+(?:result|company|stock)\b", lowered):
            return valid[index : index + 1]
    numeric = re.search(r"\b(?:result|company|stock)\s*#\s*(\d+)\b", lowered)
    if numeric:
        index = int(numeric.group(1)) - 1
        return valid[index : index + 1] if index >= 0 else []

    # A deep-research request is intentionally bounded. When no company was named,
    # investigate the top result and disclose that resolution in the report.
    return valid[:1]


def _valid_indices(indices: list[int], evidence_count: int) -> list[int]:
    return list(dict.fromkeys(i for i in indices if 1 <= i <= evidence_count))


def _render_evidence(evidence: list[EvidenceRecord]) -> str:
    return "\n\n".join(item.render() for item in evidence)


def _card_evidence(candidate: ResearchCandidate) -> list[tuple[str, Citation]]:
    output: list[tuple[str, Citation]] = []
    seen: set[str] = set()
    for match in (candidate.semantic_matches or {}).values():
        for card in match.get("best_cards", [])[:2]:
            card_id = str(card.get("card_id") or card.get("text") or "")
            if not card_id or card_id in seen:
                continue
            seen.add(card_id)
            filing_date = None
            try:
                if card.get("filing_date"):
                    filing_date = date.fromisoformat(str(card["filing_date"])[:10])
            except ValueError:
                pass
            text = str(card.get("text") or "").strip()
            if not text:
                continue
            output.append(
                (
                    text,
                    Citation(
                        source_type="company_card",
                        url=str(card.get("source_url") or ""),
                        accession=card.get("source_accession"),
                        description=(
                            f"{candidate.ticker} verified filing card "
                            f"({card.get('card_type')}, {card.get('directness')})"
                        ),
                        excerpt=str(card.get("source_excerpt") or "")[:600] or None,
                        filing_date=filing_date,
                    ),
                )
            )
            if len(output) >= 6:
                return output
    return output


def _news_citation(source: NewsSource) -> Citation:
    return Citation(
        source_type="news",
        url=source.url,
        description=source.title,
        excerpt=source.excerpt[:600],
        filing_date=source.published_date,
    )


async def _plan_research(
    company: Company,
    question: str,
    *,
    max_queries: int,
) -> DeepResearchPlan:
    plan = await generate_structured(
        DeepResearchPlan,
        [
            {"role": "system", "content": DEEP_RESEARCH_PLAN_SYSTEM},
            {
                "role": "user",
                "content": DEEP_RESEARCH_PLAN_USER.format(
                    company_name=company.name,
                    ticker=company.ticker,
                    sector=company.sector,
                    industry=company.industry,
                    today=date.today().isoformat(),
                    question=question,
                ),
            },
        ],
    )
    plan.angles = plan.angles[: max(1, min(max_queries, 3))]
    return plan


async def _run_angle_agent(
    company: Company,
    question: str,
    angle: ResearchAngle,
    evidence_text: str,
) -> AngleAssessment:
    return await generate_structured(
        AngleAssessment,
        [
            {"role": "system", "content": ANGLE_AGENT_SYSTEM},
            {
                "role": "user",
                "content": ANGLE_AGENT_USER.format(
                    company_name=company.name,
                    ticker=company.ticker,
                    question=question,
                    angle_name=angle.name,
                    objective=angle.objective,
                    evidence=evidence_text,
                ),
            },
        ],
    )


def _fallback_synthesis(
    assessments: list[AngleAssessment],
    *,
    news_available: bool,
) -> DeepResearchSynthesis:
    def dedupe(claims: list[EvidenceClaim]) -> list[EvidenceClaim]:
        output: list[EvidenceClaim] = []
        seen: set[str] = set()
        for claim in claims:
            key = re.sub(r"\W+", " ", claim.statement.lower()).strip()
            if key and key not in seen:
                seen.add(key)
                output.append(claim)
        return output

    supporting = dedupe(
        [claim for item in assessments for claim in item.supporting_findings]
    )
    limiting = dedupe([claim for item in assessments for claim in item.limiting_findings])
    return DeepResearchSynthesis(
        direction="unclear",
        magnitude="unclear",
        confidence="low",
        executive_summary=(
            "The evidence was collected, but the synthesis model did not produce a valid "
            "overall assessment."
        ),
        impact_mechanisms=supporting[:5],
        counterevidence=limiting[:5],
        watch_items=["Look for direct management disclosure and measurable financial effects."],
        evidence_boundary=(
            "Current-news search and official filing evidence were reviewed."
            if news_available
            else "Current-news search was unavailable; this assessment is filing-only."
        ),
    )


async def _synthesize(
    company: Company,
    question: str,
    evidence: list[EvidenceRecord],
    assessments: list[AngleAssessment],
    *,
    news_available: bool,
) -> DeepResearchSynthesis:
    try:
        synthesis = await generate_structured(
            DeepResearchSynthesis,
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM},
                {
                    "role": "user",
                    "content": SYNTHESIS_USER.format(
                        company_name=company.name,
                        ticker=company.ticker,
                        question=question,
                        news_available="yes" if news_available else "no",
                        evidence=_render_evidence(evidence),
                        assessments=json.dumps(
                            [assessment.model_dump(mode="json") for assessment in assessments],
                            indent=2,
                        ),
                    ),
                },
            ],
        )
        if not news_available and "news" not in synthesis.evidence_boundary.lower():
            synthesis.evidence_boundary = (
                "Current-news search was unavailable; this assessment is filing-only. "
                + synthesis.evidence_boundary
            )
        return synthesis
    except InvalidModelOutputError:
        logger.exception("Deep-research synthesis failed for %s", company.ticker)
        return _fallback_synthesis(assessments, news_available=news_available)


def _format_claim(claim: EvidenceClaim, evidence_count: int) -> str:
    refs = _valid_indices(claim.evidence_indices, evidence_count)
    suffix = " " + " ".join(f"[{index}]" for index in refs) if refs else ""
    return f"• {claim.statement}{suffix}"


def _format_report(
    company: Company,
    question: str,
    synthesis: DeepResearchSynthesis,
    evidence: list[EvidenceRecord],
) -> tuple[str, list[Citation]]:
    evidence_count = len(evidence)
    lines = [
        f"DEEP RESEARCH — {company.name} ({company.ticker})",
        "",
        f"Question: {question}",
        "",
        "ASSESSMENT",
        f"Potential business impact: {synthesis.magnitude}",
        f"Likely direction: {synthesis.direction}",
        f"Confidence: {synthesis.confidence}",
        synthesis.executive_summary,
        "",
        "WHY IT COULD MATTER",
    ]
    lines.extend(
        _format_claim(claim, evidence_count) for claim in synthesis.impact_mechanisms
    )
    if not synthesis.impact_mechanisms:
        lines.append("• No evidence-backed transmission mechanism was established.")
    lines.extend(["", "WHY THE EFFECT COULD BE LIMITED"])
    lines.extend(_format_claim(claim, evidence_count) for claim in synthesis.counterevidence)
    if not synthesis.counterevidence:
        lines.append("• No evidence-backed limiting case was established.")
    lines.extend(["", "WHAT TO WATCH"])
    if synthesis.watch_items:
        lines.extend(f"• {item}" for item in synthesis.watch_items)
    else:
        lines.append("• No evidence-backed watch items were identified.")
    lines.extend(["", "EVIDENCE BOUNDARY", synthesis.evidence_boundary])

    used: list[int] = []
    for claim in [*synthesis.impact_mechanisms, *synthesis.counterevidence]:
        used.extend(_valid_indices(claim.evidence_indices, evidence_count))
    used = list(dict.fromkeys(used))
    citations = [evidence[index - 1].citation for index in used]
    return "\n".join(lines), citations


async def research_company_deeply(
    db: AsyncSession,
    candidate: ResearchCandidate,
    question: str,
    *,
    news_client: TavilyNewsClient | None = None,
) -> DeepResearchResult:
    settings = get_settings()
    company = (
        await db.execute(select(Company).where(Company.id == candidate.company_id))
    ).scalar_one()
    limitations: list[str] = []
    plan = await _plan_research(
        company,
        question,
        max_queries=settings.deep_research_max_news_queries,
    )

    own_news_client = news_client is None
    news_client = news_client or TavilyNewsClient()
    news_available = news_client.configured
    news_sources: list[NewsSource] = []
    if news_available:
        searches = await asyncio.gather(
            *(
                news_client.search(
                    angle.news_query,
                    lookback_days=plan.lookback_days,
                    max_results=settings.deep_research_max_news_results,
                )
                for angle in plan.angles
            ),
            return_exceptions=True,
        )
        by_url: dict[str, NewsSource] = {}
        for result in searches:
            if isinstance(result, Exception):
                limitations.append(str(result))
                continue
            for source in result:
                current = by_url.get(source.url)
                if current is None or source.score > current.score:
                    by_url[source.url] = source
        news_sources = sorted(by_url.values(), key=lambda source: source.score, reverse=True)[:12]
        if not news_sources:
            limitations.append("Current-news search returned no usable sources.")
            news_available = False
    else:
        limitations.append(
            "Current-news search is not configured; add TAVILY_API_KEY for news-backed research."
        )

    if own_news_client:
        await news_client.aclose()

    # Existing official-filing research remains a separate, citation-enforced source path.
    filing_finding = await find_catalyst(
        db,
        company,
        question,
        lookback_days=plan.lookback_days,
        max_downloads=4,
        max_chunks=12,
    )
    limitations.extend(filing_finding.limitations)

    evidence: list[EvidenceRecord] = []

    def add_evidence(source_type: str, title: str, text: str, citation: Citation) -> None:
        evidence.append(
            EvidenceRecord(
                index=len(evidence) + 1,
                source_type=source_type,
                title=title,
                text=text[:4_000],
                citation=citation,
            )
        )

    for text, citation in _card_evidence(candidate):
        add_evidence(
            "company_card",
            citation.description or "Verified filing card",
            text,
            citation,
        )
    for citation in filing_finding.citations:
        add_evidence(
            citation.source_type,
            citation.description or "Recent official filing",
            citation.excerpt or filing_finding.summary,
            citation,
        )
    for source in news_sources:
        add_evidence("news", source.title, source.excerpt, _news_citation(source))

    if not evidence:
        return DeepResearchResult(
            answer=(
                f"Deep research could not find usable company-card, official-filing, or current-news "
                f"evidence for {company.name} ({company.ticker})."
            ),
            limitations=[*limitations, "No usable evidence was retrieved."],
        )

    evidence_text = _render_evidence(evidence)
    angle_results = await asyncio.gather(
        *(
            _run_angle_agent(company, question, angle, evidence_text)
            for angle in plan.angles
        ),
        return_exceptions=True,
    )
    assessments: list[AngleAssessment] = []
    for angle, result in zip(plan.angles, angle_results, strict=True):
        if isinstance(result, Exception):
            limitations.append(f"{angle.name} agent failed: {result}")
            continue
        assessments.append(result)
        limitations.extend(result.limitations)

    if not assessments:
        return DeepResearchResult(
            answer=f"Deep-research agents could not complete an assessment for {company.ticker}.",
            citations=[],
            limitations=limitations,
        )

    synthesis = await _synthesize(
        company,
        question,
        evidence,
        assessments,
        news_available=news_available,
    )
    answer, citations = _format_report(company, question, synthesis, evidence)
    return DeepResearchResult(answer=answer, citations=citations, limitations=limitations)


async def run_deep_research(
    db: AsyncSession,
    session_id,
    question: str,
    target_tickers: list[str],
) -> DeepResearchResult:
    settings = get_settings()
    targets = (
        (
            await db.execute(
                select(ResearchCandidate)
                .where(
                    ResearchCandidate.session_id == session_id,
                    ResearchCandidate.ticker.in_(target_tickers),
                    ResearchCandidate.stage.in_(["researched", "qualified"]),
                )
                .order_by(ResearchCandidate.rank.nulls_last())
            )
        )
        .scalars()
        .all()
    )
    if not targets:
        return DeepResearchResult(
            answer="There are no researched result companies matching that reference.",
            limitations=["No deep-research target could be resolved."],
        )

    results: list[DeepResearchResult] = []
    try:
        async with asyncio.timeout(settings.deep_research_deadline_seconds):
            # One shared news client keeps connection setup bounded. Database-backed filing
            # retrieval is sequential because AsyncSession cannot be used concurrently.
            news_client = TavilyNewsClient()
            try:
                for candidate in targets[: settings.deep_research_max_companies]:
                    results.append(
                        await research_company_deeply(
                            db,
                            candidate,
                            question,
                            news_client=news_client,
                        )
                    )
            finally:
                await news_client.aclose()
    except TimeoutError:
        return DeepResearchResult(
            answer="Deep research exceeded its bounded deadline before a report was completed.",
            limitations=[
                f"Deep research timed out after {settings.deep_research_deadline_seconds}s."
            ],
        )

    return DeepResearchResult(
        answer="\n\n".join(result.answer for result in results),
        citations=[citation for result in results for citation in result.citations],
        limitations=[limitation for result in results for limitation in result.limitations],
    )
