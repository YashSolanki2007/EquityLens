from datetime import date, timedelta

import numpy as np

from app.services.iv_model_evaluation import (
    _score_surfaces,
    historical_walk_forward_backtest,
)


def _surface_history(count: int = 42) -> dict:
    base = np.asarray(
        [
            [31, 28, 25, 27, 30],
            [30, 27, 24, 26, 29],
            [29, 26, 23, 25, 28],
            [28, 25, 22, 24, 27],
        ],
        dtype=float,
    )
    skew = np.tile(np.asarray([1.5, 0.7, 0.0, -0.5, -1.0]), (4, 1))
    term = np.tile(np.asarray([1.2, 0.4, -0.4, -0.8])[:, None], (1, 5))
    surfaces = [
        base
        + 0.03 * index
        + skew * np.cos(index / 7)
        + term * np.sin(index / 9)
        for index in range(count)
    ]
    dates = []
    current = date(2026, 5, 4)
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current += timedelta(days=1)
    return {"dates": dates, "surfaces": np.asarray(surfaces).tolist()}


def test_forward_score_compares_model_with_no_change_baseline():
    baseline = np.full((4, 5), 20.0)
    actual = np.full((4, 5), 24.0)
    forecast = np.full((4, 5), 23.0)

    result = _score_surfaces(forecast, baseline, actual)

    assert result["model_rmse"] == 1
    assert result["baseline_rmse"] == 4
    assert result["improvement_over_baseline_percent"] == 75
    assert result["directional_accuracy_percent"] == 100
    assert result["bias_vol_points"] == -1


def test_historical_backtest_is_causal_and_reports_baseline_comparison():
    report = historical_walk_forward_backtest({"TEST": _surface_history()})

    assert report["available"] is True
    assert report["observations"] == 6
    assert report["symbols"] == 1
    assert report["target_sessions"] == 6
    assert report["first_target_date"] == _surface_history()["dates"][36]
    assert report["model_rmse"] >= 0
    assert report["baseline_rmse"] >= 0
    assert len(report["improvement_confidence_interval_95"]) == 2
    assert sum(report["component_counts"].values()) == report["observations"]
    assert report["per_symbol"][0]["ticker"] == "TEST"
    assert "not option-strategy P&L" in report["limitation"]


def test_historical_backtest_excludes_only_targets_affected_by_recent_gaps():
    history = _surface_history()
    history["dates"][35:] = [
        (date.fromisoformat(value) + timedelta(days=7)).isoformat()
        for value in history["dates"][35:]
    ]

    report = historical_walk_forward_backtest({"TEST": history})

    assert report["available"] is True
    assert 0 < report["observations"] < 6
    assert report["excluded_for_gaps"] > 0
