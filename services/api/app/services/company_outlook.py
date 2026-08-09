"""Cached, evidence-grounded short- and medium-term company outlook."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.llm import generate_structured, get_provider
from app.models import Company
from app.prompts.company_outlook import (
    COMPANY_OUTLOOK_SYSTEM,
    COMPANY_OUTLOOK_USER,
    PROMPT_VERSION,
)
from app.schemas.company import CompanyOutlookOut, HorizonOutlook
from app.services.company_chat import _compact_technical, _technical
from app.services.market_data.forecasting import get_price_forecast
from app.services.research.news import NewsSource, TavilyNewsClient

Direction = Literal["positive", "mixed", "negative", "unavailable"]

OUTLOOK_TTL_SECONDS = 60 * 60
OUTLOOK_SIMULATIONS = 2_000
GENERIC_COMPANY_WORDS = {
    "and",
    "company",
    "corporation",
    "development",
    "enterprises",
    "holdings",
    "industries",
    "industry",
    "infrastructure",
    "international",
    "limited",
    "services",
    "solutions",
    "technologies",
}


class OutlookNarrative(BaseModel):
    short_term_summary: str = Field(min_length=20, max_length=420)
    medium_term_summary: str = Field(min_length=20, max_length=420)


def _finite(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _signal(value: object, threshold: float = 0.0) -> float | None:
    parsed = _finite(value)
    if parsed is None:
        return None
    if parsed > threshold:
        return 1.0
    if parsed < -threshold:
        return -1.0
    return 0.0


def _mean(values: list[float | None]) -> float | None:
    valid = [value for value in values if value is not None]
    return sum(valid) / len(valid) if valid else None


def _direction(score: float | None) -> Direction:
    if score is None:
        return "unavailable"
    if score >= 0.22:
        return "positive"
    if score <= -0.22:
        return "negative"
    return "mixed"


def _forecast_return(forecast: dict, index: int) -> float | None:
    last_price = _finite(forecast.get("last_price"))
    points = forecast.get("points") or []
    if not last_price or not points:
        return None
    point = points[min(index, len(points) - 1)]
    median = _finite(point.get("median"))
    if median is None:
        return None
    return (median / last_price - 1) * 100


def _regression_return(forecast: dict, index: int) -> float | None:
    points = forecast.get("regression_points") or []
    if not forecast.get("regression_available") or not points:
        return None
    point = points[min(index, len(points) - 1)]
    return _finite(point.get("predicted_return_percent"))


def _assess_directions(
    technical: dict | None,
    forecast: dict | None,
) -> tuple[Direction, Direction, int, Literal["high", "medium", "low"]]:
    rsi = _finite((technical or {}).get("rsi_14"))
    rsi_signal = (
        1.0
        if rsi is not None and rsi > 55
        else -1.0
        if rsi is not None and rsi < 45
        else 0.0
        if rsi is not None
        else None
    )
    short_forecast_return = _forecast_return(forecast or {}, 4)
    medium_forecast_return = _forecast_return(forecast or {}, 29)
    short_regression_return = _regression_return(forecast or {}, 4)
    medium_regression_return = _regression_return(forecast or {}, 29)
    regression_r_squared = _finite(
        (forecast or {}).get("regression_validation_r_squared")
    )
    if regression_r_squared is None or regression_r_squared <= 0:
        short_regression_return = None
        medium_regression_return = None
    short_score = _mean(
        [
            rsi_signal,
            _signal((technical or {}).get("macd_histogram")),
            _signal((technical or {}).get("ema_9_vs_ema_21_percent"), 0.15),
            _signal((technical or {}).get("return_5c_percent"), 0.5),
            _signal(short_forecast_return, 0.5),
            _signal(short_regression_return, 0.5),
        ]
    )
    medium_score = _mean(
        [
            _signal((technical or {}).get("ema_9_vs_ema_21_percent"), 0.15),
            _signal((technical or {}).get("return_15c_percent"), 1.0),
            _signal((technical or {}).get("return_60c_percent"), 2.0),
            _signal(medium_forecast_return, 1.0),
            _signal(medium_regression_return, 1.0),
        ]
    )

    available_inputs = sum(
        value is not None
        for value in (
            rsi_signal,
            _finite((technical or {}).get("macd_histogram")),
            _finite((technical or {}).get("ema_9_vs_ema_21_percent")),
            _finite((technical or {}).get("return_5c_percent")),
            _finite((technical or {}).get("return_15c_percent")),
            short_forecast_return,
            medium_forecast_return,
            short_regression_return,
            medium_regression_return,
        )
    )
    agreement = abs(_mean([short_score, medium_score]) or 0.0)
    confidence = round(min(88, 25 + available_inputs * 7 + agreement * 14))
    label: Literal["high", "medium", "low"] = (
        "high" if confidence >= 75 else "medium" if confidence >= 50 else "low"
    )
    return _direction(short_score), _direction(medium_score), confidence, label


def _compact_forecast(forecast: dict | None) -> dict:
    if not forecast or not forecast.get("available"):
        return {
            "available": False,
            "limitations": (forecast or {}).get("limitations") or [],
        }
    points = forecast.get("points") or []

    def point(index: int) -> dict | None:
        if not points:
            return None
        value = points[min(index, len(points) - 1)]
        return {
            "date": value.get("date"),
            "median": value.get("median"),
            "p10": value.get("p10"),
            "p90": value.get("p90"),
            "annualized_volatility_percent": value.get(
                "annualized_volatility_percent"
            ),
        }

    regression_points = forecast.get("regression_points") or []

    def regression_point(index: int) -> dict | None:
        if not forecast.get("regression_available") or not regression_points:
            return None
        value = regression_points[min(index, len(regression_points) - 1)]
        return {
            "date": value.get("date"),
            "predicted_price": value.get("predicted_price"),
            "predicted_return_percent": value.get("predicted_return_percent"),
        }

    return {
        "available": True,
        "last_price": forecast.get("last_price"),
        "five_session": point(4),
        "twenty_five_session": point(24),
        "thirty_session": point(29),
        "probability_finish_above_last_at_30_sessions": forecast.get(
            "probability_finish_above_last"
        ),
        "current_annualized_volatility_percent": forecast.get(
            "current_annualized_volatility_percent"
        ),
        "multiple_regression": {
            "available": forecast.get("regression_available", False),
            "model": forecast.get("regression_model"),
            "five_session": regression_point(4),
            "twenty_five_session": regression_point(24),
            "thirty_session": regression_point(29),
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
        "limitations": forecast.get("limitations") or [],
    }


def _compact_news(news: list[NewsSource]) -> list[dict]:
    return [
        {
            "title": source.title,
            "published_date": source.published_date,
            "excerpt": source.excerpt[:900],
        }
        for source in news[:5]
    ]


def _relevant_news(company: Company, news: list[NewsSource]) -> list[NewsSource]:
    ticker_pattern = re.compile(
        rf"(?<![A-Z0-9]){re.escape(company.ticker.upper())}(?![A-Z0-9])"
    )
    name_tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", company.name.lower())
        if len(token) >= 4 and token not in GENERIC_COMPANY_WORDS
    ]
    required_name_matches = 1 if len(name_tokens) <= 1 else 2
    relevant = []
    for source in news:
        text = f"{source.title} {source.excerpt}".lower()
        if ticker_pattern.search(text.upper()):
            relevant.append(source)
            continue
        matched = sum(
            bool(re.search(rf"\b{re.escape(token)}\b", text))
            for token in name_tokens
        )
        if name_tokens and matched >= required_name_matches:
            relevant.append(source)
    return relevant[:5]


def _clean_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:420]


def _fallback_sentence(
    horizon: str,
    direction: Direction,
    technical: dict | None,
    forecast: dict | None,
) -> str:
    rsi = _finite((technical or {}).get("rsi_14"))
    forecast_return = _forecast_return(
        forecast or {},
        4 if horizon == "3–5 days" else 29,
    )
    drivers = []
    if rsi is not None:
        drivers.append(f"daily RSI is {rsi:.1f}")
    if forecast_return is not None:
        drivers.append(
            f"the model median is {forecast_return:+.1f}% versus the last close"
        )
    evidence = " and ".join(drivers) or "the required market signals are unavailable"
    return (
        f"The {horizon} evidence is {direction}: {evidence}; this is a statistical "
        "research scenario rather than a price target."
    )


async def _get_news(company: Company) -> tuple[list[NewsSource], str | None]:
    settings = get_settings()
    client = TavilyNewsClient()
    try:
        if not client.configured:
            return [], "Current-news research is unavailable because Tavily is not configured."
        results = await client.search(
            (
                f"{company.name} {company.ticker} {company.exchange} stock "
                "latest news earnings order regulation corporate development"
            )[:500],
            lookback_days=min(60, settings.deep_research_lookback_days),
            max_results=min(5, settings.deep_research_max_news_results),
        )
        relevant = _relevant_news(company, results)
        if not relevant:
            return [], "No clearly company-specific recent news was found."
        return relevant, None
    except Exception as exc:
        return [], f"Current-news research was unavailable: {exc}"
    finally:
        await client.aclose()


async def get_company_outlook(
    db: AsyncSession,
    company: Company,
) -> CompanyOutlookOut:
    del db  # Reserved for future filing-event enrichment.
    provider = get_provider()
    market_ticker = company.market_data_ticker or (
        f"{company.ticker}.NS" if company.country == "IN" else company.ticker
    )
    cache = FileCache(get_settings().cache_path, "company_outlooks")
    key = cache_key(
        PROMPT_VERSION,
        company.ticker,
        market_ticker,
        provider.model_name,
    )
    cached = cache.get(key, OUTLOOK_TTL_SECONDS)
    if cached:
        result = CompanyOutlookOut.model_validate(cached)
        result.cached = True
        return result

    technical_result, forecast_result, news_result = await asyncio.gather(
        _technical(company, "1d"),
        get_price_forecast(
            company.ticker,
            market_ticker,
            horizon_days=30,
            simulations=OUTLOOK_SIMULATIONS,
        ),
        _get_news(company),
        return_exceptions=True,
    )

    limitations: list[str] = []
    technical: dict | None = None
    forecast: dict | None = None
    news: list[NewsSource] = []

    if isinstance(technical_result, BaseException):
        limitations.append(f"Daily technical indicators were unavailable: {technical_result}")
    else:
        technical = _compact_technical(technical_result)
    if isinstance(forecast_result, BaseException):
        limitations.append(f"The statistical forecast was unavailable: {forecast_result}")
    else:
        forecast = forecast_result
        limitations.extend(forecast.get("limitations") or [])
        limitations.extend(forecast.get("regression_limitations") or [])
    if isinstance(news_result, BaseException):
        limitations.append(f"Current-news research was unavailable: {news_result}")
    else:
        news, news_limitation = news_result
        if news_limitation:
            limitations.append(news_limitation)

    short_direction, medium_direction, confidence, confidence_label = (
        _assess_directions(technical, forecast)
    )
    evidence_available = technical is not None or (
        forecast is not None and forecast.get("available")
    )

    try:
        narrative = await generate_structured(
            OutlookNarrative,
            [
                {"role": "system", "content": COMPANY_OUTLOOK_SYSTEM},
                {
                    "role": "user",
                    "content": COMPANY_OUTLOOK_USER.format(
                        company_name=company.name,
                        ticker=company.ticker,
                        exchange=company.exchange,
                        short_direction=short_direction,
                        medium_direction=medium_direction,
                        technical=json.dumps(technical or {"available": False}, default=str),
                        forecast=json.dumps(_compact_forecast(forecast), default=str),
                        news=json.dumps(_compact_news(news), default=str),
                        limitations=json.dumps(list(dict.fromkeys(limitations))),
                    ),
                },
            ],
            provider=provider,
            temperature=0.05,
        )
        short_summary = _clean_sentence(narrative.short_term_summary)
        medium_summary = _clean_sentence(narrative.medium_term_summary)
    except Exception:
        limitations.append(
            "Llama synthesis was unavailable; the displayed wording is a deterministic signal summary."
        )
        short_summary = _fallback_sentence(
            "3–5 day", short_direction, technical, forecast
        )
        medium_summary = _fallback_sentence(
            "25–30 day", medium_direction, technical, forecast
        )

    citations: list[dict] = []
    source_url = (technical or {}).get("source_url") or (
        forecast or {}
    ).get("source_url")
    if source_url:
        citations.append(
            {
                "source_type": "market_data",
                "url": source_url,
                "description": "Historical prices used for indicators and statistical scenarios",
            }
        )
    citations.extend(
        {
            "source_type": "news",
            "url": source.url,
            "description": source.title,
            "excerpt": source.excerpt[:600],
            "filing_date": source.published_date,
        }
        for source in news[:5]
    )

    data_used = []
    if technical is not None:
        data_used.append("daily technical indicators")
    if forecast is not None and forecast.get("available"):
        data_used.append("30-session ARIMA-GARCH Monte Carlo scenarios")
    if forecast is not None and forecast.get("regression_available"):
        data_used.append("price-volume-VWAP multiple regression")
    if news:
        data_used.append("Tavily current-news research")

    result = CompanyOutlookOut(
        ticker=company.ticker,
        short_term=HorizonOutlook(
            horizon="3–5 trading days",
            direction=short_direction,
            summary=short_summary,
        ),
        medium_term=HorizonOutlook(
            horizon="25–30 trading days",
            direction=medium_direction,
            summary=medium_summary,
        ),
        confidence_label=confidence_label,
        confidence_percent=confidence if evidence_available else 0,
        citations=citations,
        limitations=list(dict.fromkeys(limitations)),
        data_used=data_used,
        model_name=provider.model_name,
        generated_at=datetime.now(UTC),
    )
    cache.put(
        key,
        result.model_dump(mode="json"),
        source="technical_indicators_statistical_forecast_and_current_news",
        model_name=provider.model_name,
        prompt_version=PROMPT_VERSION,
    )
    return result
