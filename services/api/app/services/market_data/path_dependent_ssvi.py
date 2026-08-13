"""Path-dependent parsimonious SSVI forecasts for NSE option surfaces.

This is an additional challenger model; the existing FPCA--VAR implementation
remains untouched.  The implementation follows Andrès, Boumezoued and
Jourdain (2025):

* each daily surface is compressed into the four parsimonious SSVI parameters
  ``a``, ``p``, ``rho`` and ``eta``;
* the ATM term-structure parameters ``a`` and ``p`` are linked to time-shifted
  power-law weighted returns and squared returns;
* their multiplicative residuals are forecast with a discrete OU conditional
  mean; and
* ``rho`` and ``eta`` use the bounded conditional mean of a Jacobi process.

The paper estimates on 1--24 month index surfaces with roughly a decade of
history.  NSE single-stock options provide a much shorter and narrower panel,
so the kernels are fixed to the paper's reported S&P 500 estimates while the
linear coefficients and mean reversion are re-estimated for each stock.  That
adaptation is explicitly reported by the API and evaluation UI.
"""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.stats import norm

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.services.market_data.iv_surface import (
    DELTA_BUCKETS,
    FORECAST_TTL_SECONDS,
    MAX_IV_PERCENT,
    MINIMUM_VALIDATION_SURFACES,
    TENOR_DAYS,
    _empty_strategy,
    _fit_fpca_core,
    _interpolate_tenor,
    _market_bucket_points,
    _next_weekday,
    _select_component_count,
    _smooth_surface,
    build_iv_strategies,
    get_fno_lot_size,
    load_historical_surfaces,
)

MODEL_NAME = "Path-dependent parsimonious SSVI (PDV + OU/Jacobi conditional mean)"
MODEL_VERSION = "nse-path-dependent-ssvi-v1"
PAPER_URL = "https://arxiv.org/abs/2312.15950"

# The paper finds the squared-return feature needs at least ~1,000 business
# days for longer maturities.  The trend cut-off is kept shorter because the
# available NSE surface grid ends at 90 days.
TREND_CUTOFF_DAYS = 252
ACTIVITY_CUTOFF_DAYS = 1_000
MINIMUM_PARAMETER_SURFACES = 24
MINIMUM_BACKTEST_SURFACES = MINIMUM_VALIDATION_SURFACES
BOOTSTRAP_SAMPLES = 5_000
MEANINGFUL_MOVE_VOL_POINTS = 0.25

# Paper Table 2, S&P 500 calibration.  Coefficients are estimated on each NSE
# stock; only kernel shapes are transferred to avoid tuning on a 50-day panel.
KERNELS = {
    "a": {"alpha_trend": 1.12, "delta_trend": 0.03, "alpha_activity": 0.88, "delta_activity": 0.03},
    "p": {"alpha_trend": 1.01, "delta_trend": 0.02, "alpha_activity": 0.78, "delta_activity": 0.01},
}


def parsimonious_ssvi_total_variance(
    log_forward_moneyness: np.ndarray | float,
    years: np.ndarray | float,
    parameters: np.ndarray | list[float] | tuple[float, float, float, float],
) -> np.ndarray:
    """Return total variance for the paper's four-parameter SSVI surface."""

    a, p, rho, eta = (float(value) for value in parameters)
    maturity = np.maximum(np.asarray(years, dtype=float), 1e-8)
    k = np.asarray(log_forward_moneyness, dtype=float)
    theta = np.maximum(a * maturity**p, 1e-10)
    phi = eta / np.sqrt(theta * (1.0 + theta))
    radical = np.sqrt((phi * k + rho) ** 2 + 1.0 - rho**2)
    return np.maximum(theta / 2.0 * (1.0 + rho * phi * k + radical), 1e-10)


def _delta_d1(bucket_index: int) -> float:
    _, side, target = DELTA_BUCKETS[bucket_index]
    if side == "atm":
        return 0.0
    call_delta = 1.0 - target if side == "put" else target
    return float(norm.ppf(call_delta))


def _log_moneyness_from_delta(
    bucket_index: int,
    volatility: np.ndarray | float,
    years: np.ndarray | float,
) -> np.ndarray:
    sigma = np.asarray(volatility, dtype=float)
    maturity = np.asarray(years, dtype=float)
    if DELTA_BUCKETS[bucket_index][1] == "atm":
        return np.zeros_like(sigma + maturity)
    d1 = _delta_d1(bucket_index)
    return 0.5 * sigma**2 * maturity - d1 * sigma * np.sqrt(maturity)


def ssvi_surface_from_parameters(parameters: np.ndarray | list[float]) -> np.ndarray:
    """Evaluate SSVI on the product's fixed tenor/delta quote grid.

    Delta coordinates depend on volatility.  A short fixed-point iteration maps
    the parametric log-moneyness surface back to the five quoted delta buckets.
    """

    result = np.empty((len(TENOR_DAYS), len(DELTA_BUCKETS)), dtype=float)
    for tenor_index, days in enumerate(TENOR_DAYS):
        years = float(days / 365.25)
        atm = math.sqrt(
            float(parsimonious_ssvi_total_variance(0.0, years, parameters)) / years
        )
        for bucket_index in range(len(DELTA_BUCKETS)):
            sigma = atm
            for _ in range(12):
                k = float(_log_moneyness_from_delta(bucket_index, sigma, years))
                next_sigma = math.sqrt(
                    float(parsimonious_ssvi_total_variance(k, years, parameters)) / years
                )
                if abs(next_sigma - sigma) < 1e-9:
                    break
                sigma = 0.55 * sigma + 0.45 * next_sigma
            result[tenor_index, bucket_index] = sigma * 100.0
    return np.clip(result, 1.0, MAX_IV_PERCENT)


def calibrate_parsimonious_ssvi(surface: np.ndarray) -> dict[str, Any]:
    """Fit ``a, p, rho, eta`` to one 4x5 delta-quoted IV surface."""

    values = np.asarray(surface, dtype=float)
    if values.shape != (len(TENOR_DAYS), len(DELTA_BUCKETS)) or not np.isfinite(values).all():
        raise ValueError("A complete 4x5 IV surface is required for SSVI calibration.")
    observations: list[tuple[float, float, float]] = []
    for tenor_index, days in enumerate(TENOR_DAYS):
        years = float(days / 365.25)
        for bucket_index in range(len(DELTA_BUCKETS)):
            sigma = float(values[tenor_index, bucket_index] / 100.0)
            k = float(_log_moneyness_from_delta(bucket_index, sigma, years))
            observations.append((k, years, sigma))
    k = np.asarray([item[0] for item in observations])
    maturity = np.asarray([item[1] for item in observations])
    observed_sigma = np.asarray([item[2] for item in observations])

    atm_variance = (values[:, 2] / 100.0) ** 2 * (TENOR_DAYS / 365.25)
    slope, intercept = np.polyfit(
        np.log(TENOR_DAYS / 365.25),
        np.log(np.maximum(atm_variance, 1e-8)),
        1,
    )
    initial = np.asarray(
        [
            float(np.clip(math.exp(intercept), 0.002, 0.5)),
            float(np.clip(slope, 0.15, 1.8)),
            -0.35,
            0.75,
        ]
    )

    def residuals(parameters: np.ndarray) -> np.ndarray:
        predicted = np.sqrt(
            parsimonious_ssvi_total_variance(k, maturity, parameters) / maturity
        )
        return (predicted - observed_sigma) * 100.0

    fit = least_squares(
        residuals,
        initial,
        bounds=(
            np.asarray([1e-5, 0.02, -0.995, 0.01]),
            np.asarray([2.0, 2.5, 0.995, math.sqrt(2.0) * 0.999]),
        ),
        loss="soft_l1",
        f_scale=0.75,
        max_nfev=500,
    )
    parameters = np.asarray(fit.x, dtype=float)
    fitted_surface = ssvi_surface_from_parameters(parameters)
    return {
        "parameters": parameters,
        "fitted_surface": fitted_surface,
        "calibration_rmse": float(np.sqrt(np.mean((values - fitted_surface) ** 2))),
        "success": bool(fit.success),
    }


def _price_series(price_history: dict[str, Any] | pd.Series) -> pd.Series:
    if isinstance(price_history, pd.Series):
        series = price_history.copy()
    else:
        candles = list(price_history.get("candles") or [])
        series = pd.Series(
            [float(item["close"]) for item in candles],
            index=pd.to_datetime([item["time"] for item in candles]),
            dtype=float,
        )
    series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
    return series[~series.index.duplicated(keep="last")].sort_index().dropna()


def _tspl_feature(
    returns: np.ndarray,
    *,
    alpha: float,
    delta: float,
    squared: bool,
    cutoff: int,
    shift: int = 0,
) -> float:
    usable = np.asarray(returns[-cutoff:], dtype=float)[::-1]
    if not len(usable):
        return 0.0
    lags_years = (np.arange(len(usable), dtype=float) + shift) / 252.0
    weights = 1.0 / np.power(lags_years + delta, alpha)
    if shift:
        # The unknown target-session return has conditional mean zero but still
        # occupies the newest kernel weight.
        zero_weight = 1.0 / delta**alpha
        weights = weights / (weights.sum() + zero_weight)
    else:
        weights = weights / weights.sum()
    if squared:
        return float(math.sqrt(max(0.0, np.sum(weights * usable**2))))
    return float(np.sum(weights * usable))


def path_features(
    price_history: dict[str, Any] | pd.Series,
    as_of: date | str,
    parameter: str,
    *,
    next_session: bool = False,
) -> tuple[float, float]:
    """Return the paper's trend ``R1`` and activity ``Sigma`` features."""

    prices = _price_series(price_history)
    cutoff = pd.Timestamp(as_of).normalize()
    prices = prices.loc[prices.index <= cutoff]
    price_values = prices.to_numpy(dtype=float)
    returns = np.diff(price_values) / price_values[:-1]
    settings = KERNELS[parameter]
    shift = 1 if next_session else 0
    trend = _tspl_feature(
        returns,
        alpha=settings["alpha_trend"],
        delta=settings["delta_trend"],
        squared=False,
        cutoff=TREND_CUTOFF_DAYS,
        shift=shift,
    )
    activity = _tspl_feature(
        returns,
        alpha=settings["alpha_activity"],
        delta=settings["delta_activity"],
        squared=True,
        cutoff=ACTIVITY_CUTOFF_DAYS,
        shift=shift,
    )
    return trend, max(activity, 1e-8)


def _ridge_coefficients(x: np.ndarray, y: np.ndarray, alpha: float = 1e-4) -> np.ndarray:
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    return np.linalg.solve(x.T @ x + alpha * penalty, x.T @ y)


def _ou_parameter_forecast(
    values: np.ndarray,
    features: np.ndarray,
    next_feature: np.ndarray,
    *,
    logarithmic: bool,
) -> tuple[float, dict[str, float]]:
    target = np.log(np.maximum(values, 1e-8)) if logarithmic else values
    coefficients = _ridge_coefficients(features, target)
    fitted = features @ coefficients
    sigma = np.maximum(features[:, 2], 1e-8)
    residuals = (target - fitted) / sigma
    centered = residuals - float(np.mean(residuals))
    denominator = float(np.dot(centered[:-1], centered[:-1]))
    phi = (
        float(np.dot(centered[:-1], centered[1:]) / denominator)
        if denominator > 1e-12
        else 0.0
    )
    phi = float(np.clip(phi, 0.0, 0.995))
    expected_residual = float(np.mean(residuals) + phi * (residuals[-1] - np.mean(residuals)))
    conditional = float(next_feature @ coefficients + expected_residual * next_feature[2])
    predicted = math.exp(conditional) if logarithmic else abs(conditional)
    return predicted, {
        "trend": float(next_feature[1]),
        "activity": float(next_feature[2]),
        "ou_persistence": phi,
        "residual": float(residuals[-1]),
    }


def _jacobi_conditional_mean(values: np.ndarray, lower: float, upper: float) -> tuple[float, dict[str, float]]:
    values = np.asarray(values, dtype=float)
    long_mean = float(np.clip(np.mean(values), lower, upper))
    centered = values - long_mean
    denominator = float(np.dot(centered[:-1], centered[:-1]))
    phi = (
        float(np.dot(centered[:-1], centered[1:]) / denominator)
        if denominator > 1e-12
        else 0.0
    )
    phi = float(np.clip(phi, 0.0, 0.995))
    prediction = float(np.clip(long_mean + phi * (values[-1] - long_mean), lower, upper))
    return prediction, {"long_run_mean": long_mean, "persistence": phi}


def forecast_parameters(
    parameters: np.ndarray,
    history_dates: list[str],
    price_history: dict[str, Any] | pd.Series,
) -> dict[str, Any]:
    if len(parameters) < MINIMUM_PARAMETER_SURFACES:
        raise ValueError(
            f"At least {MINIMUM_PARAMETER_SURFACES} calibrated SSVI surfaces are required."
        )
    feature_matrices: dict[str, np.ndarray] = {}
    next_features: dict[str, np.ndarray] = {}
    for name in ("a", "p"):
        feature_matrices[name] = np.asarray(
            [
                [1.0, *path_features(price_history, surface_date, name)]
                for surface_date in history_dates
            ],
            dtype=float,
        )
        next_features[name] = np.asarray(
            [
                1.0,
                *path_features(
                    price_history,
                    history_dates[-1],
                    name,
                    next_session=True,
                ),
            ],
            dtype=float,
        )
    a, a_state = _ou_parameter_forecast(
        parameters[:, 0], feature_matrices["a"], next_features["a"], logarithmic=False
    )
    p, p_state = _ou_parameter_forecast(
        parameters[:, 1], feature_matrices["p"], next_features["p"], logarithmic=True
    )
    rho, rho_state = _jacobi_conditional_mean(parameters[:, 2], -0.995, 0.995)
    eta, eta_state = _jacobi_conditional_mean(
        parameters[:, 3], 0.01, math.sqrt(2.0) * 0.999
    )
    predicted = np.asarray(
        [np.clip(a, 1e-5, 2.0), np.clip(p, 0.02, 2.5), rho, eta],
        dtype=float,
    )
    return {
        "parameters": predicted,
        "path_features": {"a": a_state, "p": p_state},
        "jacobi_state": {"rho": rho_state, "eta": eta_state},
    }


def static_arbitrage_checks(parameters: np.ndarray | list[float]) -> dict[str, Any]:
    a, p, rho, eta = (float(value) for value in parameters)
    butterfly_bound = eta**2 * (1.0 + abs(rho))
    calendar_monotone = a > 0 and p >= 0
    butterfly_safe = butterfly_bound < 4.0
    finite_positive = True
    maturity_grid = np.asarray([7, 14, 30, 60, 90, 180, 365, 730], dtype=float) / 365.25
    for k in np.linspace(-1.0, 1.0, 81):
        values = parsimonious_ssvi_total_variance(k, maturity_grid, parameters)
        finite_positive = finite_positive and bool(np.isfinite(values).all() and np.all(values > 0))
    return {
        "calendar_monotonic": calendar_monotone,
        "butterfly_condition": butterfly_safe,
        "finite_positive_scan": finite_positive,
        "butterfly_bound": round(butterfly_bound, 6),
        "butterfly_limit": 4.0,
        "passed": bool(calendar_monotone and butterfly_safe and finite_positive),
    }


def fit_path_dependent_ssvi(
    surfaces: np.ndarray,
    history_dates: list[str],
    price_history: dict[str, Any] | pd.Series,
    *,
    validation_start: int = MINIMUM_PARAMETER_SURFACES,
) -> dict[str, Any]:
    values = np.asarray(surfaces, dtype=float)
    if values.ndim != 3 or len(values) != len(history_dates):
        raise ValueError("Surface history and dates must be aligned.")
    if len(values) < max(MINIMUM_PARAMETER_SURFACES + 1, validation_start + 1):
        raise ValueError("Too few surfaces for a causal path-dependent validation window.")

    calibrations = [calibrate_parsimonious_ssvi(surface) for surface in values]
    parameters = np.asarray([item["parameters"] for item in calibrations], dtype=float)
    calibration_rmse = float(np.mean([item["calibration_rmse"] for item in calibrations]))
    errors: list[np.ndarray] = []
    baseline_errors: list[np.ndarray] = []
    directional_hits = 0
    directional_cells = 0
    for target_index in range(validation_start, len(values)):
        state = forecast_parameters(
            parameters[:target_index],
            history_dates[:target_index],
            price_history,
        )
        predicted_surface = ssvi_surface_from_parameters(state["parameters"])
        actual = values[target_index]
        baseline = values[target_index - 1]
        errors.append(actual - predicted_surface)
        baseline_errors.append(actual - baseline)
        predicted_move = predicted_surface - baseline
        actual_move = actual - baseline
        meaningful = np.abs(predicted_move) >= MEANINGFUL_MOVE_VOL_POINTS
        directional_hits += int(
            np.sum(np.sign(predicted_move[meaningful]) == np.sign(actual_move[meaningful]))
        )
        directional_cells += int(np.sum(meaningful))
    error_array = np.asarray(errors)
    baseline_array = np.asarray(baseline_errors)
    rmse_surface = np.sqrt(np.mean(error_array**2, axis=0))
    model_rmse = float(np.sqrt(np.mean(error_array**2)))
    baseline_rmse = float(np.sqrt(np.mean(baseline_array**2)))
    final_state = forecast_parameters(parameters, history_dates, price_history)
    forecast_surface = ssvi_surface_from_parameters(final_state["parameters"])
    return {
        "forecast_surface": forecast_surface,
        "parameters": final_state["parameters"],
        "path_features": final_state["path_features"],
        "jacobi_state": final_state["jacobi_state"],
        "rmse_surface": rmse_surface,
        "validation_sessions": len(errors),
        "validation_model_rmse": model_rmse,
        "validation_baseline_rmse": baseline_rmse,
        "validation_improvement_over_baseline_percent": (
            (baseline_rmse - model_rmse) / baseline_rmse * 100.0
            if baseline_rmse > 1e-12
            else 0.0
        ),
        "validation_directional_accuracy_percent": (
            directional_hits / directional_cells * 100.0 if directional_cells else None
        ),
        "calibration_rmse": calibration_rmse,
        "arbitrage_checks": static_arbitrage_checks(final_state["parameters"]),
    }


def _unavailable_forecast(
    ticker: str,
    symbol: str,
    expiry: str | None,
    limitation: str,
    *,
    observations: int = 0,
) -> dict[str, Any]:
    return {
        "ticker": ticker,
        "symbol": symbol,
        "available": False,
        "selected_expiry": expiry,
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "model_family": "path_dependent_ssvi",
        "observations": observations,
        "validation_sessions": 0,
        "validation_rmse_by_components": {},
        "fourth_component_improvement_percent": None,
        "component_selection_note": "The four-parameter path-dependent SSVI fit could not be evaluated.",
        "comparisons": [],
        "strategy": _empty_strategy(
            "The path-dependent IV forecast is unavailable, so no option structure was generated."
        ),
        "strategies": [],
        "overall_status": "unavailable",
        "summary": "The path-dependent SSVI forecast is not available for this selection.",
        "method_note": "This predicts next-session option-market IV, not realized volatility.",
        "adaptation_note": "NSE single-stock surfaces have materially less tenor and history than the paper's index data.",
        "source": "NSE India daily F&O bhavcopies, current option chain and yfinance closes",
        "source_url": f"https://www.nseindia.com/option-chain?symbol={symbol}",
        "paper_url": PAPER_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "is_carried_forward": False,
        "refresh_limitation": None,
        "limitation": limitation,
    }


def compare_path_forecast_to_market(
    *,
    ticker: str,
    symbol: str,
    chain: dict[str, Any],
    history_dates: list[str],
    history_surfaces: np.ndarray,
    price_history: dict[str, Any],
    lot_size: int | None,
) -> dict[str, Any]:
    selected_expiry = chain.get("selected_expiry")
    if not selected_expiry:
        return _unavailable_forecast(ticker, symbol, None, "No listed NSE expiry is available.")
    if len(history_surfaces) < MINIMUM_PARAMETER_SURFACES + 1:
        return _unavailable_forecast(
            ticker,
            symbol,
            selected_expiry,
            f"Only {len(history_surfaces)} surfaces were available; at least {MINIMUM_PARAMETER_SURFACES + 1} are required.",
            observations=len(history_surfaces),
        )
    try:
        expiry_date = datetime.strptime(selected_expiry, "%d-%b-%Y").date()
        exchange_timestamp = chain.get("exchange_timestamp")
        as_of = (
            datetime.strptime(exchange_timestamp, "%d-%b-%Y %H:%M:%S").date()
            if exchange_timestamp
            else datetime.now().date()
        )
    except ValueError:
        return _unavailable_forecast(ticker, symbol, selected_expiry, "The expiry timestamp could not be interpreted.")

    model = fit_path_dependent_ssvi(
        history_surfaces,
        history_dates,
        price_history,
        validation_start=MINIMUM_PARAMETER_SURFACES,
    )
    days_to_expiry = max(1, (expiry_date - as_of).days)
    predicted = _interpolate_tenor(model["forecast_surface"], days_to_expiry)
    errors = _interpolate_tenor(model["rmse_surface"], days_to_expiry)
    market_by_label = {item["label"]: item for item in _market_bucket_points(chain)}
    comparisons: list[dict[str, Any]] = []
    for index, (label, _, _) in enumerate(DELTA_BUCKETS):
        market = market_by_label.get(label)
        if market is None:
            continue
        forecast_iv = float(predicted[index])
        market_iv = float(market["market_iv_percent"])
        gap = market_iv - forecast_iv
        model_error = float(errors[index])
        threshold = max(2.0, 1.96 * model_error)
        significant = abs(gap) > threshold
        status = "expensive" if gap > threshold else "cheap" if gap < -threshold else "in_line"
        explanation = (
            f"Market IV is {abs(gap):.2f} volatility points {'above' if gap >= 0 else 'below'} "
            f"the path-dependent forecast; this {'exceeds' if significant else 'does not exceed'} "
            f"the {threshold:.2f}-point 95% model-error band."
        )
        comparisons.append(
            {
                **market,
                "predicted_iv_percent": round(forecast_iv, 2),
                "difference_vol_points": round(gap, 2),
                "model_error_vol_points": round(model_error, 2),
                "material_threshold_vol_points": round(threshold, 2),
                "standardized_gap": round(gap / max(model_error, 1e-8), 3),
                "significant": significant,
                "status": status,
                "explanation": explanation,
            }
        )

    dislocations = [item for item in comparisons if item["significant"]]
    if dislocations:
        strongest = max(dislocations, key=lambda item: abs(float(item["standardized_gap"])))
        overall_status = strongest["status"]
        summary = (
            f"{strongest['label']} IV is model-significantly {strongest['status']}: "
            f"{strongest['market_iv_percent']:.1f}% in the market versus "
            f"{strongest['predicted_iv_percent']:.1f}% forecast (|z| "
            f"{abs(strongest['standardized_gap']):.2f})."
        )
    else:
        overall_status = "in_line"
        summary = "No IV bucket clears the path model's 95% error band; no significant mispricing is flagged."
    primary_strategy, strategies = build_iv_strategies(chain, comparisons, lot_size)
    parameters = model["parameters"]
    checks = model["arbitrage_checks"]
    return {
        "ticker": ticker,
        "symbol": symbol,
        "available": bool(comparisons),
        "selected_expiry": selected_expiry,
        "days_to_expiry": days_to_expiry,
        "forecast_for_date": _next_weekday(date.fromisoformat(history_dates[-1])).isoformat(),
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "model_family": "path_dependent_ssvi",
        "observations": len(history_surfaces),
        "fit_start": history_dates[0],
        "fit_end": history_dates[-1],
        "principal_components": None,
        "explained_variance_percent": None,
        "validation_sessions": model["validation_sessions"],
        "validation_rmse_by_components": {"path_ssvi": round(model["validation_model_rmse"], 4)},
        "fourth_component_improvement_percent": None,
        "component_selection_note": (
            f"Four SSVI parameters fitted daily; mean calibration RMSE {model['calibration_rmse']:.2f} vol points. "
            f"Causal validation RMSE {model['validation_model_rmse']:.2f} versus "
            f"{model['validation_baseline_rmse']:.2f} for no change."
        ),
        "validation_model_rmse": round(model["validation_model_rmse"], 4),
        "validation_baseline_rmse": round(model["validation_baseline_rmse"], 4),
        "validation_improvement_over_baseline_percent": round(model["validation_improvement_over_baseline_percent"], 3),
        "validation_directional_accuracy_percent": (
            round(model["validation_directional_accuracy_percent"], 3)
            if model["validation_directional_accuracy_percent"] is not None
            else None
        ),
        "ssvi_parameters": {
            "a": round(float(parameters[0]), 8),
            "p": round(float(parameters[1]), 8),
            "rho": round(float(parameters[2]), 8),
            "eta": round(float(parameters[3]), 8),
        },
        "path_features": model["path_features"],
        "static_arbitrage_checks": checks,
        "tenor_grid_days": TENOR_DAYS.astype(int).tolist(),
        "comparisons": comparisons,
        "strategy": primary_strategy,
        "strategies": strategies,
        "overall_status": overall_status,
        "summary": summary,
        "method_note": (
            "The conditional mean of the paper's PDV/OU/Jacobi dynamics produces a fast next-session surface. "
            "A flagged gap is statistically unusual relative to walk-forward error, not a risk-free arbitrage."
        ),
        "adaptation_note": (
            "The paper uses 1-24 month SPX/SX5E surfaces and decade-scale histories. Here its four-parameter SSVI "
            "and reported path kernels are retained, but coefficients are re-estimated per NSE stock on a 14-90 "
            "day grid; 1,000-day closes support the activity feature."
        ),
        "source": "NSE India daily F&O bhavcopies, current option chain and yfinance closes",
        "source_url": chain.get("source_url") or f"https://www.nseindia.com/option-chain?symbol={symbol}",
        "paper_url": PAPER_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "is_carried_forward": False,
        "refresh_limitation": None,
        "limitation": None if comparisons else "The selected expiry did not contain enough usable delta-bucket IVs.",
    }


async def get_path_dependent_iv_surface_forecast(
    ticker: str,
    symbol: str,
    expiry: str | None = None,
) -> dict[str, Any]:
    from app.services.market_data.india_trading import get_options_chain, get_price_history

    chain = await get_options_chain(ticker, symbol, expiry)
    if not chain.get("available"):
        return _unavailable_forecast(
            ticker,
            symbol,
            expiry,
            chain.get("limitation") or "No current NSE option chain is available.",
        )
    cache = FileCache(get_settings().cache_path, "iv_forecasts")
    key = cache_key(
        MODEL_VERSION,
        symbol.upper(),
        str(chain.get("selected_expiry") or ""),
        str(chain.get("exchange_timestamp") or ""),
    )
    cached = cache.get(key, FORECAST_TTL_SECONDS)
    if cached is not None:
        return cached
    try:
        (history_dates, history_surfaces), lot_size, price_history = await asyncio.gather(
            load_historical_surfaces(symbol),
            get_fno_lot_size(symbol, chain.get("selected_expiry")),
            get_price_history(ticker, f"{symbol}.NS", "5Y"),
        )
        result = await asyncio.to_thread(
            compare_path_forecast_to_market,
            ticker=ticker,
            symbol=symbol,
            chain=chain,
            history_dates=history_dates,
            history_surfaces=history_surfaces,
            price_history=price_history,
            lot_size=lot_size,
        )
    except Exception as exc:
        result = _unavailable_forecast(
            ticker,
            symbol,
            chain.get("selected_expiry"),
            f"The path-dependent SSVI model could not be fitted: {exc}",
        )
    cache.put(key, result, source=result["source"], model_name=MODEL_NAME)
    return result


def _pooled_rmse(values: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def _cluster_bootstrap(observations: list[dict[str, Any]]) -> tuple[float | None, float | None, float | None, float | None]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        grouped[str(item["target_date"])].append(item)
    sessions = sorted(grouped)
    if len(sessions) < 2:
        return None, None, None, None
    rng = np.random.default_rng(20_260_813)
    improvements = np.empty(BOOTSTRAP_SAMPLES)
    for index in range(BOOTSTRAP_SAMPLES):
        sampled_sessions = rng.choice(sessions, len(sessions), replace=True)
        sampled = [item for session in sampled_sessions for item in grouped[str(session)]]
        model = _pooled_rmse([item["model_rmse"] for item in sampled])
        baseline = _pooled_rmse([item["baseline_rmse"] for item in sampled])
        improvements[index] = (baseline - model) / baseline * 100.0 if baseline > 1e-12 else 0.0
    lower, upper = np.quantile(improvements, [0.025, 0.975])
    probability = float(np.mean(improvements > 0) * 100.0)
    p_value = float(min(1.0, 2.0 * min(np.mean(improvements <= 0), np.mean(improvements >= 0))))
    return float(lower), float(upper), probability, p_value


def historical_path_dependent_backtest(
    histories: dict[str, dict[str, Any]],
    price_histories: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Causal expanding-window OOS evaluation on cached official NSE surfaces."""

    observations: list[dict[str, Any]] = []
    excluded_for_gaps = 0
    for symbol, history in histories.items():
        price_history = price_histories.get(symbol)
        if not price_history:
            continue
        dates = [date.fromisoformat(str(value)) for value in history.get("dates") or []]
        surfaces = np.asarray(history.get("surfaces") or [], dtype=float)
        if len(dates) != len(surfaces) or surfaces.ndim != 3 or len(surfaces) <= MINIMUM_BACKTEST_SURFACES:
            continue
        if any(not 0 < (right - left).days <= 4 for left, right in zip(dates, dates[1:], strict=False)):
            excluded_for_gaps += max(0, len(dates) - MINIMUM_BACKTEST_SURFACES)
            continue
        evaluation_surfaces = np.asarray([_smooth_surface(surface) for surface in surfaces])
        calibrations = [calibrate_parsimonious_ssvi(surface) for surface in evaluation_surfaces]
        parameters = np.asarray([item["parameters"] for item in calibrations], dtype=float)
        for target_index in range(MINIMUM_BACKTEST_SURFACES, len(surfaces)):
            state = forecast_parameters(
                parameters[:target_index],
                [item.isoformat() for item in dates[:target_index]],
                price_history,
            )
            forecast = ssvi_surface_from_parameters(state["parameters"])
            actual = evaluation_surfaces[target_index]
            baseline = evaluation_surfaces[target_index - 1]
            model_rmse = float(np.sqrt(np.mean((actual - forecast) ** 2)))
            baseline_rmse = float(np.sqrt(np.mean((actual - baseline) ** 2)))
            training = evaluation_surfaces[:target_index]
            flat = training.reshape(len(training), -1)
            centered = flat - flat.mean(axis=0)
            singular_values = np.linalg.svd(centered, full_matrices=False, compute_uv=False)
            variances = singular_values**2
            cumulative = np.cumsum(variances) / float(variances.sum()) * 100.0
            component_count, _ = _select_component_count(cumulative)
            fpca_forecast = np.asarray(
                _fit_fpca_core(training, component_count)["forecast_surface"],
                dtype=float,
            )
            fpca_rmse = float(np.sqrt(np.mean((actual - fpca_forecast) ** 2)))
            predicted_move = forecast - baseline
            actual_move = actual - baseline
            meaningful = np.abs(predicted_move) >= MEANINGFUL_MOVE_VOL_POINTS
            observations.append(
                {
                    "ticker": symbol,
                    "target_date": dates[target_index].isoformat(),
                    "model_rmse": model_rmse,
                    "baseline_rmse": baseline_rmse,
                    "fpca_rmse": fpca_rmse,
                    "directional_hits": int(np.sum(np.sign(predicted_move[meaningful]) == np.sign(actual_move[meaningful]))),
                    "directional_cells": int(np.sum(meaningful)),
                    "calibration_rmse": float(calibrations[target_index - 1]["calibration_rmse"]),
                    "arbitrage_passed": bool(static_arbitrage_checks(state["parameters"])["passed"]),
                }
            )
    if not observations:
        return {
            "available": False,
            "verdict": "Insufficient continuous history",
            "verdict_detail": "No symbol had enough aligned option surfaces and 5-year daily closes for a causal target.",
            "observations": 0,
            "excluded_for_gaps": excluded_for_gaps,
            "source": "Official NSE F&O bhavcopies and yfinance daily closes",
            "paper_url": PAPER_URL,
            "strengths": [],
            "weaknesses": [],
        }
    model_rmse = _pooled_rmse([item["model_rmse"] for item in observations])
    baseline_rmse = _pooled_rmse([item["baseline_rmse"] for item in observations])
    fpca_rmse = _pooled_rmse([item["fpca_rmse"] for item in observations])
    improvement = (baseline_rmse - model_rmse) / baseline_rmse * 100.0 if baseline_rmse > 1e-12 else 0.0
    lower, upper, probability, p_value = _cluster_bootstrap(observations)
    directional_cells = sum(item["directional_cells"] for item in observations)
    directional_hits = sum(item["directional_hits"] for item in observations)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        grouped[item["ticker"]].append(item)
    per_symbol = []
    for symbol, values in grouped.items():
        symbol_model = _pooled_rmse([item["model_rmse"] for item in values])
        symbol_baseline = _pooled_rmse([item["baseline_rmse"] for item in values])
        cells = sum(item["directional_cells"] for item in values)
        per_symbol.append(
            {
                "ticker": symbol,
                "observations": len(values),
                "model_rmse": symbol_model,
                "baseline_rmse": symbol_baseline,
                "improvement_over_baseline_percent": (symbol_baseline - symbol_model) / symbol_baseline * 100.0 if symbol_baseline > 1e-12 else 0.0,
                "model_win_rate_percent": sum(item["model_rmse"] < item["baseline_rmse"] for item in values) / len(values) * 100.0,
                "directional_accuracy_percent": sum(item["directional_hits"] for item in values) / cells * 100.0 if cells else None,
            }
        )
    per_symbol.sort(key=lambda item: item["improvement_over_baseline_percent"], reverse=True)
    statistically_significant = bool(lower is not None and lower > 0 and p_value is not None and p_value < 0.05)
    difference_significant = bool(p_value is not None and p_value < 0.05)
    significance_result = (
        "Significantly better than no change"
        if statistically_significant
        else "Significantly worse than no change"
        if difference_significant and upper is not None and upper < 0
        else "Not statistically different from no change"
    )
    if statistically_significant:
        verdict = "Statistically significant OOS edge"
        verdict_detail = "Path-dependent SSVI reduced next-session surface RMSE versus no change and its date-clustered 95% interval stayed above zero."
    elif improvement <= 0:
        verdict = "No OOS forecasting edge"
        verdict_detail = "The challenger did not beat the no-change surface in pooled out-of-sample RMSE. Keep it in research, not production trade selection."
    else:
        verdict = "Positive but not statistically significant"
        verdict_detail = "The point estimate improved on no change, but the date-clustered confidence interval includes zero."
    return {
        "available": True,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "statistically_significant": statistically_significant,
        "difference_statistically_significant": difference_significant,
        "significance_result": significance_result,
        "bootstrap_p_value_two_sided": p_value,
        "observations": len(observations),
        "symbols": len(grouped),
        "target_sessions": len({item["target_date"] for item in observations}),
        "first_target_date": min(item["target_date"] for item in observations),
        "last_target_date": max(item["target_date"] for item in observations),
        "excluded_for_gaps": excluded_for_gaps,
        "model_rmse": model_rmse,
        "baseline_rmse": baseline_rmse,
        "fpca_rmse_same_sample": fpca_rmse,
        "improvement_over_fpca_percent": (
            (fpca_rmse - model_rmse) / fpca_rmse * 100.0
            if fpca_rmse > 1e-12
            else None
        ),
        "improvement_over_baseline_percent": improvement,
        "improvement_confidence_interval_95": [lower, upper],
        "bootstrap_probability_model_beats_baseline_percent": probability,
        "model_win_rate_percent": sum(item["model_rmse"] < item["baseline_rmse"] for item in observations) / len(observations) * 100.0,
        "directional_accuracy_percent": directional_hits / directional_cells * 100.0 if directional_cells else None,
        "meaningful_directional_cells": directional_cells,
        "average_calibration_rmse": float(np.mean([item["calibration_rmse"] for item in observations])),
        "static_arbitrage_pass_rate_percent": float(np.mean([item["arbitrage_passed"] for item in observations]) * 100.0),
        "per_symbol": per_symbol,
        "source": "Official NSE F&O bhavcopy closing IVs and yfinance daily underlying closes",
        "paper_url": PAPER_URL,
        "methodology": "Expanding-window, one-observed-session-ahead forecasts; every target surface and target-session return are excluded. Confidence intervals cluster-bootstrap complete target sessions.",
        "limitation": "This tests surface IV error, not executable spread P&L. The NSE sample is much shorter and has fewer tenors than the paper's SPX/SX5E panel.",
        "strengths": [
            "Four parameters generate the whole surface quickly and transparently.",
            "The SSVI constraints preserve calendar monotonicity and the paper's sufficient butterfly-arbitrage bound.",
            "Trend and long-memory activity features encode leverage and volatility clustering directly from the underlying path.",
        ],
        "weaknesses": [
            "The paper validates broad index options with 1-24 month tenors; NSE single-stock 14-90 day surfaces are a material domain shift.",
            "A 50-session option history is too short to re-estimate all TSPL kernel hyperparameters, so paper-reported kernels are transferred.",
            "The conditional-mean forecast does not replay bid-ask spreads, slippage, theta or realized spread P&L.",
            "The authors leave asset-management and trading-strategy impact for future research; mispricing labels here are model-relative, not arbitrage claims.",
        ],
    }


async def get_cached_path_dependent_backtest(
    histories: dict[str, dict[str, Any]],
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    from app.services.market_data.india_trading import get_price_history

    cache = FileCache(get_settings().cache_path, "iv_model_evaluation")
    key = cache_key(
        MODEL_VERSION,
        "historical-backtest",
        ",".join(sorted(histories)),
    )
    if not force_refresh:
        cached = cache.get(key, 6 * 60 * 60)
        if cached is not None:
            return cached
    semaphore = asyncio.Semaphore(6)

    async def load(symbol: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            return symbol, await get_price_history(symbol, f"{symbol}.NS", "5Y")

    loaded = await asyncio.gather(*(load(symbol) for symbol in histories))
    prices = dict(loaded)
    result = await asyncio.to_thread(historical_path_dependent_backtest, histories, prices)
    cache.put(key, result, source=result.get("source", "NSE/yfinance"), model_name=MODEL_NAME)
    return result
