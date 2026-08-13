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
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm import (
    InvalidModelOutputError,
    LLMProvider,
    generate_structured,
    get_company_chat_provider,
)
from app.models import Company, CompanyCard, ResearchCandidate
from app.prompts.deep_research import (
    ANGLE_AGENT_SYSTEM,
    ANGLE_AGENT_USER,
    DEEP_RESEARCH_PLAN_SYSTEM,
    DEEP_RESEARCH_PLAN_USER,
    SYNTHESIS_SYSTEM,
    SYNTHESIS_USER,
)
from app.schemas.search import Citation
from app.services.market_data.india_trading import get_price_history
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
    lookback_days: int = Field(default=90, ge=1, le=365)
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

NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}


def requested_lookback_days(question: str) -> int | None:
    """Extract an explicit recent research window without model inference."""

    if re.search(
        r"\b(?:over\s+the\s+)?(?:past|last|previous)\s+(?:few|several)\s+days?\b",
        question,
        flags=re.IGNORECASE,
    ):
        return 7
    match = re.search(
        r"\b(?:over\s+the\s+)?(?:past|last|previous)\s+"
        r"(?P<count>\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+"
        r"(?P<unit>calendar\s+days?|trading\s+days?|sessions?|days?|weeks?|months?)\b",
        question,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    raw_count = match.group("count").lower()
    count = int(raw_count) if raw_count.isdigit() else NUMBER_WORDS[raw_count]
    unit = match.group("unit").lower()
    multiplier = 30 if unit.startswith("month") else 7 if unit.startswith("week") else 1
    return max(1, min(count * multiplier, 365))


def is_price_move_research_question(question: str) -> bool:
    """Identify causal questions about a company's recent share-price movement."""

    asks_cause = bool(
        re.search(
            r"\b(why|cause[ds]?|reason(?:s)?|driver(?:s)?|behind|explain(?:ed|s|ing)?)\b",
            question,
            flags=re.IGNORECASE,
        )
    )
    mentions_move = bool(
        re.search(
            r"\b(stock|share|price|declin(?:e|ed|ing)|drop(?:ped|ping)?|fell|fall(?:en|ing)?|"
            r"down|slid(?:e|ing)|rise|rose|rally|rallied|jump(?:ed)?|gain(?:ed)?|movement?)\b",
            question,
            flags=re.IGNORECASE,
        )
    )
    return asks_cause and mentions_move


def _price_move_plan(company: Company, question: str, lookback_days: int) -> DeepResearchPlan:
    """Build the three retrieval angles deterministically for latency and exactness."""

    subject = f"{company.name} {company.ticker}"
    return DeepResearchPlan(
        event_or_factor=question,
        lookback_days=lookback_days,
        angles=[
            ResearchAngle(
                name="Company-specific catalysts",
                objective="Find dated company news that coincides with the observed move.",
                news_query=f"{subject} share price company news last {lookback_days} days",
            ),
            ResearchAngle(
                name="Official disclosures",
                objective="Find exchange announcements or company disclosures in the window.",
                news_query=(
                    f"{subject} NSE BSE exchange filing announcement last {lookback_days} days"
                ),
            ),
            ResearchAngle(
                name="Market and sector alternatives",
                objective="Test whether sector or broad-market moves offer a competing explanation.",
                news_query=(
                    f"{subject} pharmaceutical sector market share price move last "
                    f"{lookback_days} days"
                ),
            ),
        ],
    )


def _history_range_for_lookback(lookback_days: int) -> str:
    if lookback_days <= 31:
        return "1M"
    if lookback_days <= 93:
        return "3M"
    if lookback_days <= 186:
        return "6M"
    return "1Y"


def _summarize_price_window(history: dict, lookback_days: int) -> tuple[str, Citation] | None:
    parsed: list[tuple[date, dict]] = []
    for candle in history.get("candles") or []:
        try:
            parsed.append((date.fromisoformat(str(candle["time"])[:10]), candle))
        except (KeyError, TypeError, ValueError):
            continue
    parsed.sort(key=lambda item: item[0])
    if not parsed:
        return None

    window_end = date.today()
    window_start = window_end - timedelta(days=lookback_days)
    selected = [(day, candle) for day, candle in parsed if window_start <= day <= window_end]
    if not selected:
        return None

    first_day, _first = selected[0]
    last_day, last = selected[-1]
    baseline = next(
        (
            (day, candle)
            for day, candle in reversed(parsed)
            if day <= window_start
        ),
        selected[0],
    )
    baseline_day, baseline_candle = baseline
    first_close = float(baseline_candle["close"])
    last_close = float(last["close"])
    change_percent = (
        round((last_close / first_close - 1) * 100, 4) if first_close else None
    )
    direction = (
        "rise"
        if change_percent is not None and change_percent > 0.05
        else "decline"
        if change_percent is not None and change_percent < -0.05
        else "flat"
    )

    index_by_day = {day: index for index, (day, _candle) in enumerate(parsed)}
    daily_moves: list[dict] = []
    for day, candle in selected:
        index = index_by_day[day]
        if index == 0:
            continue
        prior_close = float(parsed[index - 1][1]["close"])
        close = float(candle["close"])
        daily_moves.append(
            {
                "date": day.isoformat(),
                "close": round(close, 4),
                "daily_change_percent": (
                    round((close / prior_close - 1) * 100, 4) if prior_close else None
                ),
                "volume": candle.get("volume"),
            }
        )
    largest_moves = sorted(
        daily_moves,
        key=lambda item: abs(item["daily_change_percent"] or 0),
        reverse=True,
    )[:3]
    payload = {
        "requested_calendar_window": {
            "start": window_start.isoformat(),
            "end": window_end.isoformat(),
            "lookback_days": lookback_days,
        },
        "available_trading_window": {
            "reference_close_date": baseline_day.isoformat(),
            "first_session": first_day.isoformat(),
            "last_session": last_day.isoformat(),
            "trading_sessions": len(selected),
        },
        "currency": history.get("currency"),
        "start_close": round(first_close, 4),
        "end_close": round(last_close, 4),
        "observed_change_percent": change_percent,
        "observed_direction": direction,
        "largest_daily_moves": largest_moves,
        "data_status": (
            "delayed_or_unverified"
            if history.get("is_delayed_or_unverified")
            else "verified"
        ),
        "retrieved_at": history.get("retrieved_at"),
    }
    citation = Citation(
        source_type="market_data",
        url=str(history.get("source_url") or ""),
        description=(
            f"Historical closes used to measure the {lookback_days}-day share-price move"
        ),
        excerpt=json.dumps(payload, default=str)[:600],
        filing_date=last_day,
    )
    return json.dumps(payload, default=str, ensure_ascii=False), citation


async def _price_move_evidence(
    company: Company,
    lookback_days: int,
) -> tuple[str, Citation] | None:
    market_ticker = company.market_data_ticker or (
        f"{company.ticker}.NS" if company.country == "IN" else company.ticker
    )
    history = await get_price_history(
        company.ticker,
        market_ticker,
        _history_range_for_lookback(lookback_days),
    )
    return _summarize_price_window(history, lookback_days)


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
    provider: LLMProvider,
    exact_lookback_days: int | None = None,
    conversation_context: str = "No earlier turns.",
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
                    conversation_context=conversation_context,
                    exact_window=(
                        f"{exact_lookback_days} days; preserve this exact window"
                        if exact_lookback_days is not None
                        else "not explicitly specified"
                    ),
                ),
            },
        ],
        provider=provider,
    )
    if exact_lookback_days is not None:
        plan.lookback_days = exact_lookback_days
    plan.angles = plan.angles[: max(1, min(max_queries, 3))]
    return plan


async def _run_angle_agent(
    company: Company,
    question: str,
    angle: ResearchAngle,
    evidence_text: str,
    provider: LLMProvider,
    conversation_context: str = "No earlier turns.",
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
                    conversation_context=conversation_context,
                    angle_name=angle.name,
                    objective=angle.objective,
                    evidence=evidence_text,
                ),
            },
        ],
        provider=provider,
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


def _price_move_fallback_synthesis(
    company: Company,
    evidence: list[EvidenceRecord],
    *,
    news_available: bool,
) -> DeepResearchSynthesis:
    """Return a conservative useful attribution when hosted reasoning is unavailable."""

    news = [item for item in evidence if item.source_type == "news"]
    market_terms = re.compile(
        r"\b(nifty|sensex|market|sector|healthcare|pharma|equities|index|indices)\b",
        flags=re.IGNORECASE,
    )
    generic_terms = re.compile(
        r"\b(share price today|stock price live|best .* stocks|stocks to buy)\b",
        flags=re.IGNORECASE,
    )
    catalyst_terms = re.compile(
        r"\b(results?|earnings|guidance|fda|usfda|warning letter|recall|approval|"
        r"acquisition|merger|order|launch|regulatory|plant|facility|promoter|stake|"
        r"dividend|downgrade|upgrade)\b",
        flags=re.IGNORECASE,
    )
    market_sources = [
        item
        for item in news
        if market_terms.search(f"{item.title} {item.text}")
        and not generic_terms.search(item.title)
    ]
    direct_sources = [
        item
        for item in news
        if (
            company.ticker.lower() in item.title.lower()
            or company.name.split()[0].lower() in item.title.lower()
        )
        if catalyst_terms.search(f"{item.title} {item.text}")
        and not generic_terms.search(item.title)
    ]

    supporting: list[EvidenceClaim] = []
    if direct_sources:
        item = direct_sources[0]
        supporting.append(
            EvidenceClaim(
                statement=(
                    f'A company-specific development was retrieved in "{item.title}". '
                    "Its timing makes it relevant, but the available excerpt does not prove "
                    "that it caused the price move."
                ),
                evidence_indices=[item.index],
            )
        )
    if market_sources:
        item = market_sources[0]
        supporting.append(
            EvidenceClaim(
                statement=(
                    f'A contemporaneous market report, "{item.title}", points to broader '
                    "market or healthcare/pharma weakness. That is a plausible contributor, "
                    "not proof of a company-specific cause."
                ),
                evidence_indices=[item.index],
            )
        )

    if direct_sources:
        summary = (
            "The decline is confirmed by the price series. Relevant company-specific news "
            "was found, but the retrieved evidence does not establish a single definitive cause."
        )
    elif market_sources:
        summary = (
            "The decline is confirmed by the price series. No direct company-specific catalyst "
            "was established in the retrieved window; broader market or sector weakness is the "
            "best-supported plausible contributor."
        )
    else:
        summary = (
            "The decline is confirmed by the price series, but the retrieved sources do not "
            "establish a company-specific or market-wide cause. Attribution remains unresolved."
        )

    return DeepResearchSynthesis(
        direction="unclear",
        magnitude="unclear",
        confidence="low",
        executive_summary=summary,
        impact_mechanisms=supporting,
        counterevidence=[
            EvidenceClaim(
                statement=(
                    "No retrieved source directly attributed the observed move to a specific "
                    "company event; publication timing alone is insufficient to prove causation."
                ),
                evidence_indices=[],
            )
        ],
        watch_items=[
            "Company exchange announcements, management commentary, and subsequent sector-relative performance."
        ],
        evidence_boundary=(
            f"Reviewed the measured price move and {len(news)} current-news source(s). "
            + (
                "Current-news retrieval was available."
                if news_available
                else "Current-news retrieval was unavailable."
            )
        ),
    )


async def _synthesize(
    company: Company,
    question: str,
    evidence: list[EvidenceRecord],
    assessments: list[AngleAssessment],
    *,
    news_available: bool,
    provider: LLMProvider,
    conversation_context: str = "No earlier turns.",
    runtime_limitations: list[str] | None = None,
) -> DeepResearchSynthesis:
    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM},
        {
            "role": "user",
            "content": SYNTHESIS_USER.format(
                company_name=company.name,
                ticker=company.ticker,
                question=question,
                conversation_context=conversation_context,
                news_available="yes" if news_available else "no",
                evidence=_render_evidence(evidence),
                assessments=json.dumps(
                    [assessment.model_dump(mode="json") for assessment in assessments],
                    indent=2,
                ),
            ),
        },
    ]
    try:
        if is_price_move_research_question(question):
            async with asyncio.timeout(25):
                synthesis = await generate_structured(
                    DeepResearchSynthesis,
                    messages,
                    provider=provider,
                )
        else:
            synthesis = await generate_structured(
                DeepResearchSynthesis,
                messages,
                provider=provider,
            )
        if not news_available and "news" not in synthesis.evidence_boundary.lower():
            synthesis.evidence_boundary = (
                "Current-news search was unavailable; this assessment is filing-only. "
                + synthesis.evidence_boundary
            )
        return synthesis
    except TimeoutError:
        logger.warning(
            "Thinking synthesis timed out for %s; retrying without extended reasoning",
            company.ticker,
        )
        if runtime_limitations is not None:
            runtime_limitations.append(
                "Nemotron extended reasoning exceeded the 25-second chat budget; "
                "the response used conservative deterministic attribution over the retrieved evidence."
            )
        return _price_move_fallback_synthesis(
            company,
            evidence,
            news_available=news_available,
        )
    except InvalidModelOutputError:
        logger.exception("Deep-research synthesis failed for %s", company.ticker)
        if is_price_move_research_question(question):
            if runtime_limitations is not None:
                runtime_limitations.append(
                    "Nemotron did not return a valid structured attribution; "
                    "the response used conservative deterministic attribution."
                )
            return _price_move_fallback_synthesis(
                company,
                evidence,
                news_available=news_available,
            )
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
    price_move_question = is_price_move_research_question(question)
    price_record = next(
        (
            item
            for item in evidence
            if item.source_type == "market_data"
            and item.title.startswith("Observed share-price move")
        ),
        None,
    )
    lines = [
        f"DEEP RESEARCH — {company.name} ({company.ticker})",
        "",
        f"Question: {question}",
        "",
        "ASSESSMENT",
    ]
    if price_move_question:
        if price_record is not None:
            try:
                price_payload = json.loads(price_record.text)
                trading_window = price_payload["available_trading_window"]
                lines.append(
                    "Observed move: "
                    f"{price_payload['observed_change_percent']:+.2f}% from "
                    f"the {trading_window['reference_close_date']} reference close to "
                    f"{trading_window['last_session']} "
                    f"({trading_window['trading_sessions']} trading sessions) "
                    f"[{price_record.index}]"
                )
            except (KeyError, TypeError, ValueError):
                pass
        lines.extend(
            [
                f"Attribution confidence: {synthesis.confidence}",
                synthesis.executive_summary,
                "",
                "EVIDENCE-BACKED DRIVERS",
            ]
        )
    else:
        lines.extend(
            [
                f"Potential business impact: {synthesis.magnitude}",
                f"Likely direction: {synthesis.direction}",
                f"Confidence: {synthesis.confidence}",
                synthesis.executive_summary,
                "",
                "WHY IT COULD MATTER",
            ]
        )
    lines.extend(
        _format_claim(claim, evidence_count) for claim in synthesis.impact_mechanisms
    )
    if not synthesis.impact_mechanisms:
        lines.append("• No evidence-backed transmission mechanism was established.")
    lines.extend(
        [
            "",
            (
                "ALTERNATIVE EXPLANATIONS AND ATTRIBUTION LIMITS"
                if price_move_question
                else "WHY THE EFFECT COULD BE LIMITED"
            ),
        ]
    )
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
    if price_move_question and price_record is not None:
        used.insert(0, price_record.index)
    used = list(dict.fromkeys(used))
    citations = [evidence[index - 1].citation for index in used]
    return "\n".join(lines), citations


async def research_company_deeply(
    db: AsyncSession,
    candidate: ResearchCandidate,
    question: str,
    *,
    news_client: TavilyNewsClient | None = None,
    conversation_context: str = "No earlier turns.",
) -> DeepResearchResult:
    settings = get_settings()
    provider = get_company_chat_provider(reasoning=True)
    company = (
        await db.execute(select(Company).where(Company.id == candidate.company_id))
    ).scalar_one()
    limitations: list[str] = []
    exact_lookback_days = requested_lookback_days(question)
    price_move_question = is_price_move_research_question(question)
    if price_move_question:
        plan = _price_move_plan(company, question, exact_lookback_days or 7)
    else:
        plan = await _plan_research(
            company,
            question,
            max_queries=settings.deep_research_max_news_queries,
            provider=provider,
            exact_lookback_days=exact_lookback_days,
            conversation_context=conversation_context,
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

    # Price-move research includes an official-disclosure web query and avoids a
    # separate 550B filing-classification call. Other catalyst research retains the
    # dedicated filing-corpus analysis.
    if price_move_question:
        filing_citations: list[Citation] = []
    else:
        filing_finding = await find_catalyst(
            db,
            company,
            question,
            lookback_days=plan.lookback_days,
            max_downloads=4,
            max_chunks=12,
            provider=provider,
        )
        limitations.extend(filing_finding.limitations)
        filing_citations = filing_finding.citations

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

    if price_move_question:
        try:
            price_evidence = await _price_move_evidence(company, plan.lookback_days)
            if price_evidence is None:
                limitations.append(
                    "No price observations were available inside the requested research window."
                )
            else:
                text, citation = price_evidence
                add_evidence(
                    "market_data",
                    f"Observed share-price move over the requested {plan.lookback_days}-day window",
                    text,
                    citation,
                )
        except Exception as exc:
            limitations.append(f"Observed price-move data was unavailable: {exc}")

    card_evidence = _card_evidence(candidate)
    if price_move_question:
        cutoff = date.today() - timedelta(days=plan.lookback_days)
        card_evidence = [
            (text, citation)
            for text, citation in card_evidence
            if citation.filing_date is not None and citation.filing_date >= cutoff
        ]
    for text, citation in card_evidence:
        add_evidence(
            "company_card",
            citation.description or "Verified filing card",
            text,
            citation,
        )
    for citation in filing_citations:
        add_evidence(
            citation.source_type,
            citation.description or "Recent official filing",
            citation.excerpt or "Official filing evidence",
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

    assessments: list[AngleAssessment] = []
    if not price_move_question:
        evidence_text = _render_evidence(evidence)
        angle_results = await asyncio.gather(
            *(
                _run_angle_agent(
                    company,
                    question,
                    angle,
                    evidence_text,
                    provider,
                    conversation_context,
                )
                for angle in plan.angles
            ),
            return_exceptions=True,
        )
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
        provider=provider,
        conversation_context=conversation_context,
        runtime_limitations=limitations,
    )
    answer, citations = _format_report(company, question, synthesis, evidence)
    return DeepResearchResult(answer=answer, citations=citations, limitations=limitations)


async def research_company_page_deeply(
    db: AsyncSession,
    company: Company,
    question: str,
    *,
    conversation_context: str = "No earlier turns.",
) -> DeepResearchResult:
    """Run the full research workflow directly from a company page.

    Search-session deep research already carries semantic-card snippets on its
    ResearchCandidate. Company pages instead hydrate the latest verified cards here
    and adapt them to the same citation-enforced pipeline.
    """

    cards = list(
        (
            await db.execute(
                select(CompanyCard)
                .where(CompanyCard.company_id == company.id)
                .order_by(desc(CompanyCard.confidence), desc(CompanyCard.filing_date))
                .limit(12)
            )
        )
        .scalars()
        .all()
    )
    best_cards = [
        {
            "card_id": str(card.id),
            "text": card.text,
            "filing_date": card.filing_date,
            "source_url": card.source_url,
            "source_accession": card.source_filing_accession,
            "source_excerpt": card.source_excerpt,
            "card_type": card.card_type,
            "directness": card.directness,
        }
        for card in cards
    ]
    candidate = SimpleNamespace(
        company_id=company.id,
        ticker=company.ticker,
        semantic_matches={"company_page": {"best_cards": best_cards}},
    )
    return await research_company_deeply(
        db,
        candidate,
        question,
        conversation_context=conversation_context,
    )


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
