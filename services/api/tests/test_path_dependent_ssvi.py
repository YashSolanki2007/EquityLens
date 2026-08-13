from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.schemas.trading import IVSurfaceForecastOut
from app.services.market_data.path_dependent_ssvi import (
    MINIMUM_PARAMETER_SURFACES,
    calibrate_parsimonious_ssvi,
    fit_path_dependent_ssvi,
    parsimonious_ssvi_total_variance,
    path_features,
    ssvi_surface_from_parameters,
    static_arbitrage_checks,
)


def _prices(count: int = 1_250) -> pd.Series:
    dates = pd.bdate_range("2021-01-01", periods=count)
    returns = 0.00025 + 0.008 * np.sin(np.arange(count) / 17.0)
    return pd.Series(100 * np.exp(np.cumsum(returns)), index=dates)


def _history(count: int = 38):
    prices = _prices()
    dates = [item.date().isoformat() for item in prices.index[-count:]]
    surfaces = []
    for index in range(count):
        parameters = np.asarray(
            [
                0.045 + 0.004 * np.sin(index / 6),
                0.92 + 0.05 * np.cos(index / 8),
                -0.45 + 0.04 * np.sin(index / 7),
                0.82 + 0.03 * np.cos(index / 9),
            ]
        )
        surfaces.append(ssvi_surface_from_parameters(parameters))
    return dates, np.asarray(surfaces), prices


def test_parsimonious_ssvi_calibration_recovers_a_valid_surface():
    parameters = np.asarray([0.052, 0.95, -0.42, 0.86])
    surface = ssvi_surface_from_parameters(parameters)

    result = calibrate_parsimonious_ssvi(surface)

    assert result["success"]
    assert result["calibration_rmse"] < 0.15
    assert static_arbitrage_checks(result["parameters"])["passed"]
    assert np.isfinite(result["fitted_surface"]).all()


def test_ssvi_total_variance_is_positive_and_calendar_monotone_at_atm():
    parameters = np.asarray([0.05, 0.9, -0.4, 0.8])
    maturities = np.asarray([14, 30, 60, 90, 180]) / 365.25

    variance = parsimonious_ssvi_total_variance(0.0, maturities, parameters)

    assert np.all(variance > 0)
    assert np.all(np.diff(variance) > 0)


def test_path_features_exclude_the_unknown_target_return():
    prices = _prices()
    source_date = prices.index[-2].date()
    original = path_features(prices, source_date, "a", next_session=True)
    changed_future = prices.copy()
    changed_future.iloc[-1] *= 2.0

    after_future_change = path_features(
        changed_future,
        source_date,
        "a",
        next_session=True,
    )

    assert original == after_future_change


def test_path_dependent_fit_returns_causal_validation_and_arbitrage_checks():
    dates, surfaces, prices = _history(MINIMUM_PARAMETER_SURFACES + 5)

    result = fit_path_dependent_ssvi(
        surfaces,
        dates,
        prices,
        validation_start=MINIMUM_PARAMETER_SURFACES,
    )

    assert result["forecast_surface"].shape == (4, 5)
    assert result["rmse_surface"].shape == (4, 5)
    assert result["validation_sessions"] == 5
    assert np.isfinite(result["validation_model_rmse"])
    assert np.isfinite(result["validation_baseline_rmse"])
    assert result["arbitrage_checks"]["passed"]


def test_path_dependent_response_schema_accepts_model_metadata():
    raw = {
        "ticker": "TEST",
        "symbol": "TEST",
        "available": False,
        "selected_expiry": None,
        "model": "Path SSVI",
        "model_version": "test",
        "model_family": "path_dependent_ssvi",
        "observations": 0,
        "validation_sessions": 0,
        "validation_rmse_by_components": {},
        "fourth_component_improvement_percent": None,
        "component_selection_note": "test",
        "comparisons": [],
        "strategy": {
            "available": False,
            "signal": "no_trade",
            "strategy_name": "No trade",
            "rationale": "test",
        },
        "strategies": [],
        "overall_status": "unavailable",
        "summary": "test",
        "method_note": "test",
        "adaptation_note": "test",
        "source": "test",
        "source_url": "https://example.com",
        "paper_url": "https://arxiv.org/abs/2312.15950",
        "generated_at": "2026-08-13T00:00:00Z",
        "is_delayed_or_unverified": True,
    }

    parsed = IVSurfaceForecastOut.model_validate(raw)

    assert parsed.model_family == "path_dependent_ssvi"
