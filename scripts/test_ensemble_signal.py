import unittest

import numpy as np
import pandas as pd

from scripts.generate_ensemble_signal import (
    FEATURE_COLUMNS,
    FORECAST_HORIZON,
    build_feature_frame,
    kalman_trend_forecast,
    walk_forward_ensemble,
)


class EnsembleSignalTests(unittest.TestCase):
    def test_target_is_exactly_five_sessions_ahead(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=80)
        close = pd.Series(np.exp(np.arange(80) * 0.01), index=dates)
        frame = build_feature_frame(close)

        self.assertAlmostEqual(frame["target_5d"].iloc[20], 0.05)
        self.assertTrue(frame["target_5d"].tail(FORECAST_HORIZON).isna().all())

    def test_kalman_forecast_never_uses_a_future_price(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=100)
        log_price = pd.Series(np.linspace(7, 7.2, 100), index=dates)
        changed = log_price.copy()
        changed.iloc[-1] += 0.2

        original = kalman_trend_forecast(log_price)
        revised = kalman_trend_forecast(changed)

        pd.testing.assert_series_equal(original.iloc[:-1], revised.iloc[:-1])

    def test_future_price_change_does_not_rewrite_earlier_ensemble_forecasts(self) -> None:
        random = np.random.default_rng(8)
        dates = pd.bdate_range("2010-01-04", periods=760)
        returns = random.normal(0.0003, 0.01, len(dates))
        close = pd.Series(5_000 * np.exp(np.cumsum(returns)), index=dates)
        changed = close.copy()
        changed.iloc[-1] *= 1.08

        original = walk_forward_ensemble(build_feature_frame(close))
        revised = walk_forward_ensemble(build_feature_frame(changed))

        cutoff = -1
        for column in ("ridge_forecast", "kalman_forecast", "boosting_forecast", "ensemble_forecast"):
            np.testing.assert_allclose(
                original[column].iloc[:cutoff],
                revised[column].iloc[:cutoff],
                equal_nan=True,
            )

    def test_feature_set_is_finite_once_lookbacks_complete(self) -> None:
        dates = pd.bdate_range("2020-01-01", periods=100)
        close = pd.Series(5_000 * np.exp(np.arange(100) * 0.0002), index=dates)
        frame = build_feature_frame(close)
        self.assertTrue(np.isfinite(frame.loc[:, FEATURE_COLUMNS].iloc[-10:]).all().all())


if __name__ == "__main__":
    unittest.main()
