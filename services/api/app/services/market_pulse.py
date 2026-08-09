"""A cached, source-grounded pulse of news that may affect Indian markets."""

import asyncio
import hashlib
import logging
import re
from datetime import UTC, date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel, Field

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.llm import generate_structured, get_provider
from app.prompts.market_pulse import MARKET_PULSE_SYSTEM, MARKET_PULSE_USER
from app.schemas.market import MarketPulseArticle, MarketPulseOut
from app.services.research.news import NewsSource, TavilyNewsClient

logger = logging.getLogger(__name__)

PROMPT_VERSION = "market-pulse-v9"
MAX_MODEL_SOURCE_CHARS = 2_600
MAX_CANDIDATES = 10
MAX_ARTICLES_PER_DOMAIN = 1

MARKET_PROFILES = {
    "IN": {
        "name": "Indian",
        "queries": (
            "latest India economy RBI inflation rupee fiscal policy Nifty Sensex market news",
            "latest geopolitics oil energy trade tariffs developments affecting Indian markets",
            "latest India technology semiconductor regulation SEBI policy affecting NSE stocks",
        ),
        "title_signals": (
            "india",
            "indian",
            "nifty",
            "reserve bank",
            "rbi",
            "rupee",
            "sebi",
            "sensex",
        ),
        "channels": "RBI policy, bond yields, the rupee, imported oil costs, trade, and NSE sector exposure",
    },
}

INDIA_GLOBAL_TITLE_SIGNALS = (
    "conflict",
    "energy",
    "export",
    "geopolit",
    "oil",
    "sanction",
    "supply chain",
    "tariff",
    "trade",
    "war",
)
STOCK_PICKING_TITLE_PATTERNS = (
    "stocks worth watching",
    "stocks to buy",
    "stock to buy",
    "best stocks",
    "top stocks",
    "buy now",
    "price target",
    "earnings",
    "reports profit",
    "reports loss",
    "profit on",
    "profit jump",
    "profits jump",
    "record profit",
    "shares higher",
    "shares lower",
    "stock rises",
    "stock falls",
    "market expectations",
)
EXCLUDED_PUBLISHER_DOMAINS = {
    "cryptobriefing.com",
    "fool.com",
    "investorplace.com",
    "linkedin.com",
    "seekingalpha.com",
    "simplywall.st",
    "whalesbook.com",
}

Category = Literal[
    "monetary_policy",
    "economy",
    "geopolitics",
    "energy_trade",
    "technology_regulation",
    "other",
]
ImpactDirection = Literal["positive", "negative", "mixed", "unclear"]


class ModelArticle(BaseModel):
    source_index: int
    category: Category = "other"
    summary_lines: list[str] = Field(default_factory=list)
    market_relevance: str
    impact_direction: ImpactDirection = "unclear"
    affected_areas: list[str] = Field(default_factory=list)


class ModelMarketPulse(BaseModel):
    overview: str
    key_themes: list[str] = Field(default_factory=list)
    articles: list[ModelArticle] = Field(default_factory=list)


def _domain(url: str) -> str:
    return (urlparse(url).hostname or "News source").removeprefix("www.").lower()


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
        and key.lower() not in {"gclid", "fbclid", "ref", "source"}
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(query),
            "",
        )
    )


def _normalized_title(title: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", title.lower()).strip()


def _is_duplicate_title(title: str, accepted: list[NewsSource]) -> bool:
    normalized = _normalized_title(title)
    return any(
        SequenceMatcher(None, normalized, _normalized_title(item.title)).ratio() >= 0.88
        for item in accepted
    )


def _has_market_title_signal(title: str) -> bool:
    lowered = title.lower()
    if any(pattern in lowered for pattern in STOCK_PICKING_TITLE_PATTERNS):
        return False
    if any(signal in lowered for signal in MARKET_PROFILES["IN"]["title_signals"]):
        return True
    return any(signal in lowered for signal in INDIA_GLOBAL_TITLE_SIGNALS)


def _url_date_conflicts(source: NewsSource) -> bool:
    """Reject obvious stale-result metadata, such as a February URL dated July."""
    if source.published_date is None:
        return True
    path = urlparse(source.url).path
    match = re.search(r"/(20\d{2})[/-](\d{1,2})[/-](\d{1,2})(?:/|$)", path)
    if match is None:
        return False
    try:
        url_date = date(*(int(part) for part in match.groups()))
    except ValueError:
        return False
    return abs((url_date - source.published_date).days) > 3


def select_recent_sources(
    result_groups: list[list[NewsSource]],
    *,
    today: date,
    lookback_days: int,
    limit: int,
) -> list[NewsSource]:
    """Strictly filter, interleave, and deduplicate results from multiple topics."""
    oldest_allowed = today - timedelta(days=max(1, lookback_days))
    eligible_groups = [
        sorted(
            [
                item
                for item in group
                if item.published_date is not None
                and oldest_allowed <= item.published_date <= today
                and _has_market_title_signal(item.title)
                and not _url_date_conflicts(item)
                and _domain(item.url) not in EXCLUDED_PUBLISHER_DOMAINS
            ],
            key=lambda item: (item.published_date or date.min, item.score),
            reverse=True,
        )
        for group in result_groups
    ]
    accepted: list[NewsSource] = []
    seen_urls: set[str] = set()
    domain_counts: dict[str, int] = {}
    cursor = 0

    while len(accepted) < limit and any(cursor < len(group) for group in eligible_groups):
        for group in eligible_groups:
            if cursor >= len(group):
                continue
            item = group[cursor]
            canonical = _canonical_url(item.url)
            domain = _domain(item.url)
            if (
                canonical in seen_urls
                or domain_counts.get(domain, 0) >= MAX_ARTICLES_PER_DOMAIN
                or _is_duplicate_title(item.title, accepted)
            ):
                continue
            accepted.append(item)
            seen_urls.add(canonical)
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
            if len(accepted) >= limit:
                break
        cursor += 1
    return accepted


def _source_text(sources: list[NewsSource]) -> str:
    rows = []
    for index, source in enumerate(sources, start=1):
        rows.append(
            f"[{index}]\n"
            f"title: {source.title}\n"
            f"published_date: {source.published_date}\n"
            f"publisher: {_domain(source.url)}\n"
            f"article_text: {source.excerpt[:MAX_MODEL_SOURCE_CHARS]}"
        )
    return "\n\n".join(rows)


def _clean_text(value: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{clipped}…"


def _summary_line(value: str) -> str:
    text = _clean_text(value, max_chars=500)
    words = text.split()
    if len(words) <= 24:
        return text
    return f"{' '.join(words[:24]).rstrip(' ,;:-.')}…"


def _fallback_lines(excerpt: str) -> list[str]:
    text = _clean_text(excerpt, max_chars=800)
    sentences = [
        _summary_line(sentence)
        for sentence in re.split(r"(?<=[.!?])\s+", text)
        if sentence.strip()
    ]
    return sentences[:3] or ["The retrieved article did not include enough text to summarize."]


def _fallback_context(source: NewsSource) -> tuple[Category, str, list[str]]:
    title = source.title.lower()
    if any(
        term in title
        for term in ("rbi", "reserve bank", "inflation", "interest rate", "rupee")
    ):
        return (
            "monetary_policy",
            "The development could affect Indian rate expectations, the rupee, bond yields, and financing conditions.",
            ["RBI policy", "Rupee", "Bond yields"],
        )
    if any(term in title for term in ("oil", "energy", "tariff", "trade", "export")):
        return (
            "energy_trade",
            "The development could affect Indian import costs, trade-sensitive industries, the rupee, or energy prices.",
            ["Import costs", "Energy", "Trade-sensitive industries"],
        )
    if any(term in title for term in ("war", "conflict", "geopolit", "sanction")):
        return (
            "geopolitics",
            "The development could affect Indian risk sentiment, supply chains, energy costs, or foreign capital flows.",
            ["Risk sentiment", "Supply chains", "Foreign flows"],
        )
    if any(
        term in title
        for term in ("ai", "chip", "semiconductor", "cyber", "sebi", "regulation")
    ):
        return (
            "technology_regulation",
            "The development could affect Indian technology valuations, regulation, or semiconductor supply chains.",
            ["Technology", "Regulation", "Semiconductors"],
        )
    if any(
        term in title
        for term in ("econom", "jobs", "employment", "nifty", "sensex", "market")
    ):
        return (
            "economy",
            "The development could influence expectations for Indian growth and broader NSE market conditions.",
            ["Indian economy", "NSE equities"],
        )
    return (
        "other",
        "This recent development may affect the Indian market backdrop; open the source for its full context.",
        [],
    )


def _article_from_source(
    source: NewsSource,
    *,
    model_article: ModelArticle | None,
) -> MarketPulseArticle:
    lines = []
    if model_article is not None:
        lines = [
            _summary_line(line)
            for line in model_article.summary_lines
            if line.strip()
        ][:3]
    for fallback in _fallback_lines(source.search_excerpt or source.excerpt):
        if len(lines) >= 3:
            break
        if fallback not in lines:
            lines.append(fallback)

    fallback_category, fallback_relevance, fallback_areas = _fallback_context(source)
    relevance = fallback_relevance
    if model_article is not None:
        candidate_relevance = _clean_text(model_article.market_relevance, max_chars=280)
        if not re.search(
            r"\b(?:buy|sell|price target|share price|stock price)\b",
            candidate_relevance,
            flags=re.IGNORECASE,
        ):
            relevance = candidate_relevance
    return MarketPulseArticle(
        id=hashlib.sha256(_canonical_url(source.url).encode()).hexdigest()[:16],
        title=source.title,
        url=source.url,
        domain=_domain(source.url),
        published_date=source.published_date or date.today(),
        category=model_article.category if model_article is not None else fallback_category,
        summary_lines=lines,
        market_relevance=relevance,
        impact_direction=(
            model_article.impact_direction if model_article is not None else "unclear"
        ),
        affected_areas=(
            list(
                dict.fromkeys(
                    _clean_text(area, max_chars=40)
                    for area in model_article.affected_areas
                    if area.strip()
                )
            )[:3]
            if model_article is not None
            else fallback_areas
        ),
    )


def assemble_market_pulse(
    sources: list[NewsSource],
    model_output: ModelMarketPulse | None,
    *,
    today: date,
    lookback_days: int,
    model_name: str,
    limitations: list[str] | None = None,
) -> MarketPulseOut:
    """Join model analysis back to authoritative source metadata by index."""
    by_index: dict[int, ModelArticle] = {}
    if model_output is not None:
        for item in model_output.articles:
            if 1 <= item.source_index <= len(sources) and item.source_index not in by_index:
                by_index[item.source_index] = item

    articles = [
        _article_from_source(source, model_article=by_index.get(index))
        for index, source in enumerate(sources, start=1)
    ]
    overview = (
        _clean_text(model_output.overview, max_chars=500)
        if model_output is not None
        else "Recent reporting from the selected window is summarized below. Open each linked source for complete context."
    )
    themes = (
        list(
            dict.fromkeys(
                _clean_text(theme, max_chars=50)
                for theme in model_output.key_themes
                if theme.strip()
            )
        )[:5]
        if model_output is not None
        else []
    )
    return MarketPulseOut(
        market="IN",
        as_of=datetime.now(UTC),
        lookback_days=lookback_days,
        oldest_allowed_date=today - timedelta(days=lookback_days),
        overview=overview,
        key_themes=themes,
        articles=articles,
        limitations=limitations or [],
        model_name=model_name,
    )


async def get_market_pulse() -> MarketPulseOut:
    settings = get_settings()
    provider = get_provider()
    today = date.today()
    lookback_days = max(1, min(settings.market_pulse_lookback_days, 7))
    max_articles = max(3, min(settings.market_pulse_max_articles, 10))
    key = cache_key(
        PROMPT_VERSION,
        "IN",
        today.isoformat(),
        str(lookback_days),
        str(max_articles),
        provider.model_name,
    )
    cache = FileCache(settings.cache_path, "market_pulse")
    cached = cache.get(key, settings.market_pulse_cache_ttl_seconds)
    if isinstance(cached, dict):
        result = MarketPulseOut.model_validate(cached)
        result.cached = True
        return result

    news = TavilyNewsClient()
    profile = MARKET_PROFILES["IN"]
    limitations: list[str] = []
    try:
        search_results = await asyncio.gather(
            *[
                news.search(query, lookback_days=lookback_days, max_results=8)
                for query in profile["queries"]
            ],
            return_exceptions=True,
        )
    finally:
        await news.aclose()

    groups: list[list[NewsSource]] = []
    for result in search_results:
        if isinstance(result, BaseException):
            logger.warning("Market-pulse news query failed: %s", result)
            limitations.append("One current-news topic search was unavailable.")
        else:
            groups.append(result)
    sources = select_recent_sources(
        groups,
        today=today,
        lookback_days=lookback_days,
        limit=min(max_articles, MAX_CANDIDATES),
    )
    if not sources:
        result = assemble_market_pulse(
            [],
            None,
            today=today,
            lookback_days=lookback_days,
            model_name=provider.model_name,
            limitations=[
                *limitations,
                "No dated articles passed the strict seven-day freshness filter.",
            ],
        )
        return result

    model_output: ModelMarketPulse | None = None
    try:
        model_output = await generate_structured(
            ModelMarketPulse,
            [
                {
                    "role": "system",
                    "content": MARKET_PULSE_SYSTEM.format(
                        market_name=profile["name"],
                        market_channels=profile["channels"],
                    ),
                },
                {
                    "role": "user",
                    "content": MARKET_PULSE_USER.format(
                        today=today.isoformat(),
                        lookback_days=lookback_days,
                        market_name=profile["name"],
                        sources=_source_text(sources),
                    ),
                },
            ],
            provider=provider,
        )
    except Exception as exc:
        logger.warning("Market-pulse summarization failed: %s", exc)
        limitations.append(
            "The AI summary was unavailable, so the page shows bounded source excerpts."
        )

    result = assemble_market_pulse(
        sources,
        model_output,
        today=today,
        lookback_days=lookback_days,
        model_name=provider.model_name,
        limitations=limitations,
    )
    if model_output is not None:
        cache.put(
            key,
            result.model_dump(mode="json"),
            source="tavily_news_and_llama_summary",
            model_name=provider.model_name,
            prompt_version=PROMPT_VERSION,
        )
    return result
