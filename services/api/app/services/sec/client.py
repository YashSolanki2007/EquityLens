"""SEC EDGAR client.

- Descriptive User-Agent from settings (SEC fair-access policy).
- Global rate limit below 8 requests/second.
- SSRF-safe: only sec.gov / www.sec.gov / data.sec.gov may be fetched.
- Response size capped; request timeouts; tenacity retries on transient failures.
- Raw JSON responses cached on disk (submissions/companyfacts: 6h TTL).
- Filing documents cached indefinitely by accession number under FILINGS_DIR.
"""

import asyncio
import hashlib
import logging
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {"sec.gov", "www.sec.gov", "data.sec.gov"}
MAX_RESPONSE_BYTES = 40 * 1024 * 1024  # generous cap; large 10-Ks are ~10-20MB

SUBMISSIONS_TTL = 6 * 3600
COMPANY_FACTS_TTL = 6 * 3600


class SecError(RuntimeError):
    pass


class ResponseTooLargeError(SecError):
    pass


class _RateLimiter:
    """Simple global spacing limiter keeping us under max_rps."""

    def __init__(self, max_rps: float):
        self._interval = 1.0 / max_rps
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


class SecClient:
    def __init__(self):
        s = get_settings()
        self._limiter = _RateLimiter(s.sec_max_rps)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": s.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        self._json_cache = FileCache(s.cache_path, "sec")
        self._filings_dir = s.filings_path

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=15),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _get(self, url: str) -> httpx.Response:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise SecError(f"Host not allowlisted: {host}")
        await self._limiter.acquire()
        async with self._client.stream("GET", url) as resp:
            resp.raise_for_status()
            declared = resp.headers.get("content-length")
            if declared and int(declared) > MAX_RESPONSE_BYTES:
                raise ResponseTooLargeError(url)
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ResponseTooLargeError(url)
                chunks.append(chunk)
            resp._content = b"".join(chunks)
            return resp

    async def _get_json_cached(self, url: str, namespace_key: str, ttl: float) -> Any:
        key = cache_key(namespace_key, url)
        cached = self._json_cache.get(key, ttl)
        if cached is not None:
            return cached
        resp = await self._get(url)
        data = resp.json()
        self._json_cache.put(key, data, source=url)
        return data

    # --- Public API ---

    async def get_submissions(self, cik: str) -> dict:
        url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
        return await self._get_json_cached(url, "submissions", SUBMISSIONS_TTL)

    async def get_company_facts(self, cik: str) -> dict:
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json"
        return await self._get_json_cached(url, "companyfacts", COMPANY_FACTS_TTL)

    @staticmethod
    def filing_doc_url(cik: str, accession: str, primary_document: str) -> str:
        acc = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{primary_document}"

    @staticmethod
    def filing_index_url(cik: str, accession: str) -> str:
        return (
            f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={int(cik)}"
            f"&type=&dateb=&owner=include&count=40"
        )

    async def download_filing_document(
        self, cik: str, accession: str, primary_document: str
    ) -> tuple[str, str]:
        """Return (html_text, sha256). Cached indefinitely on disk by accession."""
        safe_accession = accession.replace("/", "")
        path = self._filings_dir / f"{safe_accession}.html"
        if path.exists():
            content = path.read_bytes()
            return content.decode("utf-8", errors="replace"), hashlib.sha256(content).hexdigest()
        url = self.filing_doc_url(cik, accession, primary_document)
        resp = await self._get(url)
        content = resp.content
        path.write_bytes(content)
        logger.info("Downloaded filing %s (%d bytes)", accession, len(content))
        return content.decode("utf-8", errors="replace"), hashlib.sha256(content).hexdigest()

    async def aclose(self) -> None:
        await self._client.aclose()


_client: SecClient | None = None


def get_sec_client() -> SecClient:
    global _client
    if _client is None:
        _client = SecClient()
    return _client
