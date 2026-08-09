from types import SimpleNamespace

import pytest

from app.schemas.company import (
    CompanyChatRequest,
    FinancialOverviewOut,
    FinancialSeriesPoint,
)
from app.services import company_chat
from app.services.company_chat import (
    CompanyChatPlan,
    _decision_assessment,
    _derived_ratios,
    _heuristic_plan,
    _normalize_plan,
    answer_company_question,
)


def test_decision_question_requires_the_complete_evidence_stack():
    plan = _heuristic_plan(
        "I may buy this stock. Give me your confidence using RSI, options and the outlook."
    )

    assert plan.intent == "decision_support"
    assert plan.needs_financials
    assert plan.needs_ratios
    assert plan.needs_technical
    assert plan.needs_options
    assert plan.needs_forecast


def test_mixed_technical_options_question_keeps_both_data_sources():
    plan = _normalize_plan(
        CompanyChatPlan(intent="technical", needs_technical=True),
        "What do RSI and the nearest option open interest show?",
    )

    assert plan.intent == "technical"
    assert plan.needs_technical
    assert plan.needs_options


def test_decision_support_only_uses_news_when_explicitly_requested():
    base = CompanyChatPlan(intent="decision_support", needs_news=True)

    plain = _normalize_plan(base, "I may buy this stock. Give me a balanced view.")
    current = _normalize_plan(
        base,
        "I may buy this stock. Include recent news and catalysts.",
    )

    assert not plain.needs_news
    assert current.needs_news


def test_derived_ratios_calculate_cagr_and_price_position():
    overview = FinancialOverviewOut(
        ticker="TEST",
        source_url="https://example.test/financials",
        annual=[
            FinancialSeriesPoint(
                period="FY 2023",
                end_date="2023-03-31",
                revenue=100,
                net_income=10,
                net_margin_percent=10,
            ),
            FinancialSeriesPoint(
                period="FY 2025",
                end_date="2025-03-31",
                revenue=121,
                net_income=15,
                net_margin_percent=12.4,
                revenue_yoy_percent=10,
            ),
        ],
    )

    metrics = _derived_ratios(
        overview,
        {
            "current_price": 150,
            "fifty_two_week_low": 100,
            "fifty_two_week_high": 200,
        },
    )

    assert metrics["revenue_cagr_percent"] == pytest.approx(10, abs=0.02)
    assert metrics["price_position_in_52_week_range_percent"] == 50
    assert metrics["latest_annual_net_margin_percent"] == 12.4


def test_decision_assessment_withholds_medium_term_without_financial_history():
    assessment = _decision_assessment(
        {
            "rsi_14": 60,
            "macd_histogram": 1,
            "price_vs_vwap_percent": 1,
            "ema_9_vs_ema_21_percent": 1,
            "return_5c_percent": 2,
        },
        {"profit_margin_percent": 10},
        {
            "available": True,
            "last_price": 100,
            "short_term_5_session": {"median": 102},
            "medium_term_60_session": {"median": 110},
        },
        {
            "available": True,
            "distribution": {"probability_above_spot": 0.6},
        },
        False,
    )

    assert assessment["short_term_view"] == "positive"
    assert assessment["medium_term_view"] == "unavailable"
    assert not assessment["financial_history_adequate_for_long_term"]


@pytest.mark.asyncio
async def test_ratio_chat_uses_normalized_financials_and_reported_ratios(monkeypatch):
    company = SimpleNamespace(
        id="company-id",
        ticker="TEST",
        name="Test Limited",
        cik="0000000000",
        country="IN",
        exchange="NSE",
        sector="Industrials",
        industry="Machinery",
        reporting_currency="INR",
        market_data_ticker="TEST.NS",
    )
    overview = FinancialOverviewOut(
        ticker="TEST",
        currency="INR",
        source_url="https://example.test/financials",
        annual=[
            FinancialSeriesPoint(
                period="FY 2024",
                end_date="2024-03-31",
                revenue=100,
                net_income=10,
            ),
            FinancialSeriesPoint(
                period="FY 2025",
                end_date="2025-03-31",
                revenue=120,
                net_income=15,
            ),
        ],
    )

    async def fake_plan(company, question):
        return CompanyChatPlan(
            intent="ratios",
            needs_financials=True,
            needs_ratios=True,
        )

    async def fake_overview(db, company):
        return overview

    async def fake_ratios(ticker, market_data_ticker):
        return {
            "ticker": ticker,
            "market_data_ticker": market_data_ticker,
            "current_price": 100,
            "trailing_pe": 20,
            "profit_margin_percent": 12.5,
            "fifty_two_week_low": 80,
            "fifty_two_week_high": 120,
            "source_url": "https://example.test/quote",
            "retrieved_at": "2026-07-27T00:00:00Z",
            "source": "yfinance",
        }

    class FakeProvider:
        model_name = "test-llama"

        async def chat(self, messages, **kwargs):
            assert "trailing_pe" in messages[-1]["content"]
            return "The reported trailing P/E is 20 [2]."

    monkeypatch.setattr(company_chat, "_plan", fake_plan)
    monkeypatch.setattr(company_chat, "_overview", fake_overview)
    monkeypatch.setattr(company_chat, "get_trading_ratios", fake_ratios)
    monkeypatch.setattr(company_chat, "get_provider", lambda: FakeProvider())

    result = await answer_company_question(
        object(),
        company,
        CompanyChatRequest(message="Explain the valuation ratios."),
    )

    assert result.intent == "ratios"
    assert result.model_name == "test-llama"
    assert "Yahoo valuation and trading ratios" in result.data_used
    assert len(result.citations) == 1
    assert result.citations[0]["url"] == "https://example.test/quote"
