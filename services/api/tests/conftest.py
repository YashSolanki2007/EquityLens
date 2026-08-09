import json

import pytest

from app.core.llm import LLMProvider


class FakeProvider(LLMProvider):
    """Deterministic provider for tests: returns queued responses, records calls."""

    def __init__(self, responses: list[str] | None = None, embed_dim: int = 8):
        self.model_name = "fake-chat"
        self.embed_model_name = "fake-embed"
        self.responses = list(responses or [])
        self.chat_calls: list[list[dict]] = []
        self.embed_calls: list[list[str]] = []
        self.embed_dim = embed_dim

    async def chat(self, messages, *, json_schema=None, temperature=0.2, max_tokens=None) -> str:
        self.chat_calls.append(messages)
        if not self.responses:
            return "{}"
        return self.responses.pop(0)

    async def embed(self, texts):
        self.embed_calls.append(list(texts))
        return [[0.1] * self.embed_dim for _ in texts]


@pytest.fixture
def fake_provider():
    return FakeProvider()


def fake_json(obj) -> str:
    return json.dumps(obj)
