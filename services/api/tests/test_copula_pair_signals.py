from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app.services.copula_pair_signals import (
    CopulaFit,
    build_copula_signal,
    classify_signal,
    conditional_probabilities,
    fit_best_copula,
    fit_best_marginal,
)


def test_gaussian_conditional_probabilities_reduce_to_margins_at_independence():
    fit = CopulaFit("Gaussian", 0.0, None, 0.0)

    first, second = conditional_probabilities(fit, 0.2, 0.8)

    assert first.item() == pytest.approx(0.2)
    assert second.item() == pytest.approx(0.8)


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        (0.05, 0.95, "enter_short_a_long_b"),
        (0.95, 0.05, "enter_long_a_short_b"),
        (0.45, 0.55, "exit"),
        (0.2, 0.8, "watch"),
    ],
)
def test_signal_rules_match_the_paper(first: float, second: float, expected: str):
    assert classify_signal(first, second) == expected


def test_supported_margins_and_copulas_produce_finite_aic():
    rng = np.random.default_rng(230506961)
    values = rng.standard_t(df=5, size=252)
    marginal = fit_best_marginal(values)
    first = np.clip((pd.Series(values).rank().to_numpy()) / 253, 1e-6, 1 - 1e-6)
    second_values = 0.65 * values + rng.normal(scale=0.7, size=252)
    second = np.clip(
        pd.Series(second_values).rank().to_numpy() / 253,
        1e-6,
        1 - 1e-6,
    )
    copula = fit_best_copula(first, second)

    assert marginal.name in {"Gaussian", "Student-t", "Cauchy"}
    assert np.isfinite(marginal.aic)
    assert copula.family in {"Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"}
    assert np.isfinite(copula.aic)


def test_build_signal_uses_nifty_reference_spreads_and_dual_test_metadata():
    rng = np.random.default_rng(17)
    observations = 257
    dates = pd.date_range("2025-08-01", periods=observations, freq="B")
    reference = 22_000 + np.cumsum(rng.normal(scale=25, size=observations))
    common = rng.normal(scale=12, size=observations)
    spread_a = common + rng.normal(scale=3, size=observations)
    spread_b = 0.8 * common + rng.normal(scale=4, size=observations)
    closes = pd.DataFrame(
        {
            "NIFTY": reference,
            "AAA": (reference - spread_a) / 10,
            "BBB": (reference - spread_b) / 20,
        },
        index=dates,
    )
    candidate = SimpleNamespace(
        pair_id="AAA-BBB",
        stock_a="AAA",
        stock_a_name="AAA Limited",
        stock_b="BBB",
        stock_b_name="BBB Limited",
        sector="Test",
        engle_granger_p_value=0.00001,
        fdr_q_value=0.01,
        kss_statistic=-6.0,
    )

    result = build_copula_signal(candidate, closes)

    assert result is not None
    assert result.reference_ticker == "NIFTY"
    assert result.reference_beta_a > 0
    assert result.reference_beta_b > 0
    assert 0 < result.h_a_given_b < 1
    assert 0 < result.h_b_given_a < 1
    assert len(result.history) == 35
