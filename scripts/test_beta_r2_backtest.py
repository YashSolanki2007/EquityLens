import math
import unittest

import numpy as np
import pandas as pd

from scripts.generate_beta_r2_backtest import regression_signal, run_backtest


class BetaR2BacktestTests(unittest.TestCase):
    def test_perfect_log_trend_has_unit_r_squared(self) -> None:
        daily_beta = 0.001
        dates = pd.bdate_range("2011-01-03", periods=20)
        close = pd.Series(np.exp(4 + daily_beta * np.arange(20)), index=dates)

        signal = regression_signal(close, lookback=10).iloc[-1]

        self.assertAlmostEqual(float(signal["r_squared"]), 1.0, places=10)
        self.assertAlmostEqual(
            float(signal["score"]),
            math.expm1(252 * daily_beta),
            places=10,
        )

    def test_future_price_change_does_not_rewrite_past_signals(self) -> None:
        dates = pd.bdate_range("2011-01-03", periods=30)
        close = pd.Series(np.exp(4 + 0.001 * np.arange(30)), index=dates)
        changed = close.copy()
        changed.iloc[-1] *= 2

        original_signal = regression_signal(close, lookback=10)
        changed_signal = regression_signal(changed, lookback=10)

        pd.testing.assert_frame_equal(original_signal.iloc[:-1], changed_signal.iloc[:-1])

    def test_position_starts_two_closes_after_signal_observation(self) -> None:
        dates = pd.bdate_range("2011-01-03", periods=12)
        close = pd.Series(np.exp(4 + 0.002 * np.arange(12)), index=dates)

        report, _ = run_backtest(close, lookback=3, threshold=0, cost=0)

        self.assertEqual(float(report["position"].iloc[2]), 0.0)
        self.assertEqual(float(report["position"].iloc[3]), 0.0)
        self.assertEqual(float(report["position"].iloc[4]), 1.0)


if __name__ == "__main__":
    unittest.main()
