"""Construct and mark diversified paper portfolios from spot pair suggestions."""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PaperPairPortfolio
from app.schemas.pairs import PairSuggestion
from app.services.pair_suggestions import FNO_INDEXES

MAX_PORTFOLIO_PAIRS = 6
MIN_CORRELATION_OBSERVATIONS = 20
ENTRY_PRICE_SOURCE = "pair-scan NSE stock closes (spot proxy; no futures)"
MARK_PRICE_SOURCE = "Yahoo Finance unadjusted NSE stock closes (spot proxy)"


def _pair_returns(pair: PairSuggestion) -> dict[str, float]:
    gross = pair.example_long_value_inr + pair.example_short_value_inr
    long_weight = pair.example_long_value_inr / gross if gross > 0 else 0.5
    short_weight = pair.example_short_value_inr / gross if gross > 0 else 0.5
    output: dict[str, float] = {}
    for previous, current in zip(pair.chart, pair.chart[1:], strict=False):
        a_return = current.stock_a_indexed / previous.stock_a_indexed - 1
        b_return = current.stock_b_indexed / previous.stock_b_indexed - 1
        if pair.long_ticker == pair.stock_a:
            value = long_weight * a_return - short_weight * b_return
        else:
            value = long_weight * b_return - short_weight * a_return
        if math.isfinite(value):
            output[current.date] = value
    return output


def _return_correlation(
    left: dict[str, float], right: dict[str, float]
) -> float | None:
    common = sorted(set(left) & set(right))
    if len(common) < MIN_CORRELATION_OBSERVATIONS:
        return None
    a = np.asarray([left[item] for item in common], dtype=float)
    b = np.asarray([right[item] for item in common], dtype=float)
    if np.std(a) < 1e-12 or np.std(b) < 1e-12:
        return None
    value = float(np.corrcoef(a, b)[0, 1])
    return value if math.isfinite(value) else None


def _correlation_matrix(
    pairs: list[PairSuggestion],
) -> dict[tuple[str, str], float | None]:
    streams = {pair.pair_id: _pair_returns(pair) for pair in pairs}
    matrix: dict[tuple[str, str], float | None] = {}
    for index, left in enumerate(pairs):
        for right in pairs[index + 1 :]:
            value = _return_correlation(streams[left.pair_id], streams[right.pair_id])
            matrix[(left.pair_id, right.pair_id)] = value
            matrix[(right.pair_id, left.pair_id)] = value
    return matrix


def _correlations_for(
    candidate: PairSuggestion,
    selected: list[PairSuggestion],
    matrix: dict[tuple[str, str], float | None],
) -> list[float]:
    return [
        abs(value)
        for item in selected
        if (value := matrix.get((candidate.pair_id, item.pair_id))) is not None
    ]


def _selection_score(
    selected: list[PairSuggestion],
    ranks: dict[str, int],
    matrix: dict[tuple[str, str], float | None],
) -> tuple[int, float, float, int]:
    correlations = [
        abs(value)
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
        if (value := matrix.get((left.pair_id, right.pair_id))) is not None
    ]
    return (
        -len(selected),
        max(correlations, default=1.0),
        float(np.mean(correlations)) if correlations else 1.0,
        sum(ranks[item.pair_id] for item in selected),
    )


def select_diversified_pairs(
    suggestions: list[PairSuggestion], *, maximum_pairs: int = MAX_PORTFOLIO_PAIRS
) -> tuple[list[PairSuggestion], dict[str, Any]]:
    """Prefer ticker-disjoint pairs, then permit only same-side overlap."""

    candidates = [item for item in suggestions if item.signal != "watch"]
    if not candidates:
        return [], {
            "fully_ticker_disjoint": True,
            "used_same_side_overlap_fallback": False,
            "mean_absolute_pair_correlation": None,
            "maximum_absolute_pair_correlation": None,
            "target_pairs": 0,
        }
    candidates = candidates[:40]
    target = min(maximum_pairs, len(candidates))
    ranks = {item.pair_id: index + 1 for index, item in enumerate(candidates)}
    matrix = _correlation_matrix(candidates)

    trials: list[list[PairSuggestion]] = []
    for seed in candidates[: min(20, len(candidates))]:
        selected = [seed]
        used = {seed.long_ticker, seed.short_ticker}
        while len(selected) < target:
            eligible = [
                item
                for item in candidates
                if item not in selected
                and item.long_ticker not in used
                and item.short_ticker not in used
            ]
            if not eligible:
                break
            next_pair = min(
                eligible,
                key=lambda item: (
                    max(_correlations_for(item, selected, matrix), default=1.0),
                    np.mean(_correlations_for(item, selected, matrix))
                    if _correlations_for(item, selected, matrix)
                    else 1.0,
                    ranks[item.pair_id],
                ),
            )
            selected.append(next_pair)
            used.update((next_pair.long_ticker, next_pair.short_ticker))
        trials.append(selected)

    selected = min(trials, key=lambda items: _selection_score(items, ranks, matrix))
    side_by_ticker = {
        ticker: side
        for item in selected
        for ticker, side in ((item.long_ticker, "long"), (item.short_ticker, "short"))
    }
    used_fallback = False
    while len(selected) < target:
        eligible = []
        for item in candidates:
            if item in selected:
                continue
            if side_by_ticker.get(item.long_ticker, "long") != "long":
                continue
            if side_by_ticker.get(item.short_ticker, "short") != "short":
                continue
            eligible.append(item)
        if not eligible:
            break
        next_pair = min(
            eligible,
            key=lambda item: (
                sum(
                    ticker in side_by_ticker
                    for ticker in (item.long_ticker, item.short_ticker)
                ),
                max(_correlations_for(item, selected, matrix), default=1.0),
                ranks[item.pair_id],
            ),
        )
        used_fallback = used_fallback or any(
            ticker in side_by_ticker
            for ticker in (next_pair.long_ticker, next_pair.short_ticker)
        )
        selected.append(next_pair)
        side_by_ticker[next_pair.long_ticker] = "long"
        side_by_ticker[next_pair.short_ticker] = "short"

    correlations = [
        abs(value)
        for index, left in enumerate(selected)
        for right in selected[index + 1 :]
        if (value := matrix.get((left.pair_id, right.pair_id))) is not None
    ]
    per_pair_correlations = {}
    for item in selected:
        values = _correlations_for(
            item,
            [other for other in selected if other != item],
            matrix,
        )
        per_pair_correlations[item.pair_id] = (
            float(np.mean(values)) if values else (1.0 if len(selected) > 1 else 0.0)
        )
    unique_tickers = {
        ticker for item in selected for ticker in (item.long_ticker, item.short_ticker)
    }
    return selected, {
        "fully_ticker_disjoint": len(unique_tickers) == 2 * len(selected),
        "used_same_side_overlap_fallback": used_fallback,
        "mean_absolute_pair_correlation": (
            round(float(np.mean(correlations)), 4) if correlations else None
        ),
        "maximum_absolute_pair_correlation": (
            round(max(correlations), 4) if correlations else None
        ),
        "target_pairs": target,
        "selected_pairs": len(selected),
        "unique_companies": len(unique_tickers),
        "selection_method": (
            "ticker-disjoint greedy search across ranked seeds, minimizing absolute "
            "correlation of historical spot pair-return proxies"
        ),
        "per_pair_mean_absolute_correlation": per_pair_correlations,
    }


def build_positions(
    selected: list[PairSuggestion],
    investment_amount_inr: float,
    selection_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    if not selected:
        return []
    pair_budget = investment_amount_inr / len(selected)
    positions = []
    for rank, pair in enumerate(selected, start=1):
        example_gross = pair.example_long_value_inr + pair.example_short_value_inr
        long_share = pair.example_long_value_inr / example_gross
        long_notional = pair_budget * long_share
        short_notional = pair_budget - long_notional
        positions.append(
            {
                "pair_id": pair.pair_id,
                "long_ticker": pair.long_ticker,
                "short_ticker": pair.short_ticker,
                "long_units": round(long_notional / pair.example_long_price, 8),
                "short_units": round(short_notional / pair.example_short_price, 8),
                "entry_long_price": pair.example_long_price,
                "entry_short_price": pair.example_short_price,
                "entry_price_date": pair.chart[-1].date,
                "entry_long_notional": round(long_notional, 2),
                "entry_short_notional": round(short_notional, 2),
                "allocated_gross_inr": round(pair_budget, 2),
                "hedge_ratio": pair.hedge_ratio,
                "entry_zscore": pair.current_zscore,
                "entry_q_value": pair.fdr_q_value,
                "pair_quality_rank": rank,
                "mean_abs_correlation_to_portfolio": round(
                    selection_summary["per_pair_mean_absolute_correlation"].get(
                        pair.pair_id, 0.0
                    ),
                    4,
                ),
            }
        )
    return positions


def calculate_portfolio_mark(
    positions: list[dict[str, Any]],
    prices: dict[str, float],
    initial_capital_inr: float,
    mark_date: date,
) -> dict[str, Any]:
    total_pnl = 0.0
    current_gross = 0.0
    for item in positions:
        long_price = prices[item["long_ticker"]]
        short_price = prices[item["short_ticker"]]
        total_pnl += item["long_units"] * (long_price - item["entry_long_price"])
        total_pnl += item["short_units"] * (item["entry_short_price"] - short_price)
        current_gross += item["long_units"] * long_price
        current_gross += item["short_units"] * short_price
    return {
        "date": mark_date.isoformat(),
        "portfolio_value_inr": round(initial_capital_inr + total_pnl, 2),
        "total_pnl_inr": round(total_pnl, 2),
        "return_percent": round(total_pnl / initial_capital_inr * 100, 4),
        "current_gross_notional_inr": round(current_gross, 2),
    }


def _download_stock_closes_sync(
    tickers: set[str], start_date: date
) -> dict[str, dict[date, float]]:
    symbols_by_ticker = {
        ticker: FNO_INDEXES.get(ticker, ("", f"{ticker}.NS"))[1]
        for ticker in tickers
    }
    symbols = list(dict.fromkeys(symbols_by_ticker.values()))
    frame = yf.download(
        symbols,
        start=(start_date - timedelta(days=3)).isoformat(),
        end=(datetime.now(UTC).date() + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return {}
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"]
    elif len(symbols) == 1:
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
    else:
        return {}
    output: dict[str, dict[date, float]] = {}
    for ticker, symbol in symbols_by_ticker.items():
        if symbol not in closes.columns:
            continue
        values: dict[date, float] = {}
        for index, raw_price in closes[symbol].items():
            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                continue
            if math.isfinite(price) and price > 0:
                values[pd.Timestamp(index).date()] = price
        if values:
            output[ticker] = values
    return output


async def refresh_portfolio_marks(portfolio: PaperPairPortfolio) -> None:
    tickers = {
        ticker
        for item in portfolio.positions
        for ticker in (item["long_ticker"], item["short_ticker"])
    }
    closes = await asyncio.to_thread(
        _download_stock_closes_sync, tickers, portfolio.entry_price_date
    )
    common_dates = sorted(
        set.intersection(*(set(closes.get(ticker, {})) for ticker in tickers))
    ) if tickers and all(closes.get(ticker) for ticker in tickers) else []
    marks = [
        calculate_portfolio_mark(
            portfolio.positions,
            {ticker: closes[ticker][mark_date] for ticker in tickers},
            portfolio.initial_capital_inr,
            mark_date,
        )
        for mark_date in common_dates
        if mark_date >= portfolio.entry_price_date
    ]
    if not marks:
        marks = [
            {
                "date": portfolio.entry_price_date.isoformat(),
                "portfolio_value_inr": round(portfolio.initial_capital_inr, 2),
                "total_pnl_inr": 0.0,
                "return_percent": 0.0,
                "current_gross_notional_inr": round(portfolio.allocated_gross_inr, 2),
            }
        ]
    portfolio.marks = marks
    portfolio.updated_at = datetime.now(UTC)


async def current_portfolio(
    db: AsyncSession, owner_portfolio_id: UUID
) -> PaperPairPortfolio | None:
    return (
        await db.execute(
            select(PaperPairPortfolio)
            .where(
                PaperPairPortfolio.owner_portfolio_id == owner_portfolio_id,
                PaperPairPortfolio.status == "current",
            )
            .order_by(PaperPairPortfolio.created_at.desc())
        )
    ).scalars().first()


async def create_portfolio(
    db: AsyncSession,
    owner_portfolio_id: UUID,
    investment_amount_inr: float,
    p_value_threshold: float,
    suggestions: list[PairSuggestion],
) -> PaperPairPortfolio:
    selected, summary = select_diversified_pairs(suggestions)
    if not selected:
        raise ValueError("No active pair signals are available at this p-value cutoff.")
    positions = build_positions(selected, investment_amount_inr, summary)
    entry_date = max(date.fromisoformat(item["entry_price_date"]) for item in positions)
    await db.execute(
        update(PaperPairPortfolio)
        .where(
            PaperPairPortfolio.owner_portfolio_id == owner_portfolio_id,
            PaperPairPortfolio.status == "current",
        )
        .values(status="superseded")
    )
    await db.flush()
    portfolio = PaperPairPortfolio(
        owner_portfolio_id=owner_portfolio_id,
        status="current",
        initial_capital_inr=investment_amount_inr,
        allocated_gross_inr=investment_amount_inr,
        p_value_threshold=p_value_threshold,
        entry_price_date=entry_date,
        entry_price_source=ENTRY_PRICE_SOURCE,
        positions=positions,
        marks=[],
        selection_summary=summary,
        limitations=[
            "Paper research only: no orders are placed.",
            "Portfolio value is initial paper capital plus spot-leg P&L; margin, borrow availability, dividends, taxes, fees, slippage and financing are excluded.",
            "Correlation is estimated from the displayed historical stock-price window and can change after construction.",
            f"Marks use {MARK_PRICE_SOURCE} and may be delayed or revised.",
        ],
    )
    db.add(portfolio)
    await db.flush()
    await refresh_portfolio_marks(portfolio)
    await db.commit()
    return portfolio


def portfolio_response(portfolio: PaperPairPortfolio) -> dict[str, Any]:
    return {
        "id": portfolio.id,
        "owner_portfolio_id": portfolio.owner_portfolio_id,
        "status": portfolio.status,
        "initial_capital_inr": portfolio.initial_capital_inr,
        "allocated_gross_inr": portfolio.allocated_gross_inr,
        "unallocated_cash_inr": max(
            0.0, portfolio.initial_capital_inr - portfolio.allocated_gross_inr
        ),
        "p_value_threshold": portfolio.p_value_threshold,
        "entry_price_date": portfolio.entry_price_date.isoformat(),
        "entry_price_source": portfolio.entry_price_source,
        "positions": portfolio.positions,
        "marks": portfolio.marks,
        "selection_summary": portfolio.selection_summary,
        "limitations": portfolio.limitations,
        "created_at": portfolio.created_at,
        "updated_at": portfolio.updated_at,
    }
