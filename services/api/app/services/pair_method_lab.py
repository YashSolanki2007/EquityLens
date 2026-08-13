"""Development-only implementation of the dynamic cointegration paper.

The cited research uses three months of minute cryptocurrency data followed by a
one-week trading period. This lab preserves the rolling formation/trading split,
Engle-Granger and KSS tests, OU half-life ranking, and the paper's half-life-derived
Z-score window, while adapting the observations to daily NSE F&O history.
"""

from __future__ import annotations

import asyncio
import math
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, TypedDict

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tools.sm_exceptions import CollinearityWarning
from statsmodels.tsa.stattools import coint

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.schemas.pair_method_lab import (
    PairMethodLabCandidate,
    PairMethodLabChartPoint,
    PairMethodLabResponse,
)
from app.services.pair_suggestions import (
    DEFAULT_P_VALUE_THRESHOLD,
    MAX_FUTURES_CONTRACTS_PER_LEG,
    FuturesContract,
    PairUniverseMember,
    _eligible_fno_members,
    _latest_futures_contracts,
    _spread_half_life,
    benjamini_hochberg,
)

PAPER_TITLE = "Evaluation of Dynamic Cointegration-Based Pairs Trading Strategy"
PAPER_URL = "https://arxiv.org/abs/2109.10662"
HISTORY_PERIOD = "5y"
FORMATION_DAYS = 252
CURRENT_COMPARISON_DAYS = 252
TRADING_DAYS = 5
ROLLING_VALIDATION_WINDOWS = 6
MINIMUM_FORMATION_OBSERVATIONS = 220
ENGLE_GRANGER_CUTOFF = 0.0001
# Empirical 0.01% lower-tail cutoff from 1,000,000 pairs of independent Gaussian
# random walks (seed 210910662), using the lab's exact 252-observation procedure:
# OLS residual with an intercept, demeaning/standardising, and one augmented lag.
# The simulated quantile was -5.040625. This residual-based calibration is more
# appropriate here than either the generic univariate cutoff or a guessed threshold.
KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL = -5.04
MAX_HALF_LIFE_DAYS = 90
MAX_DEEP_CANDIDATES = 160
MAX_RESULTS_TO_CACHE = MAX_DEEP_CANDIDATES
PAIR_METHOD_CACHE_TTL_SECONDS = 6 * 60 * 60
TRACKER_ENTRY_ZSCORE_ABS_THRESHOLD = 1.7
TRACKER_CONFIRMED_MIN_ABS_ZSCORE = 0.6
TRACKER_CONFIRMED_MIN_ABS_DECLINE = 0.3
TRACKER_CONFIRMED_MIN_RELATIVE_DECLINE = 0.2
TRACKER_CONFIRMED_LOOKBACK_OBSERVATIONS = 5
TRACKER_EXIT_ZSCORE_ABS_TARGET = 0.2
TRACKER_MIN_REMAINING_RETURN_PERCENT = 1.5
TRACKER_FDR_Q_CUTOFF = 0.05


@dataclass(frozen=True)
class KSSResult:
    statistic: float
    passed: bool


@dataclass(frozen=True)
class FormationTest:
    stock_a_index: int
    stock_b_index: int
    p_value: float
    alpha: float
    beta: float
    correlation: float
    observations: int
    kss_statistic: float
    kss_pass: bool
    half_life_days: float | None
    adaptive_lookback_days: int | None
    current_zscore: float | None


StabilityBand = Literal[
    "strong",
    "moderate",
    "unstable",
    "insufficient_history",
]


class RollingValidation(TypedDict):
    rolling_windows: int
    stability_passes: int
    stability_score: float
    stability_band: StabilityBand
    eg_stability: float
    kss_stability: float
    entry_events: int
    success_rate: float | None
    median_z_change: float | None


def adaptive_lookback_days(half_life_days: float, available: int) -> int:
    """Equation 36 in the paper: N = 2 / theta - 1, theta = ln(2) / half-life."""

    theta = math.log(2) / max(half_life_days, 1e-9)
    lookback = int(round(2 / theta - 1))
    return max(10, min(lookback, available))


def potential_convergence_return_percent(
    *,
    spread_gap: float,
    beta: float,
    price_a: float,
    price_b: float,
) -> float:
    """Gross notional return if the raw-price spread returns to its rolling mean.

    With one unit of A and beta units of B, pair P&L is exactly the reduction in
    the raw spread gap. Dividing by both legs' gross notional keeps this metric
    independent of the particular price path used to reach the mean.
    """

    gross_notional = price_a + abs(beta) * price_b
    if gross_notional <= 0 or not math.isfinite(gross_notional):
        return 0.0
    return abs(spread_gap) / gross_notional * 100


def tracker_entry_diagnostics(
    *,
    engle_granger_pass: bool,
    kss_pass: bool,
    fdr_q_value: float,
    current_zscore: float,
    potential_convergence_return_percent: float,
    zscore_history: list[float | None],
) -> dict[str, float | str | None]:
    """Classify direct and reversal-confirmed tracker entries causally."""

    current_abs = abs(current_zscore)
    remaining_fraction = (
        max(current_abs - TRACKER_EXIT_ZSCORE_ABS_TARGET, 0.0) / current_abs
        if current_abs > 0
        else 0.0
    )
    remaining_return = potential_convergence_return_percent * remaining_fraction
    output: dict[str, float | str | None] = {
        "entry_type": None,
        "recent_peak_abs_zscore": None,
        "remaining_return_percent": round(remaining_return, 3),
    }
    if not (
        engle_granger_pass
        and kss_pass
        and math.isfinite(fdr_q_value)
        and fdr_q_value <= TRACKER_FDR_Q_CUTOFF
        and math.isfinite(current_zscore)
    ):
        return output
    if current_abs >= TRACKER_ENTRY_ZSCORE_ABS_THRESHOLD:
        output["entry_type"] = "direct"
        output["recent_peak_abs_zscore"] = round(current_abs, 3)
        return output

    history = [
        float(value)
        for value in zscore_history
        if value is not None and math.isfinite(float(value))
    ]
    if not history:
        return output
    # The separately supplied current value is authoritative because candidate fields
    # are rounded after the chart is built.
    history[-1] = current_zscore
    recent = history[-(TRACKER_CONFIRMED_LOOKBACK_OBSERVATIONS + 1) :]
    if len(recent) < 3:
        return output
    prior = recent[:-1]
    signed_prior = [value for value in prior if value * current_zscore > 0]
    if not signed_prior:
        return output
    peak_abs = max(abs(value) for value in signed_prior)
    output["recent_peak_abs_zscore"] = round(peak_abs, 3)
    recent_three = recent[-3:]
    magnitudes = [abs(value) for value in recent_three]
    same_sign = all(value * current_zscore > 0 for value in recent_three)
    trending_toward_zero = (
        same_sign and magnitudes[0] > magnitudes[1] > magnitudes[2]
    )
    absolute_decline = peak_abs - current_abs
    relative_decline = absolute_decline / peak_abs if peak_abs > 0 else 0.0
    if (
        TRACKER_CONFIRMED_MIN_ABS_ZSCORE <= current_abs
        < TRACKER_ENTRY_ZSCORE_ABS_THRESHOLD
        and peak_abs >= TRACKER_ENTRY_ZSCORE_ABS_THRESHOLD
        and absolute_decline >= TRACKER_CONFIRMED_MIN_ABS_DECLINE
        and relative_decline >= TRACKER_CONFIRMED_MIN_RELATIVE_DECLINE
        and trending_toward_zero
        and remaining_return >= TRACKER_MIN_REMAINING_RETURN_PERCENT
    ):
        output["entry_type"] = "confirmed_convergence"
    return output


def raw_hedge_futures_contract_counts(
    *,
    beta: float,
    lot_size_a: int,
    lot_size_b: int,
) -> tuple[int, int, float]:
    """Find whole futures lots whose B/A unit ratio is closest to raw-price beta."""

    candidates: list[tuple[float, int, int, int]] = []
    for contracts_a in range(1, MAX_FUTURES_CONTRACTS_PER_LEG + 1):
        for contracts_b in range(1, MAX_FUTURES_CONTRACTS_PER_LEG + 1):
            realized_beta = contracts_b * lot_size_b / (contracts_a * lot_size_a)
            relative_error = abs(realized_beta - beta) / beta
            candidates.append(
                (
                    relative_error,
                    contracts_a + contracts_b,
                    contracts_a,
                    contracts_b,
                )
            )
    relative_error, _, contracts_a, contracts_b = min(
        candidates,
        key=lambda candidate: (candidate[0], candidate[1]),
    )
    return contracts_a, contracts_b, max(0.0, 100 * (1 - relative_error))


def attach_futures_capital_plans(
    candidates: list[PairMethodLabCandidate],
    contracts_by_ticker: dict[str, list[FuturesContract]],
    futures_price_date: date | None,
) -> list[PairMethodLabCandidate]:
    """Attach nearest-common-expiry gross futures notionals to lab candidates."""

    enriched: list[PairMethodLabCandidate] = []
    for candidate in candidates:
        contracts_a = {
            contract.expiry: contract
            for contract in contracts_by_ticker.get(candidate.stock_a, [])
        }
        contracts_b = {
            contract.expiry: contract
            for contract in contracts_by_ticker.get(candidate.stock_b, [])
        }
        common_expiries = sorted(set(contracts_a) & set(contracts_b))
        base_update: dict[str, object] = {
            "futures_price_date": (
                futures_price_date.isoformat()
                if futures_price_date is not None
                else None
            ),
            "capital_plan_is_active": candidate.paper_signal != "inside_entry_band",
        }
        if not common_expiries:
            base_update.update(
                {
                    "futures_capital_available": False,
                    "futures_capital_note": (
                        "A nearest common NSE futures expiry was unavailable for one or both legs."
                    ),
                }
            )
            enriched.append(candidate.model_copy(update=base_update))
            continue

        expiry = common_expiries[0]
        contract_a = contracts_a[expiry]
        contract_b = contracts_b[expiry]
        count_a, count_b, hedge_fit = raw_hedge_futures_contract_counts(
            beta=candidate.hedge_ratio,
            lot_size_a=contract_a.lot_size,
            lot_size_b=contract_b.lot_size,
        )
        units_a = count_a * contract_a.lot_size
        units_b = count_b * contract_b.lot_size
        notional_a = units_a * contract_a.price
        notional_b = units_b * contract_b.price
        if candidate.current_zscore <= 0:
            long_ticker, short_ticker = candidate.stock_a, candidate.stock_b
            long_contracts, short_contracts = count_a, count_b
            long_units, short_units = units_a, units_b
            long_price, short_price = contract_a.price, contract_b.price
            long_notional, short_notional = notional_a, notional_b
        else:
            long_ticker, short_ticker = candidate.stock_b, candidate.stock_a
            long_contracts, short_contracts = count_b, count_a
            long_units, short_units = units_b, units_a
            long_price, short_price = contract_b.price, contract_a.price
            long_notional, short_notional = notional_b, notional_a
        base_update.update(
            {
                "futures_capital_available": True,
                "futures_expiry": expiry.isoformat(),
                "capital_long_ticker": long_ticker,
                "capital_short_ticker": short_ticker,
                "long_futures_contracts": long_contracts,
                "short_futures_contracts": short_contracts,
                "long_futures_units": long_units,
                "short_futures_units": short_units,
                "long_futures_price": round(long_price, 2),
                "short_futures_price": round(short_price, 2),
                "long_futures_notional_inr": round(long_notional, 2),
                "short_futures_notional_inr": round(short_notional, 2),
                "combined_futures_notional_inr": round(
                    long_notional + short_notional,
                    2,
                ),
                "futures_hedge_fit_percent": round(hedge_fit, 1),
                "futures_capital_note": (
                    "Gross futures notional is shown for the nearest common expiry. "
                    "Actual cash blocked is broker margin and can be materially lower."
                ),
            }
        )
        enriched.append(candidate.model_copy(update=base_update))
    return enriched


def kss_test(series: np.ndarray, *, lags: int = 1) -> KSSResult | None:
    """Return the demeaned augmented KSS t-statistic for nonlinear stationarity.

    The auxiliary regression is Δy_t on y_(t-1)^3 and lagged differences with no
    intercept. More-negative statistics reject a unit root in favour of ESTAR-type
    mean reversion. The lab uses its residual-specific 0.01% Monte Carlo cutoff.
    """

    values = np.asarray(series, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < max(40, lags + 8):
        return None
    values = values - float(values.mean())
    scale = float(values.std(ddof=1))
    if not math.isfinite(scale) or scale <= 1e-12:
        return None
    values = values / scale
    differences = np.diff(values)
    start = lags
    dependent = differences[start:]
    cubic = values[start:-1] ** 3
    columns = [cubic]
    for lag in range(1, lags + 1):
        columns.append(differences[start - lag : -lag])
    design = np.column_stack(columns)
    if len(dependent) <= design.shape[1] + 2:
        return None
    try:
        coefficients, _, _, _ = np.linalg.lstsq(design, dependent, rcond=None)
        residuals = dependent - design @ coefficients
        degrees_of_freedom = len(dependent) - design.shape[1]
        residual_variance = float(residuals @ residuals / degrees_of_freedom)
        covariance = residual_variance * np.linalg.pinv(design.T @ design)
        standard_error = math.sqrt(max(float(covariance[0, 0]), 0))
    except (ValueError, np.linalg.LinAlgError):
        return None
    if standard_error <= 0 or not math.isfinite(standard_error):
        return None
    statistic = float(coefficients[0] / standard_error)
    if not math.isfinite(statistic):
        return None
    return KSSResult(
        statistic=statistic,
        passed=statistic <= KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL,
    )


def _download_history_sync(
    members: list[PairUniverseMember],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbols = [member.market_data_ticker for member in members]
    frame = yf.download(
        symbols,
        period=HISTORY_PERIOD,
        interval="1d",
        auto_adjust=True,
        actions=False,
        progress=False,
        threads=True,
        group_by="column",
    )
    if frame is None or frame.empty:
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"].copy()
        volumes = frame["Volume"].copy()
    elif len(symbols) == 1:
        closes = frame[["Close"]].rename(columns={"Close": symbols[0]})
        volumes = frame[["Volume"]].rename(columns={"Volume": symbols[0]})
    else:
        return pd.DataFrame(), pd.DataFrame()
    closes = closes.reindex(columns=symbols).replace([np.inf, -np.inf], np.nan)
    volumes = volumes.reindex(columns=symbols).replace([np.inf, -np.inf], np.nan)
    closes.columns = [member.ticker for member in members]
    volumes.columns = [member.ticker for member in members]
    return closes, volumes


def _engle_granger(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float] | None:
    design = np.column_stack((np.ones(len(a)), b))
    try:
        alpha, beta = np.linalg.lstsq(design, a, rcond=None)[0]
    except (ValueError, np.linalg.LinAlgError):
        return None
    if not math.isfinite(beta):
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CollinearityWarning)
        try:
            _, p_value, _ = coint(a, b, trend="c", maxlag=1, autolag=None)
        except (ValueError, np.linalg.LinAlgError):
            return None
    if not math.isfinite(p_value):
        return None
    return float(p_value), float(alpha), float(beta)


def _formation_test(
    stock_a_index: int,
    stock_b_index: int,
    formation_prices: np.ndarray,
) -> FormationTest | None:
    stock_a = formation_prices[:, stock_a_index]
    stock_b = formation_prices[:, stock_b_index]
    valid = np.isfinite(stock_a) & np.isfinite(stock_b)
    observations = int(valid.sum())
    if observations < MINIMUM_FORMATION_OBSERVATIONS:
        return None
    a = stock_a[valid]
    b = stock_b[valid]
    fitted = _engle_granger(a, b)
    if fitted is None:
        return None
    p_value, alpha, beta = fitted
    spread = a - alpha - beta * b
    kss = kss_test(spread)
    if kss is None:
        return None
    half_life = _spread_half_life(spread)
    lookback = None
    current_zscore = None
    if half_life is not None and 0 < half_life <= MAX_HALF_LIFE_DAYS:
        lookback = adaptive_lookback_days(half_life, len(spread))
        sample = spread[-lookback:]
        standard_deviation = float(sample.std(ddof=1))
        if standard_deviation > 0 and math.isfinite(standard_deviation):
            current_zscore = float((spread[-1] - sample.mean()) / standard_deviation)
    correlation = float(np.corrcoef(np.diff(a), np.diff(b))[0, 1])
    if not math.isfinite(correlation):
        return None
    return FormationTest(
        stock_a_index=stock_a_index,
        stock_b_index=stock_b_index,
        p_value=p_value,
        alpha=alpha,
        beta=beta,
        correlation=correlation,
        observations=observations,
        kss_statistic=kss.statistic,
        kss_pass=kss.passed,
        half_life_days=half_life,
        adaptive_lookback_days=lookback,
        current_zscore=current_zscore,
    )


def _rolling_validation(
    prices_a: pd.Series,
    prices_b: pd.Series,
) -> RollingValidation:
    aligned = pd.concat([prices_a, prices_b], axis=1, keys=["a", "b"]).dropna()
    total_required = FORMATION_DAYS + TRADING_DAYS
    if len(aligned) < total_required:
        return {
            "rolling_windows": 0,
            "stability_passes": 0,
            "stability_score": 0.0,
            "stability_band": "insufficient_history",
            "eg_stability": 0.0,
            "kss_stability": 0.0,
            "entry_events": 0,
            "success_rate": None,
            "median_z_change": None,
        }
    last_start = len(aligned) - total_required
    starts = list(range(last_start, -1, -TRADING_DAYS))[:ROLLING_VALIDATION_WINDOWS]
    eg_passes = 0
    kss_passes = 0
    stability_passes = 0
    entry_events = 0
    successes = 0
    z_changes: list[float] = []
    valid_windows = 0
    for start in reversed(starts):
        sample = aligned.iloc[start : start + total_required]
        formation = sample.iloc[:FORMATION_DAYS]
        a = formation["a"].to_numpy(dtype=float)
        b = formation["b"].to_numpy(dtype=float)
        fitted = _engle_granger(a, b)
        if fitted is None:
            continue
        p_value, alpha, beta = fitted
        spread_formation = a - alpha - beta * b
        kss = kss_test(spread_formation)
        half_life = _spread_half_life(spread_formation)
        if kss is None or half_life is None or not 0 < half_life <= MAX_HALF_LIFE_DAYS:
            continue
        valid_windows += 1
        eg_pass = p_value <= ENGLE_GRANGER_CUTOFF
        kss_pass = kss.passed
        eg_passes += int(eg_pass)
        kss_passes += int(kss_pass)
        stability_passes += int(eg_pass and kss_pass)
        lookback = adaptive_lookback_days(half_life, len(spread_formation))
        all_spread = (
            sample["a"].to_numpy(dtype=float)
            - alpha
            - beta * sample["b"].to_numpy(dtype=float)
        )
        spread_series = pd.Series(all_spread)
        rolling_mean = spread_series.rolling(lookback).mean()
        rolling_std = spread_series.rolling(lookback).std(ddof=1).replace(0, np.nan)
        zscores = ((spread_series - rolling_mean) / rolling_std).to_numpy(dtype=float)
        validation_z = zscores[FORMATION_DAYS - 1 :]
        if len(validation_z) < 2 or not np.isfinite(validation_z).all():
            continue
        start_abs = abs(float(validation_z[0]))
        end_abs = abs(float(validation_z[-1]))
        z_changes.append(end_abs - start_abs)
        direction = 0
        for previous, current in zip(validation_z[:-1], validation_z[1:], strict=True):
            if previous > -2 and current <= -2:
                direction = -1
                break
            if previous < 2 and current >= 2:
                direction = 1
                break
        if direction == 0:
            continue
        entry_events += 1
        if (direction < 0 and validation_z[-1] > -1) or (
            direction > 0 and validation_z[-1] < 1
        ):
            successes += 1
    if valid_windows < ROLLING_VALIDATION_WINDOWS:
        stability_band: StabilityBand = "insufficient_history"
    elif stability_passes >= 5:
        stability_band = "strong"
    elif stability_passes >= 4:
        stability_band = "moderate"
    else:
        stability_band = "unstable"
    return {
        "rolling_windows": valid_windows,
        "stability_passes": stability_passes,
        "stability_score": (
            100 * stability_passes / valid_windows if valid_windows else 0.0
        ),
        "stability_band": stability_band,
        "eg_stability": 100 * eg_passes / valid_windows if valid_windows else 0.0,
        "kss_stability": 100 * kss_passes / valid_windows if valid_windows else 0.0,
        "entry_events": entry_events,
        "success_rate": 100 * successes / entry_events if entry_events else None,
        "median_z_change": float(np.median(z_changes)) if z_changes else None,
    }


def _current_method_comparison(aligned: pd.DataFrame) -> dict[str, object]:
    current = aligned.tail(CURRENT_COMPARISON_DAYS)
    if len(current) < MINIMUM_FORMATION_OBSERVATIONS:
        return {
            "p_value": None,
            "half_life": None,
            "zscore": None,
            "passed": False,
            "signal": "not_eligible",
        }
    a = current["a"].to_numpy(dtype=float)
    b = current["b"].to_numpy(dtype=float)
    fitted = _engle_granger(a, b)
    if fitted is None:
        return {
            "p_value": None,
            "half_life": None,
            "zscore": None,
            "passed": False,
            "signal": "not_eligible",
        }
    p_value, alpha, beta = fitted
    spread = a - alpha - beta * b
    half_life = _spread_half_life(spread)
    spread_series = pd.Series(spread)
    mean = spread_series.rolling(60).mean()
    standard_deviation = spread_series.rolling(60).std(ddof=1).replace(0, np.nan)
    zscore = float(((spread_series - mean) / standard_deviation).iloc[-1])
    eligible = (
        beta > 0
        and half_life is not None
        and 2 <= half_life <= MAX_HALF_LIFE_DAYS
        and math.isfinite(zscore)
    )
    passed = eligible and p_value <= DEFAULT_P_VALUE_THRESHOLD
    signal = "not_eligible"
    if eligible:
        signal = "watch"
        if zscore <= -2:
            signal = "long_a_short_b"
        elif zscore >= 2:
            signal = "short_a_long_b"
    return {
        "p_value": p_value,
        "half_life": half_life,
        "zscore": zscore if math.isfinite(zscore) else None,
        "passed": bool(passed),
        "signal": signal,
    }


def _build_candidate(
    test: FormationTest,
    q_value: float,
    members: list[PairUniverseMember],
    closes: pd.DataFrame,
) -> PairMethodLabCandidate | None:
    if (
        test.beta <= 0
        or test.half_life_days is None
        or test.adaptive_lookback_days is None
        or test.current_zscore is None
        or not 0 < test.half_life_days <= MAX_HALF_LIFE_DAYS
    ):
        return None
    member_a = members[test.stock_a_index]
    member_b = members[test.stock_b_index]
    aligned_prices = pd.concat(
        [closes[member_a.ticker], closes[member_b.ticker]],
        axis=1,
        keys=["a", "b"],
    ).dropna()
    aligned_prices = aligned_prices[(aligned_prices["a"] > 0) & (aligned_prices["b"] > 0)]
    if len(aligned_prices) < MINIMUM_FORMATION_OBSERVATIONS:
        return None
    validation = _rolling_validation(aligned_prices["a"], aligned_prices["b"])
    current = _current_method_comparison(np.log(aligned_prices))

    zscore = test.current_zscore
    if zscore <= -2:
        paper_signal = "long_a_short_b"
        long_ticker, short_ticker = member_a.ticker, member_b.ticker
    elif zscore >= 2:
        paper_signal = "short_a_long_b"
        long_ticker, short_ticker = member_b.ticker, member_a.ticker
    else:
        paper_signal = "inside_entry_band"
        long_ticker = short_ticker = None

    paper_pass = test.p_value <= ENGLE_GRANGER_CUTOFF or test.kss_pass
    current_pass = bool(current["passed"])
    if paper_pass and current_pass:
        comparison = "both_methods"
    elif paper_pass:
        comparison = "paper_only"
    elif current_pass:
        comparison = "current_only"
    else:
        comparison = "neither"

    formation_prices = aligned_prices.tail(FORMATION_DAYS)
    spread = (
        formation_prices["a"] - test.alpha - test.beta * formation_prices["b"]
    )
    lookback = test.adaptive_lookback_days
    zseries = (
        spread - spread.rolling(lookback).mean()
    ) / spread.rolling(lookback).std(ddof=1).replace(0, np.nan)
    rolling_mean = spread.rolling(lookback).mean()
    spread_gap = float(spread.iloc[-1] - rolling_mean.iloc[-1])
    latest_price_a = float(formation_prices["a"].iloc[-1])
    latest_price_b = float(formation_prices["b"].iloc[-1])
    convergence_return = potential_convergence_return_percent(
        spread_gap=spread_gap,
        beta=test.beta,
        price_a=latest_price_a,
        price_b=latest_price_b,
    )
    chart_prices = formation_prices.tail(126)
    chart_z = zseries.reindex(chart_prices.index)
    base_a = float(chart_prices["a"].iloc[0])
    base_b = float(chart_prices["b"].iloc[0])
    chart = [
        PairMethodLabChartPoint(
            date=pd.Timestamp(index).date().isoformat(),
            stock_a_indexed=round(float(row["a"]) / base_a * 100, 2),
            stock_b_indexed=round(float(row["b"]) / base_b * 100, 2),
            paper_zscore=(
                round(float(chart_z.loc[index]), 3)
                if pd.notna(chart_z.loc[index]) and math.isfinite(float(chart_z.loc[index]))
                else None
            ),
        )
        for index, row in chart_prices.iterrows()
    ]
    tracker_diagnostics = tracker_entry_diagnostics(
        engle_granger_pass=test.p_value <= ENGLE_GRANGER_CUTOFF,
        kss_pass=test.kss_pass,
        fdr_q_value=float(q_value),
        current_zscore=zscore,
        potential_convergence_return_percent=convergence_return,
        zscore_history=[point.paper_zscore for point in chart],
    )
    sector = (
        member_a.sector
        if member_a.sector == member_b.sector
        else f"{member_a.sector} · {member_b.sector}"
    )
    return PairMethodLabCandidate(
        pair_id=f"{member_a.ticker}-{member_b.ticker}",
        stock_a=member_a.ticker,
        stock_a_name=member_a.name,
        stock_a_type=member_a.instrument_type,
        stock_b=member_b.ticker,
        stock_b_name=member_b.name,
        stock_b_type=member_b.instrument_type,
        sector=sector,
        hedge_ratio=round(test.beta, 4),
        return_correlation=round(test.correlation, 3),
        observations=test.observations,
        engle_granger_p_value=test.p_value,
        fdr_q_value=float(q_value),
        engle_granger_pass=test.p_value <= ENGLE_GRANGER_CUTOFF,
        kss_statistic=round(test.kss_statistic, 4),
        kss_critical_value=KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL,
        kss_pass=test.kss_pass,
        half_life_days=round(test.half_life_days, 1),
        adaptive_lookback_days=lookback,
        current_zscore=round(zscore, 3),
        latest_price_a=round(latest_price_a, 2),
        latest_price_b=round(latest_price_b, 2),
        spread_gap_to_mean=round(spread_gap, 4),
        potential_convergence_return_percent=round(convergence_return, 3),
        paper_signal=paper_signal,
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        tracker_entry_type=tracker_diagnostics["entry_type"],
        tracker_recent_peak_abs_zscore=tracker_diagnostics[
            "recent_peak_abs_zscore"
        ],
        tracker_remaining_return_percent=tracker_diagnostics[
            "remaining_return_percent"
        ],
        rolling_windows=int(validation["rolling_windows"] or 0),
        stability_passed_windows=int(validation["stability_passes"] or 0),
        stability_score_percent=round(
            float(validation["stability_score"] or 0), 1
        ),
        stability_band=validation["stability_band"],
        engle_granger_stability_percent=round(float(validation["eg_stability"] or 0), 1),
        kss_stability_percent=round(float(validation["kss_stability"] or 0), 1),
        entry_events=int(validation["entry_events"] or 0),
        reversion_success_rate_percent=(
            round(float(validation["success_rate"]), 1)
            if validation["success_rate"] is not None
            else None
        ),
        median_five_day_z_change=(
            round(float(validation["median_z_change"]), 3)
            if validation["median_z_change"] is not None
            else None
        ),
        current_method_p_value=current["p_value"],
        current_method_half_life_days=(
            round(float(current["half_life"]), 1)
            if current["half_life"] is not None
            else None
        ),
        current_method_zscore=(
            round(float(current["zscore"]), 3)
            if current["zscore"] is not None
            else None
        ),
        current_method_pass=current_pass,
        current_method_signal=current["signal"],
        comparison=comparison,
        chart=chart,
    )


def scan_paper_method_matrix(
    members: list[PairUniverseMember],
    closes: pd.DataFrame,
) -> tuple[list[PairMethodLabCandidate], dict[str, int]]:
    if closes.empty or len(members) < 2:
        return [], {
            "price_eligible_universe": 0,
            "pairs_tested": 0,
            "engle_granger_candidates": 0,
            "kss_candidates": 0,
            "either_test_candidates": 0,
        }
    closes = closes.reindex(columns=[member.ticker for member in members])
    eligible = closes.where(closes > 0).count(axis=0) >= FORMATION_DAYS
    eligible_indices = [index for index, value in enumerate(eligible) if value]
    formation = closes.tail(FORMATION_DAYS).where(closes.tail(FORMATION_DAYS) > 0)
    formation_prices = formation.to_numpy(dtype=float)
    tests: list[FormationTest] = []
    for offset, stock_a_index in enumerate(eligible_indices[:-1]):
        for stock_b_index in eligible_indices[offset + 1 :]:
            result = _formation_test(stock_a_index, stock_b_index, formation_prices)
            if result is not None:
                tests.append(result)
    q_values = benjamini_hochberg([test.p_value for test in tests])
    significant = [
        (test, float(q_value))
        for test, q_value in zip(tests, q_values, strict=True)
        if test.beta > 0
        and test.half_life_days is not None
        and 0 < test.half_life_days <= MAX_HALF_LIFE_DAYS
        and (test.p_value <= ENGLE_GRANGER_CUTOFF or test.kss_pass)
    ]
    significant.sort(
        key=lambda item: (
            item[1],
            not (item[0].p_value <= ENGLE_GRANGER_CUTOFF and item[0].kss_pass),
            -abs(item[0].current_zscore or 0),
            item[0].half_life_days or math.inf,
            item[0].p_value,
        )
    )
    candidates = [
        candidate
        for test, q_value in significant[:MAX_DEEP_CANDIDATES]
        if (candidate := _build_candidate(test, q_value, members, closes)) is not None
    ]
    candidates.sort(
        key=lambda item: (
            item.fdr_q_value,
            not (item.engle_granger_pass and item.kss_pass),
            -abs(item.current_zscore),
            -item.stability_score_percent,
            item.half_life_days,
            item.pair_id,
        )
    )
    return candidates[:MAX_RESULTS_TO_CACHE], {
        "price_eligible_universe": len(eligible_indices),
        "pairs_tested": len(tests),
        "engle_granger_candidates": sum(
            test.p_value <= ENGLE_GRANGER_CUTOFF and test.beta > 0 for test in tests
        ),
        "kss_candidates": sum(test.kss_pass and test.beta > 0 for test in tests),
        "either_test_candidates": len(significant),
    }


def _filter_payload(payload: dict, *, limit: int, cached: bool) -> dict:
    payload = dict(payload)
    payload["cached"] = cached
    payload["results"] = list(payload.get("results", []))[:limit]
    payload["returned"] = len(payload["results"])
    return payload


async def get_pair_method_lab(
    db: AsyncSession,
    *,
    limit: int = 24,
    refresh: bool = False,
) -> PairMethodLabResponse:
    members, counts = await _eligible_fno_members(db)
    fingerprint = ",".join(
        f"{member.ticker}:{round(member.market_cap_native) if member.market_cap_native else 'index'}"
        for member in members
    )
    cache = FileCache(get_settings().cache_path, "pair_method_lab")
    key = cache_key("arxiv-2109.10662-nse-daily-spot-tracking-v14", fingerprint)
    cached = None if refresh else cache.get(key, PAIR_METHOD_CACHE_TTL_SECONDS)
    if cached is not None:
        return PairMethodLabResponse.model_validate(
            _filter_payload(cached, limit=limit, cached=True)
        )
    closes, _ = await asyncio.to_thread(_download_history_sync, members)
    results, metrics = await asyncio.to_thread(scan_paper_method_matrix, members, closes)
    futures_contracts, futures_price_date = await _latest_futures_contracts(
        {member.ticker for member in members}
    )
    results = attach_futures_capital_plans(
        results,
        futures_contracts,
        futures_price_date,
    )
    response = PairMethodLabResponse(
        paper_title=PAPER_TITLE,
        paper_url=PAPER_URL,
        official_underlyings=counts["official_underlyings"],
        universe_size=len(members),
        price_eligible_universe=metrics["price_eligible_universe"],
        pairs_tested=metrics["pairs_tested"],
        formation_days=FORMATION_DAYS,
        current_comparison_days=CURRENT_COMPARISON_DAYS,
        trading_days=TRADING_DAYS,
        rolling_validation_windows=ROLLING_VALIDATION_WINDOWS,
        engle_granger_cutoff=ENGLE_GRANGER_CUTOFF,
        kss_critical_value=KSS_CRITICAL_VALUE_0_01_PERCENT_RESIDUAL,
        engle_granger_candidates=metrics["engle_granger_candidates"],
        kss_candidates=metrics["kss_candidates"],
        either_test_candidates=metrics["either_test_candidates"],
        returned=len(results),
        generated_at=datetime.now(UTC),
        data_source="Yahoo Finance adjusted daily history + current NSE F&O universe",
        results=results,
        limitations=[
            "Development experiment only; it does not alter the production pair scanner or create trade orders.",
            "The current-scanner comparison inside this lab is deliberately refitted on the paper method's 252 trading days. The production pair scanner separately uses exactly the latest 250 common trading observations.",
            "The paper used minute cryptocurrency data, three-month formation windows, one-week execution data, and BitMEX market microstructure. This NSE comparison uses 252 daily formation observations and five daily validation observations because equivalent licensed intraday history is unavailable.",
            "Both admission tests are tightened to an approximately 0.01% pair-level threshold (99.99% significance). Engle-Granger uses p <= 0.0001; KSS uses a residual-specific -5.04 critical statistic calibrated from 1,000,000 independent 252-day random-walk pairs under the no-cointegration null.",
            "Every eligible F&O pair is screened in the latest formation window. Up to 160 candidates are ordered by Benjamini-Hochberg q-value before the deeper six-window validation. The tracker separately requires both tests, q <= 0.05 and |Z| >= 1.7 for entry. The half-life-derived adaptive window is reserved for Z-score estimation and is not used to shorten the cointegration-test sample.",
            "The lab implements the paper's pair scenario (Engle-Granger, KSS, OU half-life, adaptive Z-score window). Its nine-coin Johansen basket and crypto maker-rebate results are not treated as directly transferable to NSE stock futures.",
            "The KSS 0.01% cutoff is a reproducible Monte Carlo calibration for Gaussian random-walk innovations and the lab's exact sample length and lag specification. Different innovation distributions, volatility regimes, or lag choices can produce a different finite-sample cutoff.",
            "Daily closes do not model bid/ask spread, futures basis, brokerage, taxes, slippage, margin, rollover, or whether a signal could actually be filled.",
            "Potential convergence return is a conditional gross-notional percentage: it assumes the latest raw-price hedge reaches its adaptive rolling mean. It is not probability-weighted and is not an expected or guaranteed realised return.",
            "Long, short and combined capital figures are gross futures notionals for whole lots at the nearest common official NSE expiry. They are exposure measures, not the broker margin or cash actually paid.",
        ],
    )
    payload = response.model_dump(mode="json")
    cache.put(key, payload, source=response.data_source)
    return PairMethodLabResponse.model_validate(
        _filter_payload(payload, limit=limit, cached=False)
    )
