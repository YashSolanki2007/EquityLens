"""Grounded, company-scoped chat over financial, market, options, and news data."""

from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.llm import (
    generate_structured,
    get_company_chat_provider,
)
from app.models import Company, CompanyCard
from app.prompts.company_chat import (
    COMPANY_CHAT_PLAN_SYSTEM,
    COMPANY_CHAT_PLAN_USER,
    COMPANY_CHAT_SYSTEM,
    COMPANY_CHAT_USER,
)
from app.schemas.api import CitationOut
from app.schemas.company import (
    CompanyChatRequest,
    CompanyChatResponse,
    FinancialOverviewOut,
)
from app.services.company_financials import get_financial_overview
from app.services.ingestion import refresh_india_financial_facts
from app.services.market_data.forecasting import get_price_forecast
from app.services.market_data.india_trading import get_options_chain, get_trading_ratios
from app.services.research.deep_research import (
    is_price_move_research_question,
    research_company_page_deeply,
)
from app.services.research.news import TavilyNewsClient
from app.services.technical_scanner import (
    calculate_technical_snapshot,
    get_candle_fetcher,
)

Intent = Literal[
    "company_facts",
    "ratios",
    "technical",
    "options",
    "deep_research",
    "decision_support",
    "out_of_scope",
]

CITATION_RE = re.compile(r"\[(\d+)\]")


class CompanyChatPlan(BaseModel):
    intent: Intent
    needs_cards: bool = False
    needs_financials: bool = False
    needs_ratios: bool = False
    needs_technical: bool = False
    needs_options: bool = False
    needs_forecast: bool = False
    needs_news: bool = False
    technical_interval: Literal["15m", "1d"] = "1d"


@dataclass
class Evidence:
    label: str
    payload: dict | list | str
    citation: CitationOut | None = None
    related_citations: list[CitationOut] = field(default_factory=list)

    def render(self, index: int) -> str:
        if isinstance(self.payload, str):
            body = self.payload
        else:
            body = json.dumps(self.payload, default=str, ensure_ascii=False)
        return f"[{index}] {self.label}\n{body}"


def _heuristic_plan(question: str) -> CompanyChatPlan:
    text = question.lower()
    if is_price_move_research_question(question):
        return CompanyChatPlan(intent="deep_research", needs_cards=True, needs_news=True)
    decision = bool(
        re.search(r"\b(buy|sell|hold|invest|outlook|confidence|bullish|bearish)\b", text)
    )
    news = bool(
        re.search(
            r"\b(latest|recent|news|catalyst|regulation|geopolit|current event|deep research)\b",
            text,
        )
    )
    options = bool(
        re.search(r"\b(option|open interest|\boi\b|pcr|delta|gamma|theta|iv|strike|expiry)\b", text)
    )
    technical = bool(
        re.search(r"\b(rsi|macd|ema|vwap|momentum|technical|bollinger|atr|volume)\b", text)
    )
    ratios = bool(
        re.search(r"\b(ratio|p/?e|price.to.book|valuation|margin|roe|debt|eps)\b", text)
    )
    if decision:
        return CompanyChatPlan(
            intent="decision_support",
            needs_cards=True,
            needs_financials=True,
            needs_ratios=True,
            needs_technical=True,
            needs_options=True,
            needs_forecast=True,
            needs_news=news,
            technical_interval="15m" if "intraday" in text else "1d",
        )
    if news:
        return CompanyChatPlan(intent="deep_research", needs_cards=True, needs_news=True)
    if options:
        return CompanyChatPlan(intent="options", needs_options=True, needs_technical=technical)
    if technical:
        return CompanyChatPlan(
            intent="technical",
            needs_technical=True,
            technical_interval="15m" if "intraday" in text else "1d",
        )
    if ratios:
        return CompanyChatPlan(
            intent="ratios", needs_ratios=True, needs_financials=True
        )
    return CompanyChatPlan(
        intent="company_facts", needs_cards=True, needs_financials=True
    )


def _normalize_plan(plan: CompanyChatPlan, question: str) -> CompanyChatPlan:
    """Apply an exact retrieval budget after model classification."""

    interval = "15m" if re.search(r"\bintraday\b", question, re.IGNORECASE) else plan.technical_interval
    asks_options = bool(
        re.search(
            r"\b(option|open interest|\boi\b|pcr|delta|gamma|theta|iv|strike|expiry)\b",
            question,
            re.IGNORECASE,
        )
    )
    asks_technical = bool(
        re.search(
            r"\b(rsi|macd|ema|vwap|momentum|technical|bollinger|atr|volume)\b",
            question,
            re.IGNORECASE,
        )
    )
    asks_news = bool(
        re.search(
            r"\b(latest|recent|news|catalyst|regulation|geopolit|current event|deep research)\b",
            question,
            re.IGNORECASE,
        )
    )
    if is_price_move_research_question(question):
        return CompanyChatPlan(intent="deep_research", needs_cards=True, needs_news=True)
    if plan.intent == "decision_support":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_cards=True,
            needs_financials=True,
            needs_ratios=True,
            needs_technical=True,
            needs_options=True,
            needs_forecast=True,
            needs_news=asks_news,
            technical_interval=interval,
        )
    if plan.intent == "deep_research":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_cards=True,
            needs_news=True,
        )
    if plan.intent == "ratios":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_financials=True,
            needs_ratios=True,
        )
    if plan.intent == "technical":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_technical=True,
            needs_options=asks_options,
            technical_interval=interval,
        )
    if plan.intent == "options":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_options=True,
            needs_technical=asks_technical,
            technical_interval=interval,
        )
    if plan.intent == "company_facts":
        return CompanyChatPlan(
            intent=plan.intent,
            needs_cards=True,
            needs_financials=True,
        )
    return CompanyChatPlan(intent="out_of_scope")


async def _plan(company: Company, question: str) -> CompanyChatPlan:
    try:
        plan = await generate_structured(
            CompanyChatPlan,
            [
                {"role": "system", "content": COMPANY_CHAT_PLAN_SYSTEM},
                {
                    "role": "user",
                    "content": COMPANY_CHAT_PLAN_USER.format(
                        company_name=company.name,
                        ticker=company.ticker,
                        exchange=company.exchange,
                        sector=company.sector,
                        industry=company.industry,
                        question=question,
                    ),
                },
            ],
            temperature=0,
        )
    except Exception:
        return _heuristic_plan(question)
    return _normalize_plan(plan, question)


async def _overview(db: AsyncSession, company: Company) -> FinancialOverviewOut:
    overview = await get_financial_overview(
        db,
        ticker=company.ticker,
        cik=company.cik,
        company_id=company.id,
        country=company.country,
        currency=company.reporting_currency,
        market_data_ticker=company.market_data_ticker,
    )
    if company.country == "IN" and not overview.annual and not overview.quarterly:
        if await refresh_india_financial_facts(db, company):
            overview = await get_financial_overview(
                db,
                ticker=company.ticker,
                cik=company.cik,
                company_id=company.id,
                country=company.country,
                currency=company.reporting_currency,
                market_data_ticker=company.market_data_ticker,
            )
    return overview


async def _cards(db: AsyncSession, company: Company) -> list[CompanyCard]:
    return list(
        (
            await db.execute(
                select(CompanyCard)
                .where(CompanyCard.company_id == company.id)
                .order_by(desc(CompanyCard.confidence), desc(CompanyCard.filing_date))
                .limit(12)
            )
        )
        .scalars()
        .all()
    )


def _card_payload(cards: list[CompanyCard]) -> list[dict]:
    return [
        {
            "id": str(card.id),
            "type": card.card_type,
            "text": card.text,
            "directness": card.directness,
            "materiality": card.materiality,
            "filing_date": card.filing_date,
        }
        for card in cards[:10]
    ]


def _derived_ratios(overview: FinancialOverviewOut, ratios: dict | None) -> dict:
    derived: dict[str, float | str | None] = {}
    annual = [point for point in overview.annual if point.revenue is not None]
    if len(annual) >= 2:
        first, latest = annual[0], annual[-1]
        years = max(1.0, (datetime.fromisoformat(latest.end_date) - datetime.fromisoformat(first.end_date)).days / 365.25)
        if first.revenue and first.revenue > 0 and latest.revenue is not None:
            derived["revenue_cagr_percent"] = round(
                ((latest.revenue / first.revenue) ** (1 / years) - 1) * 100, 2
            )
    latest = annual[-1] if annual else None
    if latest:
        derived["latest_annual_net_margin_percent"] = latest.net_margin_percent
        derived["latest_annual_revenue_yoy_percent"] = latest.revenue_yoy_percent
        derived["latest_annual_net_income_yoy_percent"] = latest.net_income_yoy_percent
    if ratios:
        low = ratios.get("fifty_two_week_low")
        high = ratios.get("fifty_two_week_high")
        price = ratios.get("current_price")
        if all(value is not None for value in (low, high, price)) and high > low:
            derived["price_position_in_52_week_range_percent"] = round(
                (price - low) / (high - low) * 100, 2
            )
    return derived


def _compact_options(chain: dict) -> dict:
    if not chain.get("available"):
        return {
            "available": False,
            "limitation": chain.get("limitation"),
            "source_url": chain.get("source_url"),
        }
    summary = chain.get("scanner_summary") or {}
    strikes = chain.get("strikes") or []

    def most_active(side: str) -> list[dict]:
        ranked = sorted(
            (
                {
                    "strike": row.get("strike_price"),
                    "open_interest": (row.get(side) or {}).get("open_interest"),
                    "oi_change_percent": (row.get(side) or {}).get(
                        "percent_change_in_open_interest"
                    ),
                    "delta": (row.get(side) or {}).get("delta"),
                    "gamma": (row.get(side) or {}).get("gamma"),
                    "iv_percent": (row.get(side) or {}).get("implied_volatility"),
                }
                for row in strikes
                if row.get(side)
            ),
            key=lambda row: row.get("open_interest") or 0,
            reverse=True,
        )
        return ranked[:3]

    return {
        "available": True,
        "expiry": chain.get("selected_expiry"),
        "underlying_value": chain.get("underlying_value"),
        "aggregate_call_oi_change_percent": summary.get("call_oi_change_percent"),
        "aggregate_put_oi_change_percent": summary.get("put_oi_change_percent"),
        "put_call_oi_ratio": summary.get("put_call_oi_ratio"),
        "distribution": chain.get("distribution"),
        "most_active_calls": most_active("call"),
        "most_active_puts": most_active("put"),
        "limitation": chain.get("limitation"),
    }


async def _technical(company: Company, interval: str) -> dict:
    fetcher = get_candle_fetcher()
    try:
        candles = await fetcher.fetch(company, interval, 70)
        return calculate_technical_snapshot(
            company,
            candles,
            fetcher.source_name,
            interval=interval,
            limit=70,
        )
    finally:
        closer = getattr(fetcher, "aclose", None)
        if closer:
            await closer()


def _compact_technical(snapshot: dict) -> dict:
    return {
        "timeframe": (
            "daily, 70 trading candles"
            if snapshot.get("candle_interval") == "1d"
            else "15-minute, 70 candles"
        ),
        "as_of": snapshot.get("candle_time"),
        "price": snapshot.get("price"),
        "rsi_14": snapshot.get("rsi_14"),
        "macd_histogram": snapshot.get("macd_histogram"),
        "price_vs_vwap_percent": snapshot.get("price_vs_vwap_percent"),
        "ema_9_vs_ema_21_percent": snapshot.get("ema_9_vs_ema_21_percent"),
        "momentum_returns_percent": {
            "5_candles": snapshot.get("return_5c_percent"),
            "15_candles": snapshot.get("return_15c_percent"),
            "60_candles": snapshot.get("return_60c_percent"),
        },
        "relative_volume": snapshot.get("relative_volume"),
        "atr_percent": snapshot.get("atr_percent"),
        "bollinger_position_percent": snapshot.get("bollinger_position_percent"),
        "source": snapshot.get("source"),
        "source_url": snapshot.get("source_url"),
        "is_delayed_or_unverified": snapshot.get("is_delayed_or_unverified"),
    }


def _forecast_summary(forecast: dict) -> dict:
    if not forecast.get("available"):
        return {
            "available": False,
            "observations": forecast.get("observations"),
            "limitations": forecast.get("limitations"),
        }
    points = forecast.get("points") or []
    short = points[min(4, len(points) - 1)] if points else None
    regression_points = forecast.get("regression_points") or []
    short_regression = (
        regression_points[min(4, len(regression_points) - 1)]
        if regression_points
        else None
    )
    return {
        "available": True,
        "model": forecast.get("model")
        or "ARIMA drift + GARCH volatility + Monte Carlo",
        "last_price": forecast.get("last_price"),
        "short_term_5_session": short,
        "medium_term_60_session": {
            "median": forecast.get("median_terminal_price"),
            "range_80_low": forecast.get("terminal_range_80_low"),
            "range_80_high": forecast.get("terminal_range_80_high"),
            "probability_finish_above_last": forecast.get(
                "probability_finish_above_last"
            ),
        },
        "annualized_arima_drift_percent": forecast.get(
            "annualized_arima_drift_percent"
        ),
        "current_annualized_volatility_percent": forecast.get(
            "current_annualized_volatility_percent"
        ),
        "long_run_annualized_volatility_percent": forecast.get(
            "long_run_annualized_volatility_percent"
        ),
        "garch_alpha1": forecast.get("garch_alpha1"),
        "garch_beta1": forecast.get("garch_beta1"),
        "multiple_regression": {
            "available": forecast.get("regression_available", False),
            "model": forecast.get("regression_model"),
            "terminal_price": forecast.get("regression_terminal_price"),
            "terminal_return_percent": forecast.get(
                "regression_terminal_return_percent"
            ),
            "five_session": short_regression,
            "validation_r_squared": forecast.get(
                "regression_validation_r_squared"
            ),
            "validation_mae_percent": forecast.get(
                "regression_validation_mae_percent"
            ),
            "standardized_coefficients": forecast.get(
                "regression_standardized_coefficients"
            )
            or {},
        },
        "limitations": forecast.get("limitations"),
    }


def _sign(value: float | None, threshold: float = 0) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return 1.0 if value > threshold else -1.0 if value < threshold else 0.0


def _mean(values: list[float | None]) -> float | None:
    valid = [float(value) for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


def _view(score: float | None) -> Literal["positive", "mixed", "negative", "unavailable"]:
    if score is None:
        return "unavailable"
    if score >= 0.2:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "mixed"


def _decision_assessment(
    technical: dict | None,
    ratios: dict | None,
    forecast: dict | None,
    options: dict | None,
    financial_available: bool,
) -> dict:
    technical_score = None
    if technical:
        rsi = technical.get("rsi_14")
        momentum = technical.get("momentum_returns_percent") or {}
        rsi_signal = 1.0 if rsi is not None and rsi > 55 else -1.0 if rsi is not None and rsi < 45 else 0.0
        technical_score = _mean(
            [
                rsi_signal,
                _sign(technical.get("macd_histogram")),
                _sign(technical.get("price_vs_vwap_percent")),
                _sign(technical.get("ema_9_vs_ema_21_percent")),
                _sign(
                    technical.get("return_5c_percent")
                    if technical.get("return_5c_percent") is not None
                    else momentum.get("5_candles")
                ),
            ]
        )

    short_arima = medium_arima = None
    short_regression = medium_regression = None
    if forecast and forecast.get("available") and forecast.get("last_price"):
        last = float(forecast["last_price"])
        short_point = forecast.get("short_term_5_session") or {}
        short_median = short_point.get("median")
        terminal = (forecast.get("medium_term_60_session") or {}).get("median")
        if short_median is not None:
            short_arima = max(-1.0, min(1.0, (short_median / last - 1) / 0.05))
        if terminal is not None:
            medium_arima = max(-1.0, min(1.0, (terminal / last - 1) / 0.15))
        regression = forecast.get("multiple_regression") or {}
        short_return = (regression.get("five_session") or {}).get(
            "predicted_return_percent"
        )
        medium_return = regression.get("terminal_return_percent")
        regression_r_squared = regression.get("validation_r_squared")
        if regression_r_squared is None or float(regression_r_squared) <= 0:
            short_return = None
            medium_return = None
        if short_return is not None or medium_return is not None:
            if short_return is not None:
                short_regression = max(
                    -1.0,
                    min(1.0, float(short_return) / 5),
                )
            if medium_return is not None:
                medium_regression = max(
                    -1.0,
                    min(1.0, float(medium_return) / 15),
                )
    short_forecast = _mean([short_arima, short_regression])
    medium_forecast = _mean([medium_arima, medium_regression])

    options_score = None
    if options and options.get("available"):
        probability = (options.get("distribution") or {}).get("probability_above_spot")
        if probability is not None:
            options_score = max(-1.0, min(1.0, (float(probability) - 0.5) * 2))

    financial_score = None
    if ratios and financial_available:
        growth = ratios.get("revenue_growth_percent")
        financial_score = _mean(
            [
                _sign(ratios.get("profit_margin_percent")),
                _sign(growth),
                _sign(ratios.get("earnings_growth_percent")),
                (
                    1.0
                    if ratios.get("debt_to_equity_percent") is not None
                    and ratios["debt_to_equity_percent"] < 100
                    else -1.0
                    if ratios.get("debt_to_equity_percent") is not None
                    else None
                ),
            ]
        )

    short_score = _mean([technical_score, short_forecast, options_score])
    medium_score = _mean([technical_score, medium_forecast, financial_score])
    available_components = sum(
        value is not None
        for value in (
            technical_score,
            short_forecast,
            options_score,
            medium_forecast,
            financial_score,
        )
    )
    combined = _mean([short_score, medium_score])
    confidence = round(
        min(
            90,
            20
            + 12 * available_components
            + 10 * abs(combined or 0),
        )
    )
    return {
        "method": "deterministic signal coverage and directional agreement",
        "short_term_view": _view(short_score),
        "medium_term_view": _view(medium_score) if financial_available else "unavailable",
        "confidence_percent": confidence,
        "confidence_label": "high" if confidence >= 75 else "medium" if confidence >= 50 else "low",
        "component_views": {
            "technical": _view(technical_score),
            "short_forecast": _view(short_forecast),
            "options": _view(options_score),
            "medium_forecast": _view(medium_forecast),
            "financial": _view(financial_score),
        },
        "financial_history_adequate_for_long_term": financial_available,
        "long_term_rule": (
            "SUPPORTED: comparable financial history is present; discuss it with its limitations."
            if financial_available
            else "UNSUPPORTED: do not provide a long-term assessment because comparable financial history is missing."
        ),
    }


def _history_text(request: CompanyChatRequest) -> str:
    if not request.history:
        return "No earlier turns."
    return "\n".join(
        f"{turn.role}: {turn.content}" for turn in request.history[-6:]
    )


async def answer_company_question(
    db: AsyncSession,
    company: Company,
    request: CompanyChatRequest,
) -> CompanyChatResponse:
    plan = await _plan(company, request.message)
    provider = get_company_chat_provider()
    limitations: list[str] = []
    data_used: list[str] = []
    evidence: list[Evidence] = []

    if plan.intent == "out_of_scope":
        return CompanyChatResponse(
            ticker=company.ticker,
            intent=plan.intent,
            answer=(
                f"This chat is limited to research about {company.name} "
                f"({company.ticker}). Ask about its business, financials, ratios, "
                "technicals, options, forecasts, filings, or recent developments."
            ),
            model_name=provider.model_name,
            generated_at=datetime.now(UTC),
        )

    if plan.intent == "deep_research":
        research = await research_company_page_deeply(
            db,
            company,
            request.message,
            conversation_context=_history_text(request),
        )
        source_types = list(
            dict.fromkeys(citation.source_type for citation in research.citations)
        )
        return CompanyChatResponse(
            ticker=company.ticker,
            intent=plan.intent,
            answer=research.answer,
            citations=[
                citation.model_dump(mode="json") for citation in research.citations
            ],
            limitations=list(dict.fromkeys(research.limitations)),
            data_used=[
                "multi-angle company catalyst research",
                *source_types,
            ],
            model_name=get_company_chat_provider(reasoning=True).model_name,
            generated_at=datetime.now(UTC),
        )

    cards: list[CompanyCard] = []
    overview: FinancialOverviewOut | None = None
    if plan.needs_cards:
        cards = await _cards(db, company)
        if cards:
            data_used.append("verified filing cards")
            for card in cards[:8]:
                evidence.append(
                    Evidence(
                        f"Verified filing card: {card.card_type}",
                        {
                            "text": card.text,
                            "directness": card.directness,
                            "materiality": card.materiality,
                            "filing_date": card.filing_date,
                        },
                        CitationOut(
                            source_type="company_card",
                            url=card.source_url,
                            accession=card.source_filing_accession,
                            description=f"Verified {card.card_type} filing card",
                            excerpt=card.source_excerpt[:600],
                            filing_date=card.filing_date,
                        ),
                    )
                )
        else:
            limitations.append("No verified company cards are available.")

    if plan.needs_financials:
        overview = await _overview(db, company)
        if overview.annual or overview.quarterly:
            data_used.append("normalized financial history")
            evidence.append(
                Evidence(
                    "Normalized financial history and calculated growth/margins",
                    overview.model_dump(mode="json", exclude={"source_url", "limitations"}),
                    CitationOut(
                        source_type="financial_statements",
                        url=overview.source_url,
                        description="Normalized reported financial statements",
                    ),
                )
            )
        else:
            limitations.extend(overview.limitations)

    market_ticker = company.market_data_ticker or (
        f"{company.ticker}.NS" if company.country == "IN" else company.ticker
    )
    ratios = technical = options = forecast = None
    external_jobs: dict[str, asyncio.Task] = {}
    if plan.needs_ratios and company.country == "IN":
        external_jobs["ratios"] = asyncio.create_task(
            get_trading_ratios(company.ticker, market_ticker)
        )
    if plan.needs_technical and company.country == "IN":
        external_jobs["technical"] = asyncio.create_task(
            _technical(company, plan.technical_interval)
        )
    if plan.needs_options and company.country == "IN":
        symbol = market_ticker.removesuffix(".NS").removesuffix(".BO")
        external_jobs["options"] = asyncio.create_task(
            get_options_chain(company.ticker, symbol)
        )
    if plan.needs_forecast:
        external_jobs["forecast"] = asyncio.create_task(
            get_price_forecast(
                company.ticker,
                market_ticker,
                horizon_days=60,
                simulations=2_000,
            )
        )

    for name, job in external_jobs.items():
        try:
            value = await job
        except Exception as exc:
            limitations.append(f"{name.capitalize()} data was unavailable: {exc}")
            continue
        if name == "ratios":
            ratios = value
            data_used.append("Yahoo valuation and trading ratios")
            evidence.append(
                Evidence(
                    "Reported market ratios plus deterministic derived ratios",
                    {
                        "reported_ratios": {
                            key: val
                            for key, val in ratios.items()
                            if key
                            not in {
                                "ticker",
                                "market_data_ticker",
                                "source_url",
                                "retrieved_at",
                            }
                        },
                        "calculated_ratios": _derived_ratios(
                            overview
                            or FinancialOverviewOut(
                                ticker=company.ticker,
                                source_url=ratios["source_url"],
                            ),
                            ratios,
                        ),
                    },
                    CitationOut(
                        source_type="market_data",
                        url=ratios["source_url"],
                        description="Yahoo Finance reported ratios",
                    ),
                )
            )
        elif name == "technical":
            technical = _compact_technical(value)
            data_used.append(f"{plan.technical_interval} technical indicators")
            evidence.append(
                Evidence(
                    f"Calculated technical indicators ({plan.technical_interval}, 70 candles)",
                    technical,
                    CitationOut(
                        source_type="market_data",
                        url=technical["source_url"],
                        description="Historical candles used for technical calculations",
                    ),
                )
            )
        elif name == "options":
            options = _compact_options(value)
            if options.get("available"):
                data_used.append("NSE nearest-expiry option chain")
            else:
                limitations.append(
                    options.get("limitation")
                    or "No listed NSE option chain is available for this company."
                )
            evidence.append(
                Evidence(
                    "Nearest-expiry NSE options summary",
                    options,
                    CitationOut(
                        source_type="options_data",
                        url=value["source_url"],
                        description="NSE option-chain data with modeled Greeks",
                    ),
                )
            )
        elif name == "forecast":
            forecast = _forecast_summary(value)
            if forecast.get("available"):
                data_used.append("ARIMA-GARCH Monte Carlo scenarios")
            else:
                limitations.extend(forecast.get("limitations") or [])
            evidence.append(
                Evidence(
                    "ARIMA-GARCH Monte Carlo statistical scenarios",
                    forecast,
                    CitationOut(
                        source_type="market_data",
                        url=value["source_url"],
                        description="Historical prices used by the statistical forecast",
                    ),
                )
            )

    if plan.needs_news:
        settings = get_settings()
        news_client = TavilyNewsClient()
        try:
            if not news_client.configured:
                limitations.append(
                    "Current-news research is unavailable because Tavily is not configured."
                )
            else:
                news = await news_client.search(
                    f"{company.name} {company.ticker} {request.message}"[:500],
                    lookback_days=settings.deep_research_lookback_days,
                    max_results=settings.deep_research_max_news_results,
                )
                if news:
                    data_used.append("Tavily current-news research")
                    for source in news:
                        evidence.append(
                            Evidence(
                                "Current-news result",
                                {
                                    "title": source.title,
                                    "published_date": source.published_date,
                                    "excerpt": source.excerpt,
                                },
                                CitationOut(
                                    source_type="news",
                                    url=source.url,
                                    description=source.title,
                                    excerpt=source.excerpt[:600],
                                    filing_date=source.published_date,
                                ),
                            )
                        )
                else:
                    limitations.append(
                        "Tavily returned no usable current-news results for this company."
                    )
        except Exception as exc:
            limitations.append(f"Current-news research was unavailable: {exc}")
        finally:
            await news_client.aclose()

    financial_available = bool(
        overview
        and (
            len(overview.annual) >= 2
            or len(overview.quarterly) >= 4
        )
    )
    assessment = (
        _decision_assessment(
            technical,
            ratios,
            forecast,
            options,
            financial_available,
        )
        if plan.intent == "decision_support"
        else {}
    )
    if plan.intent == "decision_support" and not financial_available:
        limitations.append(
            "Long-term assessment unavailable because adequate comparable financial history is missing."
        )

    rendered = "\n\n".join(
        item.render(index) for index, item in enumerate(evidence, start=1)
    )
    if not rendered:
        rendered = "[1] Availability\nNo verified data was retrieved for this question."

    answer = await provider.chat(
        [
            {"role": "system", "content": COMPANY_CHAT_SYSTEM},
            {
                "role": "user",
                "content": COMPANY_CHAT_USER.format(
                    company_name=company.name,
                    ticker=company.ticker,
                    question=request.message,
                    history=_history_text(request),
                    assessment=json.dumps(assessment, default=str),
                    evidence=rendered,
                    limitations=json.dumps(list(dict.fromkeys(limitations))),
                ),
            },
        ],
        temperature=0.1,
        max_tokens=2_800,
    )

    cited: list[CitationOut] = []
    seen: set[str] = set()
    for match in CITATION_RE.findall(answer):
        index = int(match)
        if not 1 <= index <= len(evidence):
            continue
        item = evidence[index - 1]
        candidates = [
            *([item.citation] if item.citation else []),
            *item.related_citations,
        ]
        for citation in candidates:
            key = f"{citation.source_type}:{citation.url}"
            if key not in seen:
                seen.add(key)
                cited.append(citation)
    if not cited:
        for item in evidence:
            candidates = [
                *([item.citation] if item.citation else []),
                *item.related_citations,
            ]
            for citation in candidates:
                key = f"{citation.source_type}:{citation.url}"
                if key not in seen:
                    seen.add(key)
                    cited.append(citation)
                if len(cited) >= 6:
                    break
            if len(cited) >= 6:
                break
        if cited:
            limitations.append(
                "The model omitted inline evidence numbers; the retrieved source list is attached."
            )

    return CompanyChatResponse(
        ticker=company.ticker,
        intent=plan.intent,
        answer=answer,
        citations=[citation.model_dump(mode="json") for citation in cited],
        limitations=list(dict.fromkeys(limitations)),
        data_used=list(dict.fromkeys(data_used)),
        confidence_label=assessment.get("confidence_label"),
        confidence_percent=assessment.get("confidence_percent"),
        short_term_view=assessment.get("short_term_view"),
        medium_term_view=assessment.get("medium_term_view"),
        model_name=provider.model_name,
        generated_at=datetime.now(UTC),
    )
