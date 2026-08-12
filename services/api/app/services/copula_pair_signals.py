"""Copula entry and exit signals for strict pair-method candidates.

The cited paper models two stationary spreads sharing a reference asset. This NSE
adaptation uses NIFTY as that reference, daily observations instead of hourly crypto
data, and the existing lab's stricter dual-test plus BH-q admission gate.
"""

from __future__ import annotations

import asyncio
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import cauchy, kendalltau, multivariate_t, norm
from scipy.stats import t as student_t
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.schemas.copula_pair_signals import (
    CopulaPairSignal,
    CopulaPairSignalsResponse,
    CopulaSignalPoint,
)
from app.services.pair_method_lab import (
    MAX_RESULTS_TO_CACHE,
    TRACKER_FDR_Q_CUTOFF,
    _download_history_sync,
    get_pair_method_lab,
    kss_test,
)
from app.services.pair_suggestions import _eligible_fno_members

PAPER_TITLE = "Copula-Based Trading of Cointegrated Cryptocurrency Pairs"
PAPER_URL = "https://arxiv.org/abs/2305.06961"
REFERENCE_TICKER = "NIFTY"
FORMATION_DAYS = 252
TRADING_DAYS = 5
ENTRY_THRESHOLD = 0.10
EXIT_THRESHOLD = 0.10
MINIMUM_OBSERVATIONS = FORMATION_DAYS + TRADING_DAYS
CACHE_TTL_SECONDS = 6 * 60 * 60
PIT_EPSILON = 1e-6

Signal = Literal[
    "enter_long_a_short_b",
    "enter_short_a_long_b",
    "exit",
    "watch",
]


@dataclass(frozen=True)
class MarginalFit:
    name: Literal["Gaussian", "Student-t", "Cauchy"]
    parameters: tuple[float, ...]
    aic: float
    cdf: Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class CopulaFit:
    family: Literal["Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"]
    parameter: float
    degrees_of_freedom: float | None
    aic: float


def _finite(values: np.ndarray) -> np.ndarray:
    output = np.asarray(values, dtype=float)
    return output[np.isfinite(output)]


def fit_best_marginal(values: np.ndarray) -> MarginalFit:
    """Fit the paper's Gaussian, Student-t and Cauchy margins by AIC."""

    sample = _finite(values)
    if len(sample) < 40 or float(np.std(sample, ddof=1)) <= 1e-12:
        raise ValueError("A non-degenerate marginal needs at least 40 observations.")
    candidates: list[MarginalFit] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        specifications = (
            ("Gaussian", norm, 2),
            ("Student-t", student_t, 3),
            ("Cauchy", cauchy, 2),
        )
        for name, distribution, parameter_count in specifications:
            try:
                parameters = tuple(float(value) for value in distribution.fit(sample))
                log_likelihood = float(np.sum(distribution.logpdf(sample, *parameters)))
                if not math.isfinite(log_likelihood):
                    continue
                aic = 2 * parameter_count - 2 * log_likelihood
                candidates.append(
                    MarginalFit(
                        name=name,
                        parameters=parameters,
                        aic=aic,
                        cdf=lambda points, d=distribution, p=parameters: np.asarray(
                            d.cdf(points, *p), dtype=float
                        ),
                    )
                )
            except (ValueError, FloatingPointError, OverflowError):
                continue
    if not candidates:
        raise ValueError("None of the supported marginal distributions could be fitted.")
    return min(candidates, key=lambda candidate: (candidate.aic, candidate.name))


def _clip_pit(values: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(values, dtype=float), PIT_EPSILON, 1 - PIT_EPSILON)


def _gaussian_log_likelihood(uv: np.ndarray, rho: float) -> float:
    if not -0.995 < rho < 0.995:
        return -math.inf
    z = norm.ppf(uv)
    denominator = 1 - rho * rho
    log_density = (
        -0.5 * math.log(denominator)
        - (z[:, 0] ** 2 - 2 * rho * z[:, 0] * z[:, 1] + z[:, 1] ** 2)
        / (2 * denominator)
        + 0.5 * (z[:, 0] ** 2 + z[:, 1] ** 2)
    )
    return float(np.sum(log_density))


def _student_log_likelihood(uv: np.ndarray, rho: float, degrees: float) -> float:
    if not -0.995 < rho < 0.995 or not 2.01 < degrees <= 80:
        return -math.inf
    transformed = student_t.ppf(uv, degrees)
    try:
        joint = multivariate_t.logpdf(
            transformed,
            shape=np.array([[1.0, rho], [rho, 1.0]]),
            df=degrees,
        )
        marginal = student_t.logpdf(transformed[:, 0], degrees) + student_t.logpdf(
            transformed[:, 1], degrees
        )
    except (ValueError, np.linalg.LinAlgError):
        return -math.inf
    result = float(np.sum(joint - marginal))
    return result if math.isfinite(result) else -math.inf


def _clayton_log_likelihood(uv: np.ndarray, theta: float) -> float:
    if theta <= 0:
        return -math.inf
    u, v = uv[:, 0], uv[:, 1]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        total = u ** (-theta) + v ** (-theta) - 1
        density = (
            math.log1p(theta)
            + (-1 - theta) * (np.log(u) + np.log(v))
            + (-2 - 1 / theta) * np.log(total)
        )
    result = float(np.sum(density))
    return result if math.isfinite(result) else -math.inf


def _gumbel_log_likelihood(uv: np.ndarray, theta: float) -> float:
    if theta < 1:
        return -math.inf
    u, v = uv[:, 0], uv[:, 1]
    x, y = -np.log(u), -np.log(v)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        total = x**theta + y**theta
        root = total ** (1 / theta)
        log_density = (
            -root
            - np.log(u)
            - np.log(v)
            + (theta - 1) * (np.log(x) + np.log(y))
            + (2 / theta - 2) * np.log(total)
            + np.log1p((theta - 1) * total ** (-1 / theta))
        )
    result = float(np.sum(log_density))
    return result if math.isfinite(result) else -math.inf


def _frank_log_likelihood(uv: np.ndarray, theta: float) -> float:
    if abs(theta) < 1e-3 or abs(theta) > 40:
        return -math.inf
    u, v = uv[:, 0], uv[:, 1]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        denominator = np.expm1(-theta)
        part_u = np.expm1(-theta * u)
        part_v = np.expm1(-theta * v)
        inner = denominator + part_u * part_v
        numerator = -theta * denominator
        log_density = (
            math.log(numerator)
            - theta * (u + v)
            - 2 * np.log(np.abs(inner))
        )
    result = float(np.sum(log_density))
    return result if math.isfinite(result) else -math.inf


def fit_best_copula(u: np.ndarray, v: np.ndarray) -> CopulaFit:
    """Select a compact set of paper copula families by pseudo-likelihood AIC."""

    uv = np.column_stack((_clip_pit(u), _clip_pit(v)))
    if len(uv) < 40:
        raise ValueError("A copula fit needs at least 40 paired observations.")
    tau = float(kendalltau(uv[:, 0], uv[:, 1], nan_policy="omit").statistic)
    if not math.isfinite(tau):
        raise ValueError("Kendall's tau is unavailable for this pair.")
    candidates: list[CopulaFit] = []

    gaussian = minimize_scalar(
        lambda rho: -_gaussian_log_likelihood(uv, float(rho)),
        bounds=(-0.98, 0.98),
        method="bounded",
    )
    if gaussian.success and math.isfinite(float(gaussian.fun)):
        candidates.append(
            CopulaFit("Gaussian", float(gaussian.x), None, 2 + 2 * float(gaussian.fun))
        )

    initial_rho = float(np.clip(math.sin(math.pi * tau / 2), -0.9, 0.9))
    student = minimize(
        lambda parameters: -_student_log_likelihood(
            uv, float(parameters[0]), float(parameters[1])
        ),
        x0=np.array([initial_rho, 8.0]),
        bounds=((-0.98, 0.98), (2.05, 60.0)),
        method="L-BFGS-B",
    )
    if student.success and math.isfinite(float(student.fun)):
        candidates.append(
            CopulaFit(
                "Student-t",
                float(student.x[0]),
                float(student.x[1]),
                4 + 2 * float(student.fun),
            )
        )

    if tau > 0:
        clayton = minimize_scalar(
            lambda theta: -_clayton_log_likelihood(uv, float(theta)),
            bounds=(0.01, 30.0),
            method="bounded",
        )
        if clayton.success and math.isfinite(float(clayton.fun)):
            candidates.append(
                CopulaFit("Clayton", float(clayton.x), None, 2 + 2 * float(clayton.fun))
            )
        gumbel = minimize_scalar(
            lambda theta: -_gumbel_log_likelihood(uv, float(theta)),
            bounds=(1.001, 20.0),
            method="bounded",
        )
        if gumbel.success and math.isfinite(float(gumbel.fun)):
            candidates.append(
                CopulaFit("Gumbel", float(gumbel.x), None, 2 + 2 * float(gumbel.fun))
            )

    frank_bounds = (0.01, 35.0) if tau >= 0 else (-35.0, -0.01)
    frank = minimize_scalar(
        lambda theta: -_frank_log_likelihood(uv, float(theta)),
        bounds=frank_bounds,
        method="bounded",
    )
    if frank.success and math.isfinite(float(frank.fun)):
        candidates.append(
            CopulaFit("Frank", float(frank.x), None, 2 + 2 * float(frank.fun))
        )

    if not candidates:
        raise ValueError("None of the supported copula families could be fitted.")
    return min(candidates, key=lambda candidate: (candidate.aic, candidate.family))


def conditional_probabilities(
    fit: CopulaFit,
    u: np.ndarray | float,
    v: np.ndarray | float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return h(A|B) and h(B|A), the paper's two mispricing indices."""

    u_values = _clip_pit(np.atleast_1d(np.asarray(u, dtype=float)))
    v_values = _clip_pit(np.atleast_1d(np.asarray(v, dtype=float)))
    parameter = fit.parameter
    if fit.family == "Gaussian":
        z_u, z_v = norm.ppf(u_values), norm.ppf(v_values)
        scale = math.sqrt(1 - parameter * parameter)
        first = norm.cdf((z_u - parameter * z_v) / scale)
        second = norm.cdf((z_v - parameter * z_u) / scale)
    elif fit.family == "Student-t":
        degrees = float(fit.degrees_of_freedom or 8.0)
        z_u, z_v = student_t.ppf(u_values, degrees), student_t.ppf(v_values, degrees)
        base = 1 - parameter * parameter
        first_scale = np.sqrt((degrees + 1) / ((degrees + z_v**2) * base))
        second_scale = np.sqrt((degrees + 1) / ((degrees + z_u**2) * base))
        first = student_t.cdf((z_u - parameter * z_v) * first_scale, degrees + 1)
        second = student_t.cdf((z_v - parameter * z_u) * second_scale, degrees + 1)
    elif fit.family == "Clayton":
        total = u_values ** (-parameter) + v_values ** (-parameter) - 1
        first = v_values ** (-parameter - 1) * total ** (-1 / parameter - 1)
        second = u_values ** (-parameter - 1) * total ** (-1 / parameter - 1)
    elif fit.family == "Gumbel":
        x, y = -np.log(u_values), -np.log(v_values)
        total = x**parameter + y**parameter
        copula = np.exp(-(total ** (1 / parameter)))
        first = (
            copula
            * total ** (1 / parameter - 1)
            * y ** (parameter - 1)
            / v_values
        )
        second = (
            copula
            * total ** (1 / parameter - 1)
            * x ** (parameter - 1)
            / u_values
        )
    else:
        denominator = np.expm1(-parameter)
        part_u = np.expm1(-parameter * u_values)
        part_v = np.expm1(-parameter * v_values)
        inner = denominator + part_u * part_v
        first = part_u * np.exp(-parameter * v_values) / inner
        second = part_v * np.exp(-parameter * u_values) / inner
    return _clip_pit(first), _clip_pit(second)


def classify_signal(h_a_given_b: float, h_b_given_a: float) -> Signal:
    if h_a_given_b < ENTRY_THRESHOLD and h_b_given_a > 1 - ENTRY_THRESHOLD:
        return "enter_short_a_long_b"
    if h_a_given_b > 1 - ENTRY_THRESHOLD and h_b_given_a < ENTRY_THRESHOLD:
        return "enter_long_a_short_b"
    if (
        abs(h_a_given_b - 0.5) < EXIT_THRESHOLD
        and abs(h_b_given_a - 0.5) < EXIT_THRESHOLD
    ):
        return "exit"
    return "watch"


def _reference_spread(reference: np.ndarray, asset: np.ndarray) -> tuple[float, np.ndarray]:
    denominator = float(asset @ asset)
    if denominator <= 0:
        raise ValueError("Reference-spread regression is degenerate.")
    beta = float(asset @ reference / denominator)
    spread = reference - beta * asset
    if not math.isfinite(beta) or beta <= 0 or not np.isfinite(spread).all():
        raise ValueError("Reference-spread regression produced invalid values.")
    return beta, spread


def _explanation(signal: Signal, stock_a: str, stock_b: str) -> str:
    if signal == "enter_long_a_short_b":
        return f"Copula tails indicate {stock_a} is relatively undervalued: long {stock_a}, short {stock_b}."
    if signal == "enter_short_a_long_b":
        return f"Copula tails indicate {stock_b} is relatively undervalued: long {stock_b}, short {stock_a}."
    if signal == "exit":
        return "Both conditional probabilities are inside the paper's 40%–60% equilibrium band."
    return "The two conditional probabilities do not jointly satisfy an entry or exit rule."


def build_copula_signal(candidate, closes: pd.DataFrame) -> CopulaPairSignal | None:
    columns = [REFERENCE_TICKER, candidate.stock_a, candidate.stock_b]
    if candidate.stock_a == REFERENCE_TICKER or candidate.stock_b == REFERENCE_TICKER:
        return None
    if not set(columns).issubset(closes.columns):
        return None
    aligned = closes[columns].replace([np.inf, -np.inf], np.nan).dropna()
    aligned = aligned[(aligned > 0).all(axis=1)].tail(MINIMUM_OBSERVATIONS)
    if len(aligned) < MINIMUM_OBSERVATIONS:
        return None
    formation = aligned.iloc[:FORMATION_DAYS]
    reference = formation[REFERENCE_TICKER].to_numpy(dtype=float)
    beta_a, spread_a = _reference_spread(
        reference, formation[candidate.stock_a].to_numpy(dtype=float)
    )
    beta_b, spread_b = _reference_spread(
        reference, formation[candidate.stock_b].to_numpy(dtype=float)
    )
    marginal_a = fit_best_marginal(spread_a)
    marginal_b = fit_best_marginal(spread_b)
    u_formation = _clip_pit(marginal_a.cdf(spread_a))
    v_formation = _clip_pit(marginal_b.cdf(spread_b))
    copula = fit_best_copula(u_formation, v_formation)

    all_reference = aligned[REFERENCE_TICKER].to_numpy(dtype=float)
    all_spread_a = all_reference - beta_a * aligned[candidate.stock_a].to_numpy(dtype=float)
    all_spread_b = all_reference - beta_b * aligned[candidate.stock_b].to_numpy(dtype=float)
    all_u = _clip_pit(marginal_a.cdf(all_spread_a))
    all_v = _clip_pit(marginal_b.cdf(all_spread_b))
    all_h_a, all_h_b = conditional_probabilities(copula, all_u, all_v)
    h_a, h_b = float(all_h_a[-1]), float(all_h_b[-1])
    signal = classify_signal(h_a, h_b)
    long_ticker = short_ticker = None
    long_weight = short_weight = None
    if signal == "enter_long_a_short_b":
        long_ticker, short_ticker = candidate.stock_a, candidate.stock_b
        long_weight, short_weight = beta_a, beta_b
    elif signal == "enter_short_a_long_b":
        long_ticker, short_ticker = candidate.stock_b, candidate.stock_a
        long_weight, short_weight = beta_b, beta_a

    history_start = max(0, FORMATION_DAYS - 30)
    history = [
        CopulaSignalPoint(
            date=pd.Timestamp(index).date().isoformat(),
            h_a_given_b=round(float(all_h_a[position]), 4),
            h_b_given_a=round(float(all_h_b[position]), 4),
            phase="formation" if position < FORMATION_DAYS else "trading",
        )
        for position, index in enumerate(aligned.index)
        if position >= history_start
    ]
    kss_a = kss_test(spread_a)
    kss_b = kss_test(spread_b)
    tau = float(kendalltau(u_formation, v_formation, nan_policy="omit").statistic)
    return CopulaPairSignal(
        pair_id=candidate.pair_id,
        stock_a=candidate.stock_a,
        stock_a_name=candidate.stock_a_name,
        stock_b=candidate.stock_b,
        stock_b_name=candidate.stock_b_name,
        sector=candidate.sector,
        engle_granger_p_value=candidate.engle_granger_p_value,
        fdr_q_value=candidate.fdr_q_value,
        kss_statistic=candidate.kss_statistic,
        reference_ticker=REFERENCE_TICKER,
        reference_beta_a=round(beta_a, 6),
        reference_beta_b=round(beta_b, 6),
        reference_kss_a=round(kss_a.statistic, 4) if kss_a else None,
        reference_kss_b=round(kss_b.statistic, 4) if kss_b else None,
        marginal_a=marginal_a.name,
        marginal_b=marginal_b.name,
        marginal_a_aic=round(marginal_a.aic, 2),
        marginal_b_aic=round(marginal_b.aic, 2),
        copula_family=copula.family,
        copula_parameter=round(copula.parameter, 6),
        copula_degrees_of_freedom=(
            round(copula.degrees_of_freedom, 3)
            if copula.degrees_of_freedom is not None
            else None
        ),
        copula_aic=round(copula.aic, 2),
        kendall_tau=round(tau, 4),
        h_a_given_b=round(h_a, 4),
        h_b_given_a=round(h_b, 4),
        signal=signal,
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        long_weight=round(long_weight, 6) if long_weight is not None else None,
        short_weight=round(short_weight, 6) if short_weight is not None else None,
        signal_explanation=_explanation(signal, candidate.stock_a, candidate.stock_b),
        history=history,
    )


def _filter_payload(payload: dict, *, limit: int, cached: bool) -> dict:
    output = dict(payload)
    output["cached"] = cached
    output["results"] = list(output.get("results", []))[:limit]
    output["returned"] = len(output["results"])
    return output


async def get_copula_pair_signals(
    db: AsyncSession,
    *,
    limit: int = 24,
    refresh: bool = False,
) -> CopulaPairSignalsResponse:
    members, _ = await _eligible_fno_members(db)
    fingerprint = ",".join(member.ticker for member in members)
    cache = FileCache(get_settings().cache_path, "copula_pair_signals")
    key = cache_key("arxiv-2305.06961-nifty-daily-v1", fingerprint)
    cached = None if refresh else cache.get(key, CACHE_TTL_SECONDS)
    if cached is not None:
        return CopulaPairSignalsResponse.model_validate(
            _filter_payload(cached, limit=limit, cached=True)
        )

    lab = await get_pair_method_lab(
        db,
        limit=MAX_RESULTS_TO_CACHE,
        refresh=refresh,
    )
    candidates = [
        candidate
        for candidate in lab.results
        if candidate.engle_granger_pass
        and candidate.kss_pass
        and candidate.fdr_q_value < TRACKER_FDR_Q_CUTOFF
        and REFERENCE_TICKER not in {candidate.stock_a, candidate.stock_b}
    ]
    needed = {REFERENCE_TICKER} | {
        ticker
        for candidate in candidates
        for ticker in (candidate.stock_a, candidate.stock_b)
    }
    selected_members = [member for member in members if member.ticker in needed]
    closes, _ = await asyncio.to_thread(_download_history_sync, selected_members)
    results: list[CopulaPairSignal] = []
    for candidate in candidates:
        try:
            signal = await asyncio.to_thread(build_copula_signal, candidate, closes)
        except (ValueError, FloatingPointError, OverflowError, np.linalg.LinAlgError):
            signal = None
        if signal is not None:
            results.append(signal)
    signal_order = {
        "enter_long_a_short_b": 0,
        "enter_short_a_long_b": 0,
        "exit": 1,
        "watch": 2,
    }
    results.sort(
        key=lambda item: (
            signal_order[item.signal],
            item.fdr_q_value,
            item.copula_aic,
            item.pair_id,
        )
    )
    response = CopulaPairSignalsResponse(
        paper_title=PAPER_TITLE,
        paper_url=PAPER_URL,
        reference_ticker=REFERENCE_TICKER,
        formation_days=FORMATION_DAYS,
        trading_days=TRADING_DAYS,
        entry_threshold=ENTRY_THRESHOLD,
        exit_threshold=EXIT_THRESHOLD,
        fdr_q_cutoff=TRACKER_FDR_Q_CUTOFF,
        dual_test_candidates=len(candidates),
        entry_signals=sum(item.signal.startswith("enter_") for item in results),
        exit_signals=sum(item.signal == "exit" for item in results),
        returned=len(results),
        generated_at=datetime.now(UTC),
        data_source="Yahoo Finance adjusted daily closes + current NSE F&O universe",
        results=results,
        limitations=[
            "Research signal only; it does not create, close or size paper or live trades.",
            "The cited paper uses hourly cryptocurrency futures, BTC as a shared reference, three-week formation and one-week trading windows. This adaptation uses adjusted daily NSE prices, NIFTY as the reference, 252 formation days and five trading days.",
            "Pair admission remains stricter than the paper: the direct stock pair must pass both the existing Engle-Granger and residual-calibrated KSS tests with BH q < 0.05.",
            "Gaussian, Student-t, Clayton, Frank and Gumbel copulas are compared by pseudo-likelihood AIC. The paper additionally evaluates rotated and multi-parameter BB/Tawn families that are not included here.",
            "The page reports conditional-probability rules, not expected profit. It excludes futures basis, execution costs, slippage, margin, borrow constraints and taxes.",
        ],
    )
    payload = response.model_dump(mode="json")
    cache.put(key, payload, source=response.data_source)
    return CopulaPairSignalsResponse.model_validate(
        _filter_payload(payload, limit=limit, cached=False)
    )
