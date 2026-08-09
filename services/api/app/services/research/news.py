"""Current-news search used only by follow-up deep research.

The language model never browses by itself. This client performs bounded Tavily
searches and returns source text plus URLs that the Llama research workers may cite.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings

logger = logging.getLogger(__name__)

NEWS_CACHE_TTL_SECONDS = 60 * 60
MAX_SOURCE_TEXT_CHARS = 4_000


class NewsSearchError(RuntimeError):
    pass


@dataclass(frozen=True)
class NewsSource:
    title: str
    url: str
    excerpt: str
    published_date: date | None = None
    score: float = 0.0
    search_excerpt: str = ""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            try:
                return parsedate_to_datetime(value.strip()).date()
            except (TypeError, ValueError):
                return None


def _valid_public_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return value


def parse_tavily_results(payload: dict) -> list[NewsSource]:
    """Normalize and defensively bound Tavily's response."""
    sources: list[NewsSource] = []
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = _valid_public_url(item.get("url"))
        if url is None:
            continue
        title = str(item.get("title") or urlparse(url).hostname or "News source").strip()
        raw = item.get("raw_content")
        concise = item.get("content")
        content = raw if isinstance(raw, str) and raw.strip() else concise
        excerpt = str(content or "").strip()[:MAX_SOURCE_TEXT_CHARS]
        if not excerpt:
            continue
        try:
            score = float(item.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        sources.append(
            NewsSource(
                title=title[:300],
                url=url,
                excerpt=excerpt,
                published_date=_parse_date(
                    item.get("published_date") or item.get("published_at")
                ),
                score=score,
                search_excerpt=str(concise or "").strip()[:1_200],
            )
        )
    return sources


class TavilyNewsClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        settings = get_settings()
        self.api_key = api_key if api_key is not None else settings.tavily_api_key
        self.base_url = (base_url or settings.tavily_base_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=httpx.Timeout(45.0, connect=10.0),
        )
        self._cache = FileCache(settings.cache_path, "deep_research_news")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        retry=retry_if_exception(_retryable),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        *,
        lookback_days: int,
        max_results: int,
    ) -> list[NewsSource]:
        if not self.configured:
            raise NewsSearchError("TAVILY_API_KEY is not configured")

        key = cache_key(
            "tavily-news-v1",
            query,
            str(lookback_days),
            str(max_results),
        )
        cached = self._cache.get(key, NEWS_CACHE_TTL_SECONDS)
        if isinstance(cached, dict):
            return parse_tavily_results(cached)

        try:
            response = await self._client.post(
                "/search",
                json={
                    "query": query,
                    "topic": "news",
                    "search_depth": "basic",
                    "max_results": max(1, min(max_results, 10)),
                    "start_date": (
                        date.fromordinal(
                            max(1, date.today().toordinal() - max(1, lookback_days))
                        ).isoformat()
                    ),
                    "end_date": date.today().isoformat(),
                    "include_answer": False,
                    "include_raw_content": "text",
                    "include_images": False,
                    "auto_parameters": False,
                },
            )
            response.raise_for_status()
        except (httpx.HTTPError, ValueError) as exc:
            raise NewsSearchError(f"Current-news search failed: {exc}") from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise NewsSearchError("Current-news search returned an invalid response")
        self._cache.put(key, payload, source="tavily-news")
        return parse_tavily_results(payload)

    async def aclose(self) -> None:
        await self._client.aclose()
