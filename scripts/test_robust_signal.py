import unittest

import numpy as np
import pandas as pd

from scripts.generate_robust_signal import (
    TARGET_VOLATILITY,
    build_feature_frame,
    chart_points,
    completed_daily_bars,
    completed_weekly_target,
    conservative_deflated_sharpe,
    drawdown_series,
    paired_stationary_bootstrap,
    run_candidate,
    stationary_bootstrap_indices,
)


class RobustSignalTests(unittest.TestCase):
    def synthetic_close(self, periods: int = 180) -> pd.Series:
        dates = pd.bdate_range("2024-01-02", periods=periods)
        log_returns = 0.0007 + 0.001 * np.sin(np.arange(periods) / 13)
        return pd.Series(10_000 * np.exp(np.cumsum(log_returns)), index=dates)

    def test_future_price_change_does_not_rewrite_past_features(self) -> None:
        close = self.synthetic_close()
        changed = close.copy()
        changed.iloc[-1] *= 1.15

        original = build_feature_frame(close)
        revised = build_feature_frame(changed)

        pd.testing.assert_frame_equal(original.iloc[:-1], revised.iloc[:-1])

    def test_same_day_yahoo_bar_is_excluded_until_the_next_calendar_day(self) -> None:
        close = pd.Series(
            [24_570.0, 24_605.0],
            index=pd.to_datetime(["2026-08-07", "2026-08-10"]),
        )

        during_session = completed_daily_bars(
            close,
            pd.Timestamp("2026-08-10 12:30", tz="Asia/Kolkata"),
        )
        next_day = completed_daily_bars(
            close,
            pd.Timestamp("2026-08-11 00:01", tz="Asia/Kolkata"),
        )

        self.assertEqual(during_session.index[-1], pd.Timestamp("2026-08-07"))
        self.assertEqual(next_day.index[-1], pd.Timestamp("2026-08-10"))

    def test_risk_forecast_is_the_larger_causal_volatility_estimate(self) -> None:
        frame = build_feature_frame(self.synthetic_close())
        scored = frame.dropna(subset=["risk_forecast"])
        expected = scored[["annualized_ewma_sd", "annualized_rolling_sd"]].max(axis=1)

        np.testing.assert_allclose(scored["risk_forecast"], expected)

    def test_partial_final_week_cannot_create_a_rebalance(self) -> None:
        dates = pd.to_datetime(
            ["2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07", "2026-08-10"]
        )
        raw = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5, 0.9], index=dates)

        scheduled, decisions = completed_weekly_target(raw, pd.Timestamp("2026-08-10"))

        self.assertEqual(float(scheduled.loc["2026-08-10"]), 0.5)
        self.assertTrue(bool(decisions.loc["2026-08-07"]))
        self.assertFalse(bool(decisions.loc["2026-08-10"]))

    def test_chart_uses_observed_date_for_partial_final_week(self) -> None:
        close = self.synthetic_close()
        last_monday = close.index[close.index.weekday == 0][-1]
        partial = close.loc[:last_monday]
        frame = run_candidate(
            partial,
            evaluation_start=partial.index[0],
            as_of=last_monday,
            cost=0.0,
        )

        points = chart_points(frame)

        self.assertEqual(points[-1]["date"], last_monday.date().isoformat())

    def test_new_target_first_earns_return_two_rows_later(self) -> None:
        close = self.synthetic_close()
        frame = run_candidate(
            close,
            evaluation_start=close.index[0],
            as_of=close.index[-1],
            cost=0.0,
        )
        changes = frame.index[(frame["target"] > 0) & (frame["target"].shift(1).fillna(0) == 0)]
        first = frame.index.get_loc(changes[0])

        self.assertEqual(float(frame["active_position"].iloc[first]), 0.0)
        self.assertEqual(float(frame["active_position"].iloc[first + 1]), 0.0)
        self.assertGreater(float(frame["active_position"].iloc[first + 2]), 0.0)

    def test_exposure_is_unlevered_and_respects_the_risk_budget(self) -> None:
        close = self.synthetic_close()
        frame = run_candidate(
            close,
            evaluation_start=close.index[0],
            as_of=close.index[-1],
        )
        positive = frame.loc[frame["target"] > 0]

        self.assertLessEqual(float(frame["target"].max()), 1.0)
        np.testing.assert_array_less(
            positive["target"].to_numpy(),
            (TARGET_VOLATILITY / positive["risk_forecast"] + 1e-12).to_numpy(),
        )

    def test_drawdown_includes_initial_wealth(self) -> None:
        returns = pd.Series([-0.20, 0.25], index=pd.bdate_range("2026-01-01", periods=2))

        drawdown = drawdown_series(returns)

        self.assertAlmostEqual(float(drawdown.iloc[0]), -0.20)
        self.assertAlmostEqual(float(drawdown.iloc[1]), 0.0)

    def test_stationary_bootstrap_is_seed_reproducible(self) -> None:
        first = stationary_bootstrap_indices(100, 20, np.random.default_rng(7))
        second = stationary_bootstrap_indices(100, 20, np.random.default_rng(7))

        np.testing.assert_array_equal(first, second)
        self.assertTrue(((first >= 0) & (first < 100)).all())

    def test_paired_identical_series_have_zero_metric_differences(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=160)
        returns = pd.Series(0.001 + 0.004 * np.sin(np.arange(160)), index=dates)

        result = paired_stationary_bootstrap(
            returns,
            returns,
            repetitions=250,
            expected_block=10,
            seed=11,
        )

        for interval in result["paired_difference_strategy_minus_comparator"].values():
            self.assertAlmostEqual(float(interval["lower_95"]), 0.0)
            self.assertAlmostEqual(float(interval["upper_95"]), 0.0)

    def test_more_declared_trials_cannot_improve_deflated_sharpe(self) -> None:
        rng = np.random.default_rng(19)
        returns = pd.Series(rng.normal(0.008, 0.025, 120))
        trial_sharpes = [0.3, 0.45, 0.5, 0.62, 0.7]

        thirty = conservative_deflated_sharpe(returns, trial_sharpes, 30)
        one_hundred = conservative_deflated_sharpe(returns, trial_sharpes, 100)

        self.assertLessEqual(
            float(one_hundred["deflated_sharpe_probability"]),
            float(thirty["deflated_sharpe_probability"]),
        )


if __name__ == "__main__":
    unittest.main()
