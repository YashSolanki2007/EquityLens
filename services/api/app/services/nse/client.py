"""Bounded NSE India client for public corporate filing documents.

The public website requires a browser-like session cookie before its JSON endpoints
respond reliably. Raw annual-report metadata is cached for six hours. Annual-report
documents are fetched into memory only and are never retained on local disk.
"""

import asyncio
import hashlib
import logging
import time
from datetime import date
from typing import Literal
from urllib.parse import urlparse

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_HOSTS = {
    "www.nseindia.com",
    "nseindia.com",
    "nsearchives.nseindia.com",
    "archives.nseindia.com",
    # Official issuer fallbacks used when a newly listed constituent has no
    # annual-report history in NSE's equities endpoint yet.
    "www.tatacapital.com",
    "resources.groww.in",
    "static.lenskart.com",
    "www.lg.com",
    "www.mcxindia.com",
}
METADATA_TTL_SECONDS = 6 * 3600
DEALS_TTL_SECONDS = 15 * 60
MAX_DOCUMENT_BYTES = 80 * 1024 * 1024


class NseError(RuntimeError):
    pass


class _RateLimiter:
    def __init__(self, max_rps: float):
        self._interval = 1.0 / max_rps
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._last + self._interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (401, 403, 429, 500, 502, 503, 504)
    return False


class NseClient:
    def __init__(self):
        settings = get_settings()
        self._limiter = _RateLimiter(settings.nse_max_rps)
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; rv:109.0) Gecko/20100101 Firefox/118.0"
                ),
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Referer": "https://www.nseindia.com/companies-listing/"
                "corporate-filings-annual-reports",
            },
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=True,
        )
        self._session_lock = asyncio.Lock()
        self._session_ready = False
        self._cache = FileCache(settings.cache_path, "nse")

    async def _ensure_session(self, *, force: bool = False) -> None:
        if self._session_ready and not force:
            return
        async with self._session_lock:
            if self._session_ready and not force:
                return
            await self._limiter.acquire()
            response = await self._client.get("https://www.nseindia.com/option-chain")
            response.raise_for_status()
            self._session_ready = True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=12),
        retry=retry_if_exception(_is_retryable),
        reraise=True,
    )
    async def _get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        host = urlparse(url).hostname or ""
        if host not in ALLOWED_HOSTS:
            raise NseError(f"Host not allowlisted: {host}")
        if host.endswith("nseindia.com") and host in {"www.nseindia.com", "nseindia.com"}:
            await self._ensure_session()
        await self._limiter.acquire()
        response = await self._client.get(url, params=params)
        if response.status_code in (401, 403):
            self._session_ready = False
            await self._ensure_session(force=True)
            await self._limiter.acquire()
            response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response

    async def get_annual_reports(self, symbol: str) -> list[dict]:
        key = cache_key("annual_reports", symbol.upper())
        cached = self._cache.get(key, METADATA_TTL_SECONDS)
        if cached is not None:
            return list(cached)
        response = await self._get(
            "https://www.nseindia.com/api/annual-reports",
            params={"index": "equities", "symbol": symbol.upper()},
        )
        rows = list((response.json() or {}).get("data") or [])
        self._cache.put(key, rows, source=str(response.url))
        return rows

    async def get_historical_deals(
        self,
        option_type: Literal["block_deals", "bulk_deals", "short_selling"],
        from_date: date,
        to_date: date,
    ) -> list[dict]:
        """Return exchange-disclosed large deals for a bounded date range."""

        key = cache_key(
            "historical_deals",
            option_type,
            from_date.isoformat(),
            to_date.isoformat(),
        )
        cached = self._cache.get(key, DEALS_TTL_SECONDS)
        if cached is not None:
            return list(cached)
        response = await self._get(
            "https://www.nseindia.com/api/historicalOR/bulk-block-short-deals",
            params={
                "optionType": option_type,
                "from": from_date.strftime("%d-%m-%Y"),
                "to": to_date.strftime("%d-%m-%Y"),
            },
        )
        rows = list((response.json() or {}).get("data") or [])
        self._cache.put(key, rows, source=str(response.url))
        return rows

    async def get_large_deals_snapshot(self) -> dict:
        """Return the latest block, bulk, and short-sale disclosure snapshot."""

        key = cache_key("large_deals_snapshot")
        cached = self._cache.get(key, DEALS_TTL_SECONDS)
        if cached is not None:
            return dict(cached)
        response = await self._get(
            "https://www.nseindia.com/api/snapshot-capital-market-largedeal"
        )
        payload = response.json() or {}
        self._cache.put(key, payload, source=str(response.url))
        return dict(payload)

    async def download_document(self, url: str, external_id: str) -> tuple[bytes, str]:
        """Fetch a filing for immediate processing without persisting the document."""

        response = await self._get(url)
        declared = response.headers.get("content-length")
        if declared and int(declared) > MAX_DOCUMENT_BYTES:
            raise NseError(f"Document exceeds {MAX_DOCUMENT_BYTES} bytes")
        content = response.content
        if len(content) > MAX_DOCUMENT_BYTES:
            raise NseError(f"Document exceeds {MAX_DOCUMENT_BYTES} bytes")
        logger.info(
            "Fetched transient NSE document %s (%d bytes); not persisted",
            external_id,
            len(content),
        )
        return content, hashlib.sha256(content).hexdigest()

    async def aclose(self) -> None:
        await self._client.aclose()


_client: NseClient | None = None


def get_nse_client() -> NseClient:
    global _client
    if _client is None:
        _client = NseClient()
    return _client
