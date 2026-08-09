"""Deterministic financial verification from SEC Company Facts XBRL data (spec §9).

The language model is NEVER asked to calculate growth. All period selection and
arithmetic happen here, in plain Python, from cached financial_facts rows.
"""

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FinancialFact
from app.services.sec.facts import NET_INCOME_CONCEPTS, REVENUE_CONCEPTS

logger = logging.getLogger(__name__)

# A "quarterly" duration: 10-Qs report ~13-week periods.
QUARTER_MIN_DAYS = 70
QUARTER_MAX_DAYS = 100

# The comparable quarter ends ~365 days earlier (fiscal calendars wobble by a few weeks).
YOY_TARGET_DAYS = 365
YOY_TOLERANCE_DAYS = 21

MetricName = Literal["revenue_yoy_growth", "net_income_yoy_growth"]

METRIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue_yoy_growth": (
        *(f"us-gaap:{c}" for c in REVENUE_CONCEPTS),
        "normalized:Revenue",
    ),
    "net_income_yoy_growth": (
        *(f"us-gaap:{c}" for c in NET_INCOME_CONCEPTS),
        "normalized:NetIncome",
    ),
}


@dataclass
class FactValue:
    concept: str
    unit: str
    value: float
    start_date: date | None
    end_date: date
    form: str | None
    fiscal_year: int | None
    fiscal_period: str | None
    accession: str | None
    filed_date: date | None

    @property
    def duration_days(self) -> int | None:
        if self.start_date is None:
            return None
        return (self.end_date - self.start_date).days

    def period_label(self) -> str:
        if self.fiscal_period and self.fiscal_year:
            return f"{self.fiscal_period} FY{self.fiscal_year} (ended {self.end_date.isoformat()})"
        return f"quarter ended {self.end_date.isoformat()}"


@dataclass
class YoYResult:
    status: Literal["ok", "unknown", "not_directly_comparable"]
    growth_percent: float | None = None
    current: FactValue | None = None
    previous: FactValue | None = None
    concept_used: str | None = None
    note: str = ""


def is_quarterly(fact: FactValue) -> bool:
    d = fact.duration_days
    return d is not None and QUARTER_MIN_DAYS <= d <= QUARTER_MAX_DAYS


def calculate_yoy(current: float, previous: float) -> float | None:
    """growth_percent = ((current - previous) / abs(previous)) * 100; None when previous == 0."""
    if previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100.0


def _dedupe_latest(facts: list[FactValue]) -> list[FactValue]:
    """One value per (concept, start, end): prefer the most recently filed (restatements)."""
    best: dict[tuple, FactValue] = {}
    for f in facts:
        key = (f.concept, f.start_date, f.end_date)
        cur = best.get(key)
        if cur is None or (
            (f.filed_date or date.min),
            f.value,
        ) > ((cur.filed_date or date.min), cur.value):
            best[key] = f
    return sorted(best.values(), key=lambda f: f.end_date, reverse=True)


def select_yoy_pair(facts: list[FactValue], concepts: tuple[str, ...]) -> YoYResult:
    """Pick the latest quarterly fact and its same-fiscal-quarter comparison one year
    earlier, honoring the comparison rules in spec §9."""
    for concept in concepts:  # try primary concept first, then fallback
        quarterly = _dedupe_latest(
            [f for f in facts if f.concept == concept and is_quarterly(f)]
        )
        if not quarterly:
            continue
        current = quarterly[0]
        target_end = current.end_date - timedelta(days=YOY_TARGET_DAYS)
        candidates = [
            f for f in quarterly[1:] if abs((f.end_date - target_end).days) <= YOY_TOLERANCE_DAYS
        ]
        if current.fiscal_period:
            same_fp = [f for f in candidates if f.fiscal_period == current.fiscal_period]
            if same_fp:
                candidates = same_fp
        if not candidates:
            return YoYResult(
                status="unknown",
                current=current,
                concept_used=concept,
                note="No comparable quarter one year earlier with matching duration.",
            )
        # Reject mismatched durations beyond a few days.
        previous = min(candidates, key=lambda f: abs((f.end_date - target_end).days))
        cur_d, prev_d = current.duration_days or 0, previous.duration_days or 0
        if abs(cur_d - prev_d) > 10:
            return YoYResult(
                status="unknown",
                current=current,
                previous=previous,
                concept_used=concept,
                note=f"Period durations differ ({cur_d} vs {prev_d} days); not comparable.",
            )
        growth = calculate_yoy(current.value, previous.value)
        if growth is None:
            return YoYResult(
                status="unknown",
                current=current,
                previous=previous,
                concept_used=concept,
                note="Previous-period value is zero; growth percentage undefined.",
            )
        if previous.value < 0:
            return YoYResult(
                status="not_directly_comparable",
                growth_percent=growth,
                current=current,
                previous=previous,
                concept_used=concept,
                note=(
                    "Previous-period value is negative; the percentage is calculated "
                    "against its absolute value and is not directly comparable to a "
                    "simple growth threshold."
                ),
            )
        return YoYResult(
            status="ok",
            growth_percent=growth,
            current=current,
            previous=previous,
            concept_used=concept,
        )
    return YoYResult(
        status="unknown", note="No quarterly facts available for the supported concepts."
    )


async def load_facts(db: AsyncSession, company_id, concepts: tuple[str, ...]) -> list[FactValue]:
    rows = (
        (
            await db.execute(
                select(FinancialFact).where(
                    FinancialFact.company_id == company_id,
                    FinancialFact.concept.in_(concepts),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        FactValue(
            concept=r.concept,
            unit=r.unit,
            value=r.value,
            start_date=r.start_date,
            end_date=r.end_date,
            form=r.form,
            fiscal_year=r.fiscal_year,
            fiscal_period=r.fiscal_period,
            accession=r.accession,
            filed_date=r.filed_date,
        )
        for r in rows
    ]


async def compute_yoy_metric(db: AsyncSession, company_id, metric: MetricName) -> YoYResult:
    concepts = METRIC_CONCEPTS[metric]
    facts = await load_facts(db, company_id, concepts)
    return select_yoy_pair(facts, concepts)
