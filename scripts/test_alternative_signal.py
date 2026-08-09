import unittest

import numpy as np
import pandas as pd

from scripts.generate_alternative_signal import build_signal_frame, run_strategy


class AlternativeSignalTests(unittest.TestCase):
    def synthetic_close(self, periods: int = 180) -> pd.Series:
        dates = pd.bdate_range("2020-01-01", periods=periods)
        returns = 0.0004 + 0.002 * np.sin(np.arange(periods) / 11)
        return pd.Series(10_000 * np.exp(np.cumsum(returns)), index=dates)

    def test_score_is_volatility_normalized_ema_spread(self) -> None:
        close = self.synthetic_close()
        frame = build_signal_frame(close)
        scored = frame.dropna(subset=["trend_score"])
        expected = scored["ema_spread"] / (scored["daily_sd"] * np.sqrt(42))

        np.testing.assert_allclose(scored["trend_score"], expected)

    def test_signal_uses_only_score_sign(self) -> None:
        frame = build_signal_frame(self.synthetic_close())
        scored = frame.dropna(subset=["trend_score"])

        np.testing.assert_array_equal(
            scored["target"].to_numpy(),
            (scored["trend_score"] > 0).astype(float).to_numpy(),
        )

    def test_future_price_change_does_not_rewrite_past_scores(self) -> None:
        close = self.synthetic_close()
        changed = close.copy()
        changed.iloc[-1] *= 1.1

        original = build_signal_frame(close)
        revised = build_signal_frame(changed)

        pd.testing.assert_series_equal(
            original["trend_score"].iloc[:-1],
            revised["trend_score"].iloc[:-1],
        )

    def test_position_is_delayed_two_closes(self) -> None:
        close = self.synthetic_close()
        signal = build_signal_frame(close)
        first_long = signal.index[signal["target"] > 0][0]
        report, _ = run_strategy(close, close.index[0])
        location = report.index.get_loc(first_long)

        self.assertEqual(report["position"].iloc[location], 0)
        self.assertEqual(report["position"].iloc[location + 1], 0)
        self.assertEqual(report["position"].iloc[location + 2], 1)

    def test_invalid_window_order_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_signal_frame(self.synthetic_close(), fast_span=63, slow_span=21)


if __name__ == "__main__":
    unittest.main()
