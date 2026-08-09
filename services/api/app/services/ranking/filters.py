"""Deterministic structured filtering (spec §5/§7).

Market-cap conditions rely on delayed yfinance snapshots; when a snapshot is missing
the condition is marked not_verified instead of failing the company (spec §3).
"""

from dataclasses import dataclass
from typing import Literal

from app.schemas.search import StructuredCondition

FilterStatus = Literal["pass", "fail", "not_verified"]

DEFAULT_AROUND_TOLERANCE_PCT = 40.0


@dataclass
class CompanyFilterInput:
    ticker: str
    sector: str
    industry: str
    market_cap_usd: float | None  # None when market data is unavailable
    market_cap_native: float | None = None


@dataclass
class FilterResult:
    condition_index: int
    field: str
    status: FilterStatus
    required: bool
    detail: str


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _text_match(actual: str, condition: StructuredCondition) -> bool:
    wanted = [str(v).lower() for v in _as_list(condition.value)]
    actual_l = actual.lower()
    if condition.operator == "eq":
        return actual_l == wanted[0] or wanted[0] in actual_l
    if condition.operator == "in":
        return any(actual_l == w or w in actual_l for w in wanted)
    return False


def market_cap_bounds(condition: StructuredCondition) -> tuple[float | None, float | None]:
    """Lower/upper bounds implied by a market-cap condition (None = unbounded)."""
    op = condition.operator
    if op == "around":
        center = float(_as_list(condition.value)[0])
        tolerance = (
            condition.tolerance_percent
            if condition.tolerance_percent is not None
            else DEFAULT_AROUND_TOLERANCE_PCT
        )
        delta = center * tolerance / 100.0
        return center - delta, center + delta
    if op == "between":
        values = [float(v) for v in _as_list(condition.value)]
        if len(values) >= 2:
            return min(values), max(values)
        return values[0], None
    if op == "gte":
        return float(_as_list(condition.value)[0]), None
    if op == "lte":
        return None, float(_as_list(condition.value)[0])
    if op == "eq":
        v = float(_as_list(condition.value)[0])
        return v, v
    return None, None


def evaluate_condition(
    company: CompanyFilterInput, condition: StructuredCondition, index: int
) -> FilterResult:
    field = condition.field
    if field == "ticker":
        ok = any(company.ticker.upper() == str(v).upper() for v in _as_list(condition.value))
        return FilterResult(
            index, field, "pass" if ok else "fail", condition.required, "ticker match"
        )
    if field == "sector":
        ok = _text_match(company.sector, condition)
        return FilterResult(
            index, field, "pass" if ok else "fail", condition.required, f"sector={company.sector}"
        )
    if field == "industry":
        ok = _text_match(company.industry, condition)
        return FilterResult(
            index,
            field,
            "pass" if ok else "fail",
            condition.required,
            f"industry={company.industry}",
        )
    if field in {"market_cap_usd", "market_cap_native"}:
        actual = (
            company.market_cap_native
            if field == "market_cap_native"
            else company.market_cap_usd
        )
        if actual is None:
            return FilterResult(
                index,
                field,
                "not_verified",
                condition.required,
                "market data unavailable; filter not verified",
            )
        low, high = market_cap_bounds(condition)
        ok = (low is None or actual >= low) and (
            high is None or actual <= high
        )
        unit = "INR" if field == "market_cap_native" else "USD"
        return FilterResult(
            index,
            field,
            "pass" if ok else "fail",
            condition.required,
            f"market_cap_{unit.lower()}={actual:.0f}, bounds=({low}, {high})",
        )
    return FilterResult(
        index, field, "not_verified", condition.required, f"unsupported field {field}"
    )


def apply_structured_filters(
    company: CompanyFilterInput, conditions: list[StructuredCondition]
) -> tuple[bool, list[FilterResult]]:
    """Return (keep_company, per-condition results). A company is dropped only when a
    REQUIRED condition verifiably fails; not_verified keeps it (flagged)."""
    results = [evaluate_condition(company, c, i) for i, c in enumerate(conditions)]
    keep = all(not (r.required and r.status == "fail") for r in results)
    return keep, results
