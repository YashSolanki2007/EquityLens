import numpy as np

from app.services.iv_model_evaluation import _score_surfaces


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
