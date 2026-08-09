"""Deterministic company financial time series built from cached SEC XBRL facts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FinancialFact
from app.schemas.company import (
    FinancialHeadline,
    FinancialOverviewOut,
    FinancialSeriesPoint,
    RevenueMovement,
)
from app.services.research.financials import (
    QUARTER_MAX_DAYS,
    QUARTER_MIN_DAYS,
    calculate_yoy,
)
from app.services.sec.facts import NET_INCOME_CONCEPTS, REVENUE_CONCEPTS

Frequency = Literal["annual", "quarterly"]

ANNUAL_MIN_DAYS = 300
ANNUAL_MAX_DAYS = 430
MAX_ANNUAL_PERIODS = 6
MAX_QUARTERLY_PERIODS = 20

REVENUE_KEYS = tuple(f"us-gaap:{concept}" for concept in REVENUE_CONCEPTS)
NET_INCOME_KEYS = tuple(f"us-gaap:{concept}" for concept in NET_INCOME_CONCEPTS)
REVENUE_KEYS = (*REVENUE_KEYS, "normalized:Revenue")
NET_INCOME_KEYS = (*NET_INCOME_KEYS, "normalized:NetIncome")


def _duration_days(fact: FinancialFact) -> int | None:
    if fact.start_date is None:
        return None
    return (fact.end_date - fact.start_date).days


def _matches_frequency(fact: FinancialFact, frequency: Frequency) -> bool:
    duration = _duration_days(fact)
    if duration is None:
        return False
    if frequency == "quarterly":
        return (
            QUARTER_MIN_DAYS <= duration <= QUARTER_MAX_DAYS
            and fact.form in ("10-Q", "QUARTERLY")
        )
    return (
        ANNUAL_MIN_DAYS <= duration <= ANNUAL_MAX_DAYS
        and fact.form in ("10-K", "ANNUAL")
    )


def _preferred_fact(
    facts: Iterable[FinancialFact],
    concepts: tuple[str, ...],
) -> FinancialFact | None:
    rows = list(facts)
    for concept in concepts:
        candidates = [fact for fact in rows if fact.concept == concept]
        if candidates:
            return max(
                candidates,
                key=lambda fact: (
                    fact.filed_date or date.min,
                    fact.fiscal_year or 0,
                    fact.value,
                ),
            )
    return None


def _period_label(fact: FinancialFact, frequency: Frequency) -> str:
    if frequency == "annual":
        return f"Year ended {fact.end_date.strftime('%b %Y')}"
    return f"Quarter ended {fact.end_date.strftime('%b %Y')}"


def build_financial_series(
    facts: list[FinancialFact],
    frequency: Frequency,
) -> list[FinancialSeriesPoint]:
    """Collapse duplicate/restated SEC facts into one revenue/profit point per period."""
    eligible = [fact for fact in facts if _matches_frequency(fact, frequency)]
    by_period: dict[tuple[date | None, date], list[FinancialFact]] = defaultdict(list)
    for fact in eligible:
        by_period[(fact.start_date, fact.end_date)].append(fact)

    raw: list[tuple[FinancialSeriesPoint, FinancialFact | None, FinancialFact | None]] = []
    for (_, end_date), period_facts in by_period.items():
        revenue = _preferred_fact(period_facts, REVENUE_KEYS)
        net_income = _preferred_fact(period_facts, NET_INCOME_KEYS)
        anchor = revenue or net_income
        if anchor is None:
            continue
        revenue_value = revenue.value if revenue else None
        income_value = net_income.value if net_income else None
        margin = None
        if revenue_value not in (None, 0) and income_value is not None:
            margin = income_value / revenue_value * 100
        accessions = sorted(
            {
                fact.accession
                for fact in (revenue, net_income)
                if fact is not None and fact.accession
            }
        )
        raw.append(
            (
                FinancialSeriesPoint(
                    period=_period_label(anchor, frequency),
                    end_date=end_date.isoformat(),
                    revenue=revenue_value,
                    net_income=income_value,
                    net_margin_percent=round(margin, 2) if margin is not None else None,
                    accessions=accessions,
                ),
                revenue,
                net_income,
            )
        )

    raw.sort(key=lambda item: item[0].end_date)
    points = [item[0] for item in raw]
    comparison_gap_days = 330 if frequency == "annual" else 330
    comparison_max_days = 400
    for index, point in enumerate(points):
        current_end = date.fromisoformat(point.end_date)
        candidates = [
            previous
            for previous in points[:index]
            if comparison_gap_days
            <= (current_end - date.fromisoformat(previous.end_date)).days
            <= comparison_max_days
        ]
        if not candidates:
            continue
        previous = max(candidates, key=lambda item: item.end_date)
        if point.revenue is not None and previous.revenue is not None:
            growth = calculate_yoy(point.revenue, previous.revenue)
            point.revenue_yoy_percent = round(growth, 2) if growth is not None else None
        if point.net_income is not None and previous.net_income is not None:
            growth = calculate_yoy(point.net_income, previous.net_income)
            point.net_income_yoy_percent = round(growth, 2) if growth is not None else None

    limit = MAX_ANNUAL_PERIODS if frequency == "annual" else MAX_QUARTERLY_PERIODS
    return points[-limit:]


def _notable_movements(
    annual: list[FinancialSeriesPoint],
    quarterly: list[FinancialSeriesPoint],
) -> list[RevenueMovement]:
    pool: list[RevenueMovement] = []
    for frequency, points in (("annual", annual), ("quarterly", quarterly)):
        for point in points:
            if point.revenue is None or point.revenue_yoy_percent is None:
                continue
            change = point.revenue_yoy_percent
            direction: Literal["increase", "decline", "stable"]
            if change >= 5:
                direction = "increase"
            elif change <= -5:
                direction = "decline"
            else:
                direction = "stable"
            pool.append(
                RevenueMovement(
                    id=f"{frequency}:{point.end_date}",
                    period=point.period,
                    end_date=point.end_date,
                    revenue=point.revenue,
                    change_percent=change,
                    direction=direction,
                    frequency=frequency,
                )
            )
    pool.sort(key=lambda movement: (movement.end_date, abs(movement.change_percent)), reverse=True)
    return pool[:4]


def build_financial_overview(
    ticker: str,
    cik: str | None,
    facts: list[FinancialFact],
    *,
    currency: str = "USD",
    source_url: str | None = None,
) -> FinancialOverviewOut:
    annual = build_financial_series(facts, "annual")
    quarterly = build_financial_series(facts, "quarterly")
    latest = quarterly[-1] if quarterly else (annual[-1] if annual else None)
    headline = None
    if latest:
        headline = FinancialHeadline(
            period=latest.period,
            revenue=latest.revenue,
            net_income=latest.net_income,
            net_margin_percent=latest.net_margin_percent,
            revenue_yoy_percent=latest.revenue_yoy_percent,
        )
    limitations: list[str] = []
    if not annual:
        limitations.append(
            "No comparable annual revenue or net-income series was found."
            if currency != "USD"
            else "No comparable annual SEC XBRL revenue or net-income series was found."
        )
    if not quarterly:
        limitations.append(
            "No comparable three-month financial series was found."
            if currency != "USD"
            else "No true three-month SEC XBRL series was found."
        )
    return FinancialOverviewOut(
        ticker=ticker,
        annual=annual,
        quarterly=quarterly,
        headline=headline,
        notable_movements=_notable_movements(annual, quarterly),
        currency=currency,
        source_url=source_url
        or f"https://data.sec.gov/api/xbrl/companyfacts/CIK{str(cik).zfill(10)}.json",
        limitations=limitations,
    )


async def get_financial_overview(
    db: AsyncSession,
    *,
    ticker: str,
    cik: str | None,
    company_id,
    country: str = "US",
    currency: str = "USD",
    market_data_ticker: str | None = None,
) -> FinancialOverviewOut:
    facts = (
        (
            await db.execute(
                select(FinancialFact).where(FinancialFact.company_id == company_id)
            )
        )
        .scalars()
        .all()
    )
    source_url = None
    if country == "IN":
        source_url = (
            f"https://finance.yahoo.com/quote/{market_data_ticker or ticker + '.NS'}/financials/"
        )
    return build_financial_overview(
        ticker,
        cik,
        list(facts),
        currency=currency,
        source_url=source_url,
    )
