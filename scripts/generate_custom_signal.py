#!/usr/bin/env python3
"""Generate the walk-forward EquityLens custom probability signal report."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from scripts.generate_beta_r2_backtest import (
    ONE_WAY_COST,
    TRADING_DAYS,
    _finite,
    download_close,
    performance_metrics,
    regression_signal,
)


SYMBOL = "^NSEI"
LOOKBACK = 63
MINIMUM_TRAINING_ROWS = 504
REFIT_EVERY = 21
PDF_WINDOW = 756
EWMA_SPAN = 21
BETA_BINOMIAL_PRIOR_STRENGTH = 20.0
MAX_EXPECTED_WINDOW = 63
VOLATILITY_THRESHOLD_QUANTILE = 0.50
VOLATILITY_THRESHOLD_MINIMUM_ROWS = 126
VOLATILITY_THRESHOLD_QUANTILES = (0.25, 0.40, 0.50, 0.60, 0.75)

INDEX_UNIVERSE = (
    ("^BSESN", "S&P BSE Sensex"),
    ("^CNX100", "NIFTY 100"),
    ("^NSEMDCP50", "NIFTY Midcap 50"),
    ("^NSEBANK", "NIFTY Bank"),
    ("^CNXIT", "NIFTY IT"),
    ("^CNXPHARMA", "NIFTY Pharma"),
)

LARGE_CAP_UNIVERSE = (
    ("HDFCBANK.NS", "HDFC Bank"),
    ("ICICIBANK.NS", "ICICI Bank"),
    ("RELIANCE.NS", "Reliance Industries"),
    ("BHARTIARTL.NS", "Bharti Airtel"),
    ("LT.NS", "Larsen & Toubro"),
    ("INFY.NS", "Infosys"),
    ("SBIN.NS", "State Bank of India"),
    ("AXISBANK.NS", "Axis Bank"),
    ("KOTAKBANK.NS", "Kotak Mahindra Bank"),
    ("ITC.NS", "ITC"),
)

def build_model_frame(close: pd.Series, lookback: int = LOOKBACK) -> pd.DataFrame:
    trend = regression_signal(close, lookback)
    log_return = np.log(close).diff()
    simple_return = close.pct_change()
    frame = trend.copy()
    frame["return_1d"] = log_return
    frame["simple_return"] = simple_return
    frame["ewma_daily_sd"] = log_return.ewm(
        span=EWMA_SPAN, adjust=False, min_periods=EWMA_SPAN
    ).std()
    # Each historical shock is divided by the volatility forecast available
    # before that return occurred. Today's EWMA is the forecast for tomorrow.
    frame["forecast_daily_sd"] = frame["ewma_daily_sd"].shift(1)
    frame["standardized_return"] = frame["return_1d"] / frame["forecast_daily_sd"]
    frame["predicted_return"] = np.expm1(frame["beta_daily"])
    frame["standardized_forecast"] = (
        frame["predicted_return"] / frame["ewma_daily_sd"]
    )
    frame["next_return"] = simple_return.shift(-1)
    return frame.dropna(
        subset=["beta_daily", "annualized_slope", "r_squared", "standardized_return"]
    )


def beta_binomial_adjustment(
    raw_probability: float,
    completed_hits: np.ndarray,
) -> tuple[float, int, int, int]:
    """Locally calibrate a Bernoulli event using its expected waiting window."""
    expected_window = int(
        np.clip(math.ceil(1 / max(raw_probability, 1e-6)), 2, MAX_EXPECTED_WINDOW)
    )
    recent_hits = completed_hits[-expected_window:]
    observations = int(len(recent_hits))
    hits = int(recent_hits.sum())
    adjusted = (
        BETA_BINOMIAL_PRIOR_STRENGTH * raw_probability + hits
    ) / (BETA_BINOMIAL_PRIOR_STRENGTH + observations)
    return float(adjusted), expected_window, observations, hits


def yeo_johnson_tail_probability(
    predicted_return: float,
    conditional_sd: float,
    fitted_lambda: float,
    transformed_mean: float,
    transformed_sd: float,
) -> float:
    """Probability of meeting the signed forecast under the transformed PDF."""
    threshold_standardized = predicted_return / conditional_sd
    threshold_transformed = float(
        stats.yeojohnson(threshold_standardized, lmbda=fitted_lambda)
    )
    z_score = (threshold_transformed - transformed_mean) / transformed_sd
    probability = stats.norm.sf(z_score) if predicted_return >= 0 else stats.norm.cdf(z_score)
    return float(np.clip(probability, 1e-6, 1 - 1e-6))


def walk_forward_probabilities(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """Fit the Yeo–Johnson PDF and event-window adjustment without look-ahead."""
    count = len(frame)
    raw_probability = np.full(count, np.nan)
    adjusted_probability = np.full(count, np.nan)
    base_probability = np.full(count, np.nan)
    expected_window = np.full(count, np.nan)
    window_observations = np.full(count, np.nan)
    events_in_window = np.full(count, np.nan)
    days_since_hit = np.full(count, np.nan)
    lambdas = np.full(count, np.nan)
    transformed_means = np.full(count, np.nan)
    transformed_sds = np.full(count, np.nan)
    predicted = frame["predicted_return"].to_numpy(dtype=float)
    conditional_sd = frame["ewma_daily_sd"].to_numpy(dtype=float)
    standardized = frame["standardized_return"].to_numpy(dtype=float)
    next_return = frame["next_return"].to_numpy(dtype=float)
    hit = np.full(count, np.nan)

    latest_parameters: dict[str, float] = {}
    for index in range(MINIMUM_TRAINING_ROWS, count):
        if index == MINIMUM_TRAINING_ROWS or (index - MINIMUM_TRAINING_ROWS) % REFIT_EVERY == 0:
            start = max(0, index + 1 - PDF_WINDOW)
            training = standardized[start : index + 1]
            training = training[np.isfinite(training)]
            fitted_lambda = float(stats.yeojohnson_normmax(training, brack=(-2.0, 2.0)))
            transformed = stats.yeojohnson(training, lmbda=fitted_lambda)
            transformed_mean = float(transformed.mean())
            transformed_sd = float(transformed.std(ddof=1))
            latest_parameters = {
                "yeo_johnson_lambda": fitted_lambda,
                "transformed_mean": transformed_mean,
                "transformed_sd": transformed_sd,
                "pdf_training_rows": float(len(training)),
            }

        probability = yeo_johnson_tail_probability(
            predicted[index],
            conditional_sd[index],
            fitted_lambda,
            transformed_mean,
            transformed_sd,
        )
        raw_probability[index] = probability
        lambdas[index] = fitted_lambda
        transformed_means[index] = transformed_mean
        transformed_sds[index] = transformed_sd

        completed = hit[:index]
        completed = completed[np.isfinite(completed)]
        adjusted, window, observations, hits = beta_binomial_adjustment(probability, completed)
        adjusted_probability[index] = adjusted
        expected_window[index] = window
        window_observations[index] = observations
        events_in_window[index] = hits
        base_probability[index] = float(completed.mean()) if len(completed) else np.nan
        hit_locations = np.flatnonzero(completed > 0.5)
        days_since_hit[index] = (
            float(len(completed) - 1 - hit_locations[-1]) if len(hit_locations) else float(len(completed))
        )

        if np.isfinite(next_return[index]):
            hit[index] = float(
                next_return[index] >= predicted[index]
                if predicted[index] >= 0
                else next_return[index] <= predicted[index]
            )

    predictions = frame.copy()
    predictions["raw_probability"] = raw_probability
    predictions["adjusted_probability"] = adjusted_probability
    predictions["base_probability"] = base_probability
    predictions["forecast_hit"] = hit
    predictions["expected_window"] = expected_window
    predictions["window_observations"] = window_observations
    predictions["events_in_window"] = events_in_window
    predictions["days_since_hit"] = days_since_hit
    predictions["yeo_johnson_lambda"] = lambdas
    predictions["transformed_mean"] = transformed_means
    predictions["transformed_sd"] = transformed_sds
    predictions["raw_custom_score"] = (
        predictions["annualized_slope"] * predictions["raw_probability"]
    )
    predictions["custom_score"] = (
        predictions["annualized_slope"] * predictions["adjusted_probability"]
    )
    return predictions, latest_parameters


def probability_metrics(frame: pd.DataFrame) -> dict[str, float | int | None]:
    scored = frame.dropna(
        subset=["forecast_hit", "raw_probability", "adjusted_probability", "base_probability"]
    )

    def brier(probability: pd.Series) -> float:
        return float(np.square(probability - scored["forecast_hit"]).mean())

    def log_loss(probability: pd.Series) -> float:
        clipped = probability.clip(1e-7, 1 - 1e-7)
        target = scored["forecast_hit"]
        return float(-(target * np.log(clipped) + (1 - target) * np.log(1 - clipped)).mean())

    return {
        "raw_brier": _finite(brier(scored["raw_probability"])),
        "adjusted_brier": _finite(brier(scored["adjusted_probability"])),
        "base_brier": _finite(brier(scored["base_probability"])),
        "raw_log_loss": _finite(log_loss(scored["raw_probability"])),
        "adjusted_log_loss": _finite(log_loss(scored["adjusted_probability"])),
        "hit_rate": _finite(scored["forecast_hit"].mean()),
        "mean_raw_probability": _finite(scored["raw_probability"].mean()),
        "mean_adjusted_probability": _finite(scored["adjusted_probability"].mean()),
        "mean_expected_window": _finite(scored["expected_window"].mean()),
        "window_with_event_rate": _finite((scored["events_in_window"] > 0).mean()),
        "forecast_count": int(len(scored)),
    }


def calibration_bins(
    frame: pd.DataFrame, probability_column: str
) -> list[dict[str, float | int | None]]:
    scored = frame.dropna(subset=["forecast_hit", probability_column]).copy()
    scored["bin"] = pd.qcut(scored[probability_column], 5, labels=False, duplicates="drop")
    return [
        {
            "bin": int(bin_number) + 1,
            "predicted": _finite(group[probability_column].mean()),
            "observed": _finite(group["forecast_hit"].mean()),
            "count": int(len(group)),
        }
        for bin_number, group in scored.groupby("bin", observed=True)
    ]


def downside_metrics(returns: pd.Series) -> tuple[float, float]:
    """Annualized downside deviation and Sortino ratio at a zero-percent MAR."""
    downside_deviation = float(
        np.sqrt(np.square(np.minimum(returns.to_numpy(dtype=float), 0)).mean())
        * math.sqrt(TRADING_DAYS)
    )
    sortino = (
        float(returns.mean() * TRADING_DAYS / downside_deviation)
        if downside_deviation > 0
        else math.nan
    )
    return downside_deviation, sortino


def expanding_volatility_percentile_threshold(
    predictions: pd.DataFrame,
    quantile: float = VOLATILITY_THRESHOLD_QUANTILE,
) -> pd.Series:
    """Point-in-time daily-volatility cutoff using only completed observations."""
    return (
        predictions["ewma_daily_sd"]
        .shift(1)
        .expanding(min_periods=VOLATILITY_THRESHOLD_MINIMUM_ROWS)
        .quantile(quantile)
    )


def run_strategy(
    predictions: pd.DataFrame,
    close: pd.Series,
    threshold: float | pd.Series,
    evaluation_start: pd.Timestamp | None = None,
    threshold_quantile: float | None = None,
) -> tuple[pd.DataFrame, dict[str, float | int | None]]:
    if isinstance(threshold, pd.Series):
        threshold_series = threshold.reindex(predictions.index)
        threshold_method = "expanding_daily_sd_percentile"
    else:
        threshold_series = pd.Series(float(threshold), index=predictions.index)
        threshold_method = "fixed_score_threshold"
    signal_is_valid = predictions["custom_score"].notna() & threshold_series.notna()
    target = (predictions["custom_score"] > threshold_series).astype(float).where(
        signal_is_valid, 0.0
    )
    active_position = target.shift(2).fillna(0.0)
    turnover = (target.shift(1).fillna(0.0) - target.shift(2).fillna(0.0)).abs()
    benchmark_return = close.pct_change().reindex(predictions.index).fillna(0.0)
    strategy_return = active_position * benchmark_return - turnover * ONE_WAY_COST
    model_start = predictions["custom_score"].first_valid_index()
    threshold_start = threshold_series.first_valid_index()
    if model_start is None or threshold_start is None:
        raise RuntimeError("The walk-forward model did not produce any forecasts")
    model_start = max(model_start, threshold_start)
    evaluation_start = (
        model_start
        if evaluation_start is None
        else max(model_start, pd.Timestamp(evaluation_start))
    )
    report = predictions.copy()
    report["signal_threshold"] = threshold_series
    report["benchmark_return"] = benchmark_return
    report["strategy_return"] = strategy_return
    report["position"] = active_position
    report["turnover"] = turnover
    report = report.loc[evaluation_start:]
    # The comparison starts with one unit of capital at the evaluation-start
    # close, so neither series receives the preceding close-to-close return.
    report.iloc[0, report.columns.get_loc("benchmark_return")] = 0.0
    report.iloc[0, report.columns.get_loc("strategy_return")] = 0.0
    report["strategy_equity"] = (1 + report["strategy_return"]).cumprod()
    report["benchmark_equity"] = (1 + report["benchmark_return"]).cumprod()
    report["strategy_drawdown"] = report["strategy_equity"] / report["strategy_equity"].cummax() - 1
    report["benchmark_drawdown"] = report["benchmark_equity"] / report["benchmark_equity"].cummax() - 1
    strategy = performance_metrics(report["strategy_return"], report["strategy_equity"])
    benchmark = performance_metrics(report["benchmark_return"], report["benchmark_equity"])

    strategy_downside_deviation, strategy_sortino = downside_metrics(report["strategy_return"])
    benchmark_downside_deviation, benchmark_sortino = downside_metrics(report["benchmark_return"])
    market_variance = float(report["benchmark_return"].var(ddof=1))
    market_beta = float(report["strategy_return"].cov(report["benchmark_return"])) / market_variance
    entries = int(((target.shift(1).fillna(0) > target.shift(2).fillna(0)).loc[evaluation_start:]).sum())
    exits = int(((target.shift(1).fillna(0) < target.shift(2).fillna(0)).loc[evaluation_start:]).sum())
    return report, {
        "threshold": _finite(threshold_series.loc[evaluation_start:].dropna().iloc[-1]),
        "threshold_method": threshold_method,
        "threshold_quantile": _finite(threshold_quantile),
        "cagr": _finite(strategy.cagr),
        "annualized_volatility": _finite(strategy.annualized_volatility),
        "sharpe_zero_cash": _finite(strategy.sharpe_zero_cash),
        "sortino_zero_cash": _finite(strategy_sortino),
        "annualized_downside_deviation": _finite(strategy_downside_deviation),
        "max_drawdown": _finite(strategy.max_drawdown),
        "total_return": _finite(strategy.total_return),
        "market_beta": _finite(market_beta),
        "benchmark_cagr": _finite(benchmark.cagr),
        "benchmark_annualized_volatility": _finite(benchmark.annualized_volatility),
        "benchmark_sharpe_zero_cash": _finite(benchmark.sharpe_zero_cash),
        "benchmark_sortino_zero_cash": _finite(benchmark_sortino),
        "benchmark_annualized_downside_deviation": _finite(benchmark_downside_deviation),
        "benchmark_max_drawdown": _finite(benchmark.max_drawdown),
        "benchmark_total_return": _finite(benchmark.total_return),
        "time_in_market": _finite(report["position"].mean()),
        "entries": entries,
        "exits": exits,
    }


def chart_points(frame: pd.DataFrame) -> list[dict[str, float | str | None]]:
    sampled = frame.resample("W-FRI").last().dropna(subset=["strategy_equity"])
    if sampled.index[-1] != frame.index[-1]:
        sampled = pd.concat([sampled, frame.iloc[[-1]]]).sort_index()
    columns = (
        "strategy_equity",
        "benchmark_equity",
        "strategy_drawdown",
        "benchmark_drawdown",
        "annualized_slope",
        "predicted_return",
        "raw_probability",
        "adjusted_probability",
        "raw_custom_score",
        "custom_score",
        "signal_threshold",
        "position",
    )
    return [
        {"date": index.date().isoformat()}
        | {column: _finite(row[column], 6) for column in columns}
        for index, row in sampled.iterrows()
    ]


def yearly_returns(frame: pd.DataFrame) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for year, values in frame.groupby(frame.index.year):
        long = values["position"] > 0.5
        cash = ~long
        missed = values.loc[cash].sort_values("benchmark_return", ascending=False)
        held = values.loc[long].sort_values("benchmark_return")
        results.append(
            {
                "year": int(year),
                "strategy": _finite((1 + values["strategy_return"]).prod() - 1, 6),
                "benchmark": _finite((1 + values["benchmark_return"]).prod() - 1, 6),
                "gross_strategy": _finite(
                    (1 + values["position"] * values["benchmark_return"]).prod() - 1,
                    6,
                ),
                "time_in_market": _finite(long.mean(), 6),
                "switches": int(values["turnover"].sum()),
                "cost_debit_sum": _finite(values["turnover"].sum() * ONE_WAY_COST, 6),
                "long_day_market_sum": _finite(values.loc[long, "benchmark_return"].sum(), 6),
                "cash_day_market_sum": _finite(values.loc[cash, "benchmark_return"].sum(), 6),
                "best_missed_day": (
                    {
                        "date": missed.index[0].date().isoformat(),
                        "return": _finite(missed["benchmark_return"].iloc[0], 6),
                    }
                    if not missed.empty
                    else None
                ),
                "worst_held_day": (
                    {
                        "date": held.index[0].date().isoformat(),
                        "return": _finite(held["benchmark_return"].iloc[0], 6),
                    }
                    if not held.empty
                    else None
                ),
                "quarters": [
                    {
                        "quarter": int(quarter),
                        "strategy": _finite((1 + quarter_values["strategy_return"]).prod() - 1, 6),
                        "benchmark": _finite((1 + quarter_values["benchmark_return"]).prod() - 1, 6),
                        "time_in_market": _finite((quarter_values["position"] > 0.5).mean(), 6),
                    }
                    for quarter, quarter_values in values.groupby(values.index.quarter)
                ],
            }
        )
    return results


def standard_deviation_views(predictions: pd.DataFrame) -> dict[str, object]:
    valid = predictions.dropna(subset=["raw_probability", "ewma_daily_sd", "return_1d"]).copy()
    valid["daily_sd"] = valid["ewma_daily_sd"]
    # Compare each realized return with the SD forecast available at the prior
    # close. Using same-day SD would let the observation widen its own band.
    valid["forecast_daily_sd"] = valid["daily_sd"].shift(1)
    valid["standardized_return"] = valid["return_1d"] / valid["forecast_daily_sd"]
    weekly = valid.resample("W-FRI").last().dropna(subset=["ewma_daily_sd"])
    if weekly.index[-1] != valid.index[-1]:
        weekly = pd.concat([weekly, valid.iloc[[-1]]]).sort_index()
    recent = valid.dropna(subset=["forecast_daily_sd"]).tail(TRADING_DAYS)
    absolute_z = valid["standardized_return"].dropna().abs()
    return {
        "summary": {
            "current_daily_sd": _finite(valid["daily_sd"].iloc[-1]),
            "mean_daily_sd": _finite(valid["daily_sd"].mean()),
            "median_daily_sd": _finite(valid["daily_sd"].median()),
            "p10_daily_sd": _finite(valid["daily_sd"].quantile(0.10)),
            "p25_daily_sd": _finite(valid["daily_sd"].quantile(0.25)),
            "p75_daily_sd": _finite(valid["daily_sd"].quantile(0.75)),
            "p90_daily_sd": _finite(valid["daily_sd"].quantile(0.90)),
            "share_daily_sd_above_1pct": _finite((valid["daily_sd"] > 0.01).mean()),
            "absolute_return_above_1pct": _finite((valid["simple_return"].abs() >= 0.01).mean()),
            "up_return_above_1pct": _finite((valid["simple_return"] >= 0.01).mean()),
            "down_return_below_1pct": _finite((valid["simple_return"] <= -0.01).mean()),
            "current_annualized_sd": _finite(valid["ewma_daily_sd"].iloc[-1] * math.sqrt(TRADING_DAYS)),
            "median_annualized_sd": _finite(valid["ewma_daily_sd"].median() * math.sqrt(TRADING_DAYS)),
            "p90_annualized_sd": _finite(valid["ewma_daily_sd"].quantile(0.90) * math.sqrt(TRADING_DAYS)),
            "within_1sd": _finite((absolute_z <= 1).mean()),
            "within_2sd": _finite((absolute_z <= 2).mean()),
            "within_3sd": _finite((absolute_z <= 3).mean()),
        },
        "history": [
            {
                "date": index.date().isoformat(),
                "annualized_sd": _finite(row["ewma_daily_sd"] * math.sqrt(TRADING_DAYS), 6),
                "daily_sd": _finite(row["ewma_daily_sd"], 6),
            }
            for index, row in weekly.iterrows()
        ],
        "recent": [
            {
                "date": index.date().isoformat(),
                "return": _finite(row["return_1d"], 6),
                "upper_1sd": _finite(row["forecast_daily_sd"], 6),
                "lower_1sd": _finite(-row["forecast_daily_sd"], 6),
            }
            for index, row in recent.iterrows()
        ],
    }


def cross_market_row(
    symbol: str,
    name: str,
    group: str,
    close: pd.Series,
) -> dict[str, object]:
    predictions, _ = walk_forward_probabilities(build_model_frame(close))
    threshold = expanding_volatility_percentile_threshold(predictions)
    report, metrics = run_strategy(
        predictions,
        close,
        threshold,
        threshold_quantile=VOLATILITY_THRESHOLD_QUANTILE,
    )
    latest = predictions.dropna(subset=["custom_score"]).iloc[-1]
    latest_threshold = float(threshold.dropna().iloc[-1])
    return {
        "symbol": symbol,
        "name": name,
        "group": group,
        "evaluation_start": report.index[0].date().isoformat(),
        "evaluation_end": report.index[-1].date().isoformat(),
        "forecast_count": int(predictions["custom_score"].notna().sum()),
        "signal_threshold": _finite(latest_threshold),
        "threshold_method": "expanding_daily_sd_percentile",
        "threshold_quantile": VOLATILITY_THRESHOLD_QUANTILE,
        "latest_position": "long" if latest["custom_score"] > latest_threshold else "cash",
        "cagr": metrics["cagr"],
        "benchmark_cagr": metrics["benchmark_cagr"],
        "cagr_delta": _finite(float(metrics["cagr"]) - float(metrics["benchmark_cagr"])),
        "sharpe": metrics["sharpe_zero_cash"],
        "benchmark_sharpe": metrics["benchmark_sharpe_zero_cash"],
        "sharpe_delta": _finite(
            float(metrics["sharpe_zero_cash"]) - float(metrics["benchmark_sharpe_zero_cash"])
        ),
        "sortino": metrics["sortino_zero_cash"],
        "benchmark_sortino": metrics["benchmark_sortino_zero_cash"],
        "sortino_delta": _finite(
            float(metrics["sortino_zero_cash"]) - float(metrics["benchmark_sortino_zero_cash"])
        ),
        "max_drawdown": metrics["max_drawdown"],
        "benchmark_max_drawdown": metrics["benchmark_max_drawdown"],
        "drawdown_improvement": _finite(
            float(metrics["max_drawdown"]) - float(metrics["benchmark_max_drawdown"])
        ),
        "market_beta": metrics["market_beta"],
        "time_in_market": metrics["time_in_market"],
        "entries": metrics["entries"],
    }


def cross_market_summary(rows: list[dict[str, object]]) -> dict[str, float | int | None]:
    return {
        "count": len(rows),
        "cagr_win_rate": _finite(np.mean([row["cagr_delta"] > 0 for row in rows])),
        "sharpe_win_rate": _finite(np.mean([row["sharpe_delta"] > 0 for row in rows])),
        "sortino_win_rate": _finite(np.mean([row["sortino_delta"] > 0 for row in rows])),
        "drawdown_win_rate": _finite(
            np.mean([row["drawdown_improvement"] > 0 for row in rows])
        ),
        "median_cagr_delta": _finite(np.median([row["cagr_delta"] for row in rows])),
        "median_sharpe_delta": _finite(np.median([row["sharpe_delta"] for row in rows])),
        "median_sortino_delta": _finite(np.median([row["sortino_delta"] for row in rows])),
        "median_drawdown_improvement": _finite(
            np.median([row["drawdown_improvement"] for row in rows])
        ),
    }


def build_cross_market_report(end: str | None) -> dict[str, object]:
    groups: list[dict[str, object]] = []
    for group_name, universe in (
        ("Indian indices", INDEX_UNIVERSE),
        ("Indian large caps", LARGE_CAP_UNIVERSE),
    ):
        rows = [
            cross_market_row(symbol, name, group_name, download_close(symbol, end))
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
            f"Same {LOOKBACK}-session beta, 756-session Yeo-Johnson PDF, 21-session EWMA, "
            "beta-binomial prior strength 20, annualized-beta probability score, each "
            "asset's point-in-time median daily SD cutoff, and 10 bps one-way cost"
        ),
        "large_cap_selection": (
            "Top ten NIFTY 50 constituents by free-float weight in the 29 May 2026 "
            "NSE Indices factsheet; this current-membership screen has survivorship bias"
        ),
        "groups": groups,
    }


def build_report(
    close: pd.Series,
    cross_market: dict[str, object] | None = None,
) -> dict[str, object]:
    model_frame = build_model_frame(close)
    predictions, pdf_parameters = walk_forward_probabilities(model_frame)
    primary_threshold = expanding_volatility_percentile_threshold(predictions)
    evaluation_start = primary_threshold.first_valid_index()
    primary_frame, primary_metrics = run_strategy(
        predictions,
        close,
        primary_threshold,
        evaluation_start,
        VOLATILITY_THRESHOLD_QUANTILE,
    )
    sensitivity = [
        run_strategy(
            predictions,
            close,
            expanding_volatility_percentile_threshold(predictions, quantile),
            evaluation_start,
            quantile,
        )[1]
        for quantile in VOLATILITY_THRESHOLD_QUANTILES
    ]
    latest = predictions.dropna(subset=["custom_score"]).iloc[-1]
    latest_threshold = float(primary_threshold.dropna().iloc[-1])
    probability = probability_metrics(predictions)
    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": "Yahoo Finance delayed NIFTY 50 price-index history (^NSEI)",
        "evaluation_start": primary_frame.index[0].date().isoformat(),
        "evaluation_end": primary_frame.index[-1].date().isoformat(),
        "formula": "custom_score = annualized_log_price_slope * beta_binomial_adjusted_Yeo_Johnson_probability",
        "assumptions": {
            "lookback_sessions": LOOKBACK,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "refit_every_sessions": REFIT_EVERY,
            "pdf_window_sessions": PDF_WINDOW,
            "ewma_span": EWMA_SPAN,
            "beta_binomial_prior_strength": BETA_BINOMIAL_PRIOR_STRENGTH,
            "maximum_expected_window": MAX_EXPECTED_WINDOW,
            "signal_threshold": latest_threshold,
            "signal_threshold_method": "Point-in-time expanding median of the asset's daily EWMA standard deviation",
            "signal_threshold_quantile": VOLATILITY_THRESHOLD_QUANTILE,
            "signal_threshold_minimum_rows": VOLATILITY_THRESHOLD_MINIMUM_ROWS,
            "one_way_cost": ONE_WAY_COST,
            "execution": "Signal after close t; execute at close t+1; first return earned t+1 to t+2",
            "positioning": "Long 100% when annualized beta times adjusted probability exceeds the asset's point-in-time expanding median daily SD; otherwise cash",
            "cash_return": 0,
            "dividends": "Excluded: this is a price-index test",
        },
        "primary_metrics": primary_metrics,
        "probability_metrics": probability,
        "latest_signal": {
            "date": latest.name.date().isoformat(),
            "daily_beta": _finite(latest["beta_daily"]),
            "annualized_beta": _finite(latest["annualized_slope"]),
            "daily_beta_forecast": _finite(latest["predicted_return"]),
            "standardized_daily_forecast": _finite(latest["standardized_forecast"]),
            "r_squared": _finite(latest["r_squared"]),
            "conditional_daily_sd": _finite(latest["ewma_daily_sd"]),
            "raw_probability": _finite(latest["raw_probability"]),
            "adjusted_probability": _finite(latest["adjusted_probability"]),
            "raw_custom_score": _finite(latest["raw_custom_score"]),
            "custom_score": _finite(latest["custom_score"]),
            "signal_threshold": _finite(latest_threshold),
            "position": "long" if latest["custom_score"] > latest_threshold else "cash",
            "expected_window": int(latest["expected_window"]),
            "window_observations": int(latest["window_observations"]),
            "events_in_window": int(latest["events_in_window"]),
            "days_since_hit": int(latest["days_since_hit"]),
            "yeo_johnson_lambda": _finite(latest["yeo_johnson_lambda"]),
            "transformed_mean": _finite(latest["transformed_mean"]),
            "transformed_sd": _finite(latest["transformed_sd"]),
        },
        "latest_pdf_parameters": {
            key: _finite(value) for key, value in pdf_parameters.items()
        },
        "raw_calibration": calibration_bins(predictions, "raw_probability"),
        "adjusted_calibration": calibration_bins(predictions, "adjusted_probability"),
        "chart": chart_points(primary_frame),
        "yearly_returns": yearly_returns(primary_frame),
        "sensitivity": sensitivity,
        "standard_deviation": standard_deviation_views(predictions),
        "cross_market": cross_market,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--skip-cross-market",
        action="store_true",
        help="Generate only the primary symbol report",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/data/custom-signal.json"),
    )
    arguments = parser.parse_args()
    close = download_close(arguments.symbol, arguments.end)
    cross_market = None if arguments.skip_cross_market else build_cross_market_report(arguments.end)
    report = build_report(close, cross_market)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {arguments.output} through {report['evaluation_end']}")


if __name__ == "__main__":
    main()
