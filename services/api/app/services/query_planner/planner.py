"""Natural-language query -> SearchPlan (spec §5).

Plans are cached on disk keyed by normalized query + model + prompt version (§16).
"""

import logging
import re
from typing import Literal

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.llm import LLMProvider, generate_structured, get_provider
from app.prompts.planner import (
    PLANNER_EXAMPLE_ASSISTANT,
    PLANNER_EXAMPLE_USER,
    PLANNER_INDIA_EXAMPLE_ASSISTANT,
    PLANNER_INDIA_EXAMPLE_USER,
    PLANNER_SYSTEM,
    PROMPT_VERSION,
)
from app.schemas.search import SearchPlan, StructuredCondition

logger = logging.getLogger(__name__)

_INDIAN_AMOUNT_RE = re.compile(
    r"(?P<currency>₹|inr|rs\.?)?\s*"
    r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<unit>lakh\s*crores?|lac\s*crores?|l\s*cr|crores?|cr\b|lakhs?|lacs?|"
    r"trillions?|billions?|millions?)",
    re.IGNORECASE,
)
_IMPLICIT_MARKET_CAP_PATTERNS = (
    re.compile(
        r"(?P<number>\d[\d,]*(?:\.\d+)?)\s+market\s*cap",
        re.IGNORECASE,
    ),
    re.compile(
        r"market\s*cap(?:italization)?(?:\s+(?:of|around|about|above|below|over|under|"
        r"at\s+least|at\s+most))?\s+(?P<number>\d[\d,]*(?:\.\d+)?)",
        re.IGNORECASE,
    ),
)


def _indian_amount_multiplier(unit: str) -> float:
    normalized = re.sub(r"\s+", " ", unit.lower().strip())
    if normalized.startswith(("lakh crore", "lac crore", "l cr")):
        return 1_000_000_000_000.0
    if normalized.startswith(("crore", "cr")):
        return 10_000_000.0
    if normalized.startswith(("lakh", "lac")):
        return 100_000.0
    if normalized.startswith("trillion"):
        return 1_000_000_000_000.0
    if normalized.startswith("billion"):
        return 1_000_000_000.0
    if normalized.startswith("million"):
        return 1_000_000.0
    return 1.0


def _extract_indian_market_cap(
    query: str,
) -> tuple[str | None, float | list[float], float | None] | None:
    """Extract market-cap amounts as absolute INR, independent of model arithmetic."""
    if not re.search(r"market\s*cap(?:italization)?", query, re.IGNORECASE):
        return None

    amounts: list[tuple[int, int, float]] = []
    for match in _INDIAN_AMOUNT_RE.finditer(query):
        context = query[max(0, match.start() - 45) : min(len(query), match.end() + 45)]
        if not re.search(r"market\s*cap(?:italization)?", context, re.IGNORECASE):
            continue
        number = float(match.group("number").replace(",", ""))
        amounts.append(
            (
                match.start(),
                match.end(),
                number * _indian_amount_multiplier(match.group("unit")),
            )
        )

    if not amounts:
        for pattern in _IMPLICIT_MARKET_CAP_PATTERNS:
            match = pattern.search(query)
            if match:
                amounts.append(
                    (
                        match.start(),
                        match.end(),
                        float(match.group("number").replace(",", "")),
                    )
                )
                break
    if not amounts:
        return None

    amounts.sort(key=lambda item: item[0])
    context = query[max(0, amounts[0][0] - 55) : min(len(query), amounts[-1][1] + 35)].lower()
    values = [item[2] for item in amounts]

    if "between" in context and len(values) >= 2:
        return "between", values[:2], None
    if re.search(
        r"\b(?:at\s+least|minimum|min\.?|no\s+less\s+than|above|over|more\s+than|"
        r"greater\s+than)\b",
        context,
    ):
        return "gte", values[0], None
    if re.search(
        r"\b(?:at\s+most|maximum|max\.?|no\s+more\s+than|below|under|less\s+than)\b",
        context,
    ):
        return "lte", values[0], None
    if re.search(r"\b(?:around|about|approximately|roughly|near)\b", context):
        return "around", values[0], 40.0
    return None, values[0], None


def enforce_india_market_cap(plan: SearchPlan, query: str) -> SearchPlan:
    """Make INR the source of truth for every Indian market-cap condition."""
    parsed = _extract_indian_market_cap(query)
    conditions = [
        condition
        for condition in plan.base_structured_conditions
        if condition.field not in {"market_cap_usd", "market_cap_native"}
    ]
    existing = next(
        (
            condition
            for condition in plan.base_structured_conditions
            if condition.field in {"market_cap_usd", "market_cap_native"}
        ),
        None,
    )
    if parsed is None:
        if existing is not None:
            existing.field = "market_cap_native"
            conditions.append(existing)
        plan.base_structured_conditions = conditions
        return plan

    operator, value, tolerance = parsed
    condition = existing or StructuredCondition(
        field="market_cap_native",
        operator=operator or "gte",
        value=value,
        required=True,
    )
    condition.field = "market_cap_native"
    condition.value = value
    if operator is not None:
        condition.operator = operator
    if condition.operator == "around":
        condition.tolerance_percent = tolerance or condition.tolerance_percent or 40.0
    else:
        condition.tolerance_percent = None
    conditions.append(condition)
    plan.base_structured_conditions = conditions
    return plan


def normalize_query(query: str) -> str:
    return re.sub(r"\s+", " ", query.strip().lower())


def _clamp_weights(plan: SearchPlan) -> SearchPlan:
    """Defensive normalization: clamp weights/limits to sane ranges. The LLM never
    controls scoring arithmetic beyond these declared weights."""
    for cond in plan.base_semantic_conditions + plan.research_conditions:
        cond.weight = min(max(cond.weight, 0.01), 1.0)
    plan.candidate_limit = min(max(plan.candidate_limit, 1), 15)
    plan.final_limit = min(max(plan.final_limit, 1), plan.candidate_limit)
    return plan


async def plan_query(
    query: str,
    *,
    mode: str = "standard",
    market: Literal["US", "IN"] = "US",
    provider: LLMProvider | None = None,
    use_cache: bool = True,
) -> SearchPlan:
    provider = provider or get_provider()
    cache = FileCache(get_settings().cache_path, "query_plans")
    universe = "NSE_MAINBOARD" if market == "IN" else "NYSE_100"
    key = cache_key(normalize_query(query), provider.model_name, PROMPT_VERSION, mode, market)
    if use_cache:
        cached = cache.get(key, ttl_seconds=None)
        if cached:
            try:
                cached_plan = SearchPlan.model_validate(cached)
                # The market selector is authoritative. This also upgrades any
                # compatible plan cache entry created before a universe expansion.
                cached_plan.universe = universe
                return cached_plan
            except Exception:
                cache.invalidate(key)

    example_user = PLANNER_INDIA_EXAMPLE_USER if market == "IN" else PLANNER_EXAMPLE_USER
    example_assistant = (
        PLANNER_INDIA_EXAMPLE_ASSISTANT if market == "IN" else PLANNER_EXAMPLE_ASSISTANT
    )
    messages = [
        {
            "role": "system",
            "content": PLANNER_SYSTEM.format(
                market_description=(
                    "all companies in the official NSE main-board equity segment"
                    if market == "IN"
                    else "a fixed universe of 100 large NYSE-listed companies"
                ),
                universe=universe,
            ),
        },
        {"role": "user", "content": example_user},
        {"role": "assistant", "content": example_assistant},
        {"role": "user", "content": query},
    ]
    plan = await generate_structured(SearchPlan, messages, provider=provider)
    plan.original_query = query
    plan.universe = universe
    if market == "IN":
        plan = enforce_india_market_cap(plan, query)
    if mode == "quick":
        plan.candidate_limit = min(plan.candidate_limit, 5)
        plan.final_limit = min(plan.final_limit, 5)
    plan = _clamp_weights(plan)
    cache.put(
        key,
        plan.model_dump(mode="json"),
        source="query_planner",
        model_name=provider.model_name,
        prompt_version=PROMPT_VERSION,
    )
    return plan
