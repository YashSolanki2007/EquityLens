from __future__ import annotations

import numpy as np

from app.services.market_data.dynamic_functional_iv import (
    component_count,
    expanding_window_backtest,
    forecast_six_models,
    forecast_six_models_both_rules,
    functional_stationarity_test,
    model_confidence_set,
    paper_errors,
    prepare_nse_paper_grid,
    rice_shang_long_run_covariance,
)


def _surfaces(observations: int, maturities: int = 3) -> np.ndarray:
    rng = np.random.default_rng(42)
    values = np.empty((observations, maturities, 5))
    level = np.zeros((maturities, 5))
    smile = np.asarray([1.2, 0.4, 0.0, 0.3, 0.9])
    for index in range(observations):
        level = 0.92 * level + rng.normal(0, 0.15, size=level.shape)
        values[index] = 18 + smile + np.arange(maturities)[:, None] * 0.2 + level
    return values


def _last_score(scores: np.ndarray, horizon: int) -> np.ndarray:
    return np.repeat(scores[-1][None, :], horizon, axis=0)


def test_rice_shang_covariance_is_symmetric_and_has_finite_bandwidth():
    covariance, bandwidth = rice_shang_long_run_covariance(_surfaces(80)[:, 0, :])
    assert covariance.shape == (5, 5)
    assert np.allclose(covariance, covariance.T)
    assert np.all(np.isfinite(covariance))
    assert bandwidth >= 1


def test_component_rules_match_paper_definitions():
    eigenvalues = np.asarray([80.0, 15.0, 4.0, 0.8, 0.2])
    assert component_count(eigenvalues, "cpv", cpv=0.99) == 3
    assert component_count(eigenvalues, "k4") == 4


def test_all_six_models_and_benchmarks_return_paper_grid():
    forecasts, diagnostics = forecast_six_models(
        _surfaces(60),
        horizon=10,
        rule="k4",
        score_forecaster=_last_score,
    )
    assert set(forecasts) == {
        "fts",
        "dfts",
        "mfts",
        "dmfts",
        "mlfts",
        "dmlfts",
        "rw",
        "ar1",
        "ct11",
        "gg06",
    }
    assert set(diagnostics) == {
        "fts",
        "dfts",
        "mfts",
        "dmfts",
        "mlfts",
        "dmlfts",
    }
    assert all(value.shape == (10, 3, 5) for value in forecasts.values())


def test_shared_basis_optimization_matches_separate_paper_rules():
    values = _surfaces(60)
    combined, _ = forecast_six_models_both_rules(
        values,
        horizon=5,
        score_forecaster=_last_score,
    )
    for rule in ("cpv", "k4"):
        separate, _ = forecast_six_models(
            values,
            horizon=5,
            rule=rule,
            score_forecaster=_last_score,
        )
        for model in separate:
            assert np.allclose(combined[rule][model], separate[model])


def test_small_expanding_window_preserves_paper_horizon_counts():
    report = expanding_window_backtest(
        _surfaces(34),
        initial_training=24,
        out_of_sample=10,
        horizons=(1, 5, 10),
        score_forecaster=_last_score,
    )
    for rule in ("cpv", "k4"):
        horizons = report["results"][rule]["horizons"]
        assert horizons["1"]["expected_observations"] == 10
        assert horizons["5"]["expected_observations"] == 6
        assert horizons["10"]["expected_observations"] == 1
        assert horizons["1"]["models"][0]["observations"] == 10


def test_mixed_errors_apply_asymmetric_square_root_penalty():
    forecast = np.asarray([0.0, 1.0])
    actual = np.asarray([0.25, 0.75])
    errors = paper_errors(forecast, actual)
    assert errors["mafe"] == 0.25
    assert errors["msfe"] == 0.0625
    assert errors["mme_under"] == 0.375
    assert errors["mme_over"] == 0.375


def test_mcs_retains_lower_loss_model():
    rng = np.random.default_rng(7)
    losses = np.column_stack(
        [rng.normal(0.8, 0.05, 80), rng.normal(1.2, 0.05, 80)]
    )
    report = model_confidence_set(
        losses,
        ["better", "worse"],
        statistic="Tmax",
        bootstraps=200,
    )
    assert "better" in report["included"]
    assert "worse" in report["excluded"]


def test_functional_stationarity_test_returns_paper_decision_fields():
    report = functional_stationarity_test(
        _surfaces(80)[:, 0, :],
        monte_carlo_replications=100,
        brownian_terms=50,
    )
    assert 0 <= report["p_value"] <= 1
    assert report["components"] <= 5
    assert report["monte_carlo_replications"] == 100
    assert isinstance(report["rejects_stationarity_at_5_percent"], bool)


def test_nse_grid_uses_three_paper_series():
    values = _surfaces(5, maturities=4)
    selected = prepare_nse_paper_grid(values)
    assert selected.shape == (5, 3, 5)
    assert np.array_equal(selected, values[:, 1:4, :])
