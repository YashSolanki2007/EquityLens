"""Tests for strict freshness, diversity, and source-grounded market summaries."""

from datetime import date

from app.services.market_pulse import (
    ModelArticle,
    ModelMarketPulse,
    assemble_market_pulse,
    select_recent_sources,
)
from app.services.research.news import NewsSource


def source(
    title: str,
    url: str,
    published_date: date | None,
    *,
    excerpt: str = "First fact. Second fact. Third fact.",
    score: float = 0.8,
) -> NewsSource:
    return NewsSource(
        title=title,
        url=url,
        excerpt=excerpt,
        published_date=published_date,
        score=score,
        search_excerpt=excerpt,
    )


def test_recent_sources_enforce_window_dedupe_and_publisher_cap():
    today = date(2026, 7, 20)
    selected = select_recent_sources(
        [
            [
                source(
                    "RBI policy update",
                    "https://news.example/rbi?utm_source=test",
                    date(2026, 7, 20),
                ),
                source(
                    "Another economy update",
                    "https://news.example/economy",
                    date(2026, 7, 19),
                ),
                source(
                    "Third item from same publisher",
                    "https://news.example/third",
                    date(2026, 7, 18),
                ),
            ],
            [
                source(
                    "RBI policy update",
                    "https://news.example/rbi",
                    date(2026, 7, 20),
                ),
                source(
                    "Market article without a date",
                    "https://other.example/no-date",
                    None,
                ),
            ],
            [
                source(
                    "Old geopolitical story",
                    "https://world.example/old",
                    date(2026, 7, 12),
                ),
                source(
                    "New geopolitical story",
                    "https://world.example/new",
                    date(2026, 7, 14),
                ),
            ],
        ],
        today=today,
        lookback_days=7,
        limit=8,
    )

    assert [item.title for item in selected] == [
        "RBI policy update",
        "New geopolitical story",
    ]
    assert all(item.published_date and item.published_date >= date(2026, 7, 13) for item in selected)


def test_recent_sources_reject_promotional_titles_and_conflicting_url_dates():
    selected = select_recent_sources(
        [
            [
                source(
                    "3 stocks worth watching as tariffs shift demand",
                    "https://promo.example/picks",
                    date(2026, 7, 20),
                ),
                source(
                    "Semiconductor export controls tighten",
                    "https://news.example/2026/02/18/stale",
                    date(2026, 7, 20),
                ),
                source(
                    "Chipmaker posts record profits amid AI demand",
                    "https://business.example/earnings",
                    date(2026, 7, 20),
                ),
                source(
                    "Oil market faces a new trade conflict",
                    "https://fool.com/macro-story",
                    date(2026, 7, 19),
                ),
                source(
                    "Oil markets weigh a new trade conflict",
                    "https://reliable.example/2026/07/19/oil",
                    date(2026, 7, 19),
                ),
            ]
        ],
        today=date(2026, 7, 20),
        lookback_days=7,
        limit=8,
    )

    assert [item.title for item in selected] == ["Oil markets weigh a new trade conflict"]


def test_market_pulse_uses_source_metadata_and_rejects_invalid_indices():
    sources = [
        source(
            "Authoritative title",
            "https://publisher.example/article",
            date(2026, 7, 19),
        ),
        source(
            "Second source",
            "https://another.example/story",
            date(2026, 7, 18),
        ),
    ]
    model = ModelMarketPulse(
        overview="Policy and trade were the principal themes.",
        key_themes=["Policy", "Trade", "Policy"],
        articles=[
            ModelArticle(
                source_index=1,
                category="monetary_policy",
                summary_lines=["Line one.", "Line two.", "Line three."],
                market_relevance="The development could affect Treasury yields.",
                impact_direction="mixed",
                affected_areas=["Treasury yields"],
            ),
            ModelArticle(
                source_index=99,
                category="other",
                summary_lines=["This must not appear."],
                market_relevance="Invalid source.",
            ),
        ],
    )

    result = assemble_market_pulse(
        sources,
        model,
        today=date(2026, 7, 20),
        lookback_days=7,
        model_name="meta/llama-test",
    )

    assert result.articles[0].title == "Authoritative title"
    assert result.articles[0].url == "https://publisher.example/article"
    assert result.articles[0].summary_lines == ["Line one.", "Line two.", "Line three."]
    assert result.articles[1].title == "Second source"
    assert result.articles[1].category == "other"
    assert result.key_themes == ["Policy", "Trade"]
    assert result.oldest_allowed_date == date(2026, 7, 13)
    assert result.market == "IN"


def test_market_pulse_falls_back_to_bounded_excerpt_lines():
    sources = [
        source(
            "Fallback source",
            "https://publisher.example/fallback",
            date(2026, 7, 20),
            excerpt="One reported fact. A second reported fact. A third reported fact.",
        )
    ]

    result = assemble_market_pulse(
        sources,
        None,
        today=date(2026, 7, 20),
        lookback_days=7,
        model_name="meta/llama-test",
    )

    assert result.articles[0].summary_lines == [
        "One reported fact.",
        "A second reported fact.",
        "A third reported fact.",
    ]
    assert result.articles[0].impact_direction == "unclear"
    assert result.articles[0].category == "other"


def test_india_market_accepts_local_signals_and_uses_india_fallback_context():
    sources = [
        source(
            "RBI policy review focuses on inflation and liquidity",
            "https://india.example/rbi-policy",
            date(2026, 7, 20),
        )
    ]
    selected = select_recent_sources(
        [sources],
        today=date(2026, 7, 20),
        lookback_days=7,
        limit=8,
    )

    result = assemble_market_pulse(
        selected,
        None,
        today=date(2026, 7, 20),
        lookback_days=7,
        model_name="meta/llama-test",
    )

    assert result.market == "IN"
    assert result.articles[0].category == "monetary_policy"
    assert "Indian rate expectations" in result.articles[0].market_relevance
    assert result.articles[0].affected_areas == ["RBI policy", "Rupee", "Bond yields"]


def test_india_market_rejects_company_results_and_unsafe_price_predictions():
    candidates = [
        source(
            "India lender reports profit on higher loan growth",
            "https://business.example/company-results",
            date(2026, 7, 20),
        ),
        source(
            "RBI policy review focuses on inflation",
            "https://policy.example/rbi",
            date(2026, 7, 20),
        ),
        source(
            "Semiconductor stocks fall after a new global AI model",
            "https://global.example/chips",
            date(2026, 7, 20),
        ),
    ]
    selected = select_recent_sources(
        [candidates],
        today=date(2026, 7, 20),
        lookback_days=7,
        limit=8,
    )
    model = ModelMarketPulse(
        overview="RBI policy remained in focus.",
        articles=[
            ModelArticle(
                source_index=1,
                category="monetary_policy",
                summary_lines=["RBI policy remained in focus."],
                market_relevance="This could increase the stock price.",
            )
        ],
    )
    result = assemble_market_pulse(
        selected,
        model,
        today=date(2026, 7, 20),
        lookback_days=7,
        model_name="meta/llama-test",
    )

    assert [item.title for item in selected] == ["RBI policy review focuses on inflation"]
    assert "stock price" not in result.articles[0].market_relevance
    assert "Indian rate expectations" in result.articles[0].market_relevance
