"""Exact-design replication of Shang & Kearney's dynamic FTS IV study.

The paper uses six functional time-series models (static/dynamic versions of
independent, multivariate and multilevel FPCA), expanding windows, automatic
ARIMA score forecasts, two component-selection rules, and 1/5/10-day horizons.
This module deliberately keeps that experiment separate from the production
FPCA-VAR and path-dependent SSVI implementations.

Paper: https://arxiv.org/pdf/2107.14026
"""

from __future__ import annotations

import math
import os
import warnings
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

import numpy as np
from scipy.stats import norm
from statsforecast.models import AutoARIMA
from statsmodels.tsa.api import VAR
from statsmodels.tsa.ar_model import AutoReg

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings

PAPER_URL = "https://arxiv.org/pdf/2107.14026"
PAPER_NAME = "Dynamic functional time-series forecasts of implied-volatility surfaces"
REPLICATION_VERSION = "shang-kearney-2022-exact-design-v1"

PAPER_INITIAL_TRAINING = 1_827
PAPER_OUT_OF_SAMPLE = 522
PAPER_TOTAL_OBSERVATIONS = PAPER_INITIAL_TRAINING + PAPER_OUT_OF_SAMPLE
PAPER_HORIZONS = (1, 5, 10)
PAPER_TEST_OBSERVATIONS = {1: 522, 5: 518, 10: 513}
PAPER_DELTA_POINTS = (10, 25, 50, 75, 90)
PAPER_CPV = 0.99
PAPER_MULTILEVEL_CPV = 0.90
PAPER_FIXED_COMPONENTS = 4
PAPER_MCS_BOOTSTRAPS = 5_000
PAPER_MCS_ALPHA = 0.05
# NSE stock options cannot supply the paper's 1M/6M/2Y OTC FX maturities. Use
# three listed rolling points (30/60/90 days) so the estimator has the paper's
# exact three-series design, while reporting the maturity-grid non-equivalence.
NSE_SOURCE_TENOR_DAYS = (14, 30, 60, 90)
NSE_PAPER_TENOR_INDICES = (1, 2, 3)
NSE_REPLICATION_TENOR_DAYS = (30, 60, 90)

MODEL_LABELS = {
    "fts": "FTS",
    "dfts": "DFTS",
    "mfts": "MFTS",
    "dmfts": "DMFTS",
    "mlfts": "MLFTS",
    "dmlfts": "DMLFTS",
    "rw": "RW",
    "ar1": "AR(1)",
    "ct11": "CT11",
    "gg06": "GG06",
}

ComponentRule = Literal["cpv", "k4"]
ScoreForecaster = Callable[[np.ndarray, int], np.ndarray]


@dataclass(frozen=True)
class FPCABasis:
    mean: np.ndarray
    vectors: np.ndarray
    scores: np.ndarray
    eigenvalues: np.ndarray
    bandwidth: float | None


def _flat_top(value: float) -> float:
    value = abs(value)
    if value < 0.5:
        return 1.0
    if value <= 1.0:
        return 2.0 - 2.0 * value
    return 0.0


def _bartlett(value: float) -> float:
    return max(0.0, 1.0 - abs(value))


def _lag_covariance(centered: np.ndarray, lag: int) -> np.ndarray:
    """Match ftsa::long_run_covariance_estimation's denominator convention."""

    observations = len(centered)
    if lag == 0:
        return centered.T @ centered / observations
    return centered[:-lag].T @ centered[lag:] / observations


def _kernel_covariance(
    centered: np.ndarray,
    bandwidth: float,
    kernel: Callable[[float], float],
    *,
    power: int = 0,
) -> np.ndarray:
    # The ftsa reference implementation includes gamma(0) in cov_l for every
    # derivative order, including the pilot C_2 calculation.
    result = _lag_covariance(centered, 0)
    max_lag = min(len(centered) - 1, int(math.floor(bandwidth)))
    for lag in range(1, max_lag + 1):
        weight = kernel(lag / bandwidth) * (lag**power)
        if weight == 0:
            continue
        covariance = _lag_covariance(centered, lag)
        result += weight * (covariance + covariance.T)
    return (result + result.T) / 2.0


def rice_shang_long_run_covariance(curves: np.ndarray) -> tuple[np.ndarray, float]:
    """Rice-Shang plug-in long-run covariance used by the paper's DFPCA.

    This follows the CRAN ``ftsa`` reference implementation: a flat-top pilot
    bandwidth of T^.2 followed by the order-one Bartlett plug-in bandwidth.
    """

    values = np.asarray(curves, dtype=float)
    if values.ndim != 2 or len(values) < 4:
        raise ValueError("Dynamic FPCA needs a two-dimensional series with at least four rows.")
    centered = values - values.mean(axis=0)
    pilot = max(1.0, len(values) ** 0.2)
    covariance_zero = _kernel_covariance(centered, pilot, _flat_top)
    covariance_two = _kernel_covariance(centered, pilot, _flat_top, power=1)
    numerator = max(2.0 * float(np.sum(covariance_two**2)), 1e-16)
    denominator = max(
        (float(np.sum(covariance_zero**2)) + float(np.trace(covariance_zero)) ** 2)
        * (2.0 / 3.0),
        1e-16,
    )
    constant = numerator ** (1.0 / 3.0) * denominator ** (-1.0 / 3.0)
    bandwidth = max(1.0, constant * len(values) ** (1.0 / 3.0))
    return _kernel_covariance(centered, bandwidth, _bartlett), float(bandwidth)


def fit_fpca(curves: np.ndarray, *, dynamic: bool) -> FPCABasis:
    values = np.asarray(curves, dtype=float)
    if values.ndim != 2 or not np.all(np.isfinite(values)):
        raise ValueError("FPCA input must be a finite observations-by-grid matrix.")
    mean = values.mean(axis=0)
    centered = values - mean
    if dynamic:
        covariance, bandwidth = rice_shang_long_run_covariance(values)
    else:
        covariance = centered.T @ centered / len(values)
        bandwidth = None
    eigenvalues, vectors = np.linalg.eigh((covariance + covariance.T) / 2.0)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.maximum(eigenvalues[order], 0.0)
    vectors = vectors[:, order]
    scores = centered @ vectors
    return FPCABasis(mean, vectors, scores, eigenvalues, bandwidth)


def component_count(
    eigenvalues: np.ndarray,
    rule: ComponentRule,
    *,
    cpv: float = PAPER_CPV,
) -> int:
    available = len(eigenvalues)
    if available == 0:
        return 0
    if rule == "k4":
        return min(PAPER_FIXED_COMPONENTS, available)
    total = float(np.sum(np.maximum(eigenvalues, 0.0)))
    if total <= 1e-14:
        return 1
    return int(np.searchsorted(np.cumsum(eigenvalues) / total, cpv) + 1)


def auto_arima_score_forecast(scores: np.ndarray, horizon: int) -> np.ndarray:
    """Hyndman-Khandakar auto-ARIMA with the paper/R forecast defaults."""

    values = np.asarray(scores, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    forecasts = np.zeros((horizon, values.shape[1]), dtype=float)
    for column in range(values.shape[1]):
        series = values[:, column]
        if np.std(series) <= 1e-12:
            forecasts[:, column] = series[-1]
            continue
        model = AutoARIMA(
            max_p=5,
            max_q=5,
            max_d=2,
            max_order=5,
            start_p=2,
            start_q=2,
            seasonal=False,
            season_length=1,
            ic="aicc",
            stepwise=True,
            approximation=len(series) > 150,
            test="kpss",
            allowdrift=True,
            allowmean=True,
        )
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fitted = model.fit(series)
                forecasts[:, column] = np.asarray(fitted.predict(horizon)["mean"])
        except Exception:
            # forecast::auto.arima can also fail on numerically degenerate score
            # paths; its operational fallback is the last finite score.
            forecasts[:, column] = series[-1]
    return forecasts


def _reconstruct(
    basis: FPCABasis,
    score_forecast: np.ndarray,
    count: int,
) -> np.ndarray:
    return basis.mean + score_forecast[:, :count] @ basis.vectors[:, :count].T


def _fit_and_forecast(
    curves: np.ndarray,
    *,
    dynamic: bool,
    horizon: int,
    rule: ComponentRule,
    cpv: float,
    score_forecaster: ScoreForecaster,
) -> tuple[np.ndarray, int, float | None]:
    basis = fit_fpca(curves, dynamic=dynamic)
    count = component_count(basis.eigenvalues, rule, cpv=cpv)
    score_forecast = score_forecaster(basis.scores[:, :count], horizon)
    return _reconstruct(basis, score_forecast, count), count, basis.bandwidth


def forecast_independent(
    surfaces: np.ndarray,
    *,
    dynamic: bool,
    horizon: int,
    rule: ComponentRule,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
) -> tuple[np.ndarray, dict[str, Any]]:
    """FTS/DFTS: forecast each maturity-specific smile independently."""

    values = np.asarray(surfaces, dtype=float)
    forecasts = np.empty((horizon, values.shape[1], values.shape[2]))
    counts: list[int] = []
    bandwidths: list[float] = []
    for maturity in range(values.shape[1]):
        forecast, count, bandwidth = _fit_and_forecast(
            values[:, maturity, :],
            dynamic=dynamic,
            horizon=horizon,
            rule=rule,
            cpv=PAPER_CPV,
            score_forecaster=score_forecaster,
        )
        forecasts[:, maturity, :] = forecast
        counts.append(count)
        if bandwidth is not None:
            bandwidths.append(bandwidth)
    return forecasts, {"components": counts, "bandwidths": bandwidths}


def forecast_multivariate(
    surfaces: np.ndarray,
    *,
    dynamic: bool,
    horizon: int,
    rule: ComponentRule,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
) -> tuple[np.ndarray, dict[str, Any]]:
    """MFTS/DMFTS: joint standardized multivariate functional FPCA."""

    values = np.asarray(surfaces, dtype=float)
    scales = np.std(values, axis=(0, 2), ddof=1)
    scales = np.where(scales > 1e-10, scales, 1.0)
    standardized = values / scales[None, :, None]
    curves = standardized.reshape(len(values), -1)
    forecast, count, bandwidth = _fit_and_forecast(
        curves,
        dynamic=dynamic,
        horizon=horizon,
        rule=rule,
        cpv=PAPER_CPV,
        score_forecaster=score_forecaster,
    )
    reshaped = forecast.reshape(horizon, values.shape[1], values.shape[2])
    reshaped *= scales[None, :, None]
    return reshaped, {"components": [count], "bandwidths": [bandwidth] if bandwidth else []}


def forecast_multilevel(
    surfaces: np.ndarray,
    *,
    dynamic: bool,
    horizon: int,
    rule: ComponentRule,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
) -> tuple[np.ndarray, dict[str, Any]]:
    """MLFTS/DMLFTS: common smile plus maturity-specific residual smiles."""

    values = np.asarray(surfaces, dtype=float)
    common = values.mean(axis=1)
    common_mean = common.mean(axis=0)
    maturity_deviation = values.mean(axis=0) - common_mean[None, :]
    common_basis = fit_fpca(common, dynamic=dynamic)
    common_count = component_count(
        common_basis.eigenvalues,
        rule,
        cpv=PAPER_MULTILEVEL_CPV if rule == "cpv" else PAPER_CPV,
    )
    common_score_forecast = score_forecaster(
        common_basis.scores[:, :common_count], horizon
    )
    common_component = _reconstruct(
        common_basis, common_score_forecast, common_count
    )
    fitted_common_trend = (
        common_basis.scores[:, :common_count]
        @ common_basis.vectors[:, :common_count].T
    )
    residuals = (
        values
        - common_mean[None, None, :]
        - maturity_deviation[None, :, :]
        - fitted_common_trend[:, None, :]
    )
    forecasts = common_component[:, None, :] + maturity_deviation[None, :, :]
    forecasts = np.tile(forecasts, (1, 1, 1))
    counts = [common_count]
    bandwidths = [common_basis.bandwidth] if common_basis.bandwidth else []
    for maturity in range(values.shape[1]):
        residual_forecast, count, bandwidth = _fit_and_forecast(
            residuals[:, maturity, :],
            dynamic=dynamic,
            horizon=horizon,
            rule=rule,
            cpv=PAPER_MULTILEVEL_CPV if rule == "cpv" else PAPER_CPV,
            score_forecaster=score_forecaster,
        )
        forecasts[:, maturity, :] += residual_forecast
        counts.append(count)
        if bandwidth is not None:
            bandwidths.append(bandwidth)
    return forecasts, {"components": counts, "bandwidths": bandwidths}


def forecast_ar1(surfaces: np.ndarray, horizon: int) -> np.ndarray:
    """Paper benchmark: independent AR(1) at every maturity/delta quote."""

    values = np.asarray(surfaces, dtype=float)
    flattened = values.reshape(len(values), -1)
    x = flattened[:-1]
    y = flattened[1:]
    x_mean = x.mean(axis=0)
    y_mean = y.mean(axis=0)
    denominator = np.sum((x - x_mean) ** 2, axis=0)
    phi = np.divide(
        np.sum((x - x_mean) * (y - y_mean), axis=0),
        denominator,
        out=np.zeros_like(denominator),
        where=denominator > 1e-12,
    )
    intercept = y_mean - phi * x_mean
    result = np.empty((horizon, flattened.shape[1]))
    current = flattened[-1].copy()
    for step in range(horizon):
        current = intercept + phi * current
        result[step] = current
    return result.reshape(horizon, values.shape[1], values.shape[2])


def _var_forecast(values: np.ndarray, horizon: int, *, max_lags: int = 15) -> np.ndarray:
    series = np.asarray(values, dtype=float)
    usable_lags = min(max_lags, max(1, len(series) // 20))
    try:
        fitted = VAR(series).fit(maxlags=usable_lags, ic="bic", trend="c")
        lag_order = max(1, fitted.k_ar)
        if fitted.k_ar == 0:
            return np.repeat(fitted.intercept[None, :], horizon, axis=0)
        return np.asarray(fitted.forecast(series[-lag_order:], horizon))
    except (ValueError, np.linalg.LinAlgError):
        return np.repeat(series[-1][None, :], horizon, axis=0)


def forecast_ct11(surfaces: np.ndarray, horizon: int) -> np.ndarray:
    """Chalamandaris-Tsekrekos: three static factors and BIC-selected VAR(15)."""

    values = np.asarray(surfaces, dtype=float)
    flattened = values.reshape(len(values), -1)
    basis = fit_fpca(flattened, dynamic=False)
    count = min(3, basis.scores.shape[1])
    score_forecast = _var_forecast(basis.scores[:, :count], horizon, max_lags=15)
    return _reconstruct(basis, score_forecast, count).reshape(
        horizon, values.shape[1], values.shape[2]
    )


def _gg06_design(surface: np.ndarray) -> np.ndarray:
    """Recover time-adjusted moneyness from fixed-delta IV quotes."""

    maturity_years = np.asarray(NSE_REPLICATION_TENOR_DAYS, dtype=float) / 365.25
    delta = np.asarray(PAPER_DELTA_POINTS, dtype=float) / 100.0
    volatility = np.asarray(surface, dtype=float) / 100.0
    d1 = norm.ppf(delta)[None, :]
    maturity = maturity_years[:, None]
    moneyness = -d1 * volatility + 0.5 * volatility**2 * np.sqrt(maturity)
    return np.column_stack(
        [
            np.ones(surface.size),
            moneyness.ravel(),
            (moneyness**2).ravel(),
            np.broadcast_to(maturity, surface.shape).ravel(),
            (moneyness * maturity).ravel(),
        ]
    )


def forecast_gg06(surfaces: np.ndarray, horizon: int) -> np.ndarray:
    """Goncalves-Guidolin two-stage log-IV regression and coefficient VAR."""

    values = np.asarray(surfaces, dtype=float)
    coefficients = np.asarray(
        [
            np.linalg.lstsq(
                _gg06_design(surface),
                np.log(np.maximum(surface, 1e-6)).ravel(),
                rcond=None,
            )[0]
            for surface in values
        ]
    )
    coefficient_forecast = _var_forecast(coefficients, horizon, max_lags=15)
    # Future option strikes are unknown in a fixed-delta archive. Following the
    # paper's primitive-price no-change assumption, use today's recovered
    # moneyness design for every horizon.
    design = _gg06_design(values[-1])
    return np.asarray(
        [np.exp(design @ beta).reshape(values.shape[1], values.shape[2]) for beta in coefficient_forecast]
    )


def forecast_six_models(
    surfaces: np.ndarray,
    *,
    horizon: int,
    rule: ComponentRule,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    forecasts: dict[str, np.ndarray] = {}
    diagnostics: dict[str, Any] = {}
    for name, function, dynamic in (
        ("fts", forecast_independent, False),
        ("dfts", forecast_independent, True),
        ("mfts", forecast_multivariate, False),
        ("dmfts", forecast_multivariate, True),
        ("mlfts", forecast_multilevel, False),
        ("dmlfts", forecast_multilevel, True),
    ):
        forecasts[name], diagnostics[name] = function(
            surfaces,
            dynamic=dynamic,
            horizon=horizon,
            rule=rule,
            score_forecaster=score_forecaster,
        )
    forecasts["rw"] = np.repeat(surfaces[-1][None, :, :], horizon, axis=0)
    forecasts["ar1"] = forecast_ar1(surfaces, horizon)
    forecasts["ct11"] = forecast_ct11(surfaces, horizon)
    forecasts["gg06"] = forecast_gg06(surfaces, horizon)
    return forecasts, diagnostics


def _fit_and_forecast_both_rules(
    curves: np.ndarray,
    *,
    dynamic: bool,
    horizon: int,
    cpv: float,
    score_forecaster: ScoreForecaster,
) -> tuple[dict[str, np.ndarray], dict[str, int], float | None]:
    basis = fit_fpca(curves, dynamic=dynamic)
    counts = {
        "cpv": component_count(basis.eigenvalues, "cpv", cpv=cpv),
        "k4": component_count(basis.eigenvalues, "k4", cpv=cpv),
    }
    maximum = max(counts.values())
    score_forecast = score_forecaster(basis.scores[:, :maximum], horizon)
    return (
        {
            rule: _reconstruct(basis, score_forecast, count)
            for rule, count in counts.items()
        },
        counts,
        basis.bandwidth,
    )


def _forecast_model_both_rules(
    surfaces: np.ndarray,
    *,
    family: Literal["independent", "multivariate", "multilevel"],
    dynamic: bool,
    horizon: int,
    score_forecaster: ScoreForecaster,
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    values = np.asarray(surfaces, dtype=float)
    forecasts = {
        rule: np.zeros((horizon, values.shape[1], values.shape[2]))
        for rule in ("cpv", "k4")
    }
    diagnostics = {
        rule: {"components": [], "bandwidths": []}
        for rule in ("cpv", "k4")
    }
    if family == "independent":
        for maturity in range(values.shape[1]):
            result, counts, bandwidth = _fit_and_forecast_both_rules(
                values[:, maturity, :],
                dynamic=dynamic,
                horizon=horizon,
                cpv=PAPER_CPV,
                score_forecaster=score_forecaster,
            )
            for rule in ("cpv", "k4"):
                forecasts[rule][:, maturity, :] = result[rule]
                diagnostics[rule]["components"].append(counts[rule])
                if bandwidth is not None:
                    diagnostics[rule]["bandwidths"].append(bandwidth)
        return forecasts, diagnostics

    if family == "multivariate":
        scales = np.std(values, axis=(0, 2), ddof=1)
        scales = np.where(scales > 1e-10, scales, 1.0)
        result, counts, bandwidth = _fit_and_forecast_both_rules(
            (values / scales[None, :, None]).reshape(len(values), -1),
            dynamic=dynamic,
            horizon=horizon,
            cpv=PAPER_CPV,
            score_forecaster=score_forecaster,
        )
        for rule in ("cpv", "k4"):
            forecasts[rule] = (
                result[rule].reshape(horizon, values.shape[1], values.shape[2])
                * scales[None, :, None]
            )
            diagnostics[rule]["components"].append(counts[rule])
            if bandwidth is not None:
                diagnostics[rule]["bandwidths"].append(bandwidth)
        return forecasts, diagnostics

    common = values.mean(axis=1)
    common_mean = common.mean(axis=0)
    maturity_deviation = values.mean(axis=0) - common_mean[None, :]
    common_basis = fit_fpca(common, dynamic=dynamic)
    common_counts = {
        "cpv": component_count(
            common_basis.eigenvalues, "cpv", cpv=PAPER_MULTILEVEL_CPV
        ),
        "k4": component_count(common_basis.eigenvalues, "k4"),
    }
    maximum_common = max(common_counts.values())
    common_score_forecast = score_forecaster(
        common_basis.scores[:, :maximum_common], horizon
    )
    for rule in ("cpv", "k4"):
        count = common_counts[rule]
        common_result = _reconstruct(common_basis, common_score_forecast, count)
        forecasts[rule] = common_result[:, None, :] + maturity_deviation[None, :, :]
        diagnostics[rule]["components"].append(common_counts[rule])
        if common_basis.bandwidth is not None:
            diagnostics[rule]["bandwidths"].append(common_basis.bandwidth)
        fitted_common_trend = (
            common_basis.scores[:, :count] @ common_basis.vectors[:, :count].T
        )
        residuals = (
            values
            - common_mean[None, None, :]
            - maturity_deviation[None, :, :]
            - fitted_common_trend[:, None, :]
        )
        for maturity in range(values.shape[1]):
            result, residual_count, bandwidth = _fit_and_forecast(
                residuals[:, maturity, :],
                dynamic=dynamic,
                horizon=horizon,
                rule=rule,
                cpv=PAPER_MULTILEVEL_CPV if rule == "cpv" else PAPER_CPV,
                score_forecaster=score_forecaster,
            )
            forecasts[rule][:, maturity, :] += result
            diagnostics[rule]["components"].append(residual_count)
            if bandwidth is not None:
                diagnostics[rule]["bandwidths"].append(bandwidth)
    return forecasts, diagnostics


def forecast_six_models_both_rules(
    surfaces: np.ndarray,
    *,
    horizon: int,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
) -> tuple[dict[str, dict[str, np.ndarray]], dict[str, dict[str, Any]]]:
    """Estimate each FPCA basis once, then reconstruct both paper K rules."""

    jobs = (
        ("fts", "independent", False),
        ("dfts", "independent", True),
        ("mfts", "multivariate", False),
        ("dmfts", "multivariate", True),
        ("mlfts", "multilevel", False),
        ("dmlfts", "multilevel", True),
    )
    by_rule = {rule: {} for rule in ("cpv", "k4")}
    diagnostics = {rule: {} for rule in ("cpv", "k4")}

    def run(job: tuple[str, str, bool]):
        name, family, dynamic = job
        result = _forecast_model_both_rules(
            surfaces,
            family=family,  # type: ignore[arg-type]
            dynamic=dynamic,
            horizon=horizon,
            score_forecaster=score_forecaster,
        )
        return name, result

    for job in jobs:
        name, (forecasts, detail) = run(job)
        for rule in ("cpv", "k4"):
            by_rule[rule][name] = forecasts[rule]
            diagnostics[rule][name] = detail[rule]
    random_walk = np.repeat(surfaces[-1][None, :, :], horizon, axis=0)
    autoregression = forecast_ar1(surfaces, horizon)
    ct11 = forecast_ct11(surfaces, horizon)
    gg06 = forecast_gg06(surfaces, horizon)
    for rule in ("cpv", "k4"):
        by_rule[rule]["rw"] = random_walk
        by_rule[rule]["ar1"] = autoregression
        by_rule[rule]["ct11"] = ct11
        by_rule[rule]["gg06"] = gg06
    return by_rule, diagnostics


def paper_errors(forecast: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    error = np.asarray(actual, dtype=float) - np.asarray(forecast, dtype=float)
    absolute = np.abs(error)
    under = error > 0
    return {
        "mafe": float(np.mean(absolute)),
        "msfe": float(np.mean(error**2)),
        # Brailsford-Faff mixed errors used in equations (12)-(13): square-root
        # loss is applied to the side receiving the heavier penalty.
        "mme_under": float(np.mean(np.where(under, np.sqrt(absolute), absolute))),
        "mme_over": float(np.mean(np.where(under, absolute, np.sqrt(absolute)))),
    }


def _mcs_block_length(losses: np.ndarray) -> int:
    """Reproduce MCS::MCSprocedure's max selected AR order, with min.k=3."""

    maximum = 0
    max_lag = min(10, len(losses) // 4)
    if max_lag < 1:
        return 3
    for column in range(losses.shape[1]):
        series = losses[:, column]
        best_order = 0
        best_aic = math.inf
        for order in range(max_lag + 1):
            try:
                if order == 0:
                    residual = series - np.mean(series)
                    variance = max(float(np.mean(residual**2)), 1e-16)
                    aic = len(series) * math.log(variance) + 2
                else:
                    aic = float(
                        AutoReg(series, lags=order, trend="c", old_names=False).fit().aic
                    )
                if aic < best_aic:
                    best_aic = aic
                    best_order = order
            except (ValueError, np.linalg.LinAlgError):
                continue
        maximum = max(maximum, best_order)
    return max(3, maximum)


def _block_bootstrap_indices(
    observations: int,
    block_length: int,
    samples: int,
    rng: np.random.Generator,
) -> np.ndarray:
    block_count = math.ceil(observations / block_length)
    starts = rng.integers(
        0,
        observations - block_length,
        size=(samples, block_count),
    )
    offsets = np.arange(block_length)
    return (starts[..., None] + offsets).reshape(samples, -1)[:, :observations]


def model_confidence_set(
    losses: np.ndarray,
    model_names: list[str],
    *,
    statistic: Literal["Tmax", "TR"],
    alpha: float = PAPER_MCS_ALPHA,
    bootstraps: int = PAPER_MCS_BOOTSTRAPS,
    seed: int = 20_220_711,
) -> dict[str, Any]:
    """Hansen-Lunde-Nason MCS using the same sequential rule as R's MCS package."""

    values = np.asarray(losses, dtype=float)
    if values.ndim != 2 or values.shape[1] != len(model_names):
        raise ValueError("MCS losses must be observations by named models.")
    if len(model_names) < 2:
        return {
            "statistic": statistic,
            "included": model_names,
            "excluded": [],
            "block_length": 0,
            "bootstraps": bootstraps,
        }
    block_length = _mcs_block_length(values)
    indices = _block_bootstrap_indices(
        len(values), block_length, bootstraps, np.random.default_rng(seed)
    )
    active = list(range(len(model_names)))
    elimination_p: dict[int, float] = {}
    running_p = 0.0
    while len(active) > 1:
        current = values[:, active]
        means = current.mean(axis=0)
        pair_means = means[:, None] - means[None, :]
        average_differences = pair_means.sum(axis=1) / (len(active) - 1)
        bootstrap_means = current[indices].mean(axis=1)
        bootstrap_pairs = bootstrap_means[:, :, None] - bootstrap_means[:, None, :]
        pair_variance = np.mean(
            (bootstrap_pairs - pair_means[None, :, :]) ** 2,
            axis=0,
        )
        bootstrap_average = bootstrap_pairs.sum(axis=2) / (len(active) - 1)
        average_variance = np.mean(
            (bootstrap_average - average_differences[None, :]) ** 2,
            axis=0,
        )
        pair_scale = np.sqrt(np.maximum(pair_variance, 1e-16))
        average_scale = np.sqrt(np.maximum(average_variance, 1e-16))
        pair_t = pair_means / pair_scale
        average_t = average_differences / average_scale
        pair_t_boot = (bootstrap_pairs - pair_means[None, :, :]) / pair_scale[None, :, :]
        average_t_boot = (
            bootstrap_average - average_differences[None, :]
        ) / average_scale[None, :]
        if statistic == "Tmax":
            observed = float(np.max(average_t))
            simulated = np.max(average_t_boot, axis=1)
            eliminate_position = int(np.argmax(average_t))
        else:
            observed = float(np.max(np.abs(pair_t)))
            simulated = np.max(np.abs(pair_t_boot), axis=(1, 2))
            eliminate_position = int(np.argmax(np.max(pair_t, axis=1)))
        p_value = float(np.mean(simulated > observed))
        running_p = max(running_p, p_value)
        eliminated = active.pop(eliminate_position)
        elimination_p[eliminated] = running_p

    elimination_p[active[0]] = 1.0
    included = [
        model_names[index]
        for index, p_value in elimination_p.items()
        if p_value > alpha
    ]
    excluded = [name for name in model_names if name not in included]
    return {
        "statistic": statistic,
        "included": included,
        "excluded": excluded,
        "mcs_p_values": {
            model_names[index]: p_value for index, p_value in elimination_p.items()
        },
        "block_length": block_length,
        "bootstraps": bootstraps,
        "confidence_percent": (1.0 - alpha) * 100,
    }


def functional_stationarity_test(
    curves: np.ndarray,
    *,
    monte_carlo_replications: int = 1_000,
    brownian_terms: int = 500,
    seed: int = 20_220_711,
) -> dict[str, float | int | bool]:
    """Horvath-Kokoszka-Rice test matching ftsa::T_stationary defaults."""

    values = np.asarray(curves, dtype=float)
    if values.ndim != 2 or len(values) < 20:
        raise ValueError("The stationarity test needs observations by curve grid.")
    observations, grid_points = values.shape
    centered = values - values.mean(axis=0)
    bandwidth = math.sqrt(observations)
    covariance = _lag_covariance(centered, 0)
    for lag in range(1, observations):
        weight = min(1.0, max(2.0 - 2.0 * lag / bandwidth, 0.0))
        if weight == 0:
            break
        lagged = _lag_covariance(centered, lag)
        covariance += weight * (lagged + lagged.T)
    eigenvalues = np.maximum(
        np.linalg.eigvalsh((covariance + covariance.T) / 2.0)[::-1] / grid_points,
        0.0,
    )
    positive = eigenvalues[eigenvalues > 1e-14]
    component_count = min(len(positive), 15)
    if component_count == 0:
        return {
            "p_value": 1.0,
            "test_statistic": 0.0,
            "components": 0,
            "monte_carlo_replications": monte_carlo_replications,
            "rejects_stationarity_at_5_percent": False,
        }
    cumulative = np.cumsum(values, axis=0)
    full_sum = cumulative[-1]
    fractions = np.arange(1, observations + 1, dtype=float)[:, None] / observations
    bridges = (cumulative - fractions * full_sum) / math.sqrt(observations)
    statistic = float(np.sum(bridges**2) / (observations * grid_points))
    rng = np.random.default_rng(seed)
    normal_draws = rng.normal(
        size=(monte_carlo_replications, component_count, brownian_terms)
    )
    denominators = np.pi * np.arange(1, brownian_terms + 1, dtype=float)
    simulations = np.sum(
        positive[:component_count][None, :, None]
        * (normal_draws / denominators[None, None, :]) ** 2,
        axis=(1, 2),
    )
    p_value = float(np.mean(simulations >= statistic))
    return {
        "p_value": p_value,
        "test_statistic": statistic,
        "components": component_count,
        "monte_carlo_replications": monte_carlo_replications,
        "rejects_stationarity_at_5_percent": p_value < 0.05,
    }


def validate_paper_sample(surfaces: np.ndarray) -> None:
    values = np.asarray(surfaces, dtype=float)
    if values.ndim != 3 or values.shape[1:] != (3, 5):
        raise ValueError("Paper replication expects observations x 3 maturities x 5 deltas.")
    if len(values) < PAPER_TOTAL_OBSERVATIONS:
        raise ValueError(
            f"Exact paper design needs {PAPER_TOTAL_OBSERVATIONS} surfaces; got {len(values)}."
        )
    if not np.all(np.isfinite(values)):
        raise ValueError("The exact paper sample cannot contain missing IV quotes.")


_WORKER_SURFACES: np.ndarray | None = None
_WORKER_INITIAL_TRAINING = PAPER_INITIAL_TRAINING
_WORKER_MAX_HORIZON = max(PAPER_HORIZONS)


def _initialize_origin_worker(
    surfaces: np.ndarray,
    initial_training: int,
    max_horizon: int,
) -> None:
    global _WORKER_SURFACES, _WORKER_INITIAL_TRAINING, _WORKER_MAX_HORIZON
    _WORKER_SURFACES = surfaces
    _WORKER_INITIAL_TRAINING = initial_training
    _WORKER_MAX_HORIZON = max_horizon


def _forecast_origin(
    origin_offset: int,
    values: np.ndarray,
    initial_training: int,
    max_horizon: int,
    score_forecaster: ScoreForecaster,
) -> tuple[int, int, dict[str, dict[str, np.ndarray]], dict[str, dict[str, Any]]]:
    origin = initial_training + origin_offset
    available_horizon = min(max_horizon, len(values) - origin)
    forecasts, diagnostics = forecast_six_models_both_rules(
        values[:origin],
        horizon=available_horizon,
        score_forecaster=score_forecaster,
    )
    return origin_offset, available_horizon, forecasts, diagnostics


def _forecast_origin_worker(
    origin_offset: int,
) -> tuple[int, int, dict[str, dict[str, np.ndarray]], dict[str, dict[str, Any]]]:
    if _WORKER_SURFACES is None:
        raise RuntimeError("The paper backtest worker was not initialized.")
    return _forecast_origin(
        origin_offset,
        _WORKER_SURFACES,
        _WORKER_INITIAL_TRAINING,
        _WORKER_MAX_HORIZON,
        auto_arima_score_forecast,
    )


def expanding_window_backtest(
    surfaces: np.ndarray,
    *,
    initial_training: int = PAPER_INITIAL_TRAINING,
    out_of_sample: int = PAPER_OUT_OF_SAMPLE,
    horizons: tuple[int, ...] = PAPER_HORIZONS,
    score_forecaster: ScoreForecaster = auto_arima_score_forecast,
    progress: Callable[[dict[str, int]], None] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    """Run the paper's daily re-estimated, expanding-window forecast design."""

    values = np.asarray(surfaces, dtype=float)
    required = initial_training + out_of_sample
    if values.ndim != 3 or values.shape[1:] != (3, 5) or len(values) < required:
        raise ValueError(f"Backtest needs at least {required} complete 3x5 surfaces.")
    # Identical to using 1 Jan 2008--30 Dec 2016 in the paper: no observation
    # outside its fixed-length study sample affects fitting or scoring.
    values = values[-required:]
    max_horizon = max(horizons)
    losses: dict[str, dict[int, dict[str, list[float]]]] = {
        rule: {
            horizon: defaultdict(list)
            for horizon in horizons
        }
        for rule in ("cpv", "k4")
    }
    directions: dict[str, dict[int, dict[str, list[float]]]] = {
        rule: {horizon: defaultdict(list) for horizon in horizons}
        for rule in ("cpv", "k4")
    }
    component_counts: dict[str, dict[str, list[int]]] = {
        "cpv": defaultdict(list),
        "k4": defaultdict(list),
    }
    grid_errors: dict[str, dict[int, dict[str, list[np.ndarray]]]] = {
        rule: {horizon: defaultdict(list) for horizon in horizons}
        for rule in ("cpv", "k4")
    }
    if workers > 1 and score_forecaster is auto_arima_score_forecast:
        executor = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_origin_worker,
            initargs=(values, initial_training, max_horizon),
        )
        origin_results = executor.map(_forecast_origin_worker, range(out_of_sample))
    else:
        executor = None
        origin_results = (
            _forecast_origin(
                origin_offset,
                values,
                initial_training,
                max_horizon,
                score_forecaster,
            )
            for origin_offset in range(out_of_sample)
        )
    for origin_offset, available_horizon, forecasts_by_rule, diagnostics_by_rule in origin_results:
        origin = initial_training + origin_offset
        for rule in ("cpv", "k4"):
            forecasts = forecasts_by_rule[rule]
            diagnostics = diagnostics_by_rule[rule]
            for model, detail in diagnostics.items():
                component_counts[rule][model].extend(detail["components"])
            for horizon in horizons:
                if horizon > available_horizon:
                    continue
                actual = values[origin + horizon - 1]
                previous = values[origin - 1]
                actual_direction = np.sign(actual - previous)
                for model, forecast_path in forecasts.items():
                    prediction = forecast_path[horizon - 1]
                    metrics = paper_errors(prediction, actual)
                    grid_errors[rule][horizon][model].append(actual - prediction)
                    for metric, metric_value in metrics.items():
                        losses[rule][horizon][f"{model}:{metric}"].append(metric_value)
                    directions[rule][horizon][model].append(
                        float(np.mean(np.sign(prediction - previous) == actual_direction))
                    )
        if progress is not None:
            progress({"completed_origins": origin_offset + 1, "total_origins": out_of_sample})
    if executor is not None:
        executor.shutdown()

    results: dict[str, Any] = {}
    for rule in ("cpv", "k4"):
        rule_horizons: dict[str, Any] = {}
        for horizon in horizons:
            model_rows = []
            available_models = [
                model
                for model in MODEL_LABELS
                if losses[rule][horizon].get(f"{model}:mafe")
            ]
            for model in MODEL_LABELS:
                mafe = losses[rule][horizon].get(f"{model}:mafe", [])
                if not mafe:
                    continue
                model_rows.append(
                    {
                        "model": MODEL_LABELS[model],
                        "mafe": float(np.mean(mafe)),
                        "msfe": float(np.mean(losses[rule][horizon][f"{model}:msfe"])),
                        "mme_under": float(
                            np.mean(losses[rule][horizon][f"{model}:mme_under"])
                        ),
                        "mme_over": float(
                            np.mean(losses[rule][horizon][f"{model}:mme_over"])
                        ),
                        "directional_accuracy_percent": float(
                            np.mean(directions[rule][horizon][model]) * 100
                        ),
                        "observations": len(mafe),
                        "by_maturity": [
                            {
                                "maturity_index": maturity,
                                **paper_errors(
                                    np.zeros_like(
                                        np.asarray(grid_errors[rule][horizon][model])[
                                            :, maturity, :
                                        ]
                                    ),
                                    np.asarray(grid_errors[rule][horizon][model])[
                                        :, maturity, :
                                    ],
                                ),
                            }
                            for maturity in range(values.shape[1])
                        ],
                        "by_delta": [
                            {
                                "delta": PAPER_DELTA_POINTS[delta],
                                **paper_errors(
                                    np.zeros_like(
                                        np.asarray(grid_errors[rule][horizon][model])[
                                            :, :, delta
                                        ]
                                    ),
                                    np.asarray(grid_errors[rule][horizon][model])[
                                        :, :, delta
                                    ],
                                ),
                            }
                            for delta in range(values.shape[2])
                        ],
                    }
                )
            model_rows.sort(key=lambda row: row["mafe"])
            loss_matrix = np.column_stack(
                [losses[rule][horizon][f"{model}:mafe"] for model in available_models]
            )
            rule_horizons[str(horizon)] = {
                "expected_observations": max(0, out_of_sample - horizon + 1),
                "models": model_rows,
                "model_confidence_set": {
                    statistic: model_confidence_set(
                        loss_matrix,
                        [MODEL_LABELS[model] for model in available_models],
                        statistic=statistic,
                        bootstraps=PAPER_MCS_BOOTSTRAPS,
                    )
                    for statistic in ("Tmax", "TR")
                }
                if len(loss_matrix) >= 20
                else None,
            }
        results[rule] = {
            "horizons": rule_horizons,
            "average_components": {
                MODEL_LABELS[model]: float(np.mean(counts))
                for model, counts in component_counts[rule].items()
                if counts
            },
        }
    return {
        "paper": PAPER_NAME,
        "paper_url": PAPER_URL,
        "replication_version": REPLICATION_VERSION,
        "initial_training_observations": initial_training,
        "out_of_sample_observations": out_of_sample,
        "total_observations": required,
        "horizons": list(horizons),
        "component_rules": {
            "cpv": "99% CPV; multilevel common/idiosyncratic stages use the paper's 90% thresholds",
            "k4": "Four components at every FPCA stage",
        },
        "mcs": {
            "confidence_percent": 95,
            "block_bootstraps": PAPER_MCS_BOOTSTRAPS,
            "statistics": ["Tmax", "TR"],
        },
        "results": results,
    }


def prepare_nse_paper_grid(surfaces: np.ndarray) -> np.ndarray:
    values = np.asarray(surfaces, dtype=float)
    if values.ndim != 3 or values.shape[1:] != (4, 5):
        raise ValueError("Stored NSE surfaces must have four tenors and five deltas.")
    return values[:, NSE_PAPER_TENOR_INDICES, :]


def replication_eligibility(histories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eligible: list[str] = []
    eligible_details: list[dict[str, Any]] = []
    ineligible: list[dict[str, Any]] = []
    for symbol, history in sorted(histories.items()):
        dates = list(history.get("dates") or [])
        surfaces = np.asarray(history.get("surfaces") or [], dtype=float)
        reasons = []
        if len(dates) != len(surfaces) or surfaces.ndim != 3:
            reasons.append("malformed cached history")
        if len(surfaces) < PAPER_TOTAL_OBSERVATIONS:
            reasons.append(
                f"needs {PAPER_TOTAL_OBSERVATIONS - len(surfaces)} more complete surfaces"
            )
        large_gaps = 0
        if len(dates) >= PAPER_TOTAL_OBSERVATIONS:
            sample_dates = [date.fromisoformat(str(value)) for value in dates[-PAPER_TOTAL_OBSERVATIONS:]]
            large_gaps = sum(
                (right - left).days > 4
                for left, right in zip(sample_dates, sample_dates[1:], strict=False)
            )
        if reasons:
            ineligible.append(
                {
                    "ticker": symbol,
                    "observations": len(surfaces),
                    "reasons": reasons,
                    "gaps_over_four_calendar_days": large_gaps,
                }
            )
        else:
            eligible.append(symbol)
            eligible_details.append(
                {
                    "ticker": symbol,
                    "observations": len(surfaces),
                    "gaps_over_four_calendar_days": large_gaps,
                }
            )
    return {
        "eligible_symbols": eligible,
        "eligible_details": eligible_details,
        "eligible_count": len(eligible),
        "ineligible": ineligible,
        "required_surfaces_per_symbol": PAPER_TOTAL_OBSERVATIONS,
    }


def run_nse_replication(
    histories: dict[str, dict[str, Any]],
    *,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    eligibility = replication_eligibility(histories)
    per_symbol: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    symbols = eligibility["eligible_symbols"]
    for symbol_index, symbol in enumerate(symbols):
        history = histories[symbol]
        try:
            all_dates = list(history.get("dates") or [])[-PAPER_TOTAL_OBSERVATIONS:]

            def symbol_progress(
                payload: dict[str, int],
                *,
                current_symbol: str = symbol,
                current_index: int = symbol_index,
            ) -> None:
                if progress is not None:
                    progress(
                        {
                            "ticker": current_symbol,
                            "symbol_index": current_index + 1,
                            "total_symbols": len(symbols),
                            **payload,
                        }
                    )

            result = expanding_window_backtest(
                prepare_nse_paper_grid(
                    np.asarray(history.get("surfaces") or [], dtype=float)[
                        -PAPER_TOTAL_OBSERVATIONS:
                    ]
                ),
                progress=symbol_progress,
                workers=min(8, max(1, os.cpu_count() or 1)),
            )
            result.update(
                {
                    "ticker": symbol,
                    "first_date": all_dates[0],
                    "last_date": all_dates[-1],
                    "stationarity_tests": [
                        {
                            "maturity_days": maturity_days,
                            **functional_stationarity_test(
                                prepare_nse_paper_grid(
                                    np.asarray(history.get("surfaces") or [], dtype=float)[
                                        -PAPER_TOTAL_OBSERVATIONS:
                                    ]
                                )[:, maturity_index, :],
                                seed=20_220_711 + maturity_index,
                            ),
                        }
                        for maturity_index, maturity_days in enumerate(
                            NSE_REPLICATION_TENOR_DAYS
                        )
                    ],
                }
            )
            per_symbol.append(result)
        except Exception as exc:
            failures.append({"ticker": symbol, "error": str(exc)})

    leaderboard_accumulator: dict[tuple[str, str], list[float]] = defaultdict(list)
    for report in per_symbol:
        for rule in ("cpv", "k4"):
            for row in report["results"][rule]["horizons"]["1"]["models"]:
                leaderboard_accumulator[(rule, row["model"])].append(row["mafe"])
    leaderboard = [
        {
            "component_rule": rule,
            "model": model,
            "mean_one_day_mafe": float(np.mean(values)),
            "symbols": len(values),
        }
        for (rule, model), values in leaderboard_accumulator.items()
    ]
    leaderboard.sort(key=lambda row: row["mean_one_day_mafe"])
    return {
        "available": bool(per_symbol),
        "verdict": (
            "Exact-design replication complete"
            if per_symbol
            else "Exact paper sample is not yet available"
        ),
        "verdict_detail": (
            f"Completed all six functional models for {len(per_symbol)} NSE underlyings "
            "using the paper's fixed expanding-window protocol."
            if per_symbol
            else f"No stock currently has all {PAPER_TOTAL_OBSERVATIONS} required surfaces."
        ),
        "paper": PAPER_NAME,
        "paper_url": PAPER_URL,
        "replication_version": REPLICATION_VERSION,
        "paper_design": {
            "initial_training_observations": PAPER_INITIAL_TRAINING,
            "out_of_sample_observations": PAPER_OUT_OF_SAMPLE,
            "total_observations": PAPER_TOTAL_OBSERVATIONS,
            "horizons": list(PAPER_HORIZONS),
            "expected_forecasts": PAPER_TEST_OBSERVATIONS,
            "delta_points": list(PAPER_DELTA_POINTS),
            "models": [MODEL_LABELS[name] for name in ("fts", "dfts", "mfts", "dmfts", "mlfts", "dmlfts")],
            "benchmarks": ["CT11", "GG06", "RW", "AR(1)"],
            "score_forecast": "Hyndman-Khandakar automatic ARIMA, re-estimated daily",
            "dynamic_covariance": "Rice-Shang plug-in bandwidth with Bartlett kernel",
            "component_selection": ["99% CPV (90% at multilevel stages)", "K=4"],
            "mcs": "95% Hansen-Lunde-Nason set; 5,000 block bootstraps; Tmax and TR",
            "stationarity_test": "Horvath-Kokoszka-Rice with ftsa defaults and 1,000 Monte Carlo draws",
        },
        "nse_adaptation": {
            "exact_proposed_model_methodology": True,
            "exact_original_dataset": False,
            "paper_maturities": ["1M", "6M", "2Y"],
            "nse_maturity_days": list(NSE_REPLICATION_TENOR_DAYS),
            "reason": (
                "NSE listed single-stock options do not provide continuous 6M and 2Y quotes; "
                "the three available rolling tenors preserve the paper's multivariate dimension. "
                "The study uses the latest 2,349 complete observed surfaces and reports calendar gaps."
            ),
        },
        "eligibility": eligibility,
        "completed_symbols": len(per_symbol),
        "failures": failures,
        "leaderboard": leaderboard,
        "per_symbol": per_symbol,
        "strengths": [
            "Dynamic FPCA estimates serial dependence through long-run covariance.",
            "Expanding-window targets are never used in estimation.",
            "Independent, joint and common-plus-idiosyncratic structures are compared on identical targets.",
        ],
        "weaknesses": [
            "The original proprietary Bloomberg OTC FX quotes are unavailable.",
            "NSE 30/60/90-day listed tenors are not the paper's 1M/6M/2Y maturity grid.",
            "NSE surface observations can be irregular when no complete liquid smile can be reconstructed for a session.",
            "CT11/GG06 use fixed-delta OLS because contract-level vega measurement-error weights needed for the paper's GLS benchmarks are not retained.",
            "Surface forecast loss does not include bid-ask spreads, premium slippage or hedging P&L.",
        ],
    }


def _replication_fingerprint(histories: dict[str, dict[str, Any]]) -> str:
    return ",".join(
        f"{symbol}:{len(history.get('dates') or [])}:"
        f"{(history.get('dates') or [''])[0]}:{(history.get('dates') or [''])[-1]}"
        for symbol, history in sorted(histories.items())
    )


def get_cached_nse_replication(
    histories: dict[str, dict[str, Any]],
    *,
    force_refresh: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    cache = FileCache(get_settings().cache_path, "dynamic_functional_iv")
    key = cache_key(REPLICATION_VERSION, _replication_fingerprint(histories))
    latest_key = cache_key(REPLICATION_VERSION, "latest")
    if not force_refresh:
        exact = cache.get(key, None)
        if exact is not None:
            return exact
        latest = cache.get(latest_key, None)
        if latest is not None:
            return latest
        return run_nse_replication({}) | {
            "eligibility": replication_eligibility(histories),
            "verdict_detail": (
                "The exact-design backtest has not been run for the current history fingerprint. "
                "Use the offline replication command after the NSE history backfill completes."
            ),
        }
    result = run_nse_replication(histories, progress=progress)
    for cache_entry in (key, latest_key):
        cache.put(
            cache_entry,
            result,
            source="Official NSE F&O bhavcopy closing prices",
            model_name=PAPER_NAME,
        )
    return result
