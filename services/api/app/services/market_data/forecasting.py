"""ARIMA-GARCH Monte Carlo price scenarios built from daily market history.

ARIMA(1,1,1) on log prices is estimated as the equivalent ARMA(1,1) process on
daily log returns. GARCH(1,1) with Student-t innovations is fitted to the ARIMA
residuals. Every simulation step advances both the conditional return mean and
conditional variance; no constant-volatility shortcut is used.
"""

import asyncio
import hashlib
import logging
import math
import warnings
from datetime import UTC, date, datetime, timedelta

import numpy as np
from arch import arch_model
from statsmodels.tsa.arima.model import ARIMA

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.services.market_data.india_trading import get_price_history

logger = logging.getLogger(__name__)

FORECAST_TTL_SECONDS = 30 * 60
MODEL_VERSION = "arima111-garch11-t-ols-regression-v3"
MINIMUM_OBSERVATIONS = 100
TRADING_DAYS_PER_YEAR = 252
SAMPLE_PATHS = 12
REGRESSION_ROLLING_WINDOW = 20
REGRESSION_MINIMUM_ROWS = 60


def _future_weekdays(last_date: date, count: int) -> list[date]:
    days: list[date] = []
    current = last_date
    while len(days) < count:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days.append(current)
    return days


def _parameter(result, name: str, default: float = 0.0) -> float:
    names = list(
        getattr(result, "param_names", [])
        or getattr(getattr(result, "model", None), "param_names", [])
    )
    values = np.asarray(result.params, dtype=float)
    if name in names:
        return float(values[names.index(name)])
    params = getattr(result, "params", None)
    try:
        return float(params[name])
    except (KeyError, TypeError, ValueError):
        return default


def _unavailable(
    history: dict,
    *,
    horizon_days: int,
    simulations: int,
    observations: int,
    limitation: str,
) -> dict:
    candles = history.get("candles") or []
    return {
        "ticker": history["ticker"],
        "market_data_ticker": history["market_data_ticker"],
        "currency": history.get("currency") or "USD",
        "available": False,
        "horizon_days": horizon_days,
        "simulations": simulations,
        "observations": observations,
        "fit_start": candles[0]["time"] if candles else None,
        "fit_end": candles[-1]["time"] if candles else None,
        "last_price": candles[-1]["close"] if candles else None,
        "source": history.get("source") or "yfinance",
        "source_url": history.get("source_url") or "",
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "limitations": [limitation],
        "regression_available": False,
        "regression_model": (
            "Direct-horizon OLS on lagged price momentum, relative volume, "
            "and rolling VWAP gap"
        ),
        "regression_points": [],
        "regression_limitations": [limitation],
    }


def _regression_features(candles: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    closes = np.asarray([float(candle["close"]) for candle in candles], dtype=float)
    highs = np.asarray([float(candle["high"]) for candle in candles], dtype=float)
    lows = np.asarray([float(candle["low"]) for candle in candles], dtype=float)
    volumes = np.asarray(
        [max(float(candle.get("volume") or 0), 0.0) for candle in candles],
        dtype=float,
    )
    typical_prices = (highs + lows + closes) / 3
    features = np.full((len(candles), 3), np.nan, dtype=float)
    for index in range(REGRESSION_ROLLING_WINDOW, len(candles)):
        window = slice(index - REGRESSION_ROLLING_WINDOW + 1, index + 1)
        window_volumes = volumes[window]
        volume_sum = float(window_volumes.sum())
        rolling_vwap = (
            float(np.dot(typical_prices[window], window_volumes) / volume_sum)
            if volume_sum > 0
            else float(np.mean(typical_prices[window]))
        )
        average_volume = float(np.mean(window_volumes))
        features[index] = [
            math.log(closes[index] / closes[index - 1]),
            math.log(
                max(volumes[index], 1.0) / max(average_volume, 1.0)
            ),
            math.log(closes[index] / rolling_vwap),
        ]
    return closes, volumes, features


def _fit_standardized_ols(
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    means = np.mean(x, axis=0)
    scales = np.std(x, axis=0)
    scales = np.where(scales <= 1e-12, 1.0, scales)
    standardized = (x - means) / scales
    design = np.column_stack([np.ones(len(standardized)), standardized])
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    return coefficients, means, scales


def _ols_predict(
    x: np.ndarray,
    coefficients: np.ndarray,
    means: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    standardized = (x - means) / scales
    design = np.column_stack([np.ones(len(standardized)), standardized])
    return design @ coefficients


def build_multiple_regression_forecast(
    history: dict,
    *,
    horizon_days: int,
) -> dict:
    """Fit leakage-safe direct-horizon OLS price regressions.

    Features observed at session t predict the log return from t to t+h. Each
    horizon is fitted independently, so unknown future volume or VWAP values are
    never substituted into a recursive forecast.
    """

    candles = [
        candle
        for candle in history.get("candles") or []
        if all(
            candle.get(field) is not None
            and math.isfinite(float(candle[field]))
            and float(candle[field]) > 0
            for field in ("high", "low", "close")
        )
    ]
    model_name = (
        "Direct-horizon OLS on lagged price momentum, relative volume, "
        "and rolling VWAP gap"
    )
    if len(candles) < MINIMUM_OBSERVATIONS:
        return {
            "regression_available": False,
            "regression_model": model_name,
            "regression_points": [],
            "regression_observations": 0,
            "regression_limitations": [
                f"At least {MINIMUM_OBSERVATIONS} daily candles are required "
                "for the multiple regression."
            ],
        }

    closes, volumes, features = _regression_features(candles)
    latest_features = features[-1]
    if not np.all(np.isfinite(latest_features)):
        return {
            "regression_available": False,
            "regression_model": model_name,
            "regression_points": [],
            "regression_observations": 0,
            "regression_limitations": [
                "The latest price, volume, or rolling VWAP feature is invalid."
            ],
        }

    future_dates = _future_weekdays(
        date.fromisoformat(candles[-1]["time"]),
        horizon_days,
    )
    points: list[dict] = []
    terminal_coefficients: np.ndarray | None = None
    terminal_rows = 0
    terminal_validation_r_squared: float | None = None
    terminal_validation_mae_percent: float | None = None

    for horizon_index, forecast_date in enumerate(future_dates, start=1):
        feature_rows = []
        targets = []
        final_feature_index = len(candles) - horizon_index - 1
        for index in range(
            REGRESSION_ROLLING_WINDOW,
            final_feature_index + 1,
        ):
            row = features[index]
            if not np.all(np.isfinite(row)):
                continue
            feature_rows.append(row)
            targets.append(math.log(closes[index + horizon_index] / closes[index]))
        x = np.asarray(feature_rows, dtype=float)
        y = np.asarray(targets, dtype=float)
        if len(x) < REGRESSION_MINIMUM_ROWS:
            continue

        coefficients, means, scales = _fit_standardized_ols(x, y)
        predicted_return = float(
            _ols_predict(latest_features.reshape(1, -1), coefficients, means, scales)[0]
        )
        predicted_return = float(np.clip(predicted_return, -0.5, 0.5))
        points.append(
            {
                "date": forecast_date.isoformat(),
                "predicted_price": round(float(closes[-1] * math.exp(predicted_return)), 4),
                "predicted_return_percent": round(
                    (math.exp(predicted_return) - 1) * 100,
                    4,
                ),
            }
        )

        if horizon_index == horizon_days:
            terminal_coefficients = coefficients
            terminal_rows = len(x)
            split = max(40, int(len(x) * 0.8))
            purged_train_end = split - horizon_index
            if purged_train_end >= 40 and len(x) - split >= 10:
                validation_coefficients, validation_means, validation_scales = (
                    _fit_standardized_ols(
                        x[:purged_train_end],
                        y[:purged_train_end],
                    )
                )
                validation_predictions = _ols_predict(
                    x[split:],
                    validation_coefficients,
                    validation_means,
                    validation_scales,
                )
                actual = y[split:]
                residual_sum = float(np.sum((actual - validation_predictions) ** 2))
                total_sum = float(np.sum((actual - np.mean(actual)) ** 2))
                terminal_validation_r_squared = (
                    1 - residual_sum / total_sum if total_sum > 1e-12 else None
                )
                terminal_validation_mae_percent = float(
                    np.mean(
                        np.abs(
                            (np.exp(validation_predictions) - 1)
                            - (np.exp(actual) - 1)
                        )
                    )
                    * 100
                )

    if not points or terminal_coefficients is None:
        return {
            "regression_available": False,
            "regression_model": model_name,
            "regression_points": points,
            "regression_observations": terminal_rows,
            "regression_limitations": [
                "Too few complete lagged observations remain for the requested horizon."
            ],
        }

    terminal = points[-1]
    average_volume = float(
        np.mean(volumes[-REGRESSION_ROLLING_WINDOW:])
    )
    return {
        "regression_available": True,
        "regression_model": model_name,
        "regression_terminal_price": terminal["predicted_price"],
        "regression_terminal_return_percent": terminal["predicted_return_percent"],
        "regression_points": points,
        "regression_observations": terminal_rows,
        "regression_validation_r_squared": (
            round(terminal_validation_r_squared, 6)
            if terminal_validation_r_squared is not None
            else None
        ),
        "regression_validation_mae_percent": (
            round(terminal_validation_mae_percent, 4)
            if terminal_validation_mae_percent is not None
            else None
        ),
        "regression_standardized_coefficients": {
            "intercept": round(float(terminal_coefficients[0]), 8),
            "price_momentum": round(float(terminal_coefficients[1]), 8),
            "relative_volume": round(float(terminal_coefficients[2]), 8),
            "price_vs_vwap": round(float(terminal_coefficients[3]), 8),
        },
        "regression_latest_features": {
            "price_momentum_percent": round(
                (math.exp(float(latest_features[0])) - 1) * 100,
                4,
            ),
            "volume_vs_20d_average_percent": round(
                (math.exp(float(latest_features[1])) - 1) * 100,
                4,
            ),
            "price_vs_20d_vwap_percent": round(
                (math.exp(float(latest_features[2])) - 1) * 100,
                4,
            ),
            "latest_volume": round(float(volumes[-1]), 4),
            "average_volume_20d": round(average_volume, 4),
        },
        "regression_limitations": [
            "The VWAP feature is a 20-session daily-bar proxy built from typical "
            "price and reported volume, not exchange tick-level VWAP.",
            "Validation is time-ordered, but historical price-volume relationships "
            "can weaken or reverse after regime changes.",
            "The regression path is a conditional point estimate and does not add "
            "a separate probability interval.",
        ],
    }


def build_arima_garch_forecast(
    history: dict,
    *,
    horizon_days: int,
    simulations: int,
) -> dict:
    """Fit ARIMA/GARCH and generate vectorized, reproducible Monte Carlo paths."""
    candles = [
        candle
        for candle in history.get("candles") or []
        if candle.get("close") is not None
        and math.isfinite(float(candle["close"]))
        and float(candle["close"]) > 0
    ]
    closes = np.asarray([float(candle["close"]) for candle in candles], dtype=float)
    if len(closes) < MINIMUM_OBSERVATIONS:
        return _unavailable(
            history,
            horizon_days=horizon_days,
            simulations=simulations,
            observations=len(closes),
            limitation=(
                f"At least {MINIMUM_OBSERVATIONS} valid daily closes are required; "
                f"only {len(closes)} are available for this listing."
            ),
        )

    log_returns = np.diff(np.log(closes))
    if not np.all(np.isfinite(log_returns)) or float(np.std(log_returns)) <= 1e-8:
        return _unavailable(
            history,
            horizon_days=horizon_days,
            simulations=simulations,
            observations=len(closes),
            limitation="The available price history does not contain enough return variation.",
        )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # ARMA(1,1) on differenced log prices is ARIMA(1,1,1) on log prices.
        arima_fit = ARIMA(
            log_returns,
            order=(1, 0, 1),
            trend="c",
            enforce_stationarity=True,
            enforce_invertibility=True,
        ).fit()
        residuals_percent = np.asarray(arima_fit.resid, dtype=float) * 100
        residuals_percent = residuals_percent[np.isfinite(residuals_percent)]
        garch_fit = arch_model(
            residuals_percent,
            mean="Zero",
            vol="GARCH",
            p=1,
            q=1,
            dist="StudentsT",
            rescale=False,
        ).fit(disp="off", show_warning=False)

    mean_return = _parameter(arima_fit, "const", float(np.mean(log_returns)))
    ar1 = float(np.clip(_parameter(arima_fit, "ar.L1"), -0.98, 0.98))
    ma1 = float(np.clip(_parameter(arima_fit, "ma.L1"), -0.98, 0.98))

    garch_params = garch_fit.params
    omega = max(float(garch_params.get("omega", 0.0)), 1e-10)
    alpha = max(float(garch_params.get("alpha[1]", 0.0)), 0.0)
    beta = max(float(garch_params.get("beta[1]", 0.0)), 0.0)
    persistence = alpha + beta
    if persistence >= 0.999:
        scale = 0.999 / persistence if persistence else 0.0
        alpha *= scale
        beta *= scale
        persistence = alpha + beta
    degrees_of_freedom = max(float(garch_params.get("nu", 8.0)), 2.05)

    conditional_volatility = np.asarray(garch_fit.conditional_volatility, dtype=float)
    current_variance = max(float(conditional_volatility[-1] ** 2), 1e-10)
    long_run_variance = omega / max(1 - persistence, 1e-6)
    last_residual_percent = float(residuals_percent[-1])
    last_return = float(log_returns[-1])

    seed_material = (
        f"{history['market_data_ticker']}|{candles[-1]['time']}|{closes[-1]:.8f}|"
        f"{horizon_days}|{simulations}|{MODEL_VERSION}"
    )
    seed = int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8], "big")
    rng = np.random.default_rng(seed)

    log_prices = np.full(simulations, math.log(float(closes[-1])), dtype=float)
    previous_returns = np.full(simulations, last_return, dtype=float)
    previous_residuals_percent = np.full(simulations, last_residual_percent, dtype=float)
    variances = np.full(simulations, current_variance, dtype=float)
    simulated_prices = np.empty((horizon_days, simulations), dtype=float)
    mean_variances = np.empty(horizon_days, dtype=float)

    student_scale = math.sqrt(degrees_of_freedom / (degrees_of_freedom - 2))
    for step in range(horizon_days):
        variances = omega + alpha * previous_residuals_percent**2 + beta * variances
        variances = np.maximum(variances, 1e-10)
        innovations = rng.standard_t(degrees_of_freedom, size=simulations) / student_scale
        residuals_percent_step = np.sqrt(variances) * innovations
        conditional_returns = (
            mean_return
            + ar1 * (previous_returns - mean_return)
            + ma1 * (previous_residuals_percent / 100)
        )
        returns = conditional_returns + residuals_percent_step / 100
        log_prices += returns
        simulated_prices[step] = np.exp(np.clip(log_prices, -20, 30))
        mean_variances[step] = float(np.mean(variances))
        previous_returns = returns
        previous_residuals_percent = residuals_percent_step

    quantiles = np.quantile(
        simulated_prices,
        [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95],
        axis=1,
    )
    forecast_dates = _future_weekdays(date.fromisoformat(candles[-1]["time"]), horizon_days)
    points = []
    for index, forecast_date in enumerate(forecast_dates):
        points.append(
            {
                "date": forecast_date.isoformat(),
                "p05": round(float(quantiles[0, index]), 4),
                "p10": round(float(quantiles[1, index]), 4),
                "p25": round(float(quantiles[2, index]), 4),
                "median": round(float(quantiles[3, index]), 4),
                "p75": round(float(quantiles[4, index]), 4),
                "p90": round(float(quantiles[5, index]), 4),
                "p95": round(float(quantiles[6, index]), 4),
                "annualized_volatility_percent": round(
                    math.sqrt(mean_variances[index]) * math.sqrt(TRADING_DAYS_PER_YEAR),
                    4,
                ),
            }
        )

    sample_indexes = np.linspace(0, simulations - 1, min(SAMPLE_PATHS, simulations), dtype=int)
    sample_paths = [
        {
            "id": path_number + 1,
            "points": [
                {
                    "date": forecast_date.isoformat(),
                    "price": round(float(simulated_prices[index, path_index]), 4),
                }
                for index, forecast_date in enumerate(forecast_dates)
            ],
        }
        for path_number, path_index in enumerate(sample_indexes)
    ]

    terminal = simulated_prices[-1]
    result = {
        "ticker": history["ticker"],
        "market_data_ticker": history["market_data_ticker"],
        "currency": history.get("currency") or "USD",
        "available": True,
        "horizon_days": horizon_days,
        "simulations": simulations,
        "observations": len(closes),
        "fit_start": candles[0]["time"],
        "fit_end": candles[-1]["time"],
        "last_price": round(float(closes[-1]), 4),
        "median_terminal_price": round(float(np.median(terminal)), 4),
        "terminal_range_80_low": round(float(np.quantile(terminal, 0.10)), 4),
        "terminal_range_80_high": round(float(np.quantile(terminal, 0.90)), 4),
        "probability_finish_above_last": round(float(np.mean(terminal >= closes[-1])), 6),
        "annualized_arima_drift_percent": round(mean_return * TRADING_DAYS_PER_YEAR * 100, 4),
        "current_annualized_volatility_percent": round(
            math.sqrt(current_variance) * math.sqrt(TRADING_DAYS_PER_YEAR), 4
        ),
        "long_run_annualized_volatility_percent": round(
            math.sqrt(long_run_variance) * math.sqrt(TRADING_DAYS_PER_YEAR), 4
        ),
        "arima_ar1": round(ar1, 8),
        "arima_ma1": round(ma1, 8),
        "garch_omega": round(omega, 8),
        "garch_alpha1": round(alpha, 8),
        "garch_beta1": round(beta, 8),
        "student_t_degrees_of_freedom": round(degrees_of_freedom, 4),
        "points": points,
        "sample_paths": sample_paths,
        "source": history.get("source") or "yfinance",
        "source_url": history.get("source_url") or "",
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "limitations": [
            "Statistical scenario only: it excludes fundamentals, news, corporate actions, and regime changes.",
            "Forecast dates approximate exchange sessions with weekdays and do not remove local market holidays.",
            "Intervals describe model uncertainty, not guaranteed price bounds or investment advice.",
        ],
    }
    result.update(
        build_multiple_regression_forecast(
            history,
            horizon_days=horizon_days,
        )
    )
    return result


async def get_price_forecast(
    ticker: str,
    market_data_ticker: str,
    *,
    horizon_days: int,
    simulations: int,
) -> dict:
    history = await get_price_history(ticker, market_data_ticker, "5Y")
    candles = history.get("candles") or []
    last_marker = f"{candles[-1]['time']}:{candles[-1]['close']}" if candles else "empty"
    cache = FileCache(get_settings().cache_path, "price_forecasts")
    key = cache_key(
        MODEL_VERSION,
        market_data_ticker.upper(),
        last_marker,
        str(horizon_days),
        str(simulations),
    )
    cached = cache.get(key, FORECAST_TTL_SECONDS)
    if cached is not None:
        return cached
    try:
        result = await asyncio.to_thread(
            build_arima_garch_forecast,
            history,
            horizon_days=horizon_days,
            simulations=simulations,
        )
    except Exception as exc:
        logger.exception("ARIMA-GARCH forecast failed for %s", ticker)
        result = _unavailable(
            history,
            horizon_days=horizon_days,
            simulations=simulations,
            observations=len(candles),
            limitation=f"The ARIMA-GARCH model could not be fitted: {exc}",
        )
    cache.put(
        key,
        result,
        source=history.get("source") or "yfinance",
        model_name=MODEL_VERSION,
    )
    return result
