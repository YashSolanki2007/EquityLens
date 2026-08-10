import unittest

import numpy as np
import pandas as pd

from scripts.generate_custom_signal import (
    BETA_BINOMIAL_PRIOR_STRENGTH,
    VOLATILITY_THRESHOLD_MINIMUM_ROWS,
    beta_binomial_adjustment,
    build_model_frame,
    downside_metrics,
    expanding_volatility_percentile_threshold,
    rolling_score_percentile,
    walk_forward_probabilities,
    yeo_johnson_tail_probability,
)


class CustomSignalTests(unittest.TestCase):
    def test_beta_binomial_adjustment_uses_expected_window(self) -> None:
        raw_probability = 0.25
        hits = np.array([0.0, 1.0, 0.0, 1.0, 1.0])

        adjusted, window, observations, event_count = beta_binomial_adjustment(
            raw_probability, hits
        )

        expected = (BETA_BINOMIAL_PRIOR_STRENGTH * 0.25 + 3) / (
            BETA_BINOMIAL_PRIOR_STRENGTH + 4
        )
        self.assertEqual(window, 4)
        self.assertEqual(observations, 4)
        self.assertEqual(event_count, 3)
        self.assertAlmostEqual(adjusted, expected)

    def test_yeo_johnson_probability_uses_the_forecast_as_signed_tail_threshold(self) -> None:
        upper = yeo_johnson_tail_probability(0.01, 0.01, 1.0, 0.0, 1.0)
        lower = yeo_johnson_tail_probability(-0.01, 0.01, 1.0, 0.0, 1.0)

        self.assertAlmostEqual(upper, 0.15865525, places=7)
        self.assertAlmostEqual(lower, 0.15865525, places=7)

    def test_future_price_change_does_not_rewrite_earlier_forecasts(self) -> None:
        random = np.random.default_rng(7)
        dates = pd.bdate_range("2010-01-04", periods=590)
        returns = random.normal(0.0003, 0.012, len(dates))
        close = pd.Series(5_000 * np.exp(np.cumsum(returns)), index=dates)
        changed = close.copy()
        changed.iloc[-1] *= 1.08

        original, _ = walk_forward_probabilities(build_model_frame(close))
        revised, _ = walk_forward_probabilities(build_model_frame(changed))

        pd.testing.assert_series_equal(
            original["raw_probability"].iloc[:-1],
            revised["raw_probability"].iloc[:-1],
        )
        pd.testing.assert_series_equal(
            original["adjusted_probability"].iloc[:-1],
            revised["adjusted_probability"].iloc[:-1],
        )

    def test_custom_score_is_annualized_beta_scaled_by_probability(self) -> None:
        random = np.random.default_rng(11)
        dates = pd.bdate_range("2010-01-04", periods=590)
        returns = random.normal(0.0003, 0.012, len(dates))
        close = pd.Series(5_000 * np.exp(np.cumsum(returns)), index=dates)

        predictions, _ = walk_forward_probabilities(build_model_frame(close))
        scored = predictions.dropna(subset=["custom_score"])
        expected = scored["annualized_slope"] * scored["adjusted_probability"]

        np.testing.assert_allclose(scored["custom_score"], expected)

    def test_expanding_volatility_threshold_is_point_in_time(self) -> None:
        dates = pd.bdate_range(
            "2020-01-01", periods=VOLATILITY_THRESHOLD_MINIMUM_ROWS + 2
        )
        frame = pd.DataFrame(
            {"ewma_daily_sd": np.linspace(0.005, 0.015, len(dates))}, index=dates
        )
        original = expanding_volatility_percentile_threshold(frame)
        changed = frame.copy()
        changed.iloc[-1, 0] = 50.0
        revised = expanding_volatility_percentile_threshold(changed)

        pd.testing.assert_series_equal(original.iloc[:-1], revised.iloc[:-1])
        self.assertTrue(
            original.iloc[:VOLATILITY_THRESHOLD_MINIMUM_ROWS].isna().all()
        )
        self.assertAlmostEqual(
            original.iloc[VOLATILITY_THRESHOLD_MINIMUM_ROWS],
            frame.iloc[:VOLATILITY_THRESHOLD_MINIMUM_ROWS, 0].quantile(0.50),
        )

    def test_score_percentile_uses_only_prior_observations(self) -> None:
        score = pd.Series(
            np.arange(70, dtype=float),
            index=pd.bdate_range("2025-01-01", periods=70),
        )
        original = rolling_score_percentile(score, lookback=63, minimum_rows=5)
        changed = score.copy()
        changed.iloc[-1] = -1000
        revised = rolling_score_percentile(changed, lookback=63, minimum_rows=5)

        pd.testing.assert_series_equal(original.iloc[:-1], revised.iloc[:-1])
        self.assertTrue(original.iloc[:5].isna().all())
        self.assertEqual(original.iloc[5], 1.0)
        self.assertEqual(revised.iloc[-1], 0.0)

    def test_sortino_uses_zero_mar_and_only_downside_returns(self) -> None:
        returns = pd.Series([0.01, -0.01, 0.02, -0.005])
        expected_downside = np.sqrt(np.mean([0.0, 0.01**2, 0.0, 0.005**2])) * np.sqrt(252)
        expected_sortino = returns.mean() * 252 / expected_downside

        downside, sortino = downside_metrics(returns)

        self.assertAlmostEqual(downside, expected_downside)
        self.assertAlmostEqual(sortino, expected_sortino)


if __name__ == "__main__":
    unittest.main()
