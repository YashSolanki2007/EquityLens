#!/usr/bin/env python3
"""Generate the development-only five-session ensemble signal experiment.

Every forecast is made with information available after the forecast date's
close. A target attached to date t is log(close[t + 5] / close[t]); that row is
not eligible for training or error calibration until t + 5 has completed.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.generate_beta_r2_backtest import (
    ONE_WAY_COST,
    _finite,
    download_close,
    performance_metrics,
    regression_signal,
)
from scripts.generate_custom_signal import downside_metrics, rolling_score_percentile


SYMBOL = "^NSEI"
FORECAST_HORIZON = 5
MINIMUM_TRAINING_ROWS = 504
TRAINING_WINDOW = 756
REFIT_EVERY = 21
ERROR_WINDOW = 252
MINIMUM_ERROR_ROWS = 63
RIDGE_ALPHA = 10.0
BOOSTING_ITERATIONS = 60
EDGE_PERCENTILE_LOOKBACK = 252
ENTRY_EDGE_PERCENTILE = 0.70
EXIT_EDGE_PERCENTILE = 0.40
ENTRY_PROBABILITY = 0.60
ROUND_TRIP_COST = 2 * ONE_WAY_COST
MODEL_NAMES = ("ridge", "kalman", "boosting")


def build_feature_frame(close: pd.Series) -> pd.DataFrame:
    """Point-in-time features and a five-session future log-return target."""

    log_price = np.log(close)
    returns = log_price.diff()
    trend_21 = regression_signal(close, 21)
    trend_63 = regression_signal(close, 63)
    frame = pd.DataFrame(index=close.index)
    frame["close"] = close
    frame["return_1d"] = returns
    frame["momentum_5d"] = log_price.diff(5)
    frame["momentum_21d"] = log_price.diff(21)
    frame["momentum_63d"] = log_price.diff(63)
    frame["slope_21d"] = trend_21["beta_daily"]
    frame["slope_63d"] = trend_63["beta_daily"]
    frame["trend_fit_21d"] = trend_21["r_squared"]
    frame["trend_fit_63d"] = trend_63["r_squared"]
    frame["volatility_5d"] = returns.rolling(5).std()
    frame["volatility_21d"] = returns.rolling(21).std()
    frame["volatility_63d"] = returns.rolling(63).std()
    frame["volatility_ratio"] = frame["volatility_5d"] / frame["volatility_21d"]
    frame["drawdown_21d"] = close / close.rolling(21).max() - 1
    frame["drawdown_63d"] = close / close.rolling(63).max() - 1
    frame["ma_gap_21d"] = close / close.rolling(21).mean() - 1
    frame["ma_gap_63d"] = close / close.rolling(63).mean() - 1
    frame["target_5d"] = log_price.shift(-FORECAST_HORIZON) - log_price
    return frame


FEATURE_COLUMNS = (
    "return_1d",
    "momentum_5d",
    "momentum_21d",
    "momentum_63d",
    "slope_21d",
    "slope_63d",
    "trend_fit_21d",
    "trend_fit_63d",
    "volatility_5d",
    "volatility_21d",
    "volatility_63d",
    "volatility_ratio",
    "drawdown_21d",
    "drawdown_63d",
    "ma_gap_21d",
    "ma_gap_63d",
)


def kalman_trend_forecast(log_price: pd.Series, horizon: int = FORECAST_HORIZON) -> pd.Series:
    """Causal local-linear-trend Kalman filter with adaptive process noise."""

    values = log_price.to_numpy(dtype=float)
    result = np.full(len(values), np.nan)
    state = np.array([values[0], 0.0], dtype=float)
    covariance = np.diag([1e-4, 1e-6])
    transition = np.array([[1.0, 1.0], [0.0, 1.0]])
    observation = np.array([[1.0, 0.0]])
    identity = np.eye(2)
    recent_returns: list[float] = []

    for index, observed in enumerate(values):
        if index:
            recent_returns.append(values[index] - values[index - 1])
        variance = (
            float(np.var(recent_returns[-63:], ddof=1))
            if len(recent_returns) >= 21
            else 1e-4
        )
        variance = max(variance, 1e-8)
        process_noise = np.diag([0.04 * variance, 0.002 * variance])
        measurement_noise = max(0.20 * variance, 1e-8)

        if index:
            state = transition @ state
            covariance = transition @ covariance @ transition.T + process_noise
        innovation = observed - float((observation @ state)[0])
        innovation_variance = float((observation @ covariance @ observation.T)[0, 0]) + measurement_noise
        gain = covariance @ observation.T / innovation_variance
        state = state + gain[:, 0] * innovation
        covariance = (identity - gain @ observation) @ covariance

        projected = state.copy()
        for _ in range(horizon):
            projected = transition @ projected
        result[index] = projected[0] - observed

    return pd.Series(result, index=log_price.index, name="kalman")


def _normal_probability_above_cost(mean: float, sd: float) -> float:
    if not math.isfinite(sd) or sd <= 0:
        return math.nan
    return float(stats.norm.cdf((mean - ROUND_TRIP_COST) / sd))


def walk_forward_ensemble(frame: pd.DataFrame) -> pd.DataFrame:
    """Produce causal component forecasts, rolling weights and uncertainty."""

    count = len(frame)
    forecasts = {name: np.full(count, np.nan) for name in MODEL_NAMES}
    weights = {name: np.full(count, np.nan) for name in MODEL_NAMES}
    model_sd = {name: np.full(count, np.nan) for name in MODEL_NAMES}
    ensemble = np.full(count, np.nan)
    uncertainty = np.full(count, np.nan)
    lower_80 = np.full(count, np.nan)
    upper_80 = np.full(count, np.nan)
    lower_90 = np.full(count, np.nan)
    upper_90 = np.full(count, np.nan)
    positive_probability = np.full(count, np.nan)
    agreement = np.full(count, np.nan)

    features = frame.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float)
    target = frame["target_5d"].to_numpy(dtype=float)
    forecasts["kalman"] = kalman_trend_forecast(np.log(frame["close"])).to_numpy()
    ridge_model = None
    boosting_model = None
    last_refit = -REFIT_EVERY

    for index in range(count):
        if not np.isfinite(features[index]).all():
            continue
        last_completed_target = index - FORECAST_HORIZON
        eligible = np.arange(max(0, last_completed_target - TRAINING_WINDOW + 1), last_completed_target + 1)
        if len(eligible):
            valid = np.isfinite(features[eligible]).all(axis=1) & np.isfinite(target[eligible])
            eligible = eligible[valid]
        if len(eligible) < MINIMUM_TRAINING_ROWS:
            continue

        if ridge_model is None or index - last_refit >= REFIT_EVERY:
            training_x = features[eligible]
            training_y = target[eligible]
            ridge_model = make_pipeline(StandardScaler(), Ridge(alpha=RIDGE_ALPHA))
            ridge_model.fit(training_x, training_y)
            boosting_model = HistGradientBoostingRegressor(
                learning_rate=0.05,
                max_iter=BOOSTING_ITERATIONS,
                max_depth=2,
                min_samples_leaf=30,
                l2_regularization=10.0,
                random_state=7,
            )
            boosting_model.fit(training_x, training_y)
            last_refit = index

        current_x = features[index].reshape(1, -1)
        forecasts["ridge"][index] = float(ridge_model.predict(current_x)[0])
        forecasts["boosting"][index] = float(boosting_model.predict(current_x)[0])

        completed_forecast_end = index - FORECAST_HORIZON
        error_indices = np.arange(max(0, completed_forecast_end - ERROR_WINDOW + 1), completed_forecast_end + 1)
        errors: dict[str, np.ndarray] = {}
        for name in MODEL_NAMES:
            values = forecasts[name][error_indices]
            actual = target[error_indices]
            valid_error = np.isfinite(values) & np.isfinite(actual)
            errors[name] = actual[valid_error] - values[valid_error]

        fallback_sd = float(np.std(target[eligible[-ERROR_WINDOW:]], ddof=1))
        rmses = []
        for name in MODEL_NAMES:
            residual = errors[name]
            sd = (
                float(np.sqrt(np.mean(np.square(residual))))
                if len(residual) >= MINIMUM_ERROR_ROWS
                else fallback_sd
            )
            sd = max(sd, 1e-6)
            model_sd[name][index] = sd
            rmses.append(sd)

        inverse_error = 1 / np.square(np.asarray(rmses))
        raw_weights = inverse_error / inverse_error.sum()
        # A 25% equal-weight blend prevents one recently lucky model dominating.
        current_weights = 0.75 * raw_weights + 0.25 / len(MODEL_NAMES)
        current_forecasts = np.asarray([forecasts[name][index] for name in MODEL_NAMES])
        mean = float(np.dot(current_weights, current_forecasts))
        variance = float(
            np.dot(
                current_weights,
                np.square(np.asarray(rmses)) + np.square(current_forecasts - mean),
            )
        )
        sd = math.sqrt(max(variance, 1e-12))
        ensemble[index] = mean
        uncertainty[index] = sd
        positive_probability[index] = _normal_probability_above_cost(mean, sd)
        agreement[index] = float(np.sum(current_forecasts > ROUND_TRIP_COST))
        for model_index, name in enumerate(MODEL_NAMES):
            weights[name][index] = current_weights[model_index]

        completed_ensemble = ensemble[error_indices]
        actual = target[error_indices]
        valid_ensemble = np.isfinite(completed_ensemble) & np.isfinite(actual)
        absolute_error = np.abs(actual[valid_ensemble] - completed_ensemble[valid_ensemble])
        if len(absolute_error) >= MINIMUM_ERROR_ROWS:
            radius_80 = float(np.quantile(absolute_error, 0.80, method="higher"))
            radius_90 = float(np.quantile(absolute_error, 0.90, method="higher"))
            lower_80[index], upper_80[index] = mean - radius_80, mean + radius_80
            lower_90[index], upper_90[index] = mean - radius_90, mean + radius_90

    result = frame.copy()
    for name in MODEL_NAMES:
        result[f"{name}_forecast"] = forecasts[name]
        result[f"{name}_weight"] = weights[name]
        result[f"{name}_error_sd"] = model_sd[name]
    result["ensemble_forecast"] = ensemble
    result["forecast_uncertainty"] = uncertainty
    result["lower_80"] = lower_80
    result["upper_80"] = upper_80
    result["lower_90"] = lower_90
    result["upper_90"] = upper_90
    result["positive_probability"] = positive_probability
    result["model_agreement"] = agreement
    result["confidence_edge"] = (
        result["ensemble_forecast"] - ROUND_TRIP_COST
    ) / result["forecast_uncertainty"]
    result["edge_percentile"] = rolling_score_percentile(
        result["confidence_edge"],
        EDGE_PERCENTILE_LOOKBACK,
        MINIMUM_ERROR_ROWS,
    )
    return result


def run_ensemble_strategy(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float | int | None]]:
    """Apply fixed, predeclared hysteresis rules to the forecast stream."""

    target_position = np.zeros(len(frame), dtype=float)
    current = 0.0
    for index, row in enumerate(frame.itertuples()):
        valid = all(
            math.isfinite(value)
            for value in (row.edge_percentile, row.positive_probability, row.model_agreement)
        )
        if not valid:
            target_position[index] = current
            continue
        if current == 0 and (
            row.edge_percentile >= ENTRY_EDGE_PERCENTILE
            and row.positive_probability >= ENTRY_PROBABILITY
            and row.model_agreement >= 2
        ):
            current = 1.0
        elif current == 1 and (
            row.edge_percentile <= EXIT_EDGE_PERCENTILE
            or row.positive_probability <= 0.50
            or row.model_agreement <= 1
        ):
            current = 0.0
        target_position[index] = current

    result = frame.copy()
    target_series = pd.Series(target_position, index=frame.index)
    result["position"] = target_series.shift(2).fillna(0.0)
    result["turnover"] = (
        target_series.shift(1).fillna(0.0) - target_series.shift(2).fillna(0.0)
    ).abs()
    result["benchmark_return"] = result["close"].pct_change().fillna(0.0)
    result["strategy_return"] = (
        result["position"] * result["benchmark_return"] - result["turnover"] * ONE_WAY_COST
    )
    first = result["edge_percentile"].first_valid_index()
    if first is None:
        raise RuntimeError("The ensemble did not produce enough walk-forward forecasts")
    result = result.loc[first:].copy()
    result.iloc[0, result.columns.get_loc("benchmark_return")] = 0.0
    result.iloc[0, result.columns.get_loc("strategy_return")] = 0.0
    result["strategy_equity"] = (1 + result["strategy_return"]).cumprod()
    result["benchmark_equity"] = (1 + result["benchmark_return"]).cumprod()
    result["strategy_drawdown"] = result["strategy_equity"] / result["strategy_equity"].cummax() - 1
    result["benchmark_drawdown"] = result["benchmark_equity"] / result["benchmark_equity"].cummax() - 1

    strategy = performance_metrics(result["strategy_return"], result["strategy_equity"])
    benchmark = performance_metrics(result["benchmark_return"], result["benchmark_equity"])
    downside, sortino = downside_metrics(result["strategy_return"])
    benchmark_downside, benchmark_sortino = downside_metrics(result["benchmark_return"])
    return result, {
        "cagr": _finite(strategy.cagr),
        "annualized_volatility": _finite(strategy.annualized_volatility),
        "sharpe_zero_cash": _finite(strategy.sharpe_zero_cash),
        "sortino_zero_cash": _finite(sortino),
        "annualized_downside_deviation": _finite(downside),
        "max_drawdown": _finite(strategy.max_drawdown),
        "total_return": _finite(strategy.total_return),
        "benchmark_cagr": _finite(benchmark.cagr),
        "benchmark_annualized_volatility": _finite(benchmark.annualized_volatility),
        "benchmark_sharpe_zero_cash": _finite(benchmark.sharpe_zero_cash),
        "benchmark_sortino_zero_cash": _finite(benchmark_sortino),
        "benchmark_annualized_downside_deviation": _finite(benchmark_downside),
        "benchmark_max_drawdown": _finite(benchmark.max_drawdown),
        "benchmark_total_return": _finite(benchmark.total_return),
        "time_in_market": _finite(result["position"].mean()),
        "entries": int(((result["turnover"] > 0) & (result["position"] == 0)).sum()),
        "exits": int(((result["turnover"] > 0) & (result["position"] == 1)).sum()),
    }


def forecast_metrics(frame: pd.DataFrame, forecast_column: str) -> dict[str, float | int | None]:
    scored = frame.dropna(subset=[forecast_column, "target_5d"])
    error = scored[forecast_column] - scored["target_5d"]
    target = scored["target_5d"]
    baseline_mse = float(np.mean(np.square(target)))
    return {
        "count": int(len(scored)),
        "mae": _finite(np.mean(np.abs(error))),
        "rmse": _finite(np.sqrt(np.mean(np.square(error)))),
        "oos_r2_vs_zero": _finite(1 - np.mean(np.square(error)) / baseline_mse),
        "direction_accuracy": _finite(np.mean(np.sign(scored[forecast_column]) == np.sign(target))),
        "correlation": _finite(scored[forecast_column].corr(target)),
    }


def uncertainty_bins(frame: pd.DataFrame) -> list[dict[str, float | int | None]]:
    scored = frame.dropna(subset=["ensemble_forecast", "forecast_uncertainty", "target_5d"]).copy()
    scored["bin"] = pd.qcut(scored["forecast_uncertainty"], 4, labels=False, duplicates="drop")
    rows = []
    for bin_number, group in scored.groupby("bin", observed=True):
        error = group["ensemble_forecast"] - group["target_5d"]
        rows.append(
            {
                "bin": int(bin_number) + 1,
                "count": int(len(group)),
                "mean_uncertainty": _finite(group["forecast_uncertainty"].mean()),
                "mae": _finite(np.abs(error).mean()),
                "coverage_80": _finite(
                    ((group["target_5d"] >= group["lower_80"]) & (group["target_5d"] <= group["upper_80"])).mean()
                ),
                "coverage_90": _finite(
                    ((group["target_5d"] >= group["lower_90"]) & (group["target_5d"] <= group["upper_90"])).mean()
                ),
            }
        )
    return rows


def chart_points(frame: pd.DataFrame, maximum_sessions: int = 504) -> list[dict[str, object]]:
    columns = (
        "close",
        "target_5d",
        "ridge_forecast",
        "kalman_forecast",
        "boosting_forecast",
        "ensemble_forecast",
        "lower_80",
        "upper_80",
        "confidence_edge",
        "edge_percentile",
        "positive_probability",
        "model_agreement",
        "position",
        "strategy_equity",
        "benchmark_equity",
    )
    return [
        {"date": index.date().isoformat()}
        | {column: _finite(row[column], 6) for column in columns}
        for index, row in frame.tail(maximum_sessions).iterrows()
    ]


def build_report(close: pd.Series) -> dict[str, object]:
    forecasts = walk_forward_ensemble(build_feature_frame(close))
    backtest, metrics = run_ensemble_strategy(forecasts)
    latest = forecasts.dropna(subset=["ensemble_forecast"]).iloc[-1]
    completed = forecasts.dropna(subset=["ensemble_forecast", "target_5d"])
    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": "Yahoo Finance delayed NIFTY 50 price-index history (^NSEI)",
        "evaluation_start": backtest.index[0].date().isoformat(),
        "evaluation_end": backtest.index[-1].date().isoformat(),
        "status": "development_experiment",
        "assumptions": {
            "forecast_horizon_sessions": FORECAST_HORIZON,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "training_window_rows": TRAINING_WINDOW,
            "refit_every_sessions": REFIT_EVERY,
            "error_window_sessions": ERROR_WINDOW,
            "round_trip_cost": ROUND_TRIP_COST,
            "entry_edge_percentile": ENTRY_EDGE_PERCENTILE,
            "exit_edge_percentile": EXIT_EDGE_PERCENTILE,
            "entry_probability": ENTRY_PROBABILITY,
            "execution": "Forecast after close t; execute at close t+1; first return earned t+1 to t+2",
            "weights": "Inverse rolling 252-session RMSE, blended 25% with equal weights",
            "intervals": "Rolling absolute out-of-sample residual quantiles using only completed five-session targets",
        },
        "latest": {
            "date": latest.name.date().isoformat(),
            "ensemble_forecast": _finite(latest["ensemble_forecast"]),
            "forecast_uncertainty": _finite(latest["forecast_uncertainty"]),
            "lower_80": _finite(latest["lower_80"]),
            "upper_80": _finite(latest["upper_80"]),
            "lower_90": _finite(latest["lower_90"]),
            "upper_90": _finite(latest["upper_90"]),
            "positive_probability": _finite(latest["positive_probability"]),
            "confidence_edge": _finite(latest["confidence_edge"]),
            "edge_percentile": _finite(latest["edge_percentile"]),
            "model_agreement": int(latest["model_agreement"]),
            "position": "long" if backtest["position"].iloc[-1] > 0.5 else "cash",
            "models": {
                name: {
                    "forecast": _finite(latest[f"{name}_forecast"]),
                    "weight": _finite(latest[f"{name}_weight"]),
                    "rolling_error_sd": _finite(latest[f"{name}_error_sd"]),
                }
                for name in MODEL_NAMES
            },
        },
        "strategy_metrics": metrics,
        "forecast_metrics": {
            name: forecast_metrics(completed, f"{name}_forecast")
            for name in (*MODEL_NAMES, "ensemble")
        },
        "interval_coverage": {
            "coverage_80": _finite(
                ((completed["target_5d"] >= completed["lower_80"]) & (completed["target_5d"] <= completed["upper_80"])).mean()
            ),
            "coverage_90": _finite(
                ((completed["target_5d"] >= completed["lower_90"]) & (completed["target_5d"] <= completed["upper_90"])).mean()
            ),
        },
        "uncertainty_bins": uncertainty_bins(completed),
        "chart": chart_points(backtest),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=SYMBOL)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/data/ensemble-signal.json"),
    )
    arguments = parser.parse_args()
    report = build_report(download_close(arguments.symbol, arguments.end))
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Wrote {arguments.output} through {report['evaluation_end']}")


if __name__ == "__main__":
    main()
