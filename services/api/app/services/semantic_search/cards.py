"""Offline company-card generation: two model passes (extract, verify) per spec §6.

Only cards judged `entailed` with confidence >= 0.75 are stored.
"""

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm import InvalidModelOutputError, generate_structured, get_provider
from app.models import Company, CompanyCard, SecFiling
from app.prompts.cards import (
    EXTRACT_CARDS_SYSTEM,
    EXTRACT_CARDS_USER,
    PROMPT_VERSION,
    VERIFY_CARDS_BATCH_USER,
    VERIFY_CARDS_SYSTEM,
)
from app.schemas.search import CardType
from app.services.ingestion import (
    download_filing,
    download_india_filing,
    get_latest_filing,
)
from app.services.nse.client import get_nse_client
from app.services.nse.parser import (
    extract_annual_report_business_sections,
    pdf_to_pages,
)
from app.services.sec.client import get_sec_client
from app.services.sec.parser import chunk_text, extract_10k_business_sections, html_to_text

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.75
MAX_WORDS = 80
TARGET_CARDS_MAX = 25

CARD_NOISE_RE = re.compile(
    r"\b("
    r"board of directors?|independent directors?|committee meetings?|"
    r"the board and management|board .{0,100}acknowledges|"
    r"nomination and remuneration|remuneration (?:plan|policy)|esops?|"
    r"employee training|management trainee|inclusive workplace|"
    r"employees? (?:participate|are exposed)|"
    r"decentrali[sz]ed (?:business|operating) model|decentrali[sz]ed set.up|"
    r"business model.{0,80}decentrali[sz]ed|governance framework|"
    r"job safety analysis|job hazard analysis|permit.to.work|toolbox talks?|"
    r"work.related hazards?|occupational health and safety|zero.harm|safety culture|"
    r"women participation in the workforce|stakeholder feedback|"
    r"integrated reporting journey|dedicated .{0,20}esg.{0,20}section|"
    r"(?:the|this) report (?:covers|explains|includes)|"
    r"reasonable assurance|business responsibility and sustainability reporting|"
    r"financial statements .{0,40}audited|tax and other contributions|"
    r"capital management framework|enduring value for .{0,30}stakeholders|"
    r"health insurance coverage|medical reimbursement|"
    r"ownership and accountability|holds? (?:a )?\d+(?:\.\d+)? percent stake|"
    r"carbon neutral(?:ity)?|scope [123] emissions?|"
    r"scope 1.{0,40}scope 2|work environment.{0,80}safe.{0,40}inclusive|"
    r"decarboni[sz]ation initiative|circular approach|advancing circularity|"
    r"ipcc|rcp [0-9]|ssp [0-9]|global mean temperature|"
    r"hazardous waste|battery waste|biomedical waste|waste generated|"
    r"generates? (?:hazardous |other types? of )?waste|"
    r"water consumption|energy consumption|life cycle (?:assessment|perspective)|"
    r"corporate social responsibility|biodiversity|"
    r"environmentally friendly practices|environmental preservation|"
    r"promote sustainable development|circular and sustainable industrial ecosystem|"
    r"generic esg|comparative figures"
    r")\b",
    re.IGNORECASE,
)

# Chunk budget per section label — bounds model calls per company.
SECTION_CHUNK_BUDGET = {
    "Item 1 - Business": 8,
    "Item 2 - Properties": 2,
    "Item 7 - MD&A": 4,
    "Document": 8,
    "Business Overview": 8,
    "Management Discussion & Analysis": 5,
    "Customers, Segments & Geography": 5,
    "Supply Chain & Business Risks": 4,
    "Annual Report": 8,
}

INDIA_SECTION_CHUNK_BUDGET = {
    "Business Overview": 4,
    "Management Discussion & Analysis": 4,
    "Customers, Segments & Geography": 3,
    "Supply Chain & Business Risks": 2,
    "Additional Business Evidence": 4,
    "Annual Report": 6,
}


class ExtractedCard(BaseModel):
    card_type: CardType
    text: str
    directness: Literal["core", "direct", "indirect", "prospective"]
    materiality: Literal["major", "meaningful", "minor", "unknown"]


class ExtractCardsOutput(BaseModel):
    cards: list[ExtractedCard] = Field(default_factory=list, max_length=4)

    @model_validator(mode="before")
    @classmethod
    def discard_non_card_output(cls, value):
        """Keep a verbose small model from invalidating an otherwise useful batch."""
        if isinstance(value, list):
            value = {"cards": value}
        if not isinstance(value, dict) or not isinstance(value.get("cards"), list):
            return value
        valid_types = {
            "business_activity",
            "product_service",
            "customer_exposure",
            "geographic_exposure",
            "supply_chain_role",
            "macro_exposure",
        }
        valid_directness = {"core", "direct", "indirect", "prospective"}
        valid_materiality = {"major", "meaningful", "minor", "unknown"}
        cards = [
            card
            for card in value["cards"]
            if (
                isinstance(card, dict)
                and card.get("card_type") in valid_types
                and card.get("directness") in valid_directness
                and card.get("materiality") in valid_materiality
            )
        ][:4]
        return {**value, "cards": cards}


class CardVerdict(BaseModel):
    index: int
    verdict: Literal["entailed", "partially_entailed", "not_entailed"]
    confidence: float = Field(ge=0.0, le=1.0)


class VerifyCardsOutput(BaseModel):
    verdicts: list[CardVerdict] = Field(default_factory=list)


def _acceptable(card: ExtractedCard) -> bool:
    words = len(card.text.split())
    if not 5 <= words <= MAX_WORDS:
        return False
    if CARD_NOISE_RE.search(card.text):
        return False
    lowered = card.text.lower()
    if lowered.startswith(
        (
            "the company is committed to ",
            "the company aims to promote ",
            "the company focuses on creating a thriving",
            "the company adopts enhanced controls ",
            "the company conducts risk assessments ",
            "the company has established clear and accessible processes ",
            "the report explains ",
            "the report includes ",
        )
    ):
        return False
    if (
        "to its employees" in lowered
        or "preferred choice for its stakeholders" in lowered
        or "fosters its reputation" in lowered
        or "are expected to prioritize" in lowered
        or "productive, efficient, and sustainable" in lowered
        or "qualified under applicable quality control orders" in lowered
        or "exposure to high-risk geographies is continuously monitored" in lowered
        or "enable cleaner and more sustainable manufacturing operations" in lowered
        or "performance during the period reflects a business" in lowered
        or "strong execution capabilities and well-integrated partner ecosystem" in lowered
        or "growth is expected to be powered by" in lowered
        or (
            "significant investments" in lowered
            and "seize opportunities" in lowered
        )
        or "developing new capabilities and partnerships to address emerging" in lowered
        or "well-positioned at the center of key megatrends" in lowered
        or "focuses on its values and being true to them" in lowered
    ):
        return False
    return True


async def extract_cards_from_excerpt(
    company: Company, section: str, excerpt: str, *, source: str = "SEC 10-K"
) -> list[ExtractedCard]:
    messages = [
        {"role": "system", "content": EXTRACT_CARDS_SYSTEM},
        {
            "role": "user",
            "content": EXTRACT_CARDS_USER.format(
                name=company.name,
                ticker=company.ticker,
                source=source,
                section=section,
                excerpt=excerpt,
            ),
        },
    ]
    try:
        out = await generate_structured(ExtractCardsOutput, messages)
    except InvalidModelOutputError:
        return []
    return [c for c in out.cards if _acceptable(c)]


async def verify_cards_against_excerpt(
    excerpt: str, cards: list[ExtractedCard]
) -> list[tuple[ExtractedCard, float]]:
    """Return only entailed cards with their confidence."""
    accepted = await verify_card_groups([("", excerpt, cards)])
    return [(card, confidence) for card, confidence, _, _ in accepted]


async def verify_card_groups(
    groups: list[tuple[str, str, list[ExtractedCard]]],
) -> list[tuple[ExtractedCard, float, str, str]]:
    """Verify several excerpt-specific card batches in one constrained model call.

    Every candidate keeps its exact source excerpt and section. Batching only removes
    repeated API overhead; the entailment boundary remains per excerpt.
    """
    groups = [group for group in groups if group[2]]
    if not groups:
        return []

    flat: list[tuple[ExtractedCard, int, str, str]] = []
    excerpt_blocks: list[str] = []
    for excerpt_index, (section, excerpt, cards) in enumerate(groups):
        excerpt_blocks.append(
            f"Source excerpt {excerpt_index} ({section or 'filing section'}):\n"
            f"<<<EXCERPT_{excerpt_index}\n{excerpt}\nEXCERPT_{excerpt_index}>>>"
        )
        flat.extend((card, excerpt_index, section, excerpt) for card in cards)

    cards_json = "\n".join(
        (
            f"{index}: source_excerpt={excerpt_index}; "
            f"card={json.dumps(card.model_dump(mode='json'))}"
        )
        for index, (card, excerpt_index, _, _) in enumerate(flat)
    )
    messages = [
        {"role": "system", "content": VERIFY_CARDS_SYSTEM},
        {
            "role": "user",
            "content": VERIFY_CARDS_BATCH_USER.format(
                excerpts="\n\n".join(excerpt_blocks),
                cards_json=cards_json,
            ),
        },
    ]
    try:
        out = await generate_structured(VerifyCardsOutput, messages)
    except InvalidModelOutputError:
        return []

    accepted: list[tuple[ExtractedCard, float, str, str]] = []
    seen: set[int] = set()
    for verdict in out.verdicts:
        if verdict.index in seen:
            continue
        seen.add(verdict.index)
        if verdict.verdict != "entailed" or verdict.confidence < MIN_CONFIDENCE:
            continue
        if 0 <= verdict.index < len(flat):
            card, _, section, excerpt = flat[verdict.index]
            accepted.append((card, verdict.confidence, section, excerpt))
    return accepted

async def build_cards_for_company(
    db: AsyncSession, company: Company, *, replace: bool = True
) -> int:
    """Generate, verify, embed, and store cards from the latest annual filing."""
    filing_form = "ANNUAL_REPORT" if company.country == "IN" else "10-K"
    filing = await get_latest_filing(db, company.id, filing_form)
    if filing is None:
        logger.warning("No annual filing on record for %s; ingest first", company.ticker)
        return 0
    if company.country == "IN":
        candidate_filings = (
            (
                await db.execute(
                    select(SecFiling)
                    .where(
                        SecFiling.company_id == company.id,
                        SecFiling.form == "ANNUAL_REPORT",
                    )
                    .order_by(SecFiling.filing_date.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        sections = {}
        best_effort: tuple[SecFiling, dict[str, str]] | None = None
        for candidate_filing in candidate_filings:
            try:
                content = await download_india_filing(
                    db, candidate_filing, get_nse_client()
                )
                candidate_sections = extract_annual_report_business_sections(
                    pdf_to_pages(content)
                )
            except Exception as exc:
                logger.warning(
                    "Could not parse %s annual report %s: %s",
                    company.ticker,
                    candidate_filing.accession_number,
                    exc,
                )
                continue
            if candidate_sections:
                if best_effort is None:
                    best_effort = (candidate_filing, candidate_sections)
                rendered = "\n".join(candidate_sections.values())
                alphabetic = [character for character in rendered if character.isalpha()]
                latin_ratio = (
                    sum(character.isascii() for character in alphabetic)
                    / len(alphabetic)
                    if alphabetic
                    else 0.0
                )
                if len(rendered) >= 5_000 and latin_ratio >= 0.55:
                    filing = candidate_filing
                    sections = candidate_sections
                    break
        if not sections and best_effort is not None:
            filing, sections = best_effort
        if not sections:
            logger.warning("No parseable annual report on record for %s", company.ticker)
            return 0
        source_label = "NSE annual report"
    else:
        html = await download_filing(db, company, filing, get_sec_client())
        sections = extract_10k_business_sections(html_to_text(html))
        source_label = "SEC 10-K"

    provider = get_provider()
    settings = get_settings()

    excerpt_specs: list[tuple[str, str]] = []
    budget_map = (
        INDIA_SECTION_CHUNK_BUDGET
        if company.country == "IN"
        else SECTION_CHUNK_BUDGET
    )
    for section_label, section_text in sections.items():
        budget = budget_map.get(section_label, 2)
        for excerpt in chunk_text(section_text)[:budget]:
            excerpt_specs.append((section_label, excerpt))

    stored: list[CompanyCard] = []
    total = 0
    verification_batch_size = 3
    for start in range(0, len(excerpt_specs), verification_batch_size):
        if total >= TARGET_CARDS_MAX:
            break
        groups: list[tuple[str, str, list[ExtractedCard]]] = []
        for section_label, excerpt in excerpt_specs[start : start + verification_batch_size]:
            candidates = await extract_cards_from_excerpt(
                company, section_label, excerpt, source=source_label
            )
            groups.append((section_label, excerpt, candidates))
        accepted = await verify_card_groups(groups)
        for card, confidence, section_label, excerpt in accepted:
            if total >= TARGET_CARDS_MAX:
                break
            stored.append(
                CompanyCard(
                    company_id=company.id,
                    ticker=company.ticker,
                    card_type=card.card_type,
                    text=card.text,
                    directness=card.directness,
                    materiality=card.materiality,
                    source_filing_accession=filing.accession_number,
                    source_url=filing.primary_doc_url or "",
                    source_section=section_label,
                    source_excerpt=excerpt[:2000],
                    filing_date=filing.filing_date,
                    valid_from=filing.filing_date,
                    confidence=confidence,
                    model_name=provider.model_name,
                    prompt_version=PROMPT_VERSION,
                )
            )
            total += 1

    if not stored:
        logger.warning("No cards produced for %s", company.ticker)
        return 0

    # Embed all accepted cards in one batch.
    embeddings = await provider.embed([c.text for c in stored])
    for card_row, emb in zip(stored, embeddings, strict=True):
        card_row.embedding = emb
        card_row.embed_model = provider.embed_model_name

    if replace:
        await db.execute(delete(CompanyCard).where(CompanyCard.company_id == company.id))
    db.add_all(stored)
    await db.commit()
    logger.info("Stored %d cards for %s (embed_dim=%d)", total, company.ticker, settings.embed_dim)
    return total


async def build_cards_for_ticker(db: AsyncSession, ticker: str) -> int:
    company = (
        await db.execute(select(Company).where(Company.ticker == ticker.upper()))
    ).scalar_one_or_none()
    if company is None:
        raise ValueError(f"Unknown ticker {ticker}")
    return await build_cards_for_company(db, company)
