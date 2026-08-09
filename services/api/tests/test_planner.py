"""Unit tests for query-plan parsing and invalid-JSON retry (spec §17, §20)."""

import json

import pytest

from app.core.llm import InvalidModelOutputError, _extract_json, generate_structured
from app.schemas.search import SearchPlan
from app.services.query_planner.planner import normalize_query, plan_query
from tests.conftest import FakeProvider

VALID_PLAN = {
    "original_query": "data center companies",
    "universe": "NYSE_100",
    "base_semantic_conditions": [
        {
            "id": "data_center",
            "concept": "data center infrastructure",
            "card_types": ["business_activity"],
            "required": True,
            "weight": 0.6,
            "directness_required": "direct",
        }
    ],
    "base_structured_conditions": [
        {
            "field": "market_cap_usd",
            "operator": "around",
            "value": 3000000000,
            "tolerance_percent": 40,
            "required": True,
        }
    ],
    "research_conditions": [
        {
            "id": "growth",
            "type": "revenue_yoy_growth",
            "operator": "gte",
            "threshold": 20,
            "required": True,
            "weight": 0.4,
        }
    ],
    "exclusions": [],
    "ambiguities": [],
    "candidate_limit": 15,
    "final_limit": 7,
}


class TestPlanParsing:
    async def test_valid_plan_parses(self):
        provider = FakeProvider([json.dumps(VALID_PLAN)])
        plan = await plan_query("data center companies", provider=provider, use_cache=False)
        assert isinstance(plan, SearchPlan)
        assert plan.base_semantic_conditions[0].id == "data_center"
        assert plan.base_structured_conditions[0].operator == "around"
        assert plan.research_conditions[0].threshold == 20

    async def test_quick_mode_caps_limits(self):
        provider = FakeProvider([json.dumps(VALID_PLAN)])
        plan = await plan_query("q", mode="quick", provider=provider, use_cache=False)
        assert plan.candidate_limit == 5
        assert plan.final_limit == 5

    async def test_original_query_overwritten(self):
        provider = FakeProvider([json.dumps(VALID_PLAN)])
        plan = await plan_query("my actual query", provider=provider, use_cache=False)
        assert plan.original_query == "my actual query"

    async def test_india_market_cap_is_kept_in_absolute_rupees(self):
        wrong_usd_plan = {
            **VALID_PLAN,
            "base_structured_conditions": [
                {
                    "field": "market_cap_usd",
                    "operator": "gte",
                    "value": 300_000_000_000,
                    "required": True,
                }
            ],
        }
        provider = FakeProvider([json.dumps(wrong_usd_plan)])

        plan = await plan_query(
            "Find NSE grid companies with at least a 3 lakh crore market cap",
            market="IN",
            provider=provider,
            use_cache=False,
        )

        condition = plan.base_structured_conditions[0]
        assert condition.field == "market_cap_native"
        assert condition.operator == "gte"
        assert condition.value == 3_000_000_000_000

    async def test_india_crore_amount_and_around_tolerance_are_deterministic(self):
        provider = FakeProvider([json.dumps(VALID_PLAN)])

        plan = await plan_query(
            "Find Indian companies around ₹50,000 crore market cap",
            market="IN",
            provider=provider,
            use_cache=False,
        )

        condition = plan.base_structured_conditions[0]
        assert condition.field == "market_cap_native"
        assert condition.operator == "around"
        assert condition.value == 500_000_000_000
        assert condition.tolerance_percent == 40

    async def test_india_never_keeps_a_usd_market_cap_field(self):
        provider = FakeProvider([json.dumps(VALID_PLAN)])

        plan = await plan_query(
            "Find Indian data-center companies with a large market cap",
            market="IN",
            provider=provider,
            use_cache=False,
        )

        assert plan.base_structured_conditions[0].field == "market_cap_native"


class TestInvalidJsonRetry:
    def test_extract_json_ignores_trailing_model_text(self):
        assert _extract_json('{"answer": 1}\n{"extra": true}') == '{"answer": 1}'

    async def test_retry_once_with_validation_errors(self):
        provider = FakeProvider(["not json at all", json.dumps(VALID_PLAN)])
        plan = await generate_structured(
            SearchPlan,
            [{"role": "user", "content": "x"}],
            provider=provider,
        )
        assert plan.universe == "NYSE_100"
        assert len(provider.chat_calls) == 2
        # The retry message must include the validation feedback.
        retry_prompt = provider.chat_calls[1][-1]["content"]
        assert "invalid" in retry_prompt.lower()

    async def test_second_failure_raises(self):
        provider = FakeProvider(["nope", "still nope"])
        with pytest.raises(InvalidModelOutputError):
            await generate_structured(
                SearchPlan, [{"role": "user", "content": "x"}], provider=provider
            )

    async def test_json_fenced_output_accepted(self):
        fenced = f"```json\n{json.dumps(VALID_PLAN)}\n```"
        provider = FakeProvider([fenced])
        plan = await generate_structured(
            SearchPlan, [{"role": "user", "content": "x"}], provider=provider
        )
        assert plan.candidate_limit == 15


def test_normalize_query():
    assert normalize_query("  Data   Center\n companies ") == "data center companies"


class TestProviderSelection:
    def test_ollama_selected_when_configured(self, monkeypatch):
        from app.core import llm
        from app.core.config import get_settings

        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        get_settings.cache_clear()
        llm.set_provider(None)
        assert isinstance(llm.get_provider(), llm.OllamaProvider)
        llm.set_provider(None)
        get_settings.cache_clear()

    def test_nvidia_selected_with_key(self, monkeypatch):
        from app.core import llm
        from app.core.config import get_settings

        monkeypatch.setenv("LLM_PROVIDER", "nvidia")
        monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
        monkeypatch.setenv("NVIDIA_MODEL", "test/model-1b")
        get_settings.cache_clear()
        llm.set_provider(None)
        provider = llm.get_provider()
        assert isinstance(provider, llm.OpenAICompatProvider)
        assert provider.model_name == "test/model-1b"
        # Embeddings must still delegate to Ollama (index compatibility).
        assert provider.embed_model_name == "qwen3-embedding:0.6b"
        llm.set_provider(None)
        get_settings.cache_clear()
