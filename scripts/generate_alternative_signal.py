#!/usr/bin/env python3
"""Generate the alternative EquityLens EMA-regime backtest.

The candidate deliberately avoids interpreting a regression slope as a
next-session point forecast.  It uses a fast/slow trend regime, expresses the
distance between the two trends in volatility units, and trades only the sign
of that dimensionless score.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.generate_beta_r2_backtest import (
    ONE_WAY_COST,
    TRADING_DAYS,
    _finite,
    download_close,
    performance_metrics,
)
from scripts.generate_custom_signal import (
    INDEX_UNIVERSE,
    LARGE_CAP_UNIVERSE,
    downside_metrics,
)


SYMBOL = "^NSEI"
FAST_SPAN = 21
SLOW_SPAN = 63
VOLATILITY_SPAN = 21
SENSITIVITY_WINDOWS = (
    (15, 45),
    (15, 63),
    (21, 42),
    (21, 63),
    (21, 84),
    (30, 63),
    (30, 84),
)


def build_signal_frame(
    close: pd.Series,
    fast_span: int = FAST_SPAN,
    slow_span: int = SLOW_SPAN,
) -> pd.DataFrame:
    """Build a point-in-time, dimensionless fast/slow trend score."""
    if fast_span >= slow_span:
        raise ValueError("fast_span must be shorter than slow_span")

    log_return = np.log(close).diff()
    daily_sd = log_return.ewm(
        span=VOLATILITY_SPAN,
        adjust=False,
        min_periods=VOLATILITY_SPAN,
    ).std()
    fast_ema = close.ewm(
        span=fast_span,
        adjust=False,
        min_periods=fast_span,
    ).mean()
    slow_ema = close.ewm(
        span=slow_span,
        adjust=False,
        min_periods=slow_span,
    ).mean()
    horizon_gap = slow_span - fast_span
    ema_spread = np.log(fast_ema / slow_ema)
    trend_score = ema_spread / (daily_sd * math.sqrt(horizon_gap))
    valid = trend_score.replace([np.inf, -np.inf], np.nan).notna()
    target = (trend_score > 0).astype(float).where(valid, 0.0)

    return pd.DataFrame(
        {
            "close": close,
            "log_return": log_return,
            "daily_sd": daily_sd,
            "annualized_sd": daily_sd * math.sqrt(TRADING_DAYS),
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "ema_spread": ema_spread,
            "trend_score": trend_score,
            "target": target,
        },
        index=close.index,
    )


def run_strategy(
    close: pd.Series,
    evaluation_start: str | pd.Timestamp,
    fast_span: int = FAST_SPAN,
    slow_span: int = SLOW_SPAN,
) -> tuple[pd.DataFrame, dict[str, float | int | None]]:
    """Backtest the signal with the same conservative execution as the baseline."""
    frame = build_signal_frame(close, fast_span, slow_span)
    active_position = frame["target"].shift(2).fillna(0.0)
    turnover = (
        frame["target"].shift(1).fillna(0.0)
        - frame["target"].shift(2).fillna(0.0)
    ).abs()
    benchmark_return = close.pct_change().fillna(0.0)
    strategy_return = active_position * benchmark_return - turnover * ONE_WAY_COST

    report = frame.assign(
        benchmark_return=benchmark_return,
        strategy_return=strategy_return,
        position=active_position,
        turnover=turnover,
    ).loc[pd.Timestamp(evaluation_start) :].copy()
    if report.empty:
        raise RuntimeError("No observations remain after evaluation_start")

    # Both paths begin with one unit at the evaluation-start close.
    report.iloc[0, report.columns.get_loc("benchmark_return")] = 0.0
    report.iloc[0, report.columns.get_loc("strategy_return")] = 0.0
    report["strategy_equity"] = (1 + report["strategy_return"]).cumprod()
    report["benchmark_equity"] = (1 + report["benchmark_return"]).cumprod()
    report["strategy_drawdown"] = (
        report["strategy_equity"] / report["strategy_equity"].cummax() - 1
    )
    report["benchmark_drawdown"] = (
        report["benchmark_equity"] / report["benchmark_equity"].cummax() - 1
    )

    strategy = performance_metrics(report["strategy_return"], report["strategy_equity"])
    benchmark = performance_metrics(report["benchmark_return"], report["benchmark_equity"])
    strategy_downside, strategy_sortino = downside_metrics(report["strategy_return"])
    benchmark_downside, benchmark_sortino = downside_metrics(report["benchmark_return"])
    market_variance = float(report["benchmark_return"].var(ddof=1))
    market_beta = (
        float(report["strategy_return"].cov(report["benchmark_return"])) / market_variance
        if market_variance > 0
        else math.nan
    )
    target_at_execution = frame["target"].shift(1).fillna(0.0)
    prior_target = frame["target"].shift(2).fillna(0.0)
    entries = int((target_at_execution > prior_target).loc[report.index].sum())
    exits = int((target_at_execution < prior_target).loc[report.index].sum())

    metrics: dict[str, float | int | None] = {
        "fast_span": fast_span,
        "slow_span": slow_span,
        "cagr": _finite(strategy.cagr),
        "annualized_volatility": _finite(strategy.annualized_volatility),
        "sharpe_zero_cash": _finite(strategy.sharpe_zero_cash),
        "sortino_zero_cash": _finite(strategy_sortino),
        "annualized_downside_deviation": _finite(strategy_downside),
        "max_drawdown": _finite(strategy.max_drawdown),
        "total_return": _finite(strategy.total_return),
        "market_beta": _finite(market_beta),
        "benchmark_cagr": _finite(benchmark.cagr),
        "benchmark_annualized_volatility": _finite(benchmark.annualized_volatility),
        "benchmark_sharpe_zero_cash": _finite(benchmark.sharpe_zero_cash),
        "benchmark_sortino_zero_cash": _finite(benchmark_sortino),
        "benchmark_annualized_downside_deviation": _finite(benchmark_downside),
        "benchmark_max_drawdown": _finite(benchmark.max_drawdown),
        "benchmark_total_return": _finite(benchmark.total_return),
        "time_in_market": _finite(report["position"].mean()),
        "entries": entries,
        "exits": exits,
        "turnover_cost_sum": _finite(report["turnover"].sum() * ONE_WAY_COST),
    }
    return report, metrics


def chart_points(
    frame: pd.DataFrame,
    baseline_chart: list[dict[str, object]],
) -> list[dict[str, float | str | None]]:
    baseline_by_date = {str(point["date"]): point for point in baseline_chart}
    sampled = frame.resample("W-FRI").last().dropna(subset=["strategy_equity"])
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]]).sort_index()

    points: list[dict[str, float | str | None]] = []
    for index, row in sampled.iterrows():
        date = index.date().isoformat()
        baseline = baseline_by_date.get(date, {})
        points.append(
            {
                "date": date,
                "candidate_equity": _finite(row["strategy_equity"], 6),
                "original_equity": _finite(baseline.get("strategy_equity", math.nan), 6),
                "benchmark_equity": _finite(row["benchmark_equity"], 6),
                "candidate_drawdown": _finite(row["strategy_drawdown"], 6),
                "original_drawdown": _finite(baseline.get("strategy_drawdown", math.nan), 6),
                "benchmark_drawdown": _finite(row["benchmark_drawdown"], 6),
                "trend_score": _finite(row["trend_score"], 6),
                "ema_spread": _finite(row["ema_spread"], 6),
                "fast_ema": _finite(row["fast_ema"], 4),
                "slow_ema": _finite(row["slow_ema"], 4),
                "position": _finite(row["position"], 2),
                "annualized_sd": _finite(row["annualized_sd"], 6),
            }
        )
    return points


def yearly_returns(
    frame: pd.DataFrame,
    baseline_years: list[dict[str, object]],
) -> list[dict[str, float | int | None]]:
    baseline_by_year = {int(row["year"]): row for row in baseline_years}
    rows: list[dict[str, float | int | None]] = []
    for year, values in frame.groupby(frame.index.year):
        baseline = baseline_by_year.get(int(year), {})
        rows.append(
            {
                "year": int(year),
                "candidate": _finite((1 + values["strategy_return"]).prod() - 1, 6),
                "original": _finite(baseline.get("strategy", math.nan), 6),
                "benchmark": _finite((1 + values["benchmark_return"]).prod() - 1, 6),
                "time_in_market": _finite(values["position"].mean(), 6),
                "switches": int(values["turnover"].sum()),
            }
        )
    return rows


def period_metrics(frame: pd.DataFrame) -> list[dict[str, float | str | None]]:
    periods = (
        ("2012–2016", pd.Timestamp("2012-01-01"), pd.Timestamp("2016-12-31")),
        ("2017–2021", pd.Timestamp("2017-01-01"), pd.Timestamp("2021-12-31")),
        ("2022–latest", pd.Timestamp("2022-01-01"), frame.index[-1]),
    )
    rows: list[dict[str, float | str | None]] = []
    for label, start, end in periods:
        sample = frame.loc[start:end].copy()
        if sample.empty:
            continue
        sample.iloc[0, sample.columns.get_loc("strategy_return")] = 0.0
        sample.iloc[0, sample.columns.get_loc("benchmark_return")] = 0.0
        strategy_equity = (1 + sample["strategy_return"]).cumprod()
        benchmark_equity = (1 + sample["benchmark_return"]).cumprod()
        strategy = performance_metrics(sample["strategy_return"], strategy_equity)
        benchmark = performance_metrics(sample["benchmark_return"], benchmark_equity)
        _, strategy_sortino = downside_metrics(sample["strategy_return"])
        _, benchmark_sortino = downside_metrics(sample["benchmark_return"])
        rows.append(
            {
                "period": label,
                "start": sample.index[0].date().isoformat(),
                "end": sample.index[-1].date().isoformat(),
                "cagr": _finite(strategy.cagr),
                "benchmark_cagr": _finite(benchmark.cagr),
                "sharpe": _finite(strategy.sharpe_zero_cash),
                "benchmark_sharpe": _finite(benchmark.sharpe_zero_cash),
                "sortino": _finite(strategy_sortino),
                "benchmark_sortino": _finite(benchmark_sortino),
                "max_drawdown": _finite(strategy.max_drawdown),
                "benchmark_max_drawdown": _finite(benchmark.max_drawdown),
            }
        )
    return rows


def baseline_lookup(baseline: dict[str, object]) -> dict[str, dict[str, object]]:
    lookup: dict[str, dict[str, object]] = {
        SYMBOL: {
            "evaluation_start": baseline["evaluation_start"],
            **baseline["primary_metrics"],
        }
    }
    cross_market = baseline.get("cross_market")
    if isinstance(cross_market, dict):
        for group in cross_market.get("groups", []):
            for row in group["rows"]:
                lookup[str(row["symbol"])] = row
    return lookup


def cross_market_row(
    symbol: str,
    name: str,
    group: str,
    close: pd.Series,
    original: dict[str, object],
) -> dict[str, object]:
    _, metrics = run_strategy(close, str(original["evaluation_start"]))
    latest = build_signal_frame(close).iloc[-1]

    def delta(candidate_key: str, original_key: str) -> float | None:
        candidate = metrics[candidate_key]
        old = original.get(original_key)
        if candidate is None or old is None:
            return None
        return _finite(float(candidate) - float(old))

    return {
        "symbol": symbol,
        "name": name,
        "group": group,
        "evaluation_start": str(original["evaluation_start"]),
        "evaluation_end": close.index[-1].date().isoformat(),
        "latest_position": "long" if latest["target"] > 0 else "cash",
        "trend_score": _finite(latest["trend_score"]),
        "cagr": metrics["cagr"],
        "original_cagr": original.get("cagr"),
        "benchmark_cagr": metrics["benchmark_cagr"],
        "cagr_delta_original": delta("cagr", "cagr"),
        "sharpe": metrics["sharpe_zero_cash"],
        "original_sharpe": original.get("sharpe"),
        "benchmark_sharpe": metrics["benchmark_sharpe_zero_cash"],
        "sharpe_delta_original": delta("sharpe_zero_cash", "sharpe"),
        "sortino": metrics["sortino_zero_cash"],
        "original_sortino": original.get("sortino"),
        "benchmark_sortino": metrics["benchmark_sortino_zero_cash"],
        "sortino_delta_original": delta("sortino_zero_cash", "sortino"),
        "max_drawdown": metrics["max_drawdown"],
        "original_max_drawdown": original.get("max_drawdown"),
        "benchmark_max_drawdown": metrics["benchmark_max_drawdown"],
        "drawdown_delta_original": delta("max_drawdown", "max_drawdown"),
        "market_beta": metrics["market_beta"],
        "time_in_market": metrics["time_in_market"],
        "entries": metrics["entries"],
    }


def cross_market_summary(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    def values(key: str) -> list[float]:
        return [float(row[key]) for row in rows if row.get(key) is not None]

    return {
        "count": len(rows),
        "cagr_wins_vs_original": sum(value > 0 for value in values("cagr_delta_original")),
        "sharpe_wins_vs_original": sum(value > 0 for value in values("sharpe_delta_original")),
        "sortino_wins_vs_original": sum(value > 0 for value in values("sortino_delta_original")),
        "drawdown_wins_vs_original": sum(
            value > 0 for value in values("drawdown_delta_original")
        ),
        "median_cagr_delta_original": _finite(np.median(values("cagr_delta_original"))),
        "median_sharpe_delta_original": _finite(np.median(values("sharpe_delta_original"))),
        "median_sortino_delta_original": _finite(np.median(values("sortino_delta_original"))),
        "median_drawdown_delta_original": _finite(
            np.median(values("drawdown_delta_original"))
        ),
        "cagr_wins_vs_benchmark": sum(
            float(row["cagr"]) > float(row["benchmark_cagr"]) for row in rows
        ),
        "sharpe_wins_vs_benchmark": sum(
            float(row["sharpe"]) > float(row["benchmark_sharpe"]) for row in rows
        ),
    }


def build_cross_market_report(
    baseline: dict[str, object],
    end: str | None,
) -> dict[str, object]:
    lookup = baseline_lookup(baseline)
    groups: list[dict[str, object]] = []
    for group_name, universe in (
        ("Indian indices", INDEX_UNIVERSE),
        ("Indian large caps", LARGE_CAP_UNIVERSE),
    ):
        rows = [
            cross_market_row(
                symbol,
                name,
                group_name,
                download_close(symbol, end),
                lookup[symbol],
            )
            for symbol, name in universe
        ]
        groups.append(
            {
                "name": group_name,
                "summary": cross_market_summary(rows),
                "rows": rows,
            }
        )
    return {
        "frozen_parameters": (
            "21-session fast EMA, 63-session slow EMA, 21-session EWMA volatility "
            "for score scaling only, 10 bps one-way cost, and identical execution lag"
        ),
        "large_cap_selection": (
            "The stock panel inherits the baseline's current-member sample and therefore "
            "retains survivorship bias; it is a transfer test, not a portfolio result"
        ),
        "groups": groups,
    }


def build_report(
    close: pd.Series,
    baseline: dict[str, object],
    cross_market: dict[str, object] | None,
) -> dict[str, object]:
    evaluation_start = str(baseline["evaluation_start"])
    primary_frame, primary_metrics = run_strategy(close, evaluation_start)
    sensitivity = [
        run_strategy(close, evaluation_start, fast, slow)[1]
        for fast, slow in SENSITIVITY_WINDOWS
    ]
    signal_frame = build_signal_frame(close)
    latest = signal_frame.dropna(subset=["trend_score"]).iloc[-1]
    original_metrics = baseline["primary_metrics"]

    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": "Yahoo Finance delayed NIFTY 50 price-index history (^NSEI)",
        "evaluation_start": primary_frame.index[0].date().isoformat(),
        "evaluation_end": primary_frame.index[-1].date().isoformat(),
        "name": "Volatility-normalized EMA regime",
        "formula": (
            "z_t = log(EMA_21(P_t) / EMA_63(P_t)) / "
            "(EWMA_SD_21(log returns) * sqrt(42)); long when z_t > 0, else cash"
        ),
        "assumptions": {
            "fast_span": FAST_SPAN,
            "slow_span": SLOW_SPAN,
            "volatility_span": VOLATILITY_SPAN,
            "score_horizon_gap": SLOW_SPAN - FAST_SPAN,
            "entry_threshold": 0,
            "one_way_cost": ONE_WAY_COST,
            "execution": (
                "Signal after close t; execute at close t+1; first return earned t+1 to t+2"
            ),
            "positioning": "Long 100% when the 21-session EMA is above the 63-session EMA; otherwise cash",
            "cash_return": 0,
            "dividends": "Excluded: this is a price-index test",
            "parameter_policy": (
                "The month/quarter 21/63 pair was selected for interpretation before "
                "cross-market validation; neighboring pairs are disclosed without choosing a new winner"
            ),
        },
        "primary_metrics": primary_metrics,
        "original_metrics": original_metrics,
        "latest_signal": {
            "date": latest.name.date().isoformat(),
            "position": "long" if latest["target"] > 0 else "cash",
            "trend_score": _finite(latest["trend_score"]),
            "ema_spread": _finite(latest["ema_spread"]),
            "fast_ema": _finite(latest["fast_ema"]),
            "slow_ema": _finite(latest["slow_ema"]),
            "daily_sd": _finite(latest["daily_sd"]),
            "annualized_sd": _finite(latest["annualized_sd"]),
        },
        "comparison": {
            "cagr_delta_original": _finite(
                float(primary_metrics["cagr"]) - float(original_metrics["cagr"])
            ),
            "sharpe_delta_original": _finite(
                float(primary_metrics["sharpe_zero_cash"])
                - float(original_metrics["sharpe_zero_cash"])
            ),
            "sortino_delta_original": _finite(
                float(primary_metrics["sortino_zero_cash"])
                - float(original_metrics["sortino_zero_cash"])
            ),
            "drawdown_delta_original": _finite(
                float(primary_metrics["max_drawdown"])
                - float(original_metrics["max_drawdown"])
            ),
            "total_return_delta_original": _finite(
                float(primary_metrics["total_return"])
                - float(original_metrics["total_return"])
            ),
        },
        "chart": chart_points(primary_frame, baseline["chart"]),
        "yearly_returns": yearly_returns(primary_frame, baseline["yearly_returns"]),
        "subperiods": period_metrics(primary_frame),
        "sensitivity": sensitivity,
        "cross_market": cross_market,
        "design_rationale": [
            "Retains the useful idea that persistent price direction can define a market regime.",
            "Removes the annualized-slope versus daily-volatility unit mismatch.",
            "Makes no normal, transformed-normal, IID, or next-day point-forecast claim.",
            "Uses volatility only to put the displayed trend distance on a comparable scale.",
            "Uses fixed month/quarter horizons and validates them unchanged across Indian assets.",
        ],
        "limitations": [
            "A crossover is still a lagging rule and can be whipsawed in sideways markets.",
            "The NIFTY price index excludes dividends and is not itself directly tradable.",
            "Zero cash yield understates results when short-term rates are positive.",
            "The current large-cap sample has survivorship bias and is not a constituent-history portfolio.",
            "The 21/63 choice is economically motivated but still needs genuinely unseen forward data.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("apps/web/data/custom-signal.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/data/alternative-signal.json"),
    )
    parser.add_argument("--skip-cross-market", action="store_true")
    arguments = parser.parse_args()

    baseline = json.loads(arguments.baseline.read_text(encoding="utf-8"))
    close = download_close(arguments.symbol, arguments.end)
    cross_market = (
        None
        if arguments.skip_cross_market
        else build_cross_market_report(baseline, arguments.end)
    )
    report = build_report(close, baseline, cross_market)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {arguments.output} through {report['evaluation_end']}")


if __name__ == "__main__":
    main()
