"""Peer discovery and normalized comparison metrics for NSE companies.

Peer discovery is intentionally deterministic. It uses the exchange industry
classification when it is available and falls back to existing annual-report
card embeddings when the company is unclassified. A language model never
calculates the ratios or the relative ranks.
"""

import asyncio
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, CompanyCard, FinancialFact
from app.services.market_data.india_trading import get_trading_ratios

AUTO_PEER_LIMIT = 5
MAX_COMPARISON_COMPANIES = 8
SEMANTIC_NEIGHBOURS_PER_CARD = 60
UNCLASSIFIED = {"", "unclassified", "unknown", "n/a", "na", "other"}

REVENUE_CONCEPTS = (
    "normalized:Revenue",
    "us-gaap:Revenues",
    "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
)

METRIC_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": "market_cap",
        "label": "Market cap",
        "category": "Scale",
        "format": "currency_compact",
        "higher_is_better": None,
        "description": "Latest market capitalization reported by the market-data source.",
    },
    {
        "key": "trailing_pe",
        "label": "P/E",
        "category": "Valuation",
        "format": "multiple",
        "higher_is_better": False,
        "description": "Current price divided by trailing earnings per share.",
    },
    {
        "key": "price_to_book",
        "label": "P/B",
        "category": "Valuation",
        "format": "multiple",
        "higher_is_better": False,
        "description": "Current price relative to reported book value per share.",
    },
    {
        "key": "revenue_growth_percent",
        "label": "Revenue growth",
        "category": "Growth",
        "format": "percent",
        "higher_is_better": True,
        "description": "Latest reported revenue growth from the market-data source.",
    },
    {
        "key": "earnings_growth_percent",
        "label": "Earnings growth",
        "category": "Growth",
        "format": "percent",
        "higher_is_better": True,
        "description": "Latest reported earnings growth from the market-data source.",
    },
    {
        "key": "profit_margin_percent",
        "label": "Net margin",
        "category": "Profitability",
        "format": "percent",
        "higher_is_better": True,
        "description": "Net income as a percentage of revenue.",
    },
    {
        "key": "operating_margin_percent",
        "label": "Operating margin",
        "category": "Profitability",
        "format": "percent",
        "higher_is_better": True,
        "description": "Operating income as a percentage of revenue.",
    },
    {
        "key": "return_on_equity_percent",
        "label": "ROE",
        "category": "Profitability",
        "format": "percent",
        "higher_is_better": True,
        "description": "Return generated on shareholders' equity.",
    },
    {
        "key": "debt_to_equity_percent",
        "label": "Debt / equity",
        "category": "Financial strength",
        "format": "percent",
        "higher_is_better": False,
        "description": "Reported debt relative to shareholders' equity.",
    },
    {
        "key": "current_ratio",
        "label": "Current ratio",
        "category": "Financial strength",
        "format": "multiple",
        "higher_is_better": True,
        "description": "Current assets divided by current liabilities.",
    },
    {
        "key": "beta",
        "label": "Beta",
        "category": "Market",
        "format": "number",
        "higher_is_better": None,
        "description": "Historical sensitivity to broad-market movements.",
    },
    {
        "key": "price_vs_52w_high_percent",
        "label": "From 52W high",
        "category": "Market",
        "format": "percent",
        "higher_is_better": None,
        "description": "Current price relative to the 52-week high.",
    },
    {
        "key": "relative_volume",
        "label": "Relative volume",
        "category": "Market",
        "format": "multiple",
        "higher_is_better": None,
        "description": "Latest reported volume divided by average volume.",
    },
]


def _is_classified(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in UNCLASSIFIED)


def _business_card_priority(card: CompanyCard) -> float:
    text = card.text.lower()
    activity_cues = (
        "engaged in",
        "business of",
        "operates in",
        "operates as",
        "primarily engaged",
        "segments:",
        "manufactures",
        "provides",
        "specializes",
        "develops",
    )
    generic_cues = (
        "gdp",
        "inflation",
        "economy",
        "sector forms",
        "is forecast",
        "is projected",
        "shareholders",
        "total income",
        "total expenditure",
    )
    directness = {"core": 3.0, "direct": 2.0, "indirect": 1.0, "prospective": 0.0}
    return (
        sum(4.0 for cue in activity_cues if cue in text)
        - sum(3.0 for cue in generic_cues if cue in text)
        + directness.get(card.directness, 0.0)
        + min(len(card.text), 240) / 240
    )


def _business_label(texts: Iterable[str]) -> str:
    joined = " ".join(texts).lower()
    labels: list[str] = []
    keyword_groups = (
        ("Infrastructure & construction", ("infrastructure", "construction", "epc", "contracting")),
        ("Hotels & hospitality", ("hotel", "hospitality", "resort")),
        ("Financial services", ("banking", "lending", "finance", "insurance")),
        ("Pharmaceuticals", ("pharma", "pharmaceutical", "drug", "formulation")),
        ("Information technology", ("software", "information technology", "digital services")),
        ("Manufacturing", ("manufactur", "industrial products", "factory")),
        ("Real estate", ("real estate", "residential development", "commercial development")),
        ("Power & energy", ("power generation", "renewable energy", "electricity")),
        ("Consumer products", ("consumer products", "fmcg", "retail")),
    )
    for label, keywords in keyword_groups:
        if any(keyword in joined for keyword in keywords):
            labels.append(label)
        if len(labels) == 2:
            break
    return " / ".join(labels) if labels else "Business-activity peers"


async def _semantic_candidates(
    db: AsyncSession,
    company: Company,
) -> tuple[list[dict[str, Any]], str]:
    target_cards = (
        (
            await db.execute(
                select(CompanyCard)
                .where(CompanyCard.company_id == company.id)
                .where(CompanyCard.card_type == "business_activity")
                .where(CompanyCard.embedding.is_not(None))
            )
        )
        .scalars()
        .all()
    )
    target_cards.sort(key=_business_card_priority, reverse=True)
    target_cards = target_cards[:2]
    if not target_cards:
        return [], "Business-activity peers"

    best_by_company: dict[UUID, dict[str, Any]] = {}
    for target_card in target_cards:
        distance = CompanyCard.embedding.cosine_distance(target_card.embedding)
        rows = (
            await db.execute(
                select(CompanyCard, Company, distance.label("distance"))
                .join(Company, Company.id == CompanyCard.company_id)
                .where(CompanyCard.embedding.is_not(None))
                .where(CompanyCard.card_type == "business_activity")
                .where(Company.country == company.country)
                .where(Company.id != company.id)
                .order_by(distance)
                .limit(SEMANTIC_NEIGHBOURS_PER_CARD)
            )
        ).all()
        for card, candidate, raw_distance in rows:
            similarity = max(0.0, min(1.0, 1.0 - float(raw_distance)))
            current = best_by_company.get(candidate.id)
            if current is None or similarity > current["similarity"]:
                best_by_company[candidate.id] = {
                    "company": candidate,
                    "similarity": similarity,
                    "matched_text": card.text,
                }

    candidates = sorted(
        best_by_company.values(),
        key=lambda item: item["similarity"],
        reverse=True,
    )
    return candidates, _business_label(card.text for card in target_cards)


async def _classified_candidates(
    db: AsyncSession,
    company: Company,
) -> tuple[list[dict[str, Any]], str]:
    industry_match = _is_classified(company.industry)
    sector_match = _is_classified(company.sector)
    if not industry_match and not sector_match:
        return [], company.industry or "Business-activity peers"

    conditions = []
    if industry_match:
        conditions.append(Company.industry == company.industry)
    if sector_match:
        conditions.append(Company.sector == company.sector)
    companies = (
        (
            await db.execute(
                select(Company)
                .where(Company.country == company.country)
                .where(Company.id != company.id)
                .where(or_(*conditions))
                .limit(160)
            )
        )
        .scalars()
        .all()
    )
    candidates = []
    for candidate in companies:
        same_industry = industry_match and candidate.industry == company.industry
        candidates.append(
            {
                "company": candidate,
                "similarity": 0.96 if same_industry else 0.82,
                "matched_text": candidate.industry if same_industry else candidate.sector,
            }
        )
    candidates.sort(key=lambda item: item["similarity"], reverse=True)
    label = company.industry if industry_match else company.sector
    return candidates, label


async def _latest_revenues(
    db: AsyncSession,
    company_ids: Iterable[UUID],
) -> dict[UUID, float]:
    ids = list(company_ids)
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                FinancialFact.company_id,
                FinancialFact.value,
                FinancialFact.end_date,
            )
            .where(FinancialFact.company_id.in_(ids))
            .where(FinancialFact.concept.in_(REVENUE_CONCEPTS))
            .where(
                or_(
                    FinancialFact.form == "ANNUAL",
                    FinancialFact.fiscal_period == "FY",
                )
            )
            .order_by(FinancialFact.end_date.desc())
        )
    ).all()
    latest: dict[UUID, float] = {}
    for company_id, value, _ in rows:
        if company_id not in latest and value is not None and value > 0:
            latest[company_id] = float(value)
    return latest


def _rank_candidates(
    company: Company,
    candidates: list[dict[str, Any]],
    revenues: dict[UUID, float],
    limit: int,
) -> list[dict[str, Any]]:
    target_revenue = revenues.get(company.id)
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        candidate = item["company"]
        similarity = float(item["similarity"])
        candidate_revenue = revenues.get(candidate.id)
        size_similarity: float | None = None
        if target_revenue and candidate_revenue:
            log_gap = abs(math.log10(candidate_revenue / target_revenue))
            size_similarity = max(0.0, 1.0 - min(log_gap, 2.0) / 2.0)
            score = 0.78 * similarity + 0.22 * size_similarity
        else:
            score = similarity

        reason = "Similar reported business activity"
        if _is_classified(company.industry) and candidate.industry == company.industry:
            reason = f"Same {company.industry} industry"
        elif _is_classified(company.sector) and candidate.sector == company.sector:
            reason = f"Same {company.sector} sector"
        if size_similarity is not None and size_similarity >= 0.7:
            reason += " · comparable reported revenue"

        ranked.append(
            {
                **item,
                "selection_score": score,
                "selection_reason": reason,
            }
        )
    ranked.sort(key=lambda item: item["selection_score"], reverse=True)
    return ranked[:limit]


def _derived_metrics(ratios: dict[str, Any]) -> dict[str, float | None]:
    price = ratios.get("current_price")
    high = ratios.get("fifty_two_week_high")
    volume = ratios.get("volume")
    average_volume = ratios.get("average_volume")

    price_vs_high = None
    if isinstance(price, (int, float)) and isinstance(high, (int, float)) and high > 0:
        price_vs_high = (price / high - 1) * 100
    relative_volume = None
    if (
        isinstance(volume, (int, float))
        and isinstance(average_volume, (int, float))
        and average_volume > 0
    ):
        relative_volume = volume / average_volume

    direct_keys = (
        "market_cap",
        "trailing_pe",
        "price_to_book",
        "revenue_growth_percent",
        "earnings_growth_percent",
        "profit_margin_percent",
        "operating_margin_percent",
        "return_on_equity_percent",
        "debt_to_equity_percent",
        "current_ratio",
        "beta",
    )
    metrics = {key: ratios.get(key) for key in direct_keys}
    metrics["price_vs_52w_high_percent"] = price_vs_high
    metrics["relative_volume"] = relative_volume
    return metrics


def _favourability_percentiles(
    companies: list[dict[str, Any]],
) -> None:
    for definition in METRIC_DEFINITIONS:
        key = definition["key"]
        direction = definition["higher_is_better"]
        requires_positive_value = key in {
            "trailing_pe",
            "price_to_book",
            "debt_to_equity_percent",
            "current_ratio",
        }
        values = [
            float(company["metrics"][key])
            for company in companies
            if company["metrics"].get(key) is not None
            and (
                not requires_positive_value
                or float(company["metrics"][key]) > 0
            )
        ]
        for company in companies:
            company["percentiles"][key] = None
            raw = company["metrics"].get(key)
            if (
                direction is None
                or raw is None
                or len(values) < 3
                or (requires_positive_value and float(raw) <= 0)
            ):
                continue
            value = float(raw)
            less = sum(1 for candidate in values if candidate < value)
            greater = sum(1 for candidate in values if candidate > value)
            equal_others = len(values) - less - greater - 1
            favourable = less if direction else greater
            percentile = 100 * (favourable + max(equal_others, 0) / 2) / (len(values) - 1)
            company["percentiles"][key] = round(max(0.0, min(100.0, percentile)), 1)


async def _fetch_ratios(company: Company) -> tuple[dict[str, Any], str | None]:
    market_data_ticker = company.market_data_ticker or f"{company.ticker}.NS"
    try:
        ratios = await asyncio.wait_for(
            get_trading_ratios(company.ticker, market_data_ticker),
            timeout=25,
        )
        return ratios, None
    except Exception as exc:
        return {
            "ticker": company.ticker,
            "currency": company.reporting_currency,
            "source": "unavailable",
            "source_url": "",
            "retrieved_at": datetime.now(UTC).isoformat(),
        }, f"{company.ticker}: comparison metrics were unavailable ({type(exc).__name__})."


async def build_peer_comparison(
    db: AsyncSession,
    company: Company,
    *,
    peer_symbols: list[str] | None = None,
    limit: int = AUTO_PEER_LIMIT,
) -> dict[str, Any]:
    """Build a subject-plus-peers comparison.

    ``peer_symbols=None`` requests automatic discovery. Supplying a list,
    including an empty list, requests an exact manual comparison.
    """

    limit = max(1, min(limit, MAX_COMPARISON_COMPANIES - 1))
    discovery_label = company.industry
    method = "Manual peer selection"
    ranked: list[dict[str, Any]] = []

    if peer_symbols is None:
        candidates, discovery_label = await _classified_candidates(db, company)
        if candidates:
            method = "Industry classification + reported revenue proximity"
        else:
            candidates, discovery_label = await _semantic_candidates(db, company)
            method = "Annual-report business similarity + reported revenue proximity"

        candidate_ids = [company.id, *(item["company"].id for item in candidates)]
        revenues = await _latest_revenues(db, candidate_ids)
        ranked = _rank_candidates(company, candidates, revenues, limit)
        peers = [item["company"] for item in ranked]
    else:
        normalized = list(
            dict.fromkeys(
                symbol.strip().upper()
                for symbol in peer_symbols
                if symbol.strip() and symbol.strip().upper() != company.ticker
            )
        )[: MAX_COMPARISON_COMPANIES - 1]
        rows = (
            (
                await db.execute(
                    select(Company)
                    .where(Company.country == company.country)
                    .where(Company.ticker.in_(normalized))
                )
            )
            .scalars()
            .all()
        )
        by_ticker = {row.ticker: row for row in rows}
        peers = [by_ticker[symbol] for symbol in normalized if symbol in by_ticker]
        ranked = [
            {
                "company": peer,
                "similarity": None,
                "selection_reason": "Added manually",
            }
            for peer in peers
        ]

    comparison_companies = [company, *peers]
    ratio_results = await asyncio.gather(
        *(_fetch_ratios(item) for item in comparison_companies)
    )

    rank_by_id = {item["company"].id: item for item in ranked}
    output_companies: list[dict[str, Any]] = []
    limitations: list[str] = []
    retrieved_times: list[str] = []
    for index, (candidate, (ratios, error)) in enumerate(
        zip(comparison_companies, ratio_results, strict=True)
    ):
        if error:
            limitations.append(error)
        if ratios.get("retrieved_at"):
            retrieved_times.append(str(ratios["retrieved_at"]))
        metrics = _derived_metrics(ratios)
        available = sum(value is not None for value in metrics.values())
        rank_info = rank_by_id.get(candidate.id, {})
        output_companies.append(
            {
                "ticker": candidate.ticker,
                "name": candidate.name,
                "sector": candidate.sector,
                "industry": candidate.industry,
                "currency": ratios.get("currency") or candidate.reporting_currency,
                "is_subject": index == 0,
                "selection_reason": (
                    "Selected company"
                    if index == 0
                    else rank_info.get("selection_reason", "Comparable company")
                ),
                "similarity_percent": (
                    round(float(rank_info["similarity"]) * 100, 1)
                    if rank_info.get("similarity") is not None
                    else None
                ),
                "data_completeness_percent": round(
                    available / len(METRIC_DEFINITIONS) * 100,
                    1,
                ),
                "metrics": metrics,
                "percentiles": {},
                "source": ratios.get("source") or "unavailable",
                "source_url": ratios.get("source_url") or None,
                "retrieved_at": ratios.get("retrieved_at"),
            }
        )

    _favourability_percentiles(output_companies)
    subject = output_companies[0]
    favourable_metrics = sorted(
        (
            (percentile, definition["label"])
            for definition in METRIC_DEFINITIONS
            if (percentile := subject["percentiles"].get(definition["key"])) is not None
        ),
        reverse=True,
    )

    if not peers:
        limitations.append("No peer companies were selected for comparison.")
    if any(item["data_completeness_percent"] < 50 for item in output_companies):
        limitations.append(
            "Some companies have limited ratio coverage; unavailable values are excluded from ranks."
        )

    return {
        "ticker": company.ticker,
        "peer_group_label": discovery_label or "Business-activity peers",
        "selection_method": method,
        "is_manual": peer_symbols is not None,
        "metric_definitions": METRIC_DEFINITIONS,
        "companies": output_companies,
        "subject_strengths": [label for _, label in favourable_metrics[:3] if _ >= 67],
        "subject_watch_items": [
            label for percentile, label in reversed(favourable_metrics) if percentile <= 33
        ][:3],
        "source": "Yahoo Finance delayed ratios + cached annual-report evidence",
        "data_as_of": max(retrieved_times) if retrieved_times else datetime.now(UTC).isoformat(),
        "limitations": list(dict.fromkeys(limitations)),
    }
