from datetime import date

import pytest

from app.schemas.pairs import PairChartPoint, PairSuggestion
from app.services.pair_portfolios import (
    build_positions,
    calculate_portfolio_mark,
    select_diversified_pairs,
)


def suggestion(
    long_ticker: str,
    short_ticker: str,
    *,
    rank_offset: float = 0.0,
) -> PairSuggestion:
    chart = [
        PairChartPoint(
            date=f"2026-01-{day:02d}",
            stock_a_indexed=100 + day * (1 + rank_offset),
            stock_b_indexed=100 + day * (0.7 + rank_offset / 2),
            spread_zscore=2.5,
        )
        for day in range(1, 29)
    ]
    return PairSuggestion(
        pair_id=f"{long_ticker}-{short_ticker}",
        stock_a=long_ticker,
        stock_a_name=long_ticker,
        stock_a_type="stock",
        stock_b=short_ticker,
        stock_b_name=short_ticker,
        stock_b_type="stock",
        sector="Test",
        signal="long_a_short_b",
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        example_long_quantity=10,
        example_short_quantity=20,
        example_long_price=100,
        example_short_price=50,
        example_long_value_inr=1_000,
        example_short_value_inr=1_000,
        example_target_long_price=105,
        example_target_short_price=48,
        example_gross_return_percent=4.5,
        explanation="Test pair",
        hedge_ratio=2,
        current_zscore=2.5,
        cointegration_p_value=0.0001,
        fdr_q_value=0.01,
        half_life_days=10,
        return_correlation=0.8,
        observations=250,
        chart=chart,
    )


def test_selection_prefers_a_fully_disjoint_portfolio() -> None:
    suggestions = [
        suggestion("A", "B"),
        suggestion("A", "C", rank_offset=0.1),
        suggestion("D", "E", rank_offset=0.2),
        suggestion("F", "G", rank_offset=0.3),
    ]

    selected, summary = select_diversified_pairs(suggestions, maximum_pairs=3)

    tickers = [
        ticker
        for pair in selected
        for ticker in (pair.long_ticker, pair.short_ticker)
    ]
    assert len(selected) == 3
    assert len(tickers) == len(set(tickers))
    assert summary["fully_ticker_disjoint"] is True
    assert summary["used_same_side_overlap_fallback"] is False


def test_overlap_fallback_never_flips_a_ticker_side() -> None:
    suggestions = [
        suggestion("A", "B"),
        suggestion("A", "C", rank_offset=0.1),
        suggestion("D", "A", rank_offset=0.2),
        suggestion("A", "E", rank_offset=0.3),
    ]

    selected, summary = select_diversified_pairs(suggestions, maximum_pairs=3)

    long_tickers = {pair.long_ticker for pair in selected}
    short_tickers = {pair.short_ticker for pair in selected}
    assert len(selected) == 3
    assert long_tickers.isdisjoint(short_tickers)
    assert summary["used_same_side_overlap_fallback"] is True


def test_position_sizing_and_spot_mark_use_initial_capital_plus_leg_pnl() -> None:
    pair = suggestion("A", "B")
    selected, summary = select_diversified_pairs([pair])
    positions = build_positions(selected, 100_000, summary)

    mark = calculate_portfolio_mark(
        positions,
        {"A": 110, "B": 45},
        100_000,
        date(2026, 2, 1),
    )

    assert positions[0]["entry_long_notional"] == pytest.approx(50_000)
    assert positions[0]["entry_short_notional"] == pytest.approx(50_000)
    assert mark["total_pnl_inr"] == pytest.approx(10_000)
    assert mark["portfolio_value_inr"] == pytest.approx(110_000)
    assert mark["return_percent"] == pytest.approx(10)
