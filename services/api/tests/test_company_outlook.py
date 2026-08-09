from datetime import date
from types import SimpleNamespace

import pytest

from app.services import company_outlook
from app.services.company_outlook import (
    OutlookNarrative,
    _assess_directions,
    _compact_forecast,
    _relevant_news,
    get_company_outlook,
)
from app.services.research.news import NewsSource


def _forecast(start: float = 100, terminal: float = 108) -> dict:
    points = []
    for index in range(30):
        median = start + (terminal - start) * (index + 1) / 30
        points.append(
            {
                "date": f"2026-08-{index + 1:02d}",
                "median": median,
                "p10": median * 0.9,
                "p90": median * 1.1,
                "annualized_volatility_percent": 24,
            }
        )
    return {
        "available": True,
        "last_price": start,
        "points": points,
        "probability_finish_above_last": 0.62,
        "current_annualized_volatility_percent": 24,
        "regression_available": True,
        "regression_model": "Direct-horizon OLS",
        "regression_terminal_price": terminal + 1,
        "regression_terminal_return_percent": terminal + 1 - start,
        "regression_points": [
            {
                "date": point["date"],
                "predicted_price": point["median"] + 1,
                "predicted_return_percent": (point["median"] + 1) / start * 100 - 100,
            }
            for point in points
        ],
        "regression_validation_r_squared": 0.12,
        "regression_validation_mae_percent": 2.4,
        "regression_standardized_coefficients": {
            "price_momentum": 0.01,
            "relative_volume": 0.002,
            "price_vs_vwap": 0.004,
        },
        "regression_limitations": ["Regression is a point estimate."],
        "source_url": "https://example.test/history",
        "limitations": ["Scenario only."],
    }


def test_direction_assessment_uses_both_horizons():
    technical = {
        "rsi_14": 62,
        "macd_histogram": 1.2,
        "ema_9_vs_ema_21_percent": 2.0,
        "return_5c_percent": 3.0,
        "return_15c_percent": 5.0,
        "return_60c_percent": 9.0,
    }

    short, medium, confidence, label = _assess_directions(
        technical,
        _forecast(),
    )

    assert short == "positive"
    assert medium == "positive"
    assert confidence >= 75
    assert label == "high"


def test_direction_assessment_does_not_use_regression_with_negative_validation_r2():
    forecast = _forecast(start=100, terminal=100)
    forecast["regression_points"] = [
        {
            "date": point["date"],
            "predicted_price": 130,
            "predicted_return_percent": 30,
        }
        for point in forecast["points"]
    ]
    forecast["regression_validation_r_squared"] = -0.2
    technical = {
        "rsi_14": 50,
        "macd_histogram": 0,
        "ema_9_vs_ema_21_percent": 0,
        "return_5c_percent": 0,
        "return_15c_percent": 0,
        "return_60c_percent": 0,
    }

    short, medium, _, _ = _assess_directions(technical, forecast)

    assert short == "mixed"
    assert medium == "mixed"


def test_compact_forecast_selects_requested_session_windows():
    compact = _compact_forecast(_forecast())

    assert compact["five_session"]["date"] == "2026-08-05"
    assert compact["twenty_five_session"]["date"] == "2026-08-25"
    assert compact["thirty_session"]["date"] == "2026-08-30"


def test_news_filter_rejects_broad_market_articles():
    company = SimpleNamespace(
        ticker="KAUSHALYA",
        name="Kaushalya Infrastructure Development Corporation Limited",
    )
    broad = NewsSource(
        title="Top NSE stocks this year",
        url="https://example.test/broad",
        excerpt="A roundup of Indian equities including TCS and Reliance.",
    )
    specific = NewsSource(
        title="Kaushalya Infrastructure announces project update",
        url="https://example.test/specific",
        excerpt="Kaushalya published an update to investors.",
    )

    assert _relevant_news(company, [broad, specific]) == [specific]


@pytest.mark.asyncio
async def test_company_outlook_combines_technicals_forecast_and_news(monkeypatch):
    company = SimpleNamespace(
        ticker="TEST",
        name="Test Limited",
        exchange="NSE",
        country="IN",
        market_data_ticker="TEST.NS",
    )
    technical = {
        "candle_interval": "1d",
        "candle_time": "2026-07-29T00:00:00Z",
        "price": 100,
        "rsi_14": 61,
        "macd_histogram": 1,
        "price_vs_vwap_percent": 2,
        "ema_9_vs_ema_21_percent": 1.5,
        "return_5c_percent": 2,
        "return_15c_percent": 4,
        "return_60c_percent": 8,
        "relative_volume": 1.2,
        "atr_percent": 2.3,
        "bollinger_position_percent": 68,
        "source": "Yahoo history",
        "source_url": "https://example.test/history",
        "is_delayed_or_unverified": True,
    }
    news = [
        NewsSource(
            title="Test Limited wins a new order",
            url="https://example.test/news",
            excerpt="The company announced a new order.",
            published_date=date(2026, 7, 28),
        )
    ]

    class FakeCache:
        def __init__(self, *args):
            self.payload = None

        def get(self, *args):
            return None

        def put(self, key, payload, **kwargs):
            self.payload = payload

    class FakeProvider:
        model_name = "test-llama"

    async def fake_technical(company, interval):
        return technical

    async def fake_forecast(*args, **kwargs):
        return _forecast()

    async def fake_news(company):
        return news, None

    async def fake_generate(schema, messages, **kwargs):
        assert "Test Limited wins a new order" in messages[-1]["content"]
        return OutlookNarrative(
            short_term_summary="Momentum and the five-session scenario lean positive, with the recent order providing supportive but unquantified news context.",
            medium_term_summary="The 25–30 day evidence remains positive as trend measures and the model median align, though volatility keeps the outcome uncertain.",
        )

    monkeypatch.setattr(company_outlook, "FileCache", FakeCache)
    monkeypatch.setattr(company_outlook, "get_provider", lambda: FakeProvider())
    monkeypatch.setattr(company_outlook, "_technical", fake_technical)
    monkeypatch.setattr(company_outlook, "get_price_forecast", fake_forecast)
    monkeypatch.setattr(company_outlook, "_get_news", fake_news)
    monkeypatch.setattr(company_outlook, "generate_structured", fake_generate)

    result = await get_company_outlook(object(), company)

    assert result.short_term.direction == "positive"
    assert result.medium_term.direction == "positive"
    assert result.model_name == "test-llama"
    assert "Tavily current-news research" in result.data_used
    assert "price-volume-VWAP multiple regression" in result.data_used
    assert {item["url"] for item in result.citations} == {
        "https://example.test/history",
        "https://example.test/news",
    }
