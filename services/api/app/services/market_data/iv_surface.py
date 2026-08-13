"""Functional-PCA forecasts for NSE equity-option implied-volatility surfaces.

The implementation follows the MetLife paper's sequence:

1. build a daily IV surface on fixed delta and tenor coordinates;
2. smooth each surface with a tensor-product B-spline;
3. use FPCA (the discrete Karhunen-Loève decomposition), retaining the smallest
   three-to-eight-component representation that explains at least 99% of the
   observed surface variation; and
4. forecast differenced component scores with a regularized VAR(5), then
   reconstruct the next-session surface.

NSE stock options list fewer tenors than the FX data in the paper, so the
production grid uses four rolling days-to-expiry points rather than the
paper's fifteen FX expiries. That adaptation is surfaced in the API.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import time as monotonic_time
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from scipy.interpolate import SmoothBivariateSpline

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.services.nse.client import get_nse_client

logger = logging.getLogger(__name__)

MODEL_NAME = (
    "B-spline FPCA (adaptive 3-8 components, 99% variance target) + "
    "ridge VAR(5) on differenced scores"
)
MODEL_VERSION = "nse-fpca-ridge-var5-v11-adaptive99"
SURFACE_DATA_VERSION = "nse-fpca-var5-v2-durable-history"
PAPER_URL = (
    "https://investments.metlife.com/content/dam/metlifecom/us/investments/"
    "insights/research-topics/macro-strategy/pdf/"
    "MIM_Functional-PCA-Implied-Volatility-Surface-Prediction_051920.pdf"
)
ARCHIVE_URL = (
    "https://archives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{date}_F_0000.csv.zip"
)
LEGACY_ARCHIVE_URL = (
    "https://archives.nseindia.com/content/historical/DERIVATIVES/"
    "{year}/{month}/fo{day}{month}{year}bhav.csv.zip"
)
FNO_MARKET_LOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"

RISK_FREE_RATE = 0.065
DIVIDEND_YIELD = 0.0
TENOR_DAYS = np.asarray([14.0, 30.0, 60.0, 90.0])
DELTA_BUCKETS = (
    ("10Δ put", "put", 0.10),
    ("25Δ put", "put", 0.25),
    ("ATM", "atm", 0.50),
    ("25Δ call", "call", 0.25),
    ("10Δ call", "call", 0.10),
)
# Keep enough NSE history to reproduce the 2,349-observation sample used by
# Shang and Kearney (1,827 training observations plus 522 holdout observations).
# The option history is collected independently from NSE bhavcopies and persisted,
# so request-time forecasts never repeat the backfill.
TARGET_HISTORY_SURFACES = 2_500
HISTORY_BACKFILL_YEARS = 20
CANDIDATE_WEEKDAYS = 5_600
INCREMENTAL_REFRESH_WEEKDAYS = 15
BACKFILL_BATCH_DATES = 4
MINIMUM_HISTORY_SURFACES = 35
MINIMUM_VALIDATION_SURFACES = MINIMUM_HISTORY_SURFACES + 1
HISTORY_TTL_SECONDS = 24 * 60 * 60
FORECAST_TTL_SECONDS = 5 * 60
MAX_IV_PERCENT = 250.0
MINIMUM_COMPONENT_COUNT = 3
MAXIMUM_COMPONENT_COUNT = 8
EXPLAINED_VARIANCE_TARGET_PERCENT = 99.0
RIDGE_ALPHA_CANDIDATES = (0.1, 1.0, 10.0, 100.0)
LOT_SIZE_TTL_SECONDS = 24 * 60 * 60


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _black_scholes_price(
    option_type: str,
    spot: float,
    strike: float,
    years: float,
    volatility: float,
    *,
    risk_free_rate: float = RISK_FREE_RATE,
    dividend_yield: float = DIVIDEND_YIELD,
) -> float:
    root_time = math.sqrt(years)
    d1 = (
        math.log(spot / strike) + (risk_free_rate - dividend_yield + volatility**2 / 2) * years
    ) / (volatility * root_time)
    d2 = d1 - volatility * root_time
    discounted_spot = spot * math.exp(-dividend_yield * years)
    discounted_strike = strike * math.exp(-risk_free_rate * years)
    if option_type == "call":
        return discounted_spot * _normal_cdf(d1) - discounted_strike * _normal_cdf(d2)
    return discounted_strike * _normal_cdf(-d2) - discounted_spot * _normal_cdf(-d1)


def implied_volatility_percent(
    option_type: str,
    option_price: float,
    spot: float,
    strike: float,
    years: float,
) -> float | None:
    """Invert Black-Scholes with a bounded bisection solver."""

    if min(option_price, spot, strike, years) <= 0:
        return None
    discounted_spot = spot * math.exp(-DIVIDEND_YIELD * years)
    discounted_strike = strike * math.exp(-RISK_FREE_RATE * years)
    intrinsic = (
        max(0.0, discounted_spot - discounted_strike)
        if option_type == "call"
        else max(0.0, discounted_strike - discounted_spot)
    )
    upper_bound = discounted_spot if option_type == "call" else discounted_strike
    if option_price < intrinsic - 0.05 or option_price >= upper_bound:
        return None

    low, high = 0.005, 5.0
    low_price = _black_scholes_price(option_type, spot, strike, years, low)
    high_price = _black_scholes_price(option_type, spot, strike, years, high)
    if option_price < low_price - 0.05 or option_price > high_price:
        return None
    for _ in range(70):
        middle = (low + high) / 2
        model_price = _black_scholes_price(option_type, spot, strike, years, middle)
        if model_price < option_price:
            low = middle
        else:
            high = middle
    result = (low + high) * 50
    return result if 1.0 <= result <= MAX_IV_PERCENT else None


def _option_delta(
    option_type: str,
    spot: float,
    strike: float,
    years: float,
    iv_percent: float,
) -> float:
    volatility = iv_percent / 100
    d1 = (
        math.log(spot / strike) + (RISK_FREE_RATE - DIVIDEND_YIELD + volatility**2 / 2) * years
    ) / (volatility * math.sqrt(years))
    call_delta = math.exp(-DIVIDEND_YIELD * years) * _normal_cdf(d1)
    return call_delta if option_type == "call" else call_delta - math.exp(-DIVIDEND_YIELD * years)


def _nearest_bucket_iv(
    observations: list[dict[str, float | str]],
    side: str,
    target_delta: float,
) -> float | None:
    candidates = [
        row
        for row in observations
        if row["side"] == side and 0.02 <= abs(float(row["delta"])) <= 0.98
    ]
    if not candidates:
        return None
    selected = min(
        candidates,
        key=lambda row: (
            abs(abs(float(row["delta"])) - target_delta),
            -float(row["liquidity"]),
        ),
    )
    if abs(abs(float(selected["delta"])) - target_delta) > 0.18:
        return None
    return float(selected["iv"])


def _expiry_smile(rows: pd.DataFrame, spot: float, years: float) -> np.ndarray | None:
    observations: list[dict[str, float | str]] = []
    for row in rows.itertuples(index=False):
        side = "call" if str(row.OptnTp).upper() == "CE" else "put"
        strike = float(row.StrkPric)
        price = float(row.ClsPric)
        volume = float(row.TtlTradgVol)
        open_interest = float(row.OpnIntrst)
        if min(strike, price) <= 0 or (volume <= 0 and open_interest <= 0):
            continue
        # Use the cleaner OTM wing and allow both sides close to ATM.
        if side == "call" and strike < spot * 0.97:
            continue
        if side == "put" and strike > spot * 1.03:
            continue
        iv = implied_volatility_percent(side, price, spot, strike, years)
        if iv is None:
            continue
        delta = _option_delta(side, spot, strike, years, iv)
        observations.append(
            {
                "side": side,
                "iv": iv,
                "delta": delta,
                "liquidity": math.log1p(max(0.0, volume) + max(0.0, open_interest)),
            }
        )
    if len(observations) < 5:
        return None

    put_10 = _nearest_bucket_iv(observations, "put", 0.10)
    put_25 = _nearest_bucket_iv(observations, "put", 0.25)
    call_25 = _nearest_bucket_iv(observations, "call", 0.25)
    call_10 = _nearest_bucket_iv(observations, "call", 0.10)
    atm_values = [
        value
        for value in (
            _nearest_bucket_iv(observations, "put", 0.50),
            _nearest_bucket_iv(observations, "call", 0.50),
        )
        if value is not None
    ]
    smile = [put_10, put_25, np.mean(atm_values) if atm_values else None, call_25, call_10]
    if any(value is None for value in smile):
        return None
    return np.asarray(smile, dtype=float)


def surface_from_bhavcopy(frame: pd.DataFrame, symbol: str, as_of: date) -> np.ndarray | None:
    """Convert one official F&O bhavcopy into a fixed 4×5 IV surface."""

    required = {
        "FinInstrmTp",
        "TckrSymb",
        "XpryDt",
        "StrkPric",
        "OptnTp",
        "ClsPric",
        "UndrlygPric",
        "OpnIntrst",
        "TtlTradgVol",
    }
    if not required.issubset(frame.columns):
        return None
    rows = frame[
        (frame["FinInstrmTp"] == "STO")
        & (frame["TckrSymb"].astype(str).str.upper() == symbol.upper())
    ].copy()
    if rows.empty:
        return None
    for column in (
        "StrkPric",
        "ClsPric",
        "UndrlygPric",
        "OpnIntrst",
        "TtlTradgVol",
    ):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")
    rows["XpryDt"] = pd.to_datetime(rows["XpryDt"], errors="coerce")
    rows = rows.dropna(subset=["XpryDt", "StrkPric", "ClsPric", "UndrlygPric", "OptnTp"])
    if rows.empty:
        return None
    positive_spots = rows.loc[rows["UndrlygPric"] > 0, "UndrlygPric"]
    if positive_spots.empty:
        return None
    spot = float(positive_spots.median())

    smiles: list[np.ndarray] = []
    actual_tenors: list[float] = []
    for expiry, expiry_rows in rows.groupby("XpryDt"):
        expiry_date = pd.Timestamp(expiry).date()
        days = (expiry_date - as_of).days
        if days < 2 or days > 140:
            continue
        smile = _expiry_smile(expiry_rows, spot, days / 365.25)
        if smile is not None:
            actual_tenors.append(float(days))
            smiles.append(smile)
    if len(smiles) < 2:
        return None

    order = np.argsort(actual_tenors)
    tenor_array = np.asarray(actual_tenors)[order]
    smile_array = np.asarray(smiles)[order]
    surface = np.column_stack(
        [
            np.interp(TENOR_DAYS, tenor_array, smile_array[:, bucket])
            for bucket in range(len(DELTA_BUCKETS))
        ]
    )
    return surface if np.isfinite(surface).all() else None


def _smooth_surface(surface: np.ndarray) -> np.ndarray:
    tenor_coordinates, delta_coordinates = np.meshgrid(
        np.arange(surface.shape[0], dtype=float),
        np.arange(surface.shape[1], dtype=float),
        indexing="ij",
    )
    try:
        spline = SmoothBivariateSpline(
            tenor_coordinates.ravel(),
            delta_coordinates.ravel(),
            surface.ravel(),
            kx=2,
            ky=2,
            s=surface.size * 2.0,
        )
        smoothed = spline(
            np.arange(surface.shape[0], dtype=float),
            np.arange(surface.shape[1], dtype=float),
            grid=True,
        )
        return np.clip(smoothed, 1.0, MAX_IV_PERCENT)
    except (ValueError, np.linalg.LinAlgError):
        return surface.copy()


def _ridge_var5_forecast(
    differenced_scores: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Regularized VAR(5), returning the next change, residuals and ridge alpha.

    Adding FPCA scores makes an unregularized VAR grow by five predictors per
    component. Standardizing the score changes and shrinking lag coefficients
    keeps the 5-8 component models estimable with the available NSE history.
    The intercept is not penalized. Alpha is selected using the final ten
    causal one-step validation observations inside the training sample.
    """

    lag_order = 5
    if len(differenced_scores) <= lag_order + 2:
        raise ValueError("At least eight differenced score observations are required.")
    scale = np.std(differenced_scores, axis=0, ddof=1)
    scale = np.where(np.isfinite(scale) & (scale > 1e-8), scale, 1.0)
    standardized = differenced_scores / scale
    predictors = []
    targets = []
    for index in range(lag_order, len(standardized)):
        lagged = standardized[index - lag_order : index][::-1].ravel()
        predictors.append(np.concatenate(([1.0], lagged)))
        targets.append(standardized[index])
    x = np.asarray(predictors)
    y = np.asarray(targets)
    penalty = np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    validation_start = max(8, len(x) - 10)
    alpha_losses: list[float] = []
    for alpha in RIDGE_ALPHA_CANDIDATES:
        errors = []
        for target_index in range(validation_start, len(x)):
            train_x = x[:target_index]
            train_y = y[:target_index]
            coefficients = np.linalg.solve(
                train_x.T @ train_x + alpha * penalty,
                train_x.T @ train_y,
            )
            errors.append(np.mean((y[target_index] - x[target_index] @ coefficients) ** 2))
        alpha_losses.append(float(np.mean(errors)) if errors else math.inf)
    selected_alpha = float(
        RIDGE_ALPHA_CANDIDATES[int(np.argmin(alpha_losses))]
    )
    coefficients = np.linalg.solve(
        x.T @ x + selected_alpha * penalty,
        x.T @ y,
    )
    standardized_residuals = y - x @ coefficients
    latest = standardized[-lag_order:][::-1].ravel()
    standardized_forecast = np.concatenate(([1.0], latest)) @ coefficients
    return (
        standardized_forecast * scale,
        standardized_residuals * scale,
        selected_alpha,
    )


def _fit_fpca_core(
    smoothed: np.ndarray,
    component_count: int,
) -> dict[str, Any]:
    flat = smoothed.reshape(len(smoothed), -1)
    mean_surface = flat.mean(axis=0)
    centered = flat - mean_surface
    _, singular_values, right_vectors = np.linalg.svd(centered, full_matrices=False)
    variances = singular_values**2
    total_variance = float(variances.sum())
    if total_variance <= 1e-12:
        raise ValueError("The historical IV surfaces contain no usable variation.")
    cumulative = np.cumsum(variances) / total_variance
    if component_count < 1 or component_count > right_vectors.shape[0]:
        raise ValueError(f"{component_count} FPCA components cannot be fitted.")
    components = right_vectors[:component_count]
    scores = centered @ components.T
    reconstruction = mean_surface + scores @ components
    reconstruction_rmse = float(np.sqrt(np.mean((flat - reconstruction) ** 2)))
    predicted_change, _, ridge_alpha = _ridge_var5_forecast(np.diff(scores, axis=0))
    predicted_scores = scores[-1] + predicted_change
    forecast_flat = mean_surface + predicted_scores @ components
    shape = smoothed.shape[1:]
    return {
        "forecast_surface": np.clip(forecast_flat.reshape(shape), 1.0, MAX_IV_PERCENT),
        "mean_surface": mean_surface.reshape(shape),
        "component_count": component_count,
        "explained_variance_percent": float(cumulative[component_count - 1] * 100),
        "reconstruction_rmse": reconstruction_rmse,
        "ridge_alpha": ridge_alpha,
    }


def _expanding_validation(
    smoothed: np.ndarray,
    component_count: int,
) -> dict[str, Any]:
    validation_start = max(MINIMUM_HISTORY_SURFACES, len(smoothed) - 10)
    validation_errors = []
    baseline_errors = []
    directional_hits: list[float] = []
    for target_index in range(validation_start, len(smoothed)):
        predicted = _fit_fpca_core(
            smoothed[:target_index],
            component_count,
        )["forecast_surface"]
        validation_errors.append(smoothed[target_index] - predicted)
        baseline = smoothed[target_index - 1]
        baseline_errors.append(smoothed[target_index] - baseline)
        predicted_move = predicted - baseline
        actual_move = smoothed[target_index] - baseline
        meaningful = np.abs(predicted_move) >= 0.25
        if np.any(meaningful):
            directional_hits.append(
                float(
                    np.mean(
                        np.sign(predicted_move[meaningful])
                        == np.sign(actual_move[meaningful])
                    )
                )
            )
    if not validation_errors:
        raise ValueError("No one-session-ahead validation window was available.")
    errors = np.asarray(validation_errors)
    naive_errors = np.asarray(baseline_errors)
    aggregate_rmse = float(np.sqrt(np.mean(errors**2)))
    baseline_rmse = float(np.sqrt(np.mean(naive_errors**2)))
    return {
        "rmse_surface": np.sqrt(np.mean(errors**2, axis=0)),
        "aggregate_rmse": aggregate_rmse,
        "baseline_rmse": baseline_rmse,
        "improvement_over_baseline_percent": (
            (baseline_rmse - aggregate_rmse) / baseline_rmse * 100
            if baseline_rmse > 1e-12
            else 0.0
        ),
        "directional_accuracy_percent": (
            float(np.mean(directional_hits) * 100) if directional_hits else None
        ),
        "validation_sessions": len(errors),
    }


def _select_component_count(
    cumulative_variance_percent: np.ndarray,
) -> tuple[int, float]:
    """Return the smallest permitted FPCA model meeting the variance target."""

    maximum = min(MAXIMUM_COMPONENT_COUNT, len(cumulative_variance_percent))
    if maximum < MINIMUM_COMPONENT_COUNT:
        raise ValueError("Too few FPCA directions are available for component selection.")
    for component_count in range(MINIMUM_COMPONENT_COUNT, maximum + 1):
        retained = float(cumulative_variance_percent[component_count - 1])
        if retained >= EXPLAINED_VARIANCE_TARGET_PERCENT:
            return component_count, retained
    return maximum, float(cumulative_variance_percent[maximum - 1])


def fit_fpca_var(surfaces: np.ndarray) -> dict[str, Any]:
    """Retain enough PCs for 99% variance and forecast scores with ridge VAR(5)."""

    if surfaces.ndim != 3 or len(surfaces) < MINIMUM_VALIDATION_SURFACES:
        raise ValueError(
            f"At least {MINIMUM_VALIDATION_SURFACES} complete daily IV surfaces are required "
            "so the model has a one-session-ahead validation observation."
        )
    smoothed = np.asarray([_smooth_surface(surface) for surface in surfaces])
    flat = smoothed.reshape(len(smoothed), -1)
    centered = flat - flat.mean(axis=0)
    singular_values = np.linalg.svd(centered, full_matrices=False, compute_uv=False)
    variances = singular_values**2
    total_variance = float(variances.sum())
    if total_variance <= 1e-12:
        raise ValueError("The historical IV surfaces contain no usable variation.")
    cumulative_variance_percent = np.cumsum(variances) / total_variance * 100
    selected_count, retained_variance = _select_component_count(
        cumulative_variance_percent
    )
    validations = {
        component_count: _expanding_validation(smoothed, component_count)
        for component_count in range(
            MINIMUM_COMPONENT_COUNT,
            min(MAXIMUM_COMPONENT_COUNT, flat.shape[1]) + 1,
        )
    }
    selected_validation = validations[selected_count]
    result = _fit_fpca_core(smoothed, selected_count)
    result["rmse_surface"] = selected_validation["rmse_surface"]
    result["validation_sessions"] = selected_validation["validation_sessions"]
    result["validation_rmse_by_components"] = {
        str(component_count): round(validation["aggregate_rmse"], 4)
        for component_count, validation in validations.items()
    }
    result["validation_baseline_rmse"] = round(
        selected_validation["baseline_rmse"], 4
    )
    result["validation_improvement_over_baseline_percent"] = round(
        selected_validation["improvement_over_baseline_percent"], 2
    )
    result["validation_directional_accuracy_percent"] = (
        round(selected_validation["directional_accuracy_percent"], 2)
        if selected_validation["directional_accuracy_percent"] is not None
        else None
    )
    result["fourth_component_improvement_percent"] = None
    target_status = (
        "meeting"
        if retained_variance >= EXPLAINED_VARIANCE_TARGET_PERCENT
        else "falling short of"
    )
    result["component_selection_note"] = (
        f"{selected_count} components retained, {target_status} the "
        f"{EXPLAINED_VARIANCE_TARGET_PERCENT:.0f}% target with "
        f"{retained_variance:.2f}% explained variance. Ridge VAR(5) alpha "
        f"{result['ridge_alpha']:g} was selected causally; expanding-window "
        f"one-session RMSE is {selected_validation['aggregate_rmse']:.2f} versus "
        f"{selected_validation['baseline_rmse']:.2f} for no change."
    )
    return result


def _normalize_bhavcopy_frame(
    content: bytes,
    *,
    report_date: date | None = None,
    spot_by_symbol: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, str]:
    """Return current-schema option rows from either NSE bhavcopy generation."""

    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = archive.namelist()
        if not names:
            raise ValueError("The NSE bhavcopy archive is empty.")
        with archive.open(names[0]) as source:
            columns = set(pd.read_csv(source, nrows=0).columns)
        if "FinInstrmTp" in columns:
            use_columns = [
                "FinInstrmTp",
                "TckrSymb",
                "XpryDt",
                "StrkPric",
                "OptnTp",
                "ClsPric",
                "UndrlygPric",
                "OpnIntrst",
                "TtlTradgVol",
            ]
            with archive.open(names[0]) as source:
                return pd.read_csv(source, usecols=use_columns), "NSE UDiFF bhavcopy"

        option_type_column = (
            "OPTION_TYP" if "OPTION_TYP" in columns else "OPTIONTYPE"
        )
        legacy_columns = {
            "INSTRUMENT",
            "SYMBOL",
            "EXPIRY_DT",
            "STRIKE_PR",
            option_type_column,
            "CLOSE",
            "OPEN_INT",
            "CONTRACTS",
        }
        if not legacy_columns.issubset(columns):
            raise ValueError("The NSE bhavcopy schema is not recognized.")
        with archive.open(names[0]) as source:
            raw_legacy = pd.read_csv(source, usecols=sorted(legacy_columns))

    # Legacy files do not include underlying spot. Yahoo back-adjusts old prices
    # after splits and bonuses, putting them on a different scale from the
    # contemporaneous option strikes. Use the nearest stock future in the same
    # official file, discounted to spot, and retain Yahoo only as a fallback.
    future_rows = raw_legacy[raw_legacy["INSTRUMENT"] == "FUTSTK"].copy()
    future_rows["EXPIRY_DT"] = pd.to_datetime(future_rows["EXPIRY_DT"], errors="coerce")
    future_rows["CLOSE"] = pd.to_numeric(future_rows["CLOSE"], errors="coerce")
    future_rows = future_rows.dropna(subset=["EXPIRY_DT", "CLOSE"])
    if report_date is not None:
        future_rows = future_rows[future_rows["EXPIRY_DT"].dt.date >= report_date]
    future_rows = future_rows.sort_values(["SYMBOL", "EXPIRY_DT"])
    nearest_futures = future_rows.groupby("SYMBOL", sort=False).first().reset_index()
    futures_spots: dict[str, float] = {}
    for row in nearest_futures.itertuples(index=False):
        years = (
            max(0, (pd.Timestamp(row.EXPIRY_DT).date() - report_date).days) / 365.25
            if report_date is not None
            else 0.0
        )
        futures_spots[str(row.SYMBOL).upper()] = float(row.CLOSE) * math.exp(
            -RISK_FREE_RATE * years
        )

    legacy = raw_legacy.rename(
        columns={
            "INSTRUMENT": "FinInstrmTp",
            "SYMBOL": "TckrSymb",
            "EXPIRY_DT": "XpryDt",
            "STRIKE_PR": "StrkPric",
            "OPTION_TYP": "OptnTp",
            "OPTIONTYPE": "OptnTp",
            "CLOSE": "ClsPric",
            "OPEN_INT": "OpnIntrst",
            "CONTRACTS": "TtlTradgVol",
        }
    )
    legacy["FinInstrmTp"] = legacy["FinInstrmTp"].replace({"OPTSTK": "STO"})
    spots = {str(key).upper(): float(value) for key, value in (spot_by_symbol or {}).items()}
    spots.update(futures_spots)
    legacy["UndrlygPric"] = legacy["TckrSymb"].astype(str).str.upper().map(spots)
    return legacy, "NSE legacy F&O bhavcopy"


def _read_bhavcopy_surfaces(
    content: bytes,
    symbols: list[str] | tuple[str, ...],
    report_date: date,
    *,
    spot_by_symbol: dict[str, float] | None = None,
) -> tuple[dict[str, np.ndarray], str]:
    frame, source_format = _normalize_bhavcopy_frame(
        content,
        report_date=report_date,
        spot_by_symbol=spot_by_symbol,
    )
    wanted = {symbol.upper() for symbol in symbols}
    frame = frame[frame["TckrSymb"].astype(str).str.upper().isin(wanted)]
    surfaces = {
        symbol: surface
        for symbol in sorted(wanted)
        if (surface := surface_from_bhavcopy(frame, symbol, report_date)) is not None
    }
    return surfaces, source_format


def _read_bhavcopy_surface(content: bytes, symbol: str, report_date: date) -> np.ndarray | None:
    surfaces, _ = _read_bhavcopy_surfaces(content, [symbol], report_date)
    return surfaces.get(symbol.upper())


def _candidate_dates(*, now: datetime | None = None) -> list[date]:
    now_ist = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata"))
    current = now_ist.date()
    if now_ist.time() < time(18, 0):
        current -= timedelta(days=1)
    values = []
    while len(values) < CANDIDATE_WEEKDAYS:
        if current.weekday() < 5:
            values.append(current)
        current -= timedelta(days=1)
    return values


async def _historical_surface_for_date(symbol: str, report_date: date) -> np.ndarray | None:
    url = ARCHIVE_URL.format(date=f"{report_date:%Y%m%d}")
    try:
        response = await get_nse_client()._get(url)
        return await asyncio.to_thread(
            _read_bhavcopy_surface,
            response.content,
            symbol,
            report_date,
        )
    except (
        httpx.HTTPError,
        zipfile.BadZipFile,
        ValueError,
        KeyError,
        pd.errors.ParserError,
    ):
        return None


async def _historical_bhavcopy_for_date(report_date: date) -> bytes | None:
    """Fetch the official daily file, falling back to NSE's legacy archive."""

    current_url = ARCHIVE_URL.format(date=f"{report_date:%Y%m%d}")
    legacy_url = LEGACY_ARCHIVE_URL.format(
        year=f"{report_date:%Y}",
        month=f"{report_date:%b}".upper(),
        day=f"{report_date:%d}",
    )
    # The UDiFF archive is available throughout 2024 onward. Avoid a guaranteed
    # 404 against the current-format path for every older session.
    urls = (current_url, legacy_url) if report_date.year >= 2024 else (legacy_url,)
    for url in urls:
        try:
            return (await get_nse_client()._get(url)).content
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                continue
            raise
    return None


def _backfill_dates(*, years: int, now: datetime | None = None) -> list[date]:
    current = (now or datetime.now(UTC)).astimezone(ZoneInfo("Asia/Kolkata")).date()
    try:
        first = current.replace(year=current.year - years)
    except ValueError:
        first = current.replace(year=current.year - years, day=28)
    values = []
    while first <= current:
        if first.weekday() < 5:
            values.append(first)
        first += timedelta(days=1)
    return values


def _history_cache_payload(symbol: str) -> tuple[FileCache, str, dict[date, np.ndarray]]:
    cache = FileCache(get_settings().cache_path, "iv_surfaces")
    key = cache_key(SURFACE_DATA_VERSION, symbol.upper())
    payload = cache.get(key, None) or {}
    values: dict[date, np.ndarray] = {}
    for cached_date, cached_surface in zip(
        payload.get("dates") or [],
        payload.get("surfaces") or [],
        strict=False,
    ):
        try:
            parsed_date = date.fromisoformat(str(cached_date))
            parsed_surface = np.asarray(cached_surface, dtype=float)
        except (TypeError, ValueError):
            continue
        if parsed_surface.shape == (len(TENOR_DAYS), len(DELTA_BUCKETS)):
            values[parsed_date] = parsed_surface
    return cache, key, values


def _persist_surface_histories(histories: dict[str, dict[date, np.ndarray]]) -> None:
    for symbol, values in histories.items():
        cache, key, _ = _history_cache_payload(symbol)
        dated = sorted(values.items(), key=lambda item: item[0])[-TARGET_HISTORY_SURFACES:]
        cache.put(
            key,
            {
                "dates": [value.isoformat() for value, _ in dated],
                "surfaces": [surface.tolist() for _, surface in dated],
                "coverage": {
                    "observations": len(dated),
                    "first_date": dated[0][0].isoformat() if dated else None,
                    "last_date": dated[-1][0].isoformat() if dated else None,
                    "target_observations": TARGET_HISTORY_SURFACES,
                },
            },
            source="NSE equity-derivatives daily bhavcopies (current and legacy)",
            model_name=MODEL_NAME,
        )


def _adjusted_return_candles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candles = list(payload.get("candles") or [])
    if not candles:
        return []
    values = pd.DataFrame(candles)
    values["time"] = pd.to_datetime(values["time"], errors="coerce")
    values["close"] = pd.to_numeric(values["close"], errors="coerce")
    values = values.dropna(subset=["time", "close"]).sort_values("time")
    if values.empty:
        return []
    # Yahoo's unadjusted series can contain mechanical split/bonus jumps. For
    # path features we need economic returns, so neutralize only extreme moves
    # that are close to a common corporate-action ratio.
    ratios = values["close"] / values["close"].shift(1)
    factors = np.ones(len(values), dtype=float)
    corporate_ratios = np.asarray(
        [0.1, 0.2, 0.25, 1 / 3, 0.4, 0.5, 2 / 3, 0.75, 0.8, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 10.0]
    )
    for index, ratio in enumerate(ratios.to_numpy(dtype=float)):
        if index == 0 or not np.isfinite(ratio) or 0.67 <= ratio <= 1.5:
            continue
        nearest = float(corporate_ratios[np.argmin(np.abs(np.log(corporate_ratios / ratio)))])
        if abs(math.log(ratio / nearest)) <= 0.08:
            factors[index] = nearest
    economic_returns = ratios.to_numpy(dtype=float) / factors - 1.0
    adjusted = np.empty(len(values), dtype=float)
    adjusted[0] = float(values.iloc[0]["close"])
    for index in range(1, len(values)):
        adjusted[index] = adjusted[index - 1] * (1.0 + economic_returns[index])
    return [
        {"time": timestamp.date().isoformat(), "close": float(close)}
        for timestamp, close in zip(values["time"], adjusted, strict=True)
    ]


async def backfill_historical_surfaces(
    symbols: list[str] | tuple[str, ...],
    *,
    years: int = HISTORY_BACKFILL_YEARS,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Build long option histories date-first so every NSE file is fetched once."""

    from app.services.market_data.india_trading import get_price_history

    started = monotonic_time.monotonic()
    selected = sorted({str(symbol).upper() for symbol in symbols if str(symbol).strip()})
    histories = {symbol: _history_cache_payload(symbol)[2] for symbol in selected}
    price_payloads = await asyncio.gather(
        *(get_price_history(symbol, f"{symbol}.NS", "10Y") for symbol in selected)
    )
    spots: dict[str, dict[date, float]] = {}
    for symbol, payload in zip(selected, price_payloads, strict=True):
        spots[symbol] = {
            date.fromisoformat(str(candle["time"])): float(candle["close"])
            for candle in payload.get("candles") or []
            if candle.get("time") and candle.get("close")
        }

    manifest_cache = FileCache(get_settings().cache_path, "iv_surface_backfill")
    manifest_key = cache_key(
        SURFACE_DATA_VERSION,
        "paper-sample-date-first-v2",
        str(years),
        ",".join(selected),
    )
    manifest = manifest_cache.get(manifest_key, None) or {}
    attempted = set() if force else set(manifest.get("attempted_dates") or [])
    candidates = _backfill_dates(years=years)
    pending = [
        value
        for value in candidates
        if force
        or (
            value.isoformat() not in attempted
            and not all(value in histories[symbol] for symbol in selected)
        )
    ]
    downloaded_dates = 0
    unavailable_dates = 0
    parsed_surfaces = 0
    formats: dict[str, int] = {}

    for start in range(0, len(pending), BACKFILL_BATCH_DATES):
        batch_dates = pending[start : start + BACKFILL_BATCH_DATES]
        payloads = await asyncio.gather(
            *(_historical_bhavcopy_for_date(value) for value in batch_dates),
            return_exceptions=True,
        )
        for report_date, payload in zip(batch_dates, payloads, strict=True):
            if isinstance(payload, BaseException):
                logger.warning("IV history backfill failed for %s: %s", report_date, payload)
                continue
            attempted.add(report_date.isoformat())
            if payload is None:
                unavailable_dates += 1
                continue
            downloaded_dates += 1
            spot_by_symbol = {
                symbol: value
                for symbol in selected
                if (value := spots[symbol].get(report_date)) is not None
            }
            try:
                parsed, source_format = await asyncio.to_thread(
                    _read_bhavcopy_surfaces,
                    payload,
                    selected,
                    report_date,
                    spot_by_symbol=spot_by_symbol,
                )
            except (ValueError, KeyError, zipfile.BadZipFile, pd.errors.ParserError) as exc:
                logger.warning("IV history parse failed for %s: %s", report_date, exc)
                continue
            formats[source_format] = formats.get(source_format, 0) + 1
            for symbol, surface in parsed.items():
                histories[symbol][report_date] = surface
                parsed_surfaces += 1

        _persist_surface_histories(histories)
        manifest_cache.put(
            manifest_key,
            {"attempted_dates": sorted(attempted)},
            source="NSE derivatives archive backfill manifest",
            model_name=MODEL_NAME,
        )
        if progress is not None:
            progress(
                {
                    "completed_dates": min(start + len(batch_dates), len(pending)),
                    "pending_dates": len(pending),
                    "parsed_surfaces": parsed_surfaces,
                }
            )

    coverage = {
        symbol: {
            "observations": len(values),
            "first_date": min(values).isoformat() if values else None,
            "last_date": max(values).isoformat() if values else None,
        }
        for symbol, values in histories.items()
    }
    return {
        "symbols": len(selected),
        "requested_years": years,
        "candidate_weekdays": len(candidates),
        "pending_dates": len(pending),
        "downloaded_dates": downloaded_dates,
        "unavailable_dates": unavailable_dates,
        "parsed_surfaces": parsed_surfaces,
        "source_formats": formats,
        "coverage": coverage,
        "elapsed_seconds": round(monotonic_time.monotonic() - started, 2),
    }


async def load_historical_surfaces(
    symbol: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[str], np.ndarray]:
    cache = FileCache(get_settings().cache_path, "iv_surfaces")
    key = cache_key(SURFACE_DATA_VERSION, symbol.upper())
    stale_wrapper = cache.get_wrapper(key, None)
    stale_payload = (
        dict(stale_wrapper.get("payload") or {})
        if stale_wrapper is not None
        else {}
    )
    cached = None if force_refresh else cache.get(key, HISTORY_TTL_SECONDS)
    if cached is not None:
        return list(cached["dates"]), np.asarray(cached["surfaces"], dtype=float)

    # A temporarily illiquid far expiry must not erase already verified daily
    # surfaces. Seed the refresh with the last verified cache, download only
    # missing sessions, then retain the newest TARGET_HISTORY_SURFACES values.
    merged_surfaces: dict[date, np.ndarray] = {}
    for cached_date, cached_surface in zip(
        stale_payload.get("dates") or [],
        stale_payload.get("surfaces") or [],
        strict=False,
    ):
        try:
            parsed_date = date.fromisoformat(str(cached_date))
            parsed_surface = np.asarray(cached_surface, dtype=float)
        except (TypeError, ValueError):
            continue
        if parsed_surface.shape == (len(TENOR_DAYS), len(DELTA_BUCKETS)):
            merged_surfaces[parsed_date] = parsed_surface
    refresh_candidates = _candidate_dates()
    if merged_surfaces:
        refresh_candidates = refresh_candidates[:INCREMENTAL_REFRESH_WEEKDAYS]
    candidate_dates = [value for value in refresh_candidates if value not in merged_surfaces]
    # The shared NSE client enforces the configured exchange request rate.
    for start in range(0, len(candidate_dates), 4):
        batch_dates = candidate_dates[start : start + 4]
        batch = await asyncio.gather(
            *[_historical_surface_for_date(symbol, value) for value in batch_dates]
        )
        for surface_date, surface in zip(batch_dates, batch, strict=True):
            if surface is not None:
                merged_surfaces[surface_date] = surface
        if len(merged_surfaces) >= TARGET_HISTORY_SURFACES:
            break

    dated_surfaces = sorted(merged_surfaces.items(), key=lambda item: item[0])
    if len(dated_surfaces) > TARGET_HISTORY_SURFACES:
        dated_surfaces = dated_surfaces[-TARGET_HISTORY_SURFACES:]
    dates = [value.isoformat() for value, _ in dated_surfaces]
    surfaces = np.asarray([surface for _, surface in dated_surfaces])
    cache.put(
        key,
        {"dates": dates, "surfaces": surfaces.tolist()},
        source="NSE equity-derivatives daily bhavcopies",
        model_name=MODEL_NAME,
    )
    return dates, surfaces


def _parse_market_lot_sizes(text: str) -> dict[str, dict[str, int]]:
    reader = csv.reader(io.StringIO(text), skipinitialspace=True)
    headers = [str(value).strip().upper() for value in next(reader, [])]
    if "SYMBOL" not in headers:
        return {}
    symbol_index = headers.index("SYMBOL")
    values: dict[str, dict[str, int]] = {}
    for row in reader:
        if len(row) <= symbol_index:
            continue
        symbol = str(row[symbol_index]).strip().upper()
        if not symbol or symbol == "SYMBOL":
            continue
        expiry_values: dict[str, int] = {}
        for index, header in enumerate(headers):
            if index == symbol_index or not header or index >= len(row):
                continue
            try:
                lot_size = int(float(str(row[index]).strip()))
            except (TypeError, ValueError):
                continue
            if lot_size > 0:
                expiry_values[header] = lot_size
        if expiry_values:
            values[symbol] = expiry_values
    return values


async def get_fno_lot_size(symbol: str, expiry: str | None) -> int | None:
    cache = FileCache(get_settings().cache_path, "iv_market_lots")
    key = cache_key("nse_fno_market_lots_v1")
    lot_sizes = cache.get(key, LOT_SIZE_TTL_SECONDS)
    if lot_sizes is None:
        response = await get_nse_client()._get(FNO_MARKET_LOTS_URL)
        lot_sizes = _parse_market_lot_sizes(response.text)
        cache.put(key, lot_sizes, source=str(response.url))
    symbol_sizes = dict((lot_sizes or {}).get(symbol.upper()) or {})
    if not symbol_sizes:
        return None
    if expiry:
        try:
            expiry_key = datetime.strptime(expiry, "%d-%b-%Y").strftime("%b-%y").upper()
            if expiry_key in symbol_sizes:
                return int(symbol_sizes[expiry_key])
        except ValueError:
            pass
    return int(next(iter(symbol_sizes.values())))


def _market_bucket_points(chain: dict) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in chain.get("strikes") or []:
        for side in ("put", "call"):
            leg = row.get(side) or {}
            iv = leg.get("implied_volatility")
            delta = leg.get("delta")
            if iv is None or delta is None or not 1 <= float(iv) <= MAX_IV_PERCENT:
                continue
            candidates.append(
                {
                    "side": side,
                    "strike_price": float(row["strike_price"]),
                    "iv": float(iv),
                    "delta": float(delta),
                    "liquidity": math.log1p(
                        max(0.0, float(leg.get("volume") or 0))
                        + max(0.0, float(leg.get("open_interest") or 0))
                    ),
                }
            )

    points: list[dict[str, Any]] = []
    for label, side, target in DELTA_BUCKETS:
        if side == "atm":
            atm_candidates = _tradable_atm_rows(chain)
            if not atm_candidates:
                continue
            selected_atm = min(
                atm_candidates,
                key=lambda item: abs(
                    float(item["row"]["strike_price"]) - float(chain.get("underlying_value") or 0)
                ),
            )
            call_iv = float(selected_atm["call_iv"])
            put_iv = float(selected_atm["put_iv"])
            points.append(
                {
                    "label": label,
                    "side": "call_put",
                    "strike_price": float(selected_atm["row"]["strike_price"]),
                    "market_iv_percent": float(np.mean([call_iv, put_iv])),
                    "call_market_iv_percent": call_iv,
                    "put_market_iv_percent": put_iv,
                }
            )
            continue
        eligible = [item for item in candidates if item["side"] == side]
        if not eligible:
            continue
        selected = min(
            eligible,
            key=lambda item: (
                abs(abs(item["delta"]) - target),
                -item["liquidity"],
            ),
        )
        if abs(abs(selected["delta"]) - target) > 0.22:
            continue
        points.append(
            {
                "label": label,
                "side": selected["side"],
                "strike_price": selected["strike_price"],
                "market_iv_percent": selected["iv"],
            }
        )
    return points


def _execution_price(
    leg: dict[str, Any] | None,
    action: str,
) -> tuple[float | None, str | None]:
    if not leg:
        return None, None
    preferred_field = "ask_price" if action == "buy" else "bid_price"
    preferred = leg.get(preferred_field)
    if preferred is not None and float(preferred) > 0:
        return float(preferred), "ask" if action == "buy" else "bid"
    last = leg.get("last_price")
    if last is not None and float(last) > 0:
        return float(last), "last traded"
    return None, None


def _tradable_atm_rows(chain: dict[str, Any]) -> list[dict[str, Any]]:
    """Return strikes with a matched, executable call/put pair and usable IVs."""

    candidates: list[dict[str, Any]] = []
    for row in chain.get("strikes") or []:
        call = row.get("call") or {}
        put = row.get("put") or {}
        call_iv = call.get("implied_volatility")
        put_iv = put.get("implied_volatility")
        if (
            call_iv is None
            or put_iv is None
            or not 1 <= float(call_iv) <= MAX_IV_PERCENT
            or not 1 <= float(put_iv) <= MAX_IV_PERCENT
        ):
            continue
        call_buy, call_buy_source = _execution_price(call, "buy")
        put_buy, put_buy_source = _execution_price(put, "buy")
        call_sell, call_sell_source = _execution_price(call, "sell")
        put_sell, put_sell_source = _execution_price(put, "sell")
        if not all(value is not None for value in (call_buy, put_buy, call_sell, put_sell)):
            continue
        candidates.append(
            {
                "row": row,
                "call_iv": float(call_iv),
                "put_iv": float(put_iv),
                "call_buy": call_buy,
                "call_buy_source": call_buy_source,
                "put_buy": put_buy,
                "put_buy_source": put_buy_source,
                "call_sell": call_sell,
                "call_sell_source": call_sell_source,
                "put_sell": put_sell,
                "put_sell_source": put_sell_source,
            }
        )
    return candidates


def _strategy_leg(
    *,
    action: str,
    option_type: str,
    strike_price: float,
    premium_per_unit: float,
    price_source: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "option_type": option_type,
        "strike_price": round(strike_price, 2),
        "quantity_lots": 1,
        "premium_per_unit": round(premium_per_unit, 2),
        "price_source": price_source,
    }


def _payoff_points(
    *,
    lower_price: float,
    upper_price: float,
    lot_size: int,
    capital_at_risk_per_lot: float,
    payoff_per_unit: Any,
    next_session_payoff_per_unit: Any,
) -> list[dict[str, float]]:
    points = []
    for underlying_price in np.linspace(lower_price, upper_price, 41):
        pnl_per_lot = float(payoff_per_unit(float(underlying_price))) * lot_size
        next_session_pnl_per_lot = (
            float(next_session_payoff_per_unit(float(underlying_price))) * lot_size
        )
        points.append(
            {
                "underlying_price": round(float(underlying_price), 2),
                "pnl_per_lot": round(pnl_per_lot, 2),
                "next_session_pnl_per_lot": round(
                    next_session_pnl_per_lot,
                    2,
                ),
                "pnl_percent_of_capital_at_risk": round(
                    pnl_per_lot / capital_at_risk_per_lot * 100,
                    2,
                )
                if capital_at_risk_per_lot > 0
                else 0.0,
            }
        )
    return points


def _empty_strategy(rationale: str) -> dict[str, Any]:
    return {
        "strategy_id": None,
        "available": False,
        "signal": "no_trade",
        "strategy_name": "No volatility structure suggested",
        "rationale": rationale,
        "source_buckets": [],
        "legs": [],
        "payoff_points": [],
        "limitations": [
            "A strategy is shown only when the ATM IV gap exceeds the model-error band."
        ],
    }


def build_iv_strategy(
    chain: dict[str, Any],
    comparisons: list[dict[str, Any]],
    lot_size: int | None,
) -> dict[str, Any]:
    """Translate a material ATM IV gap into a defined option structure."""

    atm_comparison = next(
        (item for item in comparisons if item.get("label") == "ATM"),
        None,
    )
    if atm_comparison is None:
        return _empty_strategy(
            "An ATM IV comparison was unavailable, so a straddle-style volatility "
            "position could not be evaluated."
        )
    if not lot_size or lot_size <= 0:
        return _empty_strategy(
            "The NSE contract lot size was unavailable, so a trade-sized payoff "
            "example could not be built safely."
        )
    spot = float(chain.get("underlying_value") or 0)
    rows = list(chain.get("strikes") or [])
    if spot <= 0 or not rows:
        return _empty_strategy("The current spot or option strikes were unavailable.")

    candidate_atm_rows = _tradable_atm_rows(chain)
    if not candidate_atm_rows:
        return _empty_strategy("No ATM strike had usable call and put entry prices on both sides.")
    atm = min(
        candidate_atm_rows,
        key=lambda item: abs(float(item["row"]["strike_price"]) - spot),
    )
    strike = float(atm["row"]["strike_price"])
    call_market_iv = float(atm["call_iv"])
    put_market_iv = float(atm["put_iv"])
    market_iv = float(np.mean([call_market_iv, put_market_iv]))
    predicted_iv = float(atm_comparison["predicted_iv_percent"])
    iv_gap = predicted_iv - market_iv
    material_threshold = float(atm_comparison.get("material_threshold_vol_points") or 2.0)
    if iv_gap > material_threshold:
        strategy_status = "cheap"
    elif iv_gap < -material_threshold:
        strategy_status = "expensive"
    else:
        market_gap = market_iv - predicted_iv
        relative_label = "expensive" if market_gap >= 0 else "cheap"
        return _empty_strategy(
            f"The nearest tradable ATM strike is ₹{strike:,.0f}. Its call IV is "
            f"{call_market_iv:.2f}% and its put IV is {put_market_iv:.2f}%, which "
            f"average to {market_iv:.2f}%. The model forecasts {predicted_iv:.2f}%, "
            f"so the combined ATM position is only {abs(market_gap):.2f} volatility "
            f"points {relative_label}. The ATM forecast error is "
            f"{float(atm_comparison.get('model_error_vol_points') or 0):.2f} points, "
            f"making the required threshold max(2.00, 1.5 × error) = "
            f"{material_threshold:.2f} points. Because {abs(market_gap):.2f} does "
            f"not exceed {material_threshold:.2f}, no trade is suggested."
        )
    comparison_by_label = {str(item.get("label")): item for item in comparisons}
    try:
        expiry_date = datetime.strptime(
            str(chain.get("selected_expiry")),
            "%d-%b-%Y",
        ).date()
        exchange_timestamp = chain.get("exchange_timestamp")
        as_of = (
            datetime.strptime(exchange_timestamp, "%d-%b-%Y %H:%M:%S").date()
            if exchange_timestamp
            else datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )
        next_session_years = max(1, (expiry_date - as_of).days - 1) / 365.25
    except ValueError:
        next_session_years = 1 / 365.25

    if strategy_status == "cheap":
        debit_per_unit = float(atm["call_buy"]) + float(atm["put_buy"])
        if debit_per_unit <= 0:
            return _empty_strategy("The ATM straddle debit could not be calculated.")
        capital_at_risk = debit_per_unit * lot_size
        lower_break_even = max(0.0, strike - debit_per_unit)
        upper_break_even = strike + debit_per_unit
        scenario_span = max(spot * 0.2, debit_per_unit * 2.5)

        def long_straddle_payoff(underlying_price: float) -> float:
            return (
                max(underlying_price - strike, 0)
                + max(strike - underlying_price, 0)
                - debit_per_unit
            )

        def long_straddle_next_session(underlying_price: float) -> float:
            predicted_volatility = predicted_iv / 100
            return (
                _black_scholes_price(
                    "call",
                    underlying_price,
                    strike,
                    next_session_years,
                    predicted_volatility,
                )
                + _black_scholes_price(
                    "put",
                    underlying_price,
                    strike,
                    next_session_years,
                    predicted_volatility,
                )
                - debit_per_unit
            )

        return {
            "strategy_id": "long-atm-straddle",
            "available": True,
            "signal": "long_volatility",
            "strategy_name": "Illustrative long ATM straddle",
            "rationale": (
                f"Predicted ATM IV is {predicted_iv:.2f}% versus {market_iv:.2f}% "
                f"in the market, a {iv_gap:.2f}-point increase. Buying the ATM call "
                "and put is a long-volatility structure that can benefit from an IV "
                "rise before expiry or a sufficiently large price move."
            ),
            "source_buckets": ["ATM"],
            "expiry": chain.get("selected_expiry"),
            "lot_size": lot_size,
            "underlying_value": round(spot, 2),
            "atm_market_iv_percent": round(market_iv, 2),
            "atm_predicted_iv_percent": round(predicted_iv, 2),
            "market_iv_percent": round(market_iv, 2),
            "predicted_iv_percent": round(predicted_iv, 2),
            "iv_difference_vol_points": round(iv_gap, 2),
            "legs": [
                _strategy_leg(
                    action="buy",
                    option_type="call",
                    strike_price=strike,
                    premium_per_unit=float(atm["call_buy"]),
                    price_source=str(atm["call_buy_source"]),
                ),
                _strategy_leg(
                    action="buy",
                    option_type="put",
                    strike_price=strike,
                    premium_per_unit=float(atm["put_buy"]),
                    price_source=str(atm["put_buy_source"]),
                ),
            ],
            "entry_premium_type": "debit",
            "entry_premium_per_unit": round(debit_per_unit, 2),
            "entry_cash_flow_per_lot": round(capital_at_risk, 2),
            "capital_at_risk_per_lot": round(capital_at_risk, 2),
            "maximum_profit_per_lot": None,
            "maximum_loss_per_lot": round(capital_at_risk, 2),
            "lower_break_even": round(lower_break_even, 2),
            "upper_break_even": round(upper_break_even, 2),
            "payoff_points": _payoff_points(
                lower_price=max(0.01, strike - scenario_span),
                upper_price=strike + scenario_span,
                lot_size=lot_size,
                capital_at_risk_per_lot=capital_at_risk,
                payoff_per_unit=long_straddle_payoff,
                next_session_payoff_per_unit=long_straddle_next_session,
            ),
            "payoff_horizon": "Next session at predicted IV and at option expiry",
            "limitations": [
                "The next-session line is a Black-Scholes mark-to-model scenario using predicted IV, not a guaranteed executable value.",
                "The expiry line shows intrinsic payoff; actual early-exit value also depends on IV, theta and skew.",
                "Entry uses displayed asks for purchases and excludes brokerage, taxes and slippage.",
                "NSE individual-stock options are physically settled; open ITM legs at expiry can create delivery or funding obligations.",
            ],
        }

    put_wings = []
    call_wings = []
    for row in rows:
        row_strike = float(row["strike_price"])
        if row_strike < strike:
            price, source = _execution_price(row.get("put"), "buy")
            delta = (row.get("put") or {}).get("delta")
            if price is not None:
                put_wings.append(
                    (abs(abs(float(delta or 0)) - 0.10), -row_strike, row_strike, price, source)
                )
        if row_strike > strike:
            price, source = _execution_price(row.get("call"), "buy")
            delta = (row.get("call") or {}).get("delta")
            if price is not None:
                call_wings.append(
                    (abs(abs(float(delta or 0)) - 0.10), row_strike, row_strike, price, source)
                )
    if not put_wings or not call_wings:
        return _empty_strategy(
            "The chain did not contain usable protective wings for a defined-risk "
            "short-volatility structure."
        )
    _, _, put_strike, put_price, put_source = min(put_wings)
    _, _, call_strike, call_price, call_source = min(call_wings)
    credit_per_unit = (
        float(atm["call_sell"]) + float(atm["put_sell"]) - float(put_price) - float(call_price)
    )
    maximum_loss_per_unit = max(
        strike - put_strike - credit_per_unit,
        call_strike - strike - credit_per_unit,
    )
    if credit_per_unit <= 0 or maximum_loss_per_unit <= 0:
        return _empty_strategy(
            "The displayed bid–ask prices did not produce a valid net credit and "
            "defined maximum loss."
        )
    capital_at_risk = maximum_loss_per_unit * lot_size

    def iron_butterfly_payoff(underlying_price: float) -> float:
        return (
            credit_per_unit
            - max(strike - underlying_price, 0)
            - max(underlying_price - strike, 0)
            + max(put_strike - underlying_price, 0)
            + max(underlying_price - call_strike, 0)
        )

    put_wing_predicted_iv = float(
        (comparison_by_label.get("10Δ put") or {}).get(
            "predicted_iv_percent",
            predicted_iv,
        )
    )
    call_wing_predicted_iv = float(
        (comparison_by_label.get("10Δ call") or {}).get(
            "predicted_iv_percent",
            predicted_iv,
        )
    )

    def iron_butterfly_next_session(underlying_price: float) -> float:
        future_put_wing = _black_scholes_price(
            "put",
            underlying_price,
            put_strike,
            next_session_years,
            put_wing_predicted_iv / 100,
        )
        future_atm_put = _black_scholes_price(
            "put",
            underlying_price,
            strike,
            next_session_years,
            predicted_iv / 100,
        )
        future_atm_call = _black_scholes_price(
            "call",
            underlying_price,
            strike,
            next_session_years,
            predicted_iv / 100,
        )
        future_call_wing = _black_scholes_price(
            "call",
            underlying_price,
            call_strike,
            next_session_years,
            call_wing_predicted_iv / 100,
        )
        return (
            float(atm["put_sell"])
            + float(atm["call_sell"])
            - float(put_price)
            - float(call_price)
            + future_put_wing
            - future_atm_put
            - future_atm_call
            + future_call_wing
        )

    return {
        "strategy_id": "short-iron-butterfly",
        "available": True,
        "signal": "short_volatility_defined_risk",
        "strategy_name": "Illustrative defined-risk short iron butterfly",
        "rationale": (
            f"Market ATM IV is {market_iv:.2f}% versus a {predicted_iv:.2f}% "
            f"forecast, a {abs(iv_gap):.2f}-point expected decline. The protective "
            "wings cap the expiry loss that an uncovered short straddle would leave open."
        ),
        "source_buckets": ["ATM"],
        "expiry": chain.get("selected_expiry"),
        "lot_size": lot_size,
        "underlying_value": round(spot, 2),
        "atm_market_iv_percent": round(market_iv, 2),
        "atm_predicted_iv_percent": round(predicted_iv, 2),
        "market_iv_percent": round(market_iv, 2),
        "predicted_iv_percent": round(predicted_iv, 2),
        "iv_difference_vol_points": round(iv_gap, 2),
        "legs": [
            _strategy_leg(
                action="buy",
                option_type="put",
                strike_price=put_strike,
                premium_per_unit=float(put_price),
                price_source=str(put_source),
            ),
            _strategy_leg(
                action="sell",
                option_type="put",
                strike_price=strike,
                premium_per_unit=float(atm["put_sell"]),
                price_source=str(atm["put_sell_source"]),
            ),
            _strategy_leg(
                action="sell",
                option_type="call",
                strike_price=strike,
                premium_per_unit=float(atm["call_sell"]),
                price_source=str(atm["call_sell_source"]),
            ),
            _strategy_leg(
                action="buy",
                option_type="call",
                strike_price=call_strike,
                premium_per_unit=float(call_price),
                price_source=str(call_source),
            ),
        ],
        "entry_premium_type": "credit",
        "entry_premium_per_unit": round(credit_per_unit, 2),
        "entry_cash_flow_per_lot": round(credit_per_unit * lot_size, 2),
        "capital_at_risk_per_lot": round(capital_at_risk, 2),
        "maximum_profit_per_lot": round(credit_per_unit * lot_size, 2),
        "maximum_loss_per_lot": round(capital_at_risk, 2),
        "lower_break_even": round(strike - credit_per_unit, 2),
        "upper_break_even": round(strike + credit_per_unit, 2),
        "payoff_points": _payoff_points(
            lower_price=max(0.01, put_strike - spot * 0.08),
            upper_price=call_strike + spot * 0.08,
            lot_size=lot_size,
            capital_at_risk_per_lot=capital_at_risk,
            payoff_per_unit=iron_butterfly_payoff,
            next_session_payoff_per_unit=iron_butterfly_next_session,
        ),
        "payoff_horizon": "Next session at predicted IV and at option expiry",
        "limitations": [
            "The next-session line is a Black-Scholes mark-to-model scenario using predicted bucket IVs, not a guaranteed executable value.",
            "The expiry line does not model early exit, changing skew or broker margin changes.",
            "Entry uses displayed bids for sales and asks for purchases, excluding costs and slippage.",
            "NSE individual-stock options are physically settled; open ITM legs at expiry can create delivery or funding obligations.",
        ],
    }


def _comparison_strength(comparison: dict[str, Any]) -> float:
    return abs(float(comparison.get("difference_vol_points") or 0)) / max(
        float(comparison.get("material_threshold_vol_points") or 0.01),
        0.01,
    )


def _row_at_strike(chain: dict[str, Any], strike: float) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in chain.get("strikes") or []
            if math.isclose(float(row.get("strike_price") or 0), strike, abs_tol=0.01)
        ),
        None,
    )


def _option_leg_spec(
    row: dict[str, Any] | None,
    option_type: str,
    action: str,
    predicted_iv: float,
) -> dict[str, Any] | None:
    if row is None:
        return None
    price, source = _execution_price(row.get(option_type), action)
    if price is None or source is None:
        return None
    return {
        "action": action,
        "option_type": option_type,
        "strike_price": float(row["strike_price"]),
        "premium_per_unit": float(price),
        "price_source": source,
        "predicted_iv_percent": float(predicted_iv),
    }


def _generic_option_strategy(
    *,
    strategy_id: str,
    strategy_name: str,
    signal: str,
    rationale: str,
    source_buckets: list[str],
    chain: dict[str, Any],
    lot_size: int,
    leg_specs: list[dict[str, Any]],
    expected_premium_type: str,
    maximum_loss_per_unit: float,
    maximum_profit_per_unit: float | None,
    lower_break_even: float | None,
    upper_break_even: float | None,
    reference_market_iv: float,
    reference_predicted_iv: float,
    rank_score: float,
    scenario_span_fraction: float = 0.16,
) -> dict[str, Any] | None:
    spot = float(chain.get("underlying_value") or 0)
    if spot <= 0 or lot_size <= 0 or not leg_specs or maximum_loss_per_unit <= 0:
        return None
    net_debit = sum(
        float(leg["premium_per_unit"]) * (1 if leg["action"] == "buy" else -1) for leg in leg_specs
    )
    premium_type = "debit" if net_debit > 0 else "credit"
    if premium_type != expected_premium_type or math.isclose(net_debit, 0, abs_tol=0.01):
        return None
    entry_premium = abs(net_debit)
    capital_at_risk = maximum_loss_per_unit * lot_size

    try:
        expiry_date = datetime.strptime(
            str(chain.get("selected_expiry")),
            "%d-%b-%Y",
        ).date()
        exchange_timestamp = chain.get("exchange_timestamp")
        as_of = (
            datetime.strptime(exchange_timestamp, "%d-%b-%Y %H:%M:%S").date()
            if exchange_timestamp
            else datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )
        next_session_years = max(1, (expiry_date - as_of).days - 1) / 365.25
    except ValueError:
        next_session_years = 1 / 365.25

    def expiry_payoff(underlying_price: float) -> float:
        total = 0.0
        for leg in leg_specs:
            strike = float(leg["strike_price"])
            intrinsic = (
                max(underlying_price - strike, 0)
                if leg["option_type"] == "call"
                else max(strike - underlying_price, 0)
            )
            entry_price = float(leg["premium_per_unit"])
            total += intrinsic - entry_price if leg["action"] == "buy" else entry_price - intrinsic
        return total

    def next_session_payoff(underlying_price: float) -> float:
        total = 0.0
        for leg in leg_specs:
            modeled_price = _black_scholes_price(
                str(leg["option_type"]),
                underlying_price,
                float(leg["strike_price"]),
                next_session_years,
                float(leg["predicted_iv_percent"]) / 100,
            )
            entry_price = float(leg["premium_per_unit"])
            total += (
                modeled_price - entry_price
                if leg["action"] == "buy"
                else entry_price - modeled_price
            )
        return total

    strikes = [float(leg["strike_price"]) for leg in leg_specs]
    scenario_padding = max(spot * scenario_span_fraction, entry_premium * 2)
    return {
        "strategy_id": strategy_id,
        "available": True,
        "signal": signal,
        "strategy_name": strategy_name,
        "rationale": rationale,
        "source_buckets": source_buckets,
        "expiry": chain.get("selected_expiry"),
        "lot_size": lot_size,
        "underlying_value": round(spot, 2),
        "atm_market_iv_percent": None,
        "atm_predicted_iv_percent": None,
        "market_iv_percent": round(reference_market_iv, 2),
        "predicted_iv_percent": round(reference_predicted_iv, 2),
        "iv_difference_vol_points": round(
            reference_predicted_iv - reference_market_iv,
            2,
        ),
        "legs": [
            _strategy_leg(
                action=str(leg["action"]),
                option_type=str(leg["option_type"]),
                strike_price=float(leg["strike_price"]),
                premium_per_unit=float(leg["premium_per_unit"]),
                price_source=str(leg["price_source"]),
            )
            for leg in leg_specs
        ],
        "entry_premium_type": premium_type,
        "entry_premium_per_unit": round(entry_premium, 2),
        "entry_cash_flow_per_lot": round(entry_premium * lot_size, 2),
        "capital_at_risk_per_lot": round(capital_at_risk, 2),
        "maximum_profit_per_lot": (
            round(maximum_profit_per_unit * lot_size, 2)
            if maximum_profit_per_unit is not None
            else None
        ),
        "maximum_loss_per_lot": round(capital_at_risk, 2),
        "lower_break_even": (round(lower_break_even, 2) if lower_break_even is not None else None),
        "upper_break_even": (round(upper_break_even, 2) if upper_break_even is not None else None),
        "payoff_points": _payoff_points(
            lower_price=max(0.01, min(strikes) - scenario_padding),
            upper_price=max(strikes) + scenario_padding,
            lot_size=lot_size,
            capital_at_risk_per_lot=capital_at_risk,
            payoff_per_unit=expiry_payoff,
            next_session_payoff_per_unit=next_session_payoff,
        ),
        "payoff_horizon": "Next session at predicted IV and at option expiry",
        "limitations": [
            "The next-session line is a Black-Scholes mark-to-model scenario, not a guaranteed executable value.",
            "The structure is generated from displayed bids and asks and excludes brokerage, taxes and slippage.",
            "The signal is statistical; skew, theta and the underlying price can change before the forecast is realized.",
            "NSE individual-stock options are physically settled, so open ITM legs at expiry can create delivery or funding obligations.",
        ],
        "_rank_score": rank_score,
    }


def _build_long_strangles(
    chain: dict[str, Any],
    comparisons: list[dict[str, Any]],
    lot_size: int,
) -> list[dict[str, Any]]:
    by_label = {str(item["label"]): item for item in comparisons}
    strategies: list[dict[str, Any]] = []
    for delta_label, slug in (("25Δ", "25d"), ("10Δ", "10d")):
        put = by_label.get(f"{delta_label} put")
        call = by_label.get(f"{delta_label} call")
        if not put or not call or put["status"] != "cheap" or call["status"] != "cheap":
            continue
        put_row = _row_at_strike(chain, float(put["strike_price"]))
        call_row = _row_at_strike(chain, float(call["strike_price"]))
        put_leg = _option_leg_spec(
            put_row,
            "put",
            "buy",
            float(put["predicted_iv_percent"]),
        )
        call_leg = _option_leg_spec(
            call_row,
            "call",
            "buy",
            float(call["predicted_iv_percent"]),
        )
        spot = float(chain.get("underlying_value") or 0)
        if (
            put_leg is None
            or call_leg is None
            or not float(put["strike_price"]) < spot < float(call["strike_price"])
        ):
            continue
        debit = float(put_leg["premium_per_unit"]) + float(call_leg["premium_per_unit"])
        market_iv = float(np.mean([put["market_iv_percent"], call["market_iv_percent"]]))
        predicted_iv = float(np.mean([put["predicted_iv_percent"], call["predicted_iv_percent"]]))
        strategy = _generic_option_strategy(
            strategy_id=f"long-{slug}-strangle",
            strategy_name=f"Illustrative long {delta_label} strangle",
            signal="long_volatility",
            rationale=(
                f"Both OTM wings look cheap beyond their model-error bands: the "
                f"{delta_label} put is {abs(float(put['difference_vol_points'])):.2f} "
                f"volatility points below forecast and the {delta_label} call is "
                f"{abs(float(call['difference_vol_points'])):.2f} points below. Buying "
                f"the ₹{float(put['strike_price']):,.0f} put and "
                f"₹{float(call['strike_price']):,.0f} call expresses that OTM "
                "mispricing without requiring an ATM option."
            ),
            source_buckets=[f"{delta_label} put", f"{delta_label} call"],
            chain=chain,
            lot_size=lot_size,
            leg_specs=[put_leg, call_leg],
            expected_premium_type="debit",
            maximum_loss_per_unit=debit,
            maximum_profit_per_unit=None,
            lower_break_even=float(put["strike_price"]) - debit,
            upper_break_even=float(call["strike_price"]) + debit,
            reference_market_iv=market_iv,
            reference_predicted_iv=predicted_iv,
            rank_score=float(np.mean([_comparison_strength(put), _comparison_strength(call)])),
            scenario_span_fraction=0.22,
        )
        if strategy is not None:
            strategies.append(strategy)
    return strategies


def _build_iron_condor(
    chain: dict[str, Any],
    comparisons: list[dict[str, Any]],
    lot_size: int,
) -> dict[str, Any] | None:
    by_label = {str(item["label"]): item for item in comparisons}
    short_put = by_label.get("25Δ put")
    short_call = by_label.get("25Δ call")
    long_put = by_label.get("10Δ put")
    long_call = by_label.get("10Δ call")
    if (
        not short_put
        or not short_call
        or not long_put
        or not long_call
        or short_put["status"] != "expensive"
        or short_call["status"] != "expensive"
    ):
        return None
    strikes = [
        float(long_put["strike_price"]),
        float(short_put["strike_price"]),
        float(short_call["strike_price"]),
        float(long_call["strike_price"]),
    ]
    if not strikes[0] < strikes[1] < strikes[2] < strikes[3]:
        return None
    specs = [
        _option_leg_spec(
            _row_at_strike(chain, strikes[0]),
            "put",
            "buy",
            float(long_put["predicted_iv_percent"]),
        ),
        _option_leg_spec(
            _row_at_strike(chain, strikes[1]),
            "put",
            "sell",
            float(short_put["predicted_iv_percent"]),
        ),
        _option_leg_spec(
            _row_at_strike(chain, strikes[2]),
            "call",
            "sell",
            float(short_call["predicted_iv_percent"]),
        ),
        _option_leg_spec(
            _row_at_strike(chain, strikes[3]),
            "call",
            "buy",
            float(long_call["predicted_iv_percent"]),
        ),
    ]
    if any(spec is None for spec in specs):
        return None
    valid_specs = [spec for spec in specs if spec is not None]
    credit = -sum(
        float(spec["premium_per_unit"]) * (1 if spec["action"] == "buy" else -1)
        for spec in valid_specs
    )
    maximum_loss = max(strikes[1] - strikes[0], strikes[3] - strikes[2]) - credit
    if credit <= 0 or maximum_loss <= 0:
        return None
    market_iv = float(np.mean([short_put["market_iv_percent"], short_call["market_iv_percent"]]))
    predicted_iv = float(
        np.mean([short_put["predicted_iv_percent"], short_call["predicted_iv_percent"]])
    )
    return _generic_option_strategy(
        strategy_id="short-25d-iron-condor",
        strategy_name="Illustrative defined-risk 25Δ iron condor",
        signal="short_volatility_defined_risk",
        rationale=(
            "Both 25Δ OTM options look expensive beyond their model-error bands. "
            f"Sell the ₹{strikes[1]:,.0f} put and ₹{strikes[2]:,.0f} call, while "
            f"buying the farther ₹{strikes[0]:,.0f} put and ₹{strikes[3]:,.0f} "
            "call to cap both tail losses."
        ),
        source_buckets=["25Δ put", "25Δ call"],
        chain=chain,
        lot_size=lot_size,
        leg_specs=valid_specs,
        expected_premium_type="credit",
        maximum_loss_per_unit=maximum_loss,
        maximum_profit_per_unit=credit,
        lower_break_even=strikes[1] - credit,
        upper_break_even=strikes[2] + credit,
        reference_market_iv=market_iv,
        reference_predicted_iv=predicted_iv,
        rank_score=float(
            np.mean([_comparison_strength(short_put), _comparison_strength(short_call)])
        ),
    )


def _further_otm_row(
    chain: dict[str, Any],
    comparison: dict[str, Any],
    comparisons: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, float]:
    side = str(comparison["side"])
    strike = float(comparison["strike_price"])
    same_side = [
        item
        for item in comparisons
        if item.get("side") == side
        and (
            float(item["strike_price"]) < strike
            if side == "put"
            else float(item["strike_price"]) > strike
        )
    ]
    if same_side:
        preferred = min(
            same_side,
            key=lambda item: abs(float(item["strike_price"]) - strike),
        )
        return (
            _row_at_strike(chain, float(preferred["strike_price"])),
            float(preferred["predicted_iv_percent"]),
        )
    candidates = [
        row
        for row in chain.get("strikes") or []
        if row.get(side)
        and (
            float(row["strike_price"]) < strike
            if side == "put"
            else float(row["strike_price"]) > strike
        )
    ]
    if not candidates:
        return None, float(comparison["predicted_iv_percent"])
    return (
        min(candidates, key=lambda row: abs(float(row["strike_price"]) - strike)),
        float(comparison["predicted_iv_percent"]),
    )


def _build_otm_verticals(
    chain: dict[str, Any],
    comparisons: list[dict[str, Any]],
    lot_size: int,
) -> list[dict[str, Any]]:
    strategies: list[dict[str, Any]] = []
    for comparison in comparisons:
        side = str(comparison.get("side"))
        status = str(comparison.get("status"))
        if side not in {"call", "put"} or status not in {"cheap", "expensive"}:
            continue
        strike = float(comparison["strike_price"])
        signal_row = _row_at_strike(chain, strike)
        wing_row, wing_predicted_iv = _further_otm_row(chain, comparison, comparisons)
        signal_action = "buy" if status == "cheap" else "sell"
        wing_action = "sell" if status == "cheap" else "buy"
        signal_leg = _option_leg_spec(
            signal_row,
            side,
            signal_action,
            float(comparison["predicted_iv_percent"]),
        )
        wing_leg = _option_leg_spec(
            wing_row,
            side,
            wing_action,
            wing_predicted_iv,
        )
        if signal_leg is None or wing_leg is None:
            continue
        wing_strike = float(wing_leg["strike_price"])
        width = abs(strike - wing_strike)
        net_debit = sum(
            float(leg["premium_per_unit"]) * (1 if leg["action"] == "buy" else -1)
            for leg in (signal_leg, wing_leg)
        )
        expected_type = "debit" if status == "cheap" else "credit"
        entry_premium = abs(net_debit)
        if width <= 0 or entry_premium <= 0 or entry_premium >= width:
            continue
        if expected_type == "debit" and net_debit <= 0:
            continue
        if expected_type == "credit" and net_debit >= 0:
            continue
        maximum_loss = entry_premium if expected_type == "debit" else width - entry_premium
        maximum_profit = width - entry_premium if expected_type == "debit" else entry_premium
        break_even = strike - entry_premium if side == "put" else strike + entry_premium
        if side == "call" and status == "cheap":
            name = "Illustrative bull call debit spread"
            view = "a bullish, defined-risk expression of the cheap OTM call"
        elif side == "call":
            name = "Illustrative bear call credit spread"
            view = "a bearish, defined-risk expression of the expensive OTM call"
        elif status == "cheap":
            name = "Illustrative bear put debit spread"
            view = "a bearish, defined-risk expression of the cheap OTM put"
        else:
            name = "Illustrative bull put credit spread"
            view = "a bullish, defined-risk expression of the expensive OTM put"
        label = str(comparison["label"])
        slug = label.lower().replace("δ", "d").replace(" ", "-")
        gap = abs(float(comparison["difference_vol_points"]))
        threshold = float(comparison["material_threshold_vol_points"])
        strategy = _generic_option_strategy(
            strategy_id=f"{slug}-{expected_type}-spread",
            strategy_name=name,
            signal="directional_defined_risk",
            rationale=(
                f"The {label} market IV is {float(comparison['market_iv_percent']):.2f}% "
                f"versus {float(comparison['predicted_iv_percent']):.2f}% forecast, "
                f"a {gap:.2f}-point {status} gap that exceeds the {threshold:.2f}-point "
                f"error threshold. This spread is {view}; the farther OTM leg caps "
                "risk but also adds directional exposure."
            ),
            source_buckets=[label],
            chain=chain,
            lot_size=lot_size,
            leg_specs=[signal_leg, wing_leg],
            expected_premium_type=expected_type,
            maximum_loss_per_unit=maximum_loss,
            maximum_profit_per_unit=maximum_profit,
            lower_break_even=break_even if side == "put" else None,
            upper_break_even=break_even if side == "call" else None,
            reference_market_iv=float(comparison["market_iv_percent"]),
            reference_predicted_iv=float(comparison["predicted_iv_percent"]),
            rank_score=_comparison_strength(comparison),
        )
        if strategy is not None:
            strategies.append(strategy)
    return strategies


def build_iv_strategies(
    chain: dict[str, Any],
    comparisons: list[dict[str, Any]],
    lot_size: int | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build and rank ATM, wing, paired-wing and directional IV structures."""

    atm_strategy = build_iv_strategy(chain, comparisons, lot_size)
    if not lot_size or lot_size <= 0:
        return atm_strategy, []
    strategies: list[dict[str, Any]] = []
    if atm_strategy.get("available"):
        atm_comparison = next(
            (item for item in comparisons if item.get("label") == "ATM"),
            {},
        )
        atm_strategy["_rank_score"] = _comparison_strength(atm_comparison)
        strategies.append(atm_strategy)
    strategies.extend(_build_long_strangles(chain, comparisons, lot_size))
    iron_condor = _build_iron_condor(chain, comparisons, lot_size)
    if iron_condor is not None:
        strategies.append(iron_condor)
    strategies.extend(_build_otm_verticals(chain, comparisons, lot_size))

    unique: dict[str, dict[str, Any]] = {}
    for strategy in strategies:
        strategy_id = str(strategy.get("strategy_id") or "")
        if strategy_id and strategy_id not in unique:
            unique[strategy_id] = strategy
    ranked = sorted(
        unique.values(),
        key=lambda item: float(item.get("_rank_score") or 0),
        reverse=True,
    )[:6]
    for strategy in ranked:
        strategy.pop("_rank_score", None)
    return (ranked[0] if ranked else atm_strategy), ranked


def _interpolate_tenor(surface: np.ndarray, days_to_expiry: float) -> np.ndarray:
    return np.asarray(
        [
            np.interp(days_to_expiry, TENOR_DAYS, surface[:, bucket])
            for bucket in range(surface.shape[1])
        ]
    )


def _next_weekday(value: date) -> date:
    result = value + timedelta(days=1)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def compare_forecast_to_market(
    *,
    ticker: str,
    symbol: str,
    chain: dict,
    history_dates: list[str],
    history_surfaces: np.ndarray,
    lot_size: int | None = None,
) -> dict[str, Any]:
    if len(history_surfaces) < MINIMUM_HISTORY_SURFACES:
        return _unavailable_forecast(
            ticker,
            symbol,
            chain.get("selected_expiry"),
            (
                f"Only {len(history_surfaces)} complete historical surfaces were available; "
                f"the model requires at least {MINIMUM_HISTORY_SURFACES}."
            ),
            observations=len(history_surfaces),
        )
    selected_expiry = chain.get("selected_expiry")
    exchange_timestamp = chain.get("exchange_timestamp")
    if not selected_expiry:
        return _unavailable_forecast(
            ticker,
            symbol,
            None,
            "No listed NSE option expiry is available for this stock.",
        )
    try:
        expiry_date = datetime.strptime(selected_expiry, "%d-%b-%Y").date()
        as_of = (
            datetime.strptime(exchange_timestamp, "%d-%b-%Y %H:%M:%S").date()
            if exchange_timestamp
            else datetime.now(ZoneInfo("Asia/Kolkata")).date()
        )
    except ValueError:
        return _unavailable_forecast(
            ticker,
            symbol,
            selected_expiry,
            "The exchange expiry or timestamp could not be interpreted.",
        )
    days_to_expiry = max(1, (expiry_date - as_of).days)
    model = fit_fpca_var(history_surfaces)
    predicted = _interpolate_tenor(model["forecast_surface"], days_to_expiry)
    errors = _interpolate_tenor(model["rmse_surface"], days_to_expiry)
    market_points = _market_bucket_points(chain)
    market_by_label = {point["label"]: point for point in market_points}

    comparisons = []
    for index, (label, _, _) in enumerate(DELTA_BUCKETS):
        market = market_by_label.get(label)
        if market is None:
            continue
        forecast_iv = float(predicted[index])
        market_iv = float(market["market_iv_percent"])
        gap = market_iv - forecast_iv
        model_error = float(errors[index])
        material_threshold = max(2.0, 1.5 * model_error)
        if gap > material_threshold:
            status = "expensive"
            explanation = f"Market IV is {gap:.1f} volatility points above the model forecast."
        elif gap < -material_threshold:
            status = "cheap"
            explanation = f"Market IV is {abs(gap):.1f} volatility points below the model forecast."
        else:
            status = "in_line"
            explanation = (
                f"The {abs(gap):.2f}-point gap does not exceed the required "
                f"{material_threshold:.2f} points: max(2.00, 1.5 × the "
                f"{model_error:.2f}-point forecast error)."
            )
        comparisons.append(
            {
                **market,
                "predicted_iv_percent": round(forecast_iv, 2),
                "difference_vol_points": round(gap, 2),
                "model_error_vol_points": round(model_error, 2),
                "material_threshold_vol_points": round(material_threshold, 2),
                "status": status,
                "explanation": explanation,
            }
        )

    dislocations = [item for item in comparisons if item["status"] in {"cheap", "expensive"}]
    if dislocations:
        strongest = max(
            dislocations,
            key=lambda item: (
                abs(item["difference_vol_points"])
                / max(item["material_threshold_vol_points"], 0.01)
            ),
        )
        overall_status = strongest["status"]
        summary = (
            f"{strongest['label']} options look {strongest['status']} versus the "
            f"model: market IV {strongest['market_iv_percent']:.1f}% compared with "
            f"{strongest['predicted_iv_percent']:.1f}% predicted for the next session."
        )
    else:
        overall_status = "in_line"
        summary = (
            "No material IV dislocation was detected: the observed gaps are inside "
            "the model-error bands."
        )

    primary_strategy, strategies = build_iv_strategies(
        chain,
        comparisons,
        lot_size,
    )
    latest_history = date.fromisoformat(history_dates[-1])
    return {
        "ticker": ticker,
        "symbol": symbol,
        "available": bool(comparisons),
        "selected_expiry": selected_expiry,
        "days_to_expiry": days_to_expiry,
        "forecast_for_date": _next_weekday(latest_history).isoformat(),
        "model": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "observations": len(history_surfaces),
        "fit_start": history_dates[0],
        "fit_end": history_dates[-1],
        "principal_components": model["component_count"],
        "explained_variance_percent": round(model["explained_variance_percent"], 2),
        "validation_sessions": model["validation_sessions"],
        "validation_rmse_by_components": model["validation_rmse_by_components"],
        "fourth_component_improvement_percent": model["fourth_component_improvement_percent"],
        "component_selection_note": model["component_selection_note"],
        "tenor_grid_days": TENOR_DAYS.astype(int).tolist(),
        "comparisons": comparisons,
        "strategy": primary_strategy,
        "strategies": strategies,
        "overall_status": overall_status,
        "summary": summary,
        "method_note": (
            "This predicts the next-session option-market IV surface. It does not "
            "predict realized volatility or prove an arbitrage."
        ),
        "adaptation_note": (
            "The paper's 15 FX expiries are adapted to 14, 30, 60 and 90 days because "
            "NSE stock options list a smaller rolling expiry set."
        ),
        "source": "NSE India daily F&O bhavcopies and current option chain",
        "source_url": chain.get("source_url")
        or f"https://www.nseindia.com/option-chain?symbol={symbol}",
        "paper_url": PAPER_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "limitation": (
            None
            if comparisons
            else "The selected expiry did not contain enough usable delta-bucket IVs."
        ),
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
        "observations": observations,
        "validation_sessions": 0,
        "validation_rmse_by_components": {},
        "fourth_component_improvement_percent": None,
        "component_selection_note": (
            "Adaptive 3-8 component selection could not be evaluated."
        ),
        "comparisons": [],
        "strategy": _empty_strategy(
            "The IV forecast is unavailable, so no option structure was generated."
        ),
        "strategies": [],
        "overall_status": "unavailable",
        "summary": "The IV-surface forecast is not available for this selection.",
        "method_note": (
            "FPCA forecasts the next-session option-market IV surface, not realized volatility."
        ),
        "adaptation_note": (
            "NSE stock-option tenors use a smaller rolling grid than the FX surface in the paper."
        ),
        "source": "NSE India daily F&O bhavcopies and current option chain",
        "source_url": f"https://www.nseindia.com/option-chain?symbol={symbol}",
        "paper_url": PAPER_URL,
        "generated_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "is_carried_forward": False,
        "refresh_limitation": None,
        "limitation": limitation,
    }


def _forecast_archive_key(symbol: str, expiry: str | None) -> str:
    return cache_key(MODEL_VERSION, symbol.upper(), str(expiry or ""))


def _archive_successful_forecast(result: dict[str, Any]) -> None:
    """Persist a published forecast through its option expiry."""

    expiry = str(result.get("selected_expiry") or "")
    symbol = str(result.get("symbol") or "")
    if not result.get("available") or not expiry or not symbol:
        return
    archive = FileCache(get_settings().cache_path, "iv_forecast_history")
    payload = dict(result)
    payload["is_carried_forward"] = False
    payload["refresh_limitation"] = None
    archive.put(
        _forecast_archive_key(symbol, expiry),
        payload,
        source=str(result.get("source") or "NSE India option data"),
        model_name=MODEL_NAME,
    )


def _load_carried_forward_forecast(
    symbol: str,
    expiry: str | None,
    refresh_limitation: str,
) -> dict[str, Any] | None:
    """Return the last published forecast when a new calculation cannot finish."""

    if not expiry:
        return None
    try:
        expiry_date = datetime.strptime(expiry, "%d-%b-%Y").date()
    except ValueError:
        return None
    if expiry_date < datetime.now(ZoneInfo("Asia/Kolkata")).date():
        return None
    archive = FileCache(get_settings().cache_path, "iv_forecast_history")
    cached = archive.get(_forecast_archive_key(symbol, expiry), None)
    if not isinstance(cached, dict) or not cached.get("available"):
        return None
    result = dict(cached)
    result["is_carried_forward"] = True
    result["refresh_limitation"] = refresh_limitation
    result["limitation"] = (
        "The latest refresh could not be completed. This is the last successfully "
        "published forecast retained for follow-through; its market IV, premiums and "
        "next-session horizon are from the original publication time."
    )
    return result


async def get_iv_surface_forecast(
    ticker: str,
    symbol: str,
    expiry: str | None = None,
) -> dict[str, Any]:
    from app.services.market_data.india_trading import get_options_chain

    chain = await get_options_chain(ticker, symbol, expiry)
    if not chain.get("available"):
        limitation = chain.get("limitation") or "No current NSE option chain is available."
        carried_forward = _load_carried_forward_forecast(
            symbol,
            expiry,
            limitation,
        )
        if carried_forward is not None:
            return carried_forward
        return _unavailable_forecast(
            ticker,
            symbol,
            expiry,
            limitation,
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
    history_observations = 0
    try:
        (dates, surfaces), lot_size = await asyncio.gather(
            load_historical_surfaces(symbol),
            get_fno_lot_size(symbol, chain.get("selected_expiry")),
        )
        history_observations = len(surfaces)
        result = await asyncio.to_thread(
            compare_forecast_to_market,
            ticker=ticker,
            symbol=symbol,
            chain=chain,
            history_dates=dates,
            history_surfaces=surfaces,
            lot_size=lot_size,
        )
        result["is_carried_forward"] = False
        result["refresh_limitation"] = None
        _archive_successful_forecast(result)
    except Exception as exc:
        logger.exception("FPCA IV-surface forecast failed for %s", symbol)
        refresh_limitation = (
            f"The historical IV-surface model could not be fitted: {exc}"
        )
        result = _load_carried_forward_forecast(
            symbol,
            chain.get("selected_expiry"),
            refresh_limitation,
        ) or _unavailable_forecast(
            ticker,
            symbol,
            chain.get("selected_expiry"),
            refresh_limitation,
            observations=history_observations,
        )
    cache.put(
        key,
        result,
        source=result["source"],
        model_name=MODEL_NAME,
    )
    return result
