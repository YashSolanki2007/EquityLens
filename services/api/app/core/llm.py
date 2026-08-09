"""Model provider interface for hosted NVIDIA chat and local embeddings."""

import asyncio
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError
from tenacity import (
    retry,
    retry_if_exception,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class ModelUnavailableError(RuntimeError):
    """Raised when the local model server cannot be reached."""


class InvalidModelOutputError(ValueError):
    """Raised when model output fails schema validation after the allowed retry."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class LLMProvider(ABC):
    model_name: str
    embed_model_name: str

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        base_url: str | None = None,
        chat_model: str | None = None,
        embed_model: str | None = None,
        timeout: float = 120.0,
    ):
        s = get_settings()
        self.base_url = (base_url or s.ollama_base_url).rstrip("/")
        self.model_name = chat_model or s.ollama_chat_model
        self.embed_model_name = embed_model or s.ollama_embed_model
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, max=5),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature},
        }
        if json_schema is not None:
            payload["format"] = json_schema
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        try:
            resp = await self._client.post("/api/chat", json=payload)
        except httpx.TransportError as exc:
            raise ModelUnavailableError(f"Ollama unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code == 400 and "think" in payload:
            # Older servers / models without a thinking toggle reject the flag.
            payload.pop("think")
            resp = await self._client.post("/api/chat", json=payload)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return THINK_RE.sub("", content).strip()

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, max=5),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            resp = await self._client.post(
                "/api/embed", json={"model": self.embed_model_name, "input": texts}
            )
        except httpx.TransportError as exc:
            raise ModelUnavailableError(f"Ollama unreachable at {self.base_url}: {exc}") from exc
        resp.raise_for_status()
        return resp.json()["embeddings"]

    async def aclose(self) -> None:
        await self._client.aclose()


def _is_retryable_api_error(exc: BaseException) -> bool:
    """Transient hosted-API failures: network issues, rate limits, server errors."""
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in (429, 500, 502, 503, 504)
    return False


class OpenAICompatProvider(LLMProvider):
    """Chat via an OpenAI-compatible endpoint (e.g. NVIDIA build.nvidia.com free tier).

    Embeddings still go through local Ollama so the existing 1024-dim pgvector
    index stays valid — only the latency-critical chat calls move to the API.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
    ):
        s = get_settings()
        self.base_url = (base_url or s.nvidia_base_url).rstrip("/")
        self.model_name = model or s.nvidia_model
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key or s.nvidia_api_key}"},
            timeout=120.0,
        )
        self._embedder = OllamaProvider()
        self.embed_model_name = self._embedder.embed_model_name
        # NVIDIA's development endpoint has a shared free-tier request limit.
        # Serialize chat starts and keep them below 40 requests/minute so bulk
        # card generation does not overwhelm the endpoint.
        self._chat_lock = asyncio.Lock()
        self._last_chat_started = 0.0

    async def _throttle_chat(self) -> None:
        async with self._chat_lock:
            wait = self._last_chat_started + 1.6 - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_chat_started = time.monotonic()

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=2, max=60),
        retry=retry_if_exception(_is_retryable_api_error),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_schema: dict | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        await self._throttle_chat()
        payload: dict = {
            "model": self.model_name,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens or 4096,
        }
        if json_schema is not None:
            # NVIDIA NIM structured output; harmlessly ignored elsewhere. The prompt
            # below also spells out the schema for models without guided decoding.
            payload["nvext"] = {"guided_json": json_schema}
            payload["messages"] = [
                *messages,
                {
                    "role": "system",
                    "content": (
                        "Respond with ONLY a JSON object that validates against this "
                        "JSON schema (include every required field):\n"
                        + json.dumps(json_schema)
                    ),
                },
            ]
        try:
            resp = await self._client.post("/chat/completions", json=payload)
        except httpx.TransportError as exc:
            raise ModelUnavailableError(f"LLM API unreachable at {self.base_url}: {exc}") from exc
        if resp.status_code == 400 and "nvext" in payload:
            payload.pop("nvext")
            resp = await self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"] or ""
        return THINK_RE.sub("", content).strip()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self._embedder.embed(texts)

    async def aclose(self) -> None:
        await self._client.aclose()
        await self._embedder.aclose()


_provider: LLMProvider | None = None


def get_provider() -> LLMProvider:
    global _provider
    if _provider is None:
        s = get_settings()
        if s.llm_provider == "nvidia" and s.nvidia_api_key:
            _provider = OpenAICompatProvider()
        else:
            _provider = OllamaProvider()
    return _provider


def set_provider(provider: LLMProvider | None) -> None:
    """Override the provider (tests use a fake)."""
    global _provider
    _provider = provider


def _extract_json(text: str) -> str:
    """Best-effort extraction of a JSON object/array from model output."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.DOTALL).strip()
    start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
    if start > 0:
        text = text[start:]
    if start >= 0:
        try:
            value, _ = json.JSONDecoder().raw_decode(text)
            return json.dumps(value)
        except json.JSONDecodeError:
            pass
    return text


async def generate_structured[T: BaseModel](
    schema: type[T],
    messages: list[dict[str, str]],
    *,
    provider: LLMProvider | None = None,
    temperature: float = 0.1,
) -> T:
    """Chat with JSON-schema-constrained output, validate with Pydantic, and on
    invalid output retry exactly once with the validation errors appended (spec §17).
    """
    provider = provider or get_provider()
    json_schema = schema.model_json_schema()
    raw = await provider.chat(messages, json_schema=json_schema, temperature=temperature)
    try:
        return schema.model_validate_json(_extract_json(raw))
    except (ValidationError, json.JSONDecodeError) as exc:
        logger.warning("Invalid model JSON for %s, retrying once: %s", schema.__name__, exc)
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {
                "role": "user",
                "content": (
                    "Your previous JSON was invalid for the required schema. "
                    f"Validation errors:\n{exc}\n\n"
                    "Return ONLY corrected JSON matching the schema exactly."
                ),
            },
        ]
        raw2 = await provider.chat(retry_messages, json_schema=json_schema, temperature=0.0)
        try:
            return schema.model_validate_json(_extract_json(raw2))
        except (ValidationError, json.JSONDecodeError) as exc2:
            raise InvalidModelOutputError(
                f"Model output failed validation for {schema.__name__} after retry: {exc2}",
                raw=raw2,
            ) from exc2
