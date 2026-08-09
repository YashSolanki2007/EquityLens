#!/usr/bin/env python3
"""Generate the static EquityLens beta × R² backtest report.

The test deliberately uses the NIFTY 50 index rather than today's constituent
list, avoiding constituent survivorship bias. It is a price-index test: cash
earns 0%, dividends are excluded, and each position change costs 10 bps.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf


TRADING_DAYS = 252
DEFAULT_SYMBOL = "^NSEI"
DOWNLOAD_START = "2010-01-01"
EVALUATION_START = "2011-01-03"
LOOKBACKS = (21, 63, 126, 252)
THRESHOLDS = (0.0, 0.05, 0.10, 0.15)
PRIMARY_LOOKBACK = 63
PRIMARY_THRESHOLD = 0.05
ONE_WAY_COST = 0.001


@dataclass(frozen=True)
class Metrics:
    cagr: float
    annualized_volatility: float
    sharpe_zero_cash: float
    max_drawdown: float
    total_return: float


def _finite(value: float, digits: int = 8) -> float | None:
    return round(float(value), digits) if math.isfinite(float(value)) else None


def download_close(symbol: str, end: str | None) -> pd.Series:
    frame = yf.download(
        symbol,
        start=DOWNLOAD_START,
        end=end,
        auto_adjust=True,
        progress=False,
    )
    if frame.empty:
        raise RuntimeError(f"No Yahoo Finance history returned for {symbol}")
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna().astype(float)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    return close.rename("close")


def regression_signal(close: pd.Series, lookback: int) -> pd.DataFrame:
    """OLS log-price trend and annualized beta × R² score."""
    values = np.log(close.to_numpy())
    count = len(values)
    time = np.arange(lookback, dtype=float)
    centered_time = time - time.mean()
    time_sum_squares = float(np.dot(centered_time, centered_time))
    beta = np.full(count, np.nan)
    r_squared = np.full(count, np.nan)

    for index in range(lookback - 1, count):
        window = values[index - lookback + 1 : index + 1]
        centered_price = window - window.mean()
        slope = float(np.dot(centered_time, centered_price) / time_sum_squares)
        fitted_centered = slope * centered_time
        residual_sum_squares = float(np.square(centered_price - fitted_centered).sum())
        total_sum_squares = float(np.square(centered_price).sum())
        fit = 1 - residual_sum_squares / total_sum_squares if total_sum_squares > 1e-15 else 0
        beta[index] = slope
        r_squared[index] = min(1.0, max(0.0, fit))

    annualized_slope = np.expm1(TRADING_DAYS * beta)
    score = annualized_slope * r_squared
    return pd.DataFrame(
        {
            "beta_daily": beta,
            "annualized_slope": annualized_slope,
            "r_squared": r_squared,
            "score": score,
        },
        index=close.index,
    )


def performance_metrics(returns: pd.Series, equity: pd.Series) -> Metrics:
    years = (equity.index[-1] - equity.index[0]).days / 365.2425
    cagr = float(equity.iloc[-1] ** (1 / years) - 1)
    volatility = float(returns.std(ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(returns.mean() * TRADING_DAYS / volatility) if volatility else math.nan
    drawdown = equity / equity.cummax() - 1
    return Metrics(cagr, volatility, sharpe, float(drawdown.min()), float(equity.iloc[-1] - 1))


def run_backtest(
    close: pd.Series,
    lookback: int,
    threshold: float,
    cost: float = ONE_WAY_COST,
) -> tuple[pd.DataFrame, dict[str, float | int | None]]:
    signal = regression_signal(close, lookback)
    target = (signal["score"] > threshold).astype(float).where(signal["score"].notna(), 0.0)

    # Signal is computed after close t and executed at close t+1. The newly
    # acquired position therefore first earns the close t+1 -> close t+2 return.
    active_position = target.shift(2).fillna(0.0)
    turnover = (target.shift(1).fillna(0.0) - target.shift(2).fillna(0.0)).abs()
    benchmark_return = close.pct_change().fillna(0.0)
    strategy_return = active_position * benchmark_return - turnover * cost

    report = pd.concat(
        [
            close,
            signal,
            benchmark_return.rename("benchmark_return"),
            strategy_return.rename("strategy_return"),
            active_position.rename("position"),
            turnover.rename("turnover"),
        ],
        axis=1,
    ).loc[EVALUATION_START:]
    report["strategy_equity"] = (1 + report["strategy_return"]).cumprod()
    report["benchmark_equity"] = (1 + report["benchmark_return"]).cumprod()
    report["strategy_drawdown"] = report["strategy_equity"] / report["strategy_equity"].cummax() - 1
    report["benchmark_drawdown"] = report["benchmark_equity"] / report["benchmark_equity"].cummax() - 1

    strategy = performance_metrics(report["strategy_return"], report["strategy_equity"])
    benchmark = performance_metrics(report["benchmark_return"], report["benchmark_equity"])
    market_variance = float(report["benchmark_return"].var(ddof=1))
    market_beta = (
        float(report["strategy_return"].cov(report["benchmark_return"])) / market_variance
        if market_variance > 0
        else math.nan
    )
    entries = int(((target.shift(1).fillna(0) > target.shift(2).fillna(0)).loc[EVALUATION_START:]).sum())
    exits = int(((target.shift(1).fillna(0) < target.shift(2).fillna(0)).loc[EVALUATION_START:]).sum())

    metrics: dict[str, float | int | None] = {
        "lookback": lookback,
        "threshold": threshold,
        "cagr": _finite(strategy.cagr),
        "annualized_volatility": _finite(strategy.annualized_volatility),
        "sharpe_zero_cash": _finite(strategy.sharpe_zero_cash),
        "max_drawdown": _finite(strategy.max_drawdown),
        "total_return": _finite(strategy.total_return),
        "benchmark_cagr": _finite(benchmark.cagr),
        "benchmark_annualized_volatility": _finite(benchmark.annualized_volatility),
        "benchmark_sharpe_zero_cash": _finite(benchmark.sharpe_zero_cash),
        "benchmark_max_drawdown": _finite(benchmark.max_drawdown),
        "benchmark_total_return": _finite(benchmark.total_return),
        "time_in_market": _finite(report["position"].mean()),
        "entries": entries,
        "exits": exits,
        "turnover_cost_sum": _finite(report["turnover"].sum() * cost),
        "market_beta": _finite(market_beta),
    }
    return report, metrics


def chart_points(frame: pd.DataFrame) -> list[dict[str, float | str | None]]:
    # Weekly observations keep the embedded report light while preserving every
    # year-end point and the final observation.
    sampled = frame.resample("W-FRI").last().dropna(subset=["strategy_equity"])
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]]).sort_index()
    return [
        {
            "date": index.date().isoformat(),
            "strategy": _finite(row["strategy_equity"], 6),
            "benchmark": _finite(row["benchmark_equity"], 6),
            "strategy_drawdown": _finite(row["strategy_drawdown"], 6),
            "benchmark_drawdown": _finite(row["benchmark_drawdown"], 6),
            "score": _finite(row["score"], 6),
            "annualized_slope": _finite(row["annualized_slope"], 6),
            "r_squared": _finite(row["r_squared"], 6),
            "position": _finite(row["position"], 2),
        }
        for index, row in sampled.iterrows()
    ]


def yearly_returns(frame: pd.DataFrame) -> list[dict[str, float | int | None]]:
    grouped = frame[["strategy_return", "benchmark_return"]].groupby(frame.index.year)
    return [
        {
            "year": int(year),
            "strategy": _finite((1 + values["strategy_return"]).prod() - 1, 6),
            "benchmark": _finite((1 + values["benchmark_return"]).prod() - 1, 6),
        }
        for year, values in grouped
    ]


def build_report(close: pd.Series) -> dict[str, object]:
    primary_frame, primary_metrics = run_backtest(close, PRIMARY_LOOKBACK, PRIMARY_THRESHOLD)
    sensitivity: list[dict[str, float | int | None]] = []
    for lookback in LOOKBACKS:
        for threshold in THRESHOLDS:
            _, metrics = run_backtest(close, lookback, threshold)
            sensitivity.append(metrics)

    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": "Yahoo Finance delayed NIFTY 50 price-index history (^NSEI)",
        "formula": "score_t = (exp(252 * beta_t) - 1) * R_t^2",
        "evaluation_start": primary_frame.index[0].date().isoformat(),
        "evaluation_end": primary_frame.index[-1].date().isoformat(),
        "observations": int(len(primary_frame)),
        "assumptions": {
            "instrument": "NIFTY 50 price index (^NSEI)",
            "primary_lookback_sessions": PRIMARY_LOOKBACK,
            "entry_threshold": PRIMARY_THRESHOLD,
            "execution": "Signal after close t; execute at close t+1; first return earned t+1 to t+2",
            "one_way_cost": ONE_WAY_COST,
            "cash_return": 0,
            "dividends": "Excluded: this is a price-index test",
            "positioning": "Long 100% when score > threshold; otherwise cash; no leverage or shorts",
        },
        "primary_metrics": primary_metrics,
        "latest_signal": {
            "beta_daily": _finite(primary_frame["beta_daily"].iloc[-1], 10),
            "annualized_slope": _finite(primary_frame["annualized_slope"].iloc[-1], 8),
            "r_squared": _finite(primary_frame["r_squared"].iloc[-1], 8),
            "score": _finite(primary_frame["score"].iloc[-1], 8),
        },
        "chart": chart_points(primary_frame),
        "yearly_returns": yearly_returns(primary_frame),
        "sensitivity": sensitivity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--end", default=None, help="Exclusive Yahoo Finance end date")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/data/beta-r2-backtest.json"),
    )
    arguments = parser.parse_args()

    close = download_close(arguments.symbol, arguments.end)
    report = build_report(close)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {arguments.output} through {report['evaluation_end']}")


if __name__ == "__main__":
    main()
