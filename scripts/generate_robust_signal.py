#!/usr/bin/env python3
"""Generate the risk-budgeted trend signal research report.

The report deliberately separates drawdown control from alpha.  The candidate is
an unlevered NIFTY 50 long/cash overlay:

* regime: 15-session EMA above the 45-session EMA;
* risk forecast: the larger of a 21-session EWMA and 63-session rolling
  annualized log-return standard deviation;
* exposure: min(100%, 8% / risk forecast) while the regime is long, else cash;
* rebalance: the final completed session in each W-FRI week;
* execution: decide after close t, trade at close t+1, first earn t+1 -> t+2;
* cost: 10 bps per one-way fractional position change.

No parameter is fitted inside the backtest.  Statistical output is explicitly
selection-aware because earlier repository experiments and exploratory variants
have already inspected the same history.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats


TRADING_DAYS = 252
SYMBOL = "^NSEI"
DOWNLOAD_START = "2007-01-01"
PRIMARY_EVALUATION_START = "2008-01-01"
COMPARISON_EVALUATION_START = "2012-04-23"
FAST_SPAN = 15
SLOW_SPAN = 45
EWMA_VOLATILITY_SPAN = 21
ROLLING_VOLATILITY_WINDOW = 63
TARGET_VOLATILITY = 0.08
ONE_WAY_COST = 0.001
DECLARED_TOTAL_TRIALS = 75
BOOTSTRAP_SEED = 20_260_810
BOOTSTRAP_REPETITIONS = 3_000
BOOTSTRAP_BLOCK_LENGTHS = (10, 20, 40)
PRIMARY_BOOTSTRAP_BLOCK = 20

WINDOW_SENSITIVITY = (
    (15, 45),
    (15, 63),
    (21, 42),
    (21, 63),
    (21, 84),
    (30, 63),
    (30, 84),
)
VOLATILITY_TARGET_SENSITIVITY = (0.06, 0.08, 0.10)
COST_STRESS = (0.0, 0.001, 0.002, 0.003)

INDEX_UNIVERSE = (
    ("^BSESN", "S&P BSE Sensex"),
    ("^CNX100", "NIFTY 100"),
    ("^NSEMDCP50", "NIFTY Midcap 50"),
    ("^NSEBANK", "NIFTY Bank"),
    ("^CNXIT", "NIFTY IT"),
    ("^CNXPHARMA", "NIFTY Pharma"),
)


@dataclass(frozen=True)
class MetricBundle:
    observations: int
    cagr: float
    annualized_volatility: float
    sharpe_zero_cash: float
    sortino_zero_cash: float
    annualized_downside_deviation: float
    max_drawdown: float
    total_return: float
    worst_day: float
    expected_shortfall_95: float


def _finite(value: float | int | np.number | None, digits: int = 8) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    return round(number, digits)


def completed_daily_bars(
    close: pd.Series,
    local_now: pd.Timestamp | None = None,
) -> pd.Series:
    """Exclude Yahoo's still-revisable same-calendar-day daily bar.

    Yahoo can expose a daily row while the Indian cash session is still open.
    The research process therefore runs one completed session behind and only
    accepts rows dated before the current date in Asia/Kolkata.
    """
    now = local_now if local_now is not None else pd.Timestamp.now(tz="Asia/Kolkata")
    if now.tzinfo is None:
        now = now.tz_localize("Asia/Kolkata")
    else:
        now = now.tz_convert("Asia/Kolkata")
    completed = close.loc[close.index.normalize() < pd.Timestamp(now.date())]
    if completed.empty:
        raise RuntimeError("No completed daily bars remain after excluding the current session")
    return completed


def download_close(symbol: str, end: str | None) -> pd.Series:
    """Download an adjusted close series and normalize its index."""
    frame = yf.download(
        symbol,
        start=DOWNLOAD_START,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if frame.empty:
        raise RuntimeError(f"No Yahoo Finance history returned for {symbol}")
    close = frame["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close = close.dropna().astype(float)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    if not close.index.is_monotonic_increasing or close.index.has_duplicates:
        close = close.groupby(level=0).last().sort_index()
    return completed_daily_bars(close.rename("close"))


def build_feature_frame(
    close: pd.Series,
    fast_span: int = FAST_SPAN,
    slow_span: int = SLOW_SPAN,
) -> pd.DataFrame:
    """Build causal trend and conservative dual-timescale risk features."""
    if fast_span >= slow_span:
        raise ValueError("fast_span must be shorter than slow_span")
    log_return = np.log(close).diff()
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
    ewma_daily_sd = log_return.ewm(
        span=EWMA_VOLATILITY_SPAN,
        adjust=False,
        min_periods=EWMA_VOLATILITY_SPAN,
    ).std()
    rolling_daily_sd = log_return.rolling(
        ROLLING_VOLATILITY_WINDOW,
        min_periods=ROLLING_VOLATILITY_WINDOW,
    ).std()
    annualized_ewma_sd = ewma_daily_sd * math.sqrt(TRADING_DAYS)
    annualized_rolling_sd = rolling_daily_sd * math.sqrt(TRADING_DAYS)
    risk_forecast = pd.concat(
        [annualized_ewma_sd, annualized_rolling_sd], axis=1
    ).max(axis=1, skipna=False)
    regime = (fast_ema > slow_ema).astype(float).where(fast_ema.notna() & slow_ema.notna())
    trend_score = np.log(fast_ema / slow_ema) / (
        ewma_daily_sd * math.sqrt(slow_span - fast_span)
    )
    return pd.DataFrame(
        {
            "close": close,
            "simple_return": close.pct_change().fillna(0.0),
            "log_return": log_return,
            "fast_ema": fast_ema,
            "slow_ema": slow_ema,
            "trend_score": trend_score,
            "regime": regime,
            "annualized_ewma_sd": annualized_ewma_sd,
            "annualized_rolling_sd": annualized_rolling_sd,
            "risk_forecast": risk_forecast,
        },
        index=close.index,
    )


def completed_weekly_target(
    raw_target: pd.Series,
    as_of: pd.Timestamp,
) -> tuple[pd.Series, pd.Series]:
    """Carry completed W-FRI decisions without treating a partial week as complete."""
    periods = raw_target.index.to_period("W-FRI")
    last_in_period = raw_target.groupby(periods).tail(1)
    period_ends = last_in_period.index.to_period("W-FRI").end_time.normalize()
    completed = last_in_period.loc[period_ends <= as_of.normalize()]
    scheduled = completed.reindex(raw_target.index).ffill().fillna(0.0)
    is_decision = pd.Series(False, index=raw_target.index)
    is_decision.loc[completed.index] = True
    return scheduled.astype(float), is_decision


def desired_target(
    frame: pd.DataFrame,
    target_volatility: float = TARGET_VOLATILITY,
) -> pd.Series:
    risk_scale = (target_volatility / frame["risk_forecast"]).clip(upper=1.0)
    return (frame["regime"].fillna(0.0) * risk_scale).fillna(0.0).rename("raw_target")


def run_candidate(
    close: pd.Series,
    *,
    evaluation_start: str | pd.Timestamp,
    as_of: pd.Timestamp,
    fast_span: int = FAST_SPAN,
    slow_span: int = SLOW_SPAN,
    target_volatility: float = TARGET_VOLATILITY,
    cost: float = ONE_WAY_COST,
    rebalance: str = "weekly",
    use_trend: bool = True,
    use_volatility_scaling: bool = True,
) -> pd.DataFrame:
    """Run one causal strategy path with close-to-close execution accounting."""
    frame = build_feature_frame(close, fast_span, slow_span)
    trend = frame["regime"].fillna(0.0) if use_trend else pd.Series(1.0, index=frame.index)
    if use_volatility_scaling:
        scale = (target_volatility / frame["risk_forecast"]).clip(upper=1.0).fillna(0.0)
    else:
        scale = pd.Series(1.0, index=frame.index)
    raw_target = (trend * scale).clip(lower=0.0, upper=1.0).rename("raw_target")
    if rebalance == "weekly":
        target, is_decision = completed_weekly_target(raw_target, as_of)
    elif rebalance == "daily":
        target = raw_target.copy()
        is_decision = raw_target.notna()
    else:
        raise ValueError("rebalance must be 'daily' or 'weekly'")

    # A target observed after close t is executed at close t+1.  It first earns
    # the return timestamped t+2.  The cost is paid at the execution close t+1.
    active_position = target.shift(2).fillna(0.0)
    executed_position = target.shift(1).fillna(0.0)
    turnover = (executed_position - active_position).abs()
    strategy_return = active_position * frame["simple_return"] - cost * turnover

    report = frame.assign(
        raw_target=raw_target,
        target=target,
        is_decision=is_decision,
        active_position=active_position,
        executed_position=executed_position,
        turnover=turnover,
        cost_debit=cost * turnover,
        strategy_return=strategy_return,
        benchmark_return=frame["simple_return"],
    ).loc[pd.Timestamp(evaluation_start) :].copy()
    if report.empty:
        raise RuntimeError("No observations remain after evaluation_start")
    report.iloc[0, report.columns.get_loc("strategy_return")] = 0.0
    report.iloc[0, report.columns.get_loc("benchmark_return")] = 0.0
    report.iloc[0, report.columns.get_loc("cost_debit")] = 0.0
    report["strategy_equity"] = (1 + report["strategy_return"]).cumprod()
    report["benchmark_equity"] = (1 + report["benchmark_return"]).cumprod()
    report["strategy_drawdown"] = drawdown_series(report["strategy_return"])
    report["benchmark_drawdown"] = drawdown_series(report["benchmark_return"])
    return report


def drawdown_series(returns: pd.Series) -> pd.Series:
    values = returns.to_numpy(dtype=float)
    wealth = np.concatenate(([1.0], np.cumprod(1 + values)))
    peaks = np.maximum.accumulate(wealth)
    return pd.Series((wealth / peaks - 1)[1:], index=returns.index)


def metric_bundle(returns: pd.Series) -> MetricBundle:
    clean = returns.dropna().astype(float)
    if len(clean) < 2:
        raise ValueError("At least two returns are required")
    values = clean.to_numpy(dtype=float)
    if np.any(values <= -1):
        raise ValueError("Returns at or below -100% are unsupported")
    years = (clean.index[-1] - clean.index[0]).days / 365.2425
    if years <= 0:
        years = len(clean) / TRADING_DAYS
    equity = np.cumprod(1 + values)
    cagr = float(equity[-1] ** (1 / years) - 1)
    volatility = float(np.std(values, ddof=1) * math.sqrt(TRADING_DAYS))
    sharpe = float(np.mean(values) * TRADING_DAYS / volatility) if volatility > 0 else math.nan
    downside = float(
        np.sqrt(np.mean(np.square(np.minimum(values, 0.0)))) * math.sqrt(TRADING_DAYS)
    )
    sortino = float(np.mean(values) * TRADING_DAYS / downside) if downside > 0 else math.nan
    wealth = np.concatenate(([1.0], equity))
    max_drawdown = float(np.min(wealth / np.maximum.accumulate(wealth) - 1))
    threshold = float(np.quantile(values, 0.05))
    expected_shortfall = float(values[values <= threshold].mean())
    return MetricBundle(
        observations=len(clean),
        cagr=cagr,
        annualized_volatility=volatility,
        sharpe_zero_cash=sharpe,
        sortino_zero_cash=sortino,
        annualized_downside_deviation=downside,
        max_drawdown=max_drawdown,
        total_return=float(equity[-1] - 1),
        worst_day=float(values.min()),
        expected_shortfall_95=expected_shortfall,
    )


def metric_dict(metrics: MetricBundle, digits: int = 8) -> dict[str, float | int | None]:
    return {key: _finite(value, digits) for key, value in asdict(metrics).items()}


def strategy_metrics(frame: pd.DataFrame) -> dict[str, float | int | None]:
    metrics = metric_dict(metric_bundle(frame["strategy_return"]))
    benchmark = metric_bundle(frame["benchmark_return"])
    for key, value in asdict(benchmark).items():
        metrics[f"benchmark_{key}"] = _finite(value)
    market_variance = float(frame["benchmark_return"].var(ddof=1))
    beta = (
        float(frame["strategy_return"].cov(frame["benchmark_return"])) / market_variance
        if market_variance > 0
        else math.nan
    )
    years = max((frame.index[-1] - frame.index[0]).days / 365.2425, 1 / 365.2425)
    target_now = frame["target"]
    regime_entries = int(((target_now > 0) & (target_now.shift(1).fillna(0) == 0)).sum())
    regime_exits = int(((target_now == 0) & (target_now.shift(1).fillna(0) > 0)).sum())
    metrics.update(
        {
            "market_beta": _finite(beta),
            "average_exposure": _finite(frame["active_position"].mean()),
            "median_exposure": _finite(frame["active_position"].median()),
            "maximum_exposure": _finite(frame["active_position"].max()),
            "positive_exposure_days": _finite((frame["active_position"] > 0).mean()),
            "regime_entries": regime_entries,
            "regime_exits": regime_exits,
            "fractional_turnover": _finite(frame["turnover"].sum()),
            "annualized_fractional_turnover": _finite(frame["turnover"].sum() / years),
            "cost_debit_sum": _finite(frame["cost_debit"].sum()),
            "weekly_decisions": int(frame["is_decision"].sum()),
        }
    )
    return metrics


def constant_exposure_control(frame: pd.DataFrame) -> tuple[pd.Series, float]:
    strategy_vol = metric_bundle(frame["strategy_return"]).annualized_volatility
    benchmark_vol = metric_bundle(frame["benchmark_return"]).annualized_volatility
    scale = min(1.0, strategy_vol / benchmark_vol) if benchmark_vol > 0 else 0.0
    returns = (scale * frame["benchmark_return"]).rename("matched_return")
    returns.iloc[0] = 0.0
    return returns, scale


def numpy_metrics(values: np.ndarray) -> dict[str, float]:
    if len(values) < 2 or np.any(values <= -1):
        return {key: math.nan for key in ("cagr", "sharpe", "sortino", "max_drawdown")}
    volatility = float(np.std(values, ddof=1))
    sharpe = float(np.mean(values) / volatility * math.sqrt(TRADING_DAYS)) if volatility > 0 else math.nan
    downside = float(np.sqrt(np.mean(np.square(np.minimum(values, 0.0)))))
    sortino = float(np.mean(values) / downside * math.sqrt(TRADING_DAYS)) if downside > 0 else math.nan
    cagr = float(np.expm1(np.log1p(values).sum() * TRADING_DAYS / len(values)))
    wealth = np.concatenate(([1.0], np.cumprod(1 + values)))
    max_drawdown = float(np.min(wealth / np.maximum.accumulate(wealth) - 1))
    return {"cagr": cagr, "sharpe": sharpe, "sortino": sortino, "max_drawdown": max_drawdown}


def stationary_bootstrap_indices(
    count: int,
    expected_block: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if count <= 0 or expected_block <= 0:
        raise ValueError("count and expected_block must be positive")
    result = np.empty(count, dtype=int)
    cursor = 0
    probability = 1 / expected_block
    while cursor < count:
        start = int(rng.integers(count))
        length = int(rng.geometric(probability))
        take = min(length, count - cursor)
        result[cursor : cursor + take] = (start + np.arange(take)) % count
        cursor += take
    return result


def paired_stationary_bootstrap(
    strategy: pd.Series,
    comparator: pd.Series,
    *,
    repetitions: int,
    expected_block: int,
    seed: int,
) -> dict[str, object]:
    aligned = pd.concat([strategy, comparator], axis=1).dropna()
    left = aligned.iloc[:, 0].to_numpy(dtype=float)
    right = aligned.iloc[:, 1].to_numpy(dtype=float)
    rng = np.random.Generator(np.random.PCG64(seed))
    metric_names = ("cagr", "sharpe", "sortino", "max_drawdown")
    left_samples = {name: np.empty(repetitions) for name in metric_names}
    right_samples = {name: np.empty(repetitions) for name in metric_names}
    delta_samples = {name: np.empty(repetitions) for name in metric_names}
    valid = 0
    for _ in range(repetitions):
        indices = stationary_bootstrap_indices(len(left), expected_block, rng)
        left_metrics = numpy_metrics(left[indices])
        right_metrics = numpy_metrics(right[indices])
        if not all(math.isfinite(left_metrics[name]) and math.isfinite(right_metrics[name]) for name in metric_names):
            continue
        for name in metric_names:
            left_samples[name][valid] = left_metrics[name]
            right_samples[name][valid] = right_metrics[name]
            delta_samples[name][valid] = left_metrics[name] - right_metrics[name]
        valid += 1
    if valid < math.ceil(0.95 * repetitions):
        raise RuntimeError("Fewer than 95% of stationary-bootstrap samples were valid")

    def intervals(samples: dict[str, np.ndarray]) -> dict[str, dict[str, float | None]]:
        result: dict[str, dict[str, float | None]] = {}
        for name in metric_names:
            values = samples[name][:valid]
            result[name] = {
                "lower_95": _finite(np.quantile(values, 0.025)),
                "median": _finite(np.quantile(values, 0.5)),
                "upper_95": _finite(np.quantile(values, 0.975)),
            }
        return result

    return {
        "repetitions": repetitions,
        "valid_repetitions": valid,
        "expected_block_sessions": expected_block,
        "seed": seed,
        "strategy": intervals(left_samples),
        "comparator": intervals(right_samples),
        "paired_difference_strategy_minus_comparator": intervals(delta_samples),
        "probability_sharpe_difference_positive": _finite(
            np.mean(delta_samples["sharpe"][:valid] > 0)
        ),
    }


def hac_mean_test(values: pd.Series, max_lag: int = 21) -> dict[str, float | int | None]:
    clean = values.dropna().to_numpy(dtype=float)
    count = len(clean)
    if count <= max_lag + 2:
        raise ValueError("Not enough observations for the requested HAC lag")
    centered = clean - clean.mean()
    long_run_variance = float(np.dot(centered, centered) / count)
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / count)
        long_run_variance += 2 * weight * covariance
    if long_run_variance <= 0:
        return {
            "observations": count,
            "max_lag": max_lag,
            "annualized_mean": _finite(clean.mean() * TRADING_DAYS),
            "t_statistic": None,
            "one_sided_p_value": None,
        }
    standard_error = math.sqrt(long_run_variance / count)
    t_statistic = float(clean.mean() / standard_error)
    return {
        "observations": count,
        "max_lag": max_lag,
        "annualized_mean": _finite(clean.mean() * TRADING_DAYS),
        "annualized_standard_error": _finite(standard_error * TRADING_DAYS),
        "t_statistic": _finite(t_statistic),
        "one_sided_p_value": _finite(stats.norm.sf(t_statistic)),
        "two_sided_p_value": _finite(2 * stats.norm.sf(abs(t_statistic))),
    }


def hac_regression_alpha(
    strategy: pd.Series,
    benchmark: pd.Series,
    max_lag: int = 21,
) -> dict[str, float | int | None]:
    aligned = pd.concat([strategy, benchmark], axis=1).dropna()
    y = aligned.iloc[:, 0].to_numpy(dtype=float)
    market = aligned.iloc[:, 1].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(y)), market])
    xtx_inverse = np.linalg.inv(x.T @ x)
    coefficients = xtx_inverse @ x.T @ y
    residuals = y - x @ coefficients
    meat = np.zeros((2, 2), dtype=float)
    for index in range(len(y)):
        row = x[index] * residuals[index]
        meat += np.outer(row, row)
    for lag in range(1, max_lag + 1):
        weight = 1 - lag / (max_lag + 1)
        cross = np.zeros((2, 2), dtype=float)
        for index in range(lag, len(y)):
            cross += np.outer(x[index] * residuals[index], x[index - lag] * residuals[index - lag])
        meat += weight * (cross + cross.T)
    covariance = xtx_inverse @ meat @ xtx_inverse
    alpha_se = math.sqrt(max(float(covariance[0, 0]), 0.0))
    alpha = float(coefficients[0])
    t_statistic = alpha / alpha_se if alpha_se > 0 else math.nan
    return {
        "observations": len(y),
        "max_lag": max_lag,
        "annualized_alpha": _finite(alpha * TRADING_DAYS),
        "annualized_alpha_standard_error": _finite(alpha_se * TRADING_DAYS),
        "market_beta": _finite(coefficients[1]),
        "t_statistic": _finite(t_statistic),
        "one_sided_p_value": _finite(stats.norm.sf(t_statistic)),
        "two_sided_p_value": _finite(2 * stats.norm.sf(abs(t_statistic))),
    }


def monthly_returns(returns: pd.Series) -> pd.Series:
    return returns.groupby(returns.index.to_period("M")).apply(lambda values: (1 + values).prod() - 1)


def sharpe(returns: pd.Series, periods: int) -> float:
    clean = returns.dropna().to_numpy(dtype=float)
    standard_deviation = float(np.std(clean, ddof=1))
    return float(np.mean(clean) / standard_deviation * math.sqrt(periods)) if standard_deviation > 0 else math.nan


def conservative_deflated_sharpe(
    candidate_monthly_returns: pd.Series,
    trial_annualized_sharpes: Iterable[float],
    declared_trials: int,
) -> dict[str, float | int | None]:
    values = candidate_monthly_returns.dropna().to_numpy(dtype=float)
    trials = np.asarray(list(trial_annualized_sharpes), dtype=float) / math.sqrt(12)
    if len(values) < 24 or len(trials) < 2:
        raise ValueError("Deflated Sharpe requires 24 monthly observations and two trials")
    candidate_period_sharpe = float(np.mean(values) / np.std(values, ddof=1))
    count = max(30, declared_trials, len(trials))
    trial_mean = max(0.0, float(np.mean(trials)))
    trial_sd = max(float(np.std(trials, ddof=1)), 1 / math.sqrt(len(values) - 1))
    euler_gamma = 0.5772156649015329
    multiplier = (
        (1 - euler_gamma) * stats.norm.ppf(1 - 1 / count)
        + euler_gamma * stats.norm.ppf(1 - 1 / (count * math.e))
    )
    selection_threshold = trial_mean + trial_sd * multiplier
    skewness = float(stats.skew(values, bias=False))
    kurtosis = float(stats.kurtosis(values, fisher=False, bias=False))
    denominator = math.sqrt(
        max(
            1e-12,
            1
            - skewness * candidate_period_sharpe
            + (kurtosis - 1) * candidate_period_sharpe**2 / 4,
        )
    )
    statistic = (
        (candidate_period_sharpe - selection_threshold)
        * math.sqrt(len(values) - 1)
        / denominator
    )
    psr_zero_statistic = candidate_period_sharpe * math.sqrt(len(values) - 1) / denominator
    return {
        "observations_months": len(values),
        "declared_total_trials_lower_bound": count,
        "candidate_annualized_monthly_sharpe": _finite(candidate_period_sharpe * math.sqrt(12)),
        "trial_mean_annualized_sharpe": _finite(trial_mean * math.sqrt(12)),
        "trial_sd_annualized_sharpe": _finite(trial_sd * math.sqrt(12)),
        "selection_adjusted_threshold_annualized_sharpe": _finite(
            selection_threshold * math.sqrt(12)
        ),
        "monthly_skewness": _finite(skewness),
        "monthly_pearson_kurtosis": _finite(kurtosis),
        "probabilistic_sharpe_probability_vs_zero": _finite(stats.norm.cdf(psr_zero_statistic)),
        "deflated_sharpe_probability": _finite(stats.norm.cdf(statistic)),
    }


def local_trial_library(
    close: pd.Series,
    evaluation_start: str,
    as_of: pd.Timestamp,
) -> list[dict[str, object]]:
    """Record a conservative 45-stream local trial library for selection adjustment."""
    rows: list[dict[str, object]] = []
    for fast_span, slow_span in WINDOW_SENSITIVITY:
        for target_volatility in VOLATILITY_TARGET_SENSITIVITY:
            for rebalance in ("daily", "weekly"):
                frame = run_candidate(
                    close,
                    evaluation_start=evaluation_start,
                    as_of=as_of,
                    fast_span=fast_span,
                    slow_span=slow_span,
                    target_volatility=target_volatility,
                    rebalance=rebalance,
                )
                rows.append(
                    {
                        "name": f"ema_{fast_span}_{slow_span}_{rebalance}_vol_{target_volatility:.2f}",
                        "annualized_monthly_sharpe": _finite(
                            sharpe(monthly_returns(frame["strategy_return"]), 12)
                        ),
                    }
                )
    for name, use_trend, use_volatility in (
        ("volatility_only_weekly", False, True),
        ("trend_only_weekly", True, False),
    ):
        frame = run_candidate(
            close,
            evaluation_start=evaluation_start,
            as_of=as_of,
            use_trend=use_trend,
            use_volatility_scaling=use_volatility,
        )
        rows.append(
            {
                "name": name,
                "annualized_monthly_sharpe": _finite(
                    sharpe(monthly_returns(frame["strategy_return"]), 12)
                ),
            }
        )

    # One predeclared, literature-motivated multi-speed long/cash diagnostic.
    frame = build_feature_frame(close)
    log_price = np.log(close)
    votes = sum((log_price.diff(horizon) > 0).astype(float) for horizon in (21, 63, 252)) / 3
    multi_regime = (votes >= 2 / 3).astype(float)
    raw_target = multi_regime * (TARGET_VOLATILITY / frame["risk_forecast"]).clip(upper=1).fillna(0)
    target, _ = completed_weekly_target(raw_target, as_of)
    position = target.shift(2).fillna(0)
    turnover = (target.shift(1).fillna(0) - target.shift(2).fillna(0)).abs()
    returns = (position * frame["simple_return"] - ONE_WAY_COST * turnover).loc[evaluation_start:]
    returns.iloc[0] = 0.0
    rows.append(
        {
            "name": "multi_speed_21_63_252_weekly",
            "annualized_monthly_sharpe": _finite(sharpe(monthly_returns(returns), 12)),
        }
    )
    if len(rows) != 45:
        raise AssertionError(f"Expected 45 local trial streams, found {len(rows)}")
    return rows


def period_metrics(frame: pd.DataFrame) -> list[dict[str, object]]:
    periods = (
        ("2008–2012", "2008-01-01", "2012-12-31"),
        ("2013–2017", "2013-01-01", "2017-12-31"),
        ("2018–2022", "2018-01-01", "2022-12-31"),
        ("2023–latest", "2023-01-01", frame.index[-1]),
    )
    rows: list[dict[str, object]] = []
    for label, start, end in periods:
        sample = frame.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()
        if len(sample) < 2:
            continue
        sample.iloc[0, sample.columns.get_loc("strategy_return")] = 0.0
        sample.iloc[0, sample.columns.get_loc("benchmark_return")] = 0.0
        values: dict[str, object] = {
            "period": label,
            "start": sample.index[0].date().isoformat(),
            "end": sample.index[-1].date().isoformat(),
            "average_exposure": _finite(sample["active_position"].mean()),
        }
        for prefix, column in (("strategy", "strategy_return"), ("benchmark", "benchmark_return")):
            metrics = metric_bundle(sample[column])
            values.update(
                {
                    f"{prefix}_cagr": _finite(metrics.cagr),
                    f"{prefix}_sharpe": _finite(metrics.sharpe_zero_cash),
                    f"{prefix}_sortino": _finite(metrics.sortino_zero_cash),
                    f"{prefix}_max_drawdown": _finite(metrics.max_drawdown),
                }
            )
        rows.append(values)
    return rows


def chart_points(frame: pd.DataFrame) -> list[dict[str, object]]:
    # Grouping by period and taking the actual last row preserves the observed
    # market date.  resample("W-FRI").last() would label a partial current week
    # with a future Friday, which is unacceptable in a live-facing chart.
    sampled = frame.groupby(frame.index.to_period("W-FRI")).tail(1)
    sampled = sampled.dropna(subset=["strategy_equity"])
    return [
        {
            "date": index.date().isoformat(),
            "close": _finite(row["close"], 4),
            "strategy_equity": _finite(row["strategy_equity"], 6),
            "benchmark_equity": _finite(row["benchmark_equity"], 6),
            "strategy_drawdown": _finite(row["strategy_drawdown"], 6),
            "benchmark_drawdown": _finite(row["benchmark_drawdown"], 6),
            "fast_ema": _finite(row["fast_ema"], 4),
            "slow_ema": _finite(row["slow_ema"], 4),
            "trend_score": _finite(row["trend_score"], 6),
            "risk_forecast": _finite(row["risk_forecast"], 6),
            "target": _finite(row["target"], 6),
            "active_position": _finite(row["active_position"], 6),
        }
        for index, row in sampled.iterrows()
    ]


def recent_trade_events(frame: pd.DataFrame, count: int = 20) -> list[dict[str, object]]:
    decision = frame.loc[frame["is_decision"]].copy()
    previous = decision["target"].shift(1).fillna(0.0)
    changed = decision.loc[(decision["target"] > 0) != (previous > 0)]
    rows: list[dict[str, object]] = []
    full_index = frame.index
    for index, row in changed.tail(count).iterrows():
        location = full_index.get_loc(index)
        execution_date = (
            full_index[location + 1].date().isoformat()
            if isinstance(location, int) and location + 1 < len(full_index)
            else None
        )
        rows.append(
            {
                "decision_date": index.date().isoformat(),
                "execution_date": execution_date,
                "action": "enter" if row["target"] > 0 else "exit",
                "target_exposure": _finite(row["target"], 6),
                "close": _finite(row["close"], 4),
                "trend_score": _finite(row["trend_score"], 6),
                "risk_forecast": _finite(row["risk_forecast"], 6),
            }
        )
    return rows


def sensitivity_rows(
    close: pd.Series,
    evaluation_start: str,
    as_of: pd.Timestamp,
) -> dict[str, list[dict[str, object]]]:
    windows: list[dict[str, object]] = []
    for fast_span, slow_span in WINDOW_SENSITIVITY:
        frame = run_candidate(
            close,
            evaluation_start=evaluation_start,
            as_of=as_of,
            fast_span=fast_span,
            slow_span=slow_span,
        )
        metrics = strategy_metrics(frame)
        windows.append(
            {
                "fast_span": fast_span,
                "slow_span": slow_span,
                "cagr": metrics["cagr"],
                "sharpe": metrics["sharpe_zero_cash"],
                "sortino": metrics["sortino_zero_cash"],
                "max_drawdown": metrics["max_drawdown"],
                "average_exposure": metrics["average_exposure"],
            }
        )
    volatility_targets: list[dict[str, object]] = []
    for target_volatility in VOLATILITY_TARGET_SENSITIVITY:
        frame = run_candidate(
            close,
            evaluation_start=evaluation_start,
            as_of=as_of,
            target_volatility=target_volatility,
        )
        metrics = strategy_metrics(frame)
        volatility_targets.append(
            {
                "target_volatility": target_volatility,
                "cagr": metrics["cagr"],
                "annualized_volatility": metrics["annualized_volatility"],
                "sharpe": metrics["sharpe_zero_cash"],
                "sortino": metrics["sortino_zero_cash"],
                "max_drawdown": metrics["max_drawdown"],
            }
        )
    costs: list[dict[str, object]] = []
    for cost in COST_STRESS:
        frame = run_candidate(
            close,
            evaluation_start=evaluation_start,
            as_of=as_of,
            cost=cost,
        )
        metrics = strategy_metrics(frame)
        costs.append(
            {
                "one_way_cost": cost,
                "cagr": metrics["cagr"],
                "sharpe": metrics["sharpe_zero_cash"],
                "sortino": metrics["sortino_zero_cash"],
                "max_drawdown": metrics["max_drawdown"],
            }
        )
    return {"ema_windows": windows, "volatility_targets": volatility_targets, "costs": costs}


def cross_market_rows(
    end: str | None,
    as_of: pd.Timestamp,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for symbol, name in INDEX_UNIVERSE:
        try:
            close = download_close(symbol, end)
            start_location = min(ROLLING_VOLATILITY_WINDOW, len(close) - 1)
            evaluation_start = max(
                pd.Timestamp(PRIMARY_EVALUATION_START),
                close.index[start_location],
            )
            frame = run_candidate(
                close,
                evaluation_start=evaluation_start,
                as_of=as_of,
            )
            metrics = strategy_metrics(frame)
            rows.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "evaluation_start": frame.index[0].date().isoformat(),
                    "evaluation_end": frame.index[-1].date().isoformat(),
                    "cagr": metrics["cagr"],
                    "sharpe": metrics["sharpe_zero_cash"],
                    "sortino": metrics["sortino_zero_cash"],
                    "max_drawdown": metrics["max_drawdown"],
                    "benchmark_cagr": metrics["benchmark_cagr"],
                    "benchmark_sharpe": metrics["benchmark_sharpe_zero_cash"],
                    "benchmark_sortino": metrics["benchmark_sortino_zero_cash"],
                    "benchmark_max_drawdown": metrics["benchmark_max_drawdown"],
                    "average_exposure": metrics["average_exposure"],
                }
            )
        except Exception as error:  # pragma: no cover - network-dependent diagnostic
            rows.append({"symbol": symbol, "name": name, "error": str(error)})
    valid = [row for row in rows if "error" not in row]
    return {
        "frozen_parameters": (
            "15/45 EMA regime, max(21-session EWMA, 63-session rolling) risk forecast, "
            "8% target, weekly completed-period decisions, 10 bps one-way cost"
        ),
        "rows": rows,
        "summary": {
            "available_markets": len(valid),
            "cagr_wins": sum(row["cagr"] > row["benchmark_cagr"] for row in valid),
            "sharpe_wins": sum(row["sharpe"] > row["benchmark_sharpe"] for row in valid),
            "sortino_wins": sum(row["sortino"] > row["benchmark_sortino"] for row in valid),
            "drawdown_wins": sum(row["max_drawdown"] > row["benchmark_max_drawdown"] for row in valid),
            "median_sharpe_delta": _finite(
                np.median([row["sharpe"] - row["benchmark_sharpe"] for row in valid])
            ) if valid else None,
            "median_drawdown_improvement": _finite(
                np.median([row["max_drawdown"] - row["benchmark_max_drawdown"] for row in valid])
            ) if valid else None,
        },
    }


def build_report(
    close: pd.Series,
    *,
    end: str | None,
    bootstrap_repetitions: int,
    include_cross_market: bool,
) -> dict[str, object]:
    as_of = close.index[-1]
    primary = run_candidate(
        close,
        evaluation_start=PRIMARY_EVALUATION_START,
        as_of=as_of,
    )
    comparison = run_candidate(
        close,
        evaluation_start=COMPARISON_EVALUATION_START,
        as_of=as_of,
    )
    volatility_only = run_candidate(
        close,
        evaluation_start=PRIMARY_EVALUATION_START,
        as_of=as_of,
        use_trend=False,
    )
    trend_only = run_candidate(
        close,
        evaluation_start=PRIMARY_EVALUATION_START,
        as_of=as_of,
        use_volatility_scaling=False,
    )
    existing_ema = run_candidate(
        close,
        evaluation_start=PRIMARY_EVALUATION_START,
        as_of=as_of,
        fast_span=21,
        slow_span=63,
        use_volatility_scaling=False,
        rebalance="daily",
    )
    matched_returns, matched_scale = constant_exposure_control(primary)

    controls = {
        "volatility_only": metric_dict(metric_bundle(volatility_only["strategy_return"])),
        "trend_only": metric_dict(metric_bundle(trend_only["strategy_return"])),
        "existing_21_63_ema": metric_dict(metric_bundle(existing_ema["strategy_return"])),
        "constant_exposure_matched_volatility": {
            **metric_dict(metric_bundle(matched_returns)),
            "constant_exposure": _finite(matched_scale),
        },
        "buy_and_hold": metric_dict(metric_bundle(primary["benchmark_return"])),
    }

    bootstrap_by_comparator: dict[str, object] = {}
    for name, returns in (
        ("volatility_only", volatility_only["strategy_return"]),
        ("constant_exposure_matched_volatility", matched_returns),
    ):
        primary_result = paired_stationary_bootstrap(
            primary["strategy_return"],
            returns,
            repetitions=bootstrap_repetitions,
            expected_block=PRIMARY_BOOTSTRAP_BLOCK,
            seed=BOOTSTRAP_SEED + (0 if name == "volatility_only" else 1),
        )
        block_sensitivity: list[dict[str, object]] = []
        for block in BOOTSTRAP_BLOCK_LENGTHS:
            result = (
                primary_result
                if block == PRIMARY_BOOTSTRAP_BLOCK
                else paired_stationary_bootstrap(
                    primary["strategy_return"],
                    returns,
                    repetitions=bootstrap_repetitions,
                    expected_block=block,
                    seed=BOOTSTRAP_SEED + block + (100 if name == "volatility_only" else 200),
                )
            )
            block_sensitivity.append(
                {
                    "expected_block_sessions": block,
                    "sharpe_difference_95": result[
                        "paired_difference_strategy_minus_comparator"
                    ]["sharpe"],
                    "probability_sharpe_difference_positive": result[
                        "probability_sharpe_difference_positive"
                    ],
                }
            )
        primary_result["block_length_sensitivity"] = block_sensitivity
        bootstrap_by_comparator[name] = primary_result

    trials = local_trial_library(
        close,
        PRIMARY_EVALUATION_START,
        as_of,
    )
    deflated = conservative_deflated_sharpe(
        monthly_returns(primary["strategy_return"]),
        [float(row["annualized_monthly_sharpe"]) for row in trials],
        DECLARED_TOTAL_TRIALS,
    )
    active_vs_matched = primary["strategy_return"] - matched_returns
    hac_tests = {
        "active_return_vs_constant_exposure": hac_mean_test(active_vs_matched, 21),
        "market_model_alpha": hac_regression_alpha(
            primary["strategy_return"], primary["benchmark_return"], 21
        ),
        "lag_sensitivity": [
            hac_mean_test(active_vs_matched, lag) for lag in (5, 21, 63)
        ],
    }

    sensitivity = sensitivity_rows(
        close,
        PRIMARY_EVALUATION_START,
        as_of,
    )
    cross_market = (
        cross_market_rows(end, as_of)
        if include_cross_market
        else {"summary": {"available_markets": 0}, "rows": [], "skipped": True}
    )

    primary_metrics = strategy_metrics(primary)
    comparison_metrics = strategy_metrics(comparison)
    double_cost = next(row for row in sensitivity["costs"] if row["one_way_cost"] == 0.002)
    vol_bootstrap = bootstrap_by_comparator["volatility_only"]
    cross_summary = cross_market["summary"]
    gates = [
        {
            "gate": "Historical maximum drawdown no worse than 20%",
            "passed": bool(primary_metrics["max_drawdown"] >= -0.20),
            "value": primary_metrics["max_drawdown"],
            "required": -0.20,
        },
        {
            "gate": "Positive Sharpe at double base cost",
            "passed": bool(double_cost["sharpe"] > 0),
            "value": double_cost["sharpe"],
            "required": 0.0,
        },
        {
            "gate": "Selection-adjusted Deflated Sharpe probability at least 95%",
            "passed": bool(deflated["deflated_sharpe_probability"] >= 0.95),
            "value": deflated["deflated_sharpe_probability"],
            "required": 0.95,
        },
        {
            "gate": "95% paired-bootstrap lower bound for Sharpe edge over volatility-only above zero",
            "passed": bool(
                vol_bootstrap["paired_difference_strategy_minus_comparator"]["sharpe"][
                    "lower_95"
                ]
                > 0
            ),
            "value": vol_bootstrap["paired_difference_strategy_minus_comparator"]["sharpe"][
                "lower_95"
            ],
            "required": 0.0,
        },
        {
            "gate": "Frozen Sharpe transfer wins in at least four of six Indian indices",
            "passed": bool(cross_summary.get("sharpe_wins", 0) >= 4),
            "value": cross_summary.get("sharpe_wins"),
            "required": 4,
        },
        {
            "gate": "At least 252 genuinely unseen forward sessions",
            "passed": False,
            "value": 0,
            "required": 252,
        },
    ]
    all_passed = all(bool(gate["passed"]) for gate in gates)

    completed_decisions = primary.loc[primary["is_decision"]]
    latest_decision = completed_decisions.iloc[-1]
    latest = primary.iloc[-1]
    pending_execution = latest_decision.name == latest.name
    current_exposure = float(latest["executed_position"])
    decision_target = float(latest_decision["target"])
    target_change = decision_target - current_exposure
    if abs(target_change) < 1e-12:
        pending_action = "hold"
    elif current_exposure <= 1e-12:
        pending_action = "enter"
    elif decision_target <= 1e-12:
        pending_action = "exit"
    else:
        pending_action = "resize"
    earliest_execution_date = (
        (latest_decision.name + pd.offsets.BDay(1)).date().isoformat()
        if pending_execution and pending_action != "hold"
        else None
    )
    next_week_end = latest.name.to_period("W-FRI").end_time.normalize()
    if next_week_end <= latest.name.normalize():
        next_week_end += pd.Timedelta(days=7)
    config = {
        "fast_span": FAST_SPAN,
        "slow_span": SLOW_SPAN,
        "ewma_volatility_span": EWMA_VOLATILITY_SPAN,
        "rolling_volatility_window": ROLLING_VOLATILITY_WINDOW,
        "risk_forecast_combination": "maximum",
        "target_volatility": TARGET_VOLATILITY,
        "rebalance": "last completed W-FRI session",
        "one_way_cost": ONE_WAY_COST,
        "cash_return": 0.0,
        "leverage_cap": 1.0,
        "shorting": False,
    }
    config_hash = hashlib.sha256(
        json.dumps(config, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]

    return {
        "generated_at": pd.Timestamp.now(tz="Asia/Kolkata").isoformat(),
        "source": (
            "Yahoo Finance delayed adjusted NIFTY 50 price-index history (^NSEI); "
            "same-calendar-day bars excluded"
        ),
        "status": "research_only_not_validated",
        "name": "Risk-budgeted trend",
        "formula": (
            "weekly_target = I(EMA15 > EMA45) * min(1, 8% / "
            "max(EWMA21 annualized SD, rolling63 annualized SD))"
        ),
        "primary_evaluation_start": primary.index[0].date().isoformat(),
        "comparison_evaluation_start": comparison.index[0].date().isoformat(),
        "evaluation_end": primary.index[-1].date().isoformat(),
        "assumptions": {
            **config,
            "execution": (
                "Signal after close t; execute at close t+1; first new-position return is t+1 to t+2"
            ),
            "dividends": "Excluded because Yahoo ^NSEI is a price index",
            "taxes_and_market_impact": "Excluded; cost stress is shown separately",
            "daily_bar_policy": (
                "Only sessions dated before the current Asia/Kolkata calendar date are accepted"
            ),
            "partial_week_policy": "A current partial W-FRI period cannot create a rebalance",
        },
        "primary_metrics": primary_metrics,
        "comparison_window_metrics": comparison_metrics,
        "controls": controls,
        "latest_signal": {
            "market_date": latest.name.date().isoformat(),
            "market_data_status": "completed_sessions_only",
            "last_completed_decision_date": latest_decision.name.date().isoformat(),
            "next_scheduled_decision_date": next_week_end.date().isoformat(),
            "regime": "long" if latest["regime"] > 0 else "cash",
            "action_status": (
                "pending_next_session_close"
                if pending_execution and pending_action != "hold"
                else "no_pending_change"
            ),
            "action": pending_action,
            "pending_target": _finite(decision_target) if pending_execution else None,
            "earliest_execution_date": earliest_execution_date,
            "current_completed_close_exposure": _finite(current_exposure),
            "close": _finite(latest["close"], 4),
            "fast_ema": _finite(latest["fast_ema"], 4),
            "slow_ema": _finite(latest["slow_ema"], 4),
            "trend_score": _finite(latest["trend_score"], 8),
            "annualized_ewma_sd": _finite(latest["annualized_ewma_sd"]),
            "annualized_rolling_sd": _finite(latest["annualized_rolling_sd"]),
            "risk_forecast": _finite(latest["risk_forecast"]),
            "last_completed_target": _finite(latest_decision["target"]),
            "position_earning_latest_return": _finite(latest["active_position"]),
            "position_after_latest_close": _finite(latest["executed_position"]),
            "unscheduled_daily_target_diagnostic": _finite(latest["raw_target"]),
        },
        "subperiods": period_metrics(primary),
        "sensitivity": sensitivity,
        "cross_market": cross_market,
        "statistics": {
            "stationary_bootstrap": bootstrap_by_comparator,
            "deflated_sharpe": deflated,
            "hac": hac_tests,
            "trial_ledger": {
                "local_streams": len(trials),
                "declared_total_trials_lower_bound": DECLARED_TOTAL_TRIALS,
                "counts": {
                    "earlier_repository_configurations": 29,
                    "new_local_streams": len(trials),
                    "additional_selection_decision": 1,
                },
                "local_annualized_monthly_sharpe_min": _finite(
                    min(float(row["annualized_monthly_sharpe"]) for row in trials)
                ),
                "local_annualized_monthly_sharpe_median": _finite(
                    np.median([float(row["annualized_monthly_sharpe"]) for row in trials])
                ),
                "local_annualized_monthly_sharpe_max": _finite(
                    max(float(row["annualized_monthly_sharpe"]) for row in trials)
                ),
            },
        },
        "promotion_gates": gates,
        "verdict": {
            "passed_all_gates": all_passed,
            "classification": "paper_trade_only" if not all_passed else "historically_qualified",
            "headline": (
                "Defensive risk control, not demonstrated alpha"
                if not all_passed
                else "Historically qualified; forward evidence still required"
            ),
            "reason": (
                "The rule reduces historical drawdown, but selection-aware uncertainty, "
                "volatility-only controls, transfer tests, and the lack of unseen forward data "
                "prevent a production trading claim."
            ),
        },
        "forward_test": {
            "frozen_from": "2026-08-11",
            "minimum_sessions": 252,
            "completed_sessions": 0,
            "configuration_hash": config_hash,
            "parameters_must_not_change": True,
        },
        "recent_trade_events": recent_trade_events(primary),
        "chart": chart_points(primary),
        "references": [
            {
                "title": "Time Series Momentum — Moskowitz, Ooi and Pedersen",
                "url": "https://pages.stern.nyu.edu/~lpederse/papers/TimeSeriesMomentum.pdf",
                "role": "Trend and causal volatility-scaling motivation",
            },
            {
                "title": "Volatility Managed Portfolios — Moreira and Muir",
                "url": "https://www.nber.org/papers/w22208",
                "role": "Risk scaling motivation",
            },
            {
                "title": "The Stationary Bootstrap — Politis and Romano",
                "url": "https://doi.org/10.1080/01621459.1994.10476870",
                "role": "Dependent-return uncertainty intervals",
            },
            {
                "title": "The Deflated Sharpe Ratio — Bailey and Lopez de Prado",
                "url": "https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf",
                "role": "Selection and non-normality adjustment",
            },
            {
                "title": "A Simple, Positive Semi-definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix — Newey and West",
                "url": "https://www.nber.org/papers/t0055",
                "role": "HAC inference",
            },
            {
                "title": "On the Performance of Volatility-Managed Portfolios — Cederburg et al.",
                "url": "https://doi.org/10.1016/j.jfineco.2020.04.015",
                "role": "Important out-of-sample counterevidence",
            },
        ],
        "limitations": [
            "The NIFTY 50 price index is not directly tradable and excludes dividends.",
            "Cash earns zero; actual cash yield, financing, taxes, impact, and ETF tracking error are omitted.",
            "The same history informed many earlier and current variants, so it is not a pristine holdout.",
            "The rule is long/cash only and can miss fast rebounds or lose before a weekly exit executes.",
            "Maximum drawdown is one path-dependent historical extreme, not a promised future limit.",
            "A total-return instrument and a prospectively logged paper test are required before live use.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--end",
        default=None,
        help="Exclusive Yahoo end date (YYYY-MM-DD). Omit for latest available data.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/data/robust-signal.json"),
    )
    parser.add_argument(
        "--bootstrap-repetitions",
        type=int,
        default=BOOTSTRAP_REPETITIONS,
    )
    parser.add_argument(
        "--skip-cross-market",
        action="store_true",
        help="Skip the six-index transfer diagnostic.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.bootstrap_repetitions < 200:
        raise ValueError("Use at least 200 bootstrap repetitions")
    close = download_close(SYMBOL, args.end)
    report = build_report(
        close,
        end=args.end,
        bootstrap_repetitions=args.bootstrap_repetitions,
        include_cross_market=not args.skip_cross_market,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "status": report["status"],
                "primary_metrics": report["primary_metrics"],
                "latest_signal": report["latest_signal"],
                "verdict": report["verdict"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
