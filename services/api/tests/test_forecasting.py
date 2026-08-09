"""Deterministic coverage for ARIMA-GARCH and multiple-regression forecasts."""

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np

from app.schemas.trading import PriceForecastOut
from app.services.market_data import forecasting
from app.services.market_data.forecasting import (
    build_arima_garch_forecast,
    build_multiple_regression_forecast,
)


def _synthetic_history(observations: int = 420) -> dict:
    rng = np.random.default_rng(41)
    returns = np.empty(observations - 1)
    variance = 0.00012
    shock = 0.0
    for index in range(observations - 1):
        variance = 0.000004 + 0.08 * shock**2 + 0.88 * variance
        shock = np.sqrt(variance) * rng.standard_t(8) / np.sqrt(8 / 6)
        returns[index] = 0.00035 + 0.12 * (returns[index - 1] if index else 0) + shock
    prices = 100 * np.exp(np.r_[0.0, np.cumsum(returns)])
    start = date(2024, 1, 2)
    candles = [
        {
            "time": (start + timedelta(days=index)).isoformat(),
            "open": float(price * (1 - 0.001)),
            "high": float(price * (1.006 + 0.001 * np.sin(index / 5))),
            "low": float(price * (0.994 - 0.001 * np.cos(index / 7))),
            "close": float(price),
            "volume": float(
                100_000
                * (1 + 0.25 * np.sin(index / 11))
                * (1 + abs(returns[index - 1]) * 12 if index else 1)
            ),
        }
        for index, price in enumerate(prices)
    ]
    return {
        "ticker": "TEST",
        "market_data_ticker": "TEST.NS",
        "currency": "INR",
        "candles": candles,
        "source": "synthetic",
        "source_url": "https://example.com/history",
    }


def test_arima_garch_forecast_has_ordered_bands_and_dynamic_volatility():
    result = build_arima_garch_forecast(_synthetic_history(), horizon_days=15, simulations=500)
    parsed = PriceForecastOut.model_validate(result)

    assert parsed.available is True
    assert len(parsed.points) == 15
    assert len(parsed.sample_paths) == 12
    assert all(len(path.points) == 15 for path in parsed.sample_paths)
    assert 0 <= parsed.probability_finish_above_last <= 1
    assert all(
        point.p05 <= point.p10 <= point.p25 <= point.median <= point.p75 <= point.p90 <= point.p95
        for point in parsed.points
    )
    assert len({point.annualized_volatility_percent for point in parsed.points}) > 1
    assert parsed.regression_available is True
    assert len(parsed.regression_points) == 15
    assert parsed.regression_observations >= 60
    assert parsed.regression_validation_mae_percent is not None
    assert set(parsed.regression_standardized_coefficients) == {
        "intercept",
        "price_momentum",
        "relative_volume",
        "price_vs_vwap",
    }


def test_arima_garch_simulation_is_reproducible_for_same_data_and_controls():
    history = _synthetic_history()
    first = build_arima_garch_forecast(history, horizon_days=15, simulations=500)
    second = build_arima_garch_forecast(history, horizon_days=15, simulations=500)

    assert first["points"] == second["points"]
    assert first["sample_paths"] == second["sample_paths"]
    assert first["regression_points"] == second["regression_points"]


def test_multiple_regression_uses_direct_horizon_price_volume_and_vwap_features():
    result = build_multiple_regression_forecast(
        _synthetic_history(),
        horizon_days=15,
    )

    assert result["regression_available"] is True
    assert len(result["regression_points"]) == 15
    assert result["regression_terminal_price"] > 0
    assert result["regression_latest_features"]["latest_volume"] > 0
    assert "price_vs_20d_vwap_percent" in result["regression_latest_features"]
    assert "relative_volume" in result["regression_standardized_coefficients"]


def test_forecast_explicitly_rejects_short_listing_history():
    result = build_arima_garch_forecast(_synthetic_history(60), horizon_days=15, simulations=500)
    parsed = PriceForecastOut.model_validate(result)

    assert parsed.available is False
    assert parsed.points == []
    assert "100 valid daily closes" in parsed.limitations[0]


async def test_price_forecast_service_writes_and_reuses_cache(monkeypatch, tmp_path):
    history = _synthetic_history(120)
    build_calls = 0

    async def fake_history(ticker: str, market_data_ticker: str, range: str) -> dict:
        assert (ticker, market_data_ticker, range) == ("TEST", "TEST.NS", "5Y")
        return history

    def fake_build(history_payload: dict, *, horizon_days: int, simulations: int) -> dict:
        nonlocal build_calls
        build_calls += 1
        return {
            "ticker": history_payload["ticker"],
            "horizon_days": horizon_days,
            "simulations": simulations,
        }

    monkeypatch.setattr(forecasting, "get_price_history", fake_history)
    monkeypatch.setattr(forecasting, "build_arima_garch_forecast", fake_build)
    monkeypatch.setattr(
        forecasting,
        "get_settings",
        lambda: SimpleNamespace(cache_path=tmp_path),
    )

    first = await forecasting.get_price_forecast(
        "TEST", "TEST.NS", horizon_days=15, simulations=500
    )
    second = await forecasting.get_price_forecast(
        "TEST", "TEST.NS", horizon_days=15, simulations=500
    )

    assert first == second
    assert build_calls == 1
    assert len(list((tmp_path / "price_forecasts").glob("*.json"))) == 1
