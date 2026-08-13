"""Live walk-forward evaluation of the FPCA-VAR implied-volatility model."""

import asyncio
import logging
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import desc, select

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.models import IVModelEvaluation
from app.services.market_data.iv_surface import (
    EXPLAINED_VARIANCE_TARGET_PERCENT,
    MINIMUM_VALIDATION_SURFACES,
    MODEL_NAME,
    MODEL_VERSION,
    SURFACE_DATA_VERSION,
    TARGET_HISTORY_SURFACES,
    _fit_fpca_core,
    _historical_surface_for_date,
    _select_component_count,
    _smooth_surface,
    fit_fpca_var,
    load_historical_surfaces,
)
from app.services.market_data.path_dependent_ssvi import (
    get_cached_path_dependent_backtest,
)
from app.services.technical_scanner import get_fno_underlyings

logger = logging.getLogger(__name__)
INDIA_TZ = ZoneInfo("Asia/Kolkata")
EVIDENCE_TARGET = 100
MEANINGFUL_MOVE_VOL_POINTS = 0.25
COLLECTION_LOCK = asyncio.Lock()
HISTORICAL_MAX_GAP_DAYS = 4
HISTORICAL_BOOTSTRAP_SAMPLES = 5_000
HISTORICAL_BACKTEST_VERSION = "historical-fpca-v2-economic-verdict"

# A sector-diverse, liquid subset keeps the daily exchange workload bounded while
# still producing 25 independent next-session observations per completed session.
DEFAULT_SYMBOLS = (
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "BAJFINANCE",
    "INFY",
    "TCS",
    "ITC",
    "BHARTIARTL",
    "LT",
    "MARUTI",
    "M&M",
    "TATASTEEL",
    "JSWSTEEL",
    "SUNPHARMA",
    "DRREDDY",
    "CIPLA",
    "HINDUNILVR",
    "NTPC",
    "POWERGRID",
    "ONGC",
    "COALINDIA",
    "INDIGO",
    "DIXON",
    "MANKIND",
    "RBLBANK",
    "SHREECEM",
    "BAJAJFINSV",
)


def _next_weekday(value: date) -> date:
    candidate = value + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _rmse(errors: np.ndarray) -> float:
    return float(np.sqrt(np.mean(errors**2)))


def _score_surfaces(
    forecast: np.ndarray,
    baseline: np.ndarray,
    actual: np.ndarray,
) -> dict[str, float]:
    model_rmse = _rmse(actual - forecast)
    baseline_rmse = _rmse(actual - baseline)
    predicted_move = forecast - baseline
    actual_move = actual - baseline
    meaningful = np.abs(predicted_move) >= MEANINGFUL_MOVE_VOL_POINTS
    directional_accuracy = (
        float(
            np.mean(
                np.sign(predicted_move[meaningful])
                == np.sign(actual_move[meaningful])
            )
            * 100
        )
        if np.any(meaningful)
        else 0.0
    )
    return {
        "model_rmse": model_rmse,
        "baseline_rmse": baseline_rmse,
        "improvement_over_baseline_percent": (
            (baseline_rmse - model_rmse) / baseline_rmse * 100
            if baseline_rmse > 1e-12
            else 0.0
        ),
        "directional_accuracy_percent": directional_accuracy,
        "bias_vol_points": float(np.mean(forecast - actual)),
    }


def _pooled_rmse(values: list[float]) -> float:
    return float(np.sqrt(np.mean(np.square(values))))


def _rmse_improvement(model_rmse: float, baseline_rmse: float) -> float:
    return (
        (baseline_rmse - model_rmse) / baseline_rmse * 100
        if baseline_rmse > 1e-12
        else 0.0
    )


def _cluster_bootstrap_improvement(
    observations: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None]:
    """Resample target sessions, keeping same-day cross-sectional dependence intact."""

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped[str(observation["target_date"])].append(observation)
    target_dates = sorted(grouped)
    if len(target_dates) < 2:
        return None, None, None

    rng = np.random.default_rng(20_260_811)
    improvements = np.empty(HISTORICAL_BOOTSTRAP_SAMPLES)
    for sample_index in range(HISTORICAL_BOOTSTRAP_SAMPLES):
        sampled_dates = rng.choice(target_dates, len(target_dates), replace=True)
        sampled = [item for value in sampled_dates for item in grouped[str(value)]]
        model_rmse = _pooled_rmse([item["model_rmse"] for item in sampled])
        baseline_rmse = _pooled_rmse([item["baseline_rmse"] for item in sampled])
        improvements[sample_index] = _rmse_improvement(model_rmse, baseline_rmse)
    lower, upper = np.quantile(improvements, [0.025, 0.975])
    return (
        float(lower),
        float(upper),
        float(np.mean(improvements > 0) * 100),
    )


def historical_walk_forward_backtest(
    histories: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Run a causal next-observed-session test on cached NSE option surfaces.

    Every target surface is excluded from its fit. Histories with gaps longer
    than a normal weekend/one-day holiday are excluded because VAR(5) assumes
    equally spaced trading-session observations.
    """

    observations: list[dict[str, Any]] = []
    excluded_for_gaps = 0
    for symbol, history in histories.items():
        dates = [date.fromisoformat(str(value)) for value in history.get("dates") or []]
        surfaces = np.asarray(history.get("surfaces") or [], dtype=float)
        if len(dates) != len(surfaces) or surfaces.ndim != 3:
            continue
        smoothed = np.asarray([_smooth_surface(surface) for surface in surfaces])
        for target_index in range(MINIMUM_VALIDATION_SURFACES, len(smoothed)):
            # A single old missing surface must not invalidate every later target
            # in a multi-year history. Only the VAR(5) lag window and target must
            # represent consecutive observed sessions.
            observed_dates = dates[max(0, target_index - 6) : target_index + 1]
            if any(
                not 0 < (right - left).days <= HISTORICAL_MAX_GAP_DAYS
                for left, right in zip(observed_dates, observed_dates[1:], strict=False)
            ):
                excluded_for_gaps += 1
                continue

            training = smoothed[:target_index]
            flat = training.reshape(len(training), -1)
            centered = flat - flat.mean(axis=0)
            singular_values = np.linalg.svd(
                centered,
                full_matrices=False,
                compute_uv=False,
            )
            variances = singular_values**2
            cumulative = np.cumsum(variances) / float(variances.sum()) * 100
            component_count, _ = _select_component_count(cumulative)
            fit = _fit_fpca_core(training, component_count)
            actual = smoothed[target_index]
            baseline = training[-1]
            forecast = np.asarray(fit["forecast_surface"], dtype=float)
            metrics = _score_surfaces(forecast, baseline, actual)
            predicted_move = forecast - baseline
            actual_move = actual - baseline
            meaningful = np.abs(predicted_move) >= MEANINGFUL_MOVE_VOL_POINTS
            observations.append(
                {
                    "ticker": symbol,
                    "source_date": dates[target_index - 1].isoformat(),
                    "target_date": dates[target_index].isoformat(),
                    "component_count": component_count,
                    "explained_variance_percent": float(
                        fit["explained_variance_percent"]
                    ),
                    "reconstruction_rmse": float(fit["reconstruction_rmse"]),
                    "model_rmse": metrics["model_rmse"],
                    "baseline_rmse": metrics["baseline_rmse"],
                    "directional_hits": int(
                        np.sum(
                            np.sign(predicted_move[meaningful])
                            == np.sign(actual_move[meaningful])
                        )
                    ),
                    "directional_cells": int(np.sum(meaningful)),
                }
            )

    if not observations:
        return {
            "available": False,
            "verdict": "Insufficient continuous history",
            "verdict_detail": (
                f"At least {MINIMUM_VALIDATION_SURFACES + 1} consecutive usable "
                "option surfaces are needed for a historical target."
            ),
            "observations": 0,
            "excluded_for_gaps": excluded_for_gaps,
            "source": "Official NSE F&O bhavcopy closing prices",
        }

    model_rmse = _pooled_rmse([item["model_rmse"] for item in observations])
    baseline_rmse = _pooled_rmse([item["baseline_rmse"] for item in observations])
    improvement = _rmse_improvement(model_rmse, baseline_rmse)
    lower, upper, probability_positive = _cluster_bootstrap_improvement(observations)
    directional_cells = sum(item["directional_cells"] for item in observations)
    directional_hits = sum(item["directional_hits"] for item in observations)
    direction = (
        directional_hits / directional_cells * 100 if directional_cells else None
    )
    grouped_symbols: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        grouped_symbols[observation["ticker"]].append(observation)
    per_symbol = []
    for symbol, values in grouped_symbols.items():
        symbol_model_rmse = _pooled_rmse([item["model_rmse"] for item in values])
        symbol_baseline_rmse = _pooled_rmse(
            [item["baseline_rmse"] for item in values]
        )
        symbol_directional_cells = sum(item["directional_cells"] for item in values)
        per_symbol.append(
            {
                "ticker": symbol,
                "observations": len(values),
                "model_rmse": symbol_model_rmse,
                "baseline_rmse": symbol_baseline_rmse,
                "improvement_over_baseline_percent": _rmse_improvement(
                    symbol_model_rmse,
                    symbol_baseline_rmse,
                ),
                "model_win_rate_percent": (
                    sum(item["model_rmse"] < item["baseline_rmse"] for item in values)
                    / len(values)
                    * 100
                ),
                "directional_accuracy_percent": (
                    sum(item["directional_hits"] for item in values)
                    / symbol_directional_cells
                    * 100
                    if symbol_directional_cells
                    else None
                ),
            }
        )
    per_symbol.sort(key=lambda item: item["improvement_over_baseline_percent"], reverse=True)

    statistically_positive = lower is not None and lower > 0
    clears_thresholds = (
        improvement >= 10
        and (direction or 0) >= 55
        and statistically_positive
    )
    if clears_thresholds:
        verdict = "Historical forecasting edge"
        verdict_detail = (
            "FPCA–VAR beat no-change with a positive date-clustered confidence "
            "interval and cleared the configured RMSE and direction thresholds."
        )
    elif improvement <= 0:
        verdict = "Failed historical baseline test"
        verdict_detail = (
            "The adaptive FPCA representation captures surface variance, but its "
            "VAR forecast did not reduce next-session error versus no change."
        )
    elif statistically_positive:
        verdict = "Statistically positive but economically small"
        verdict_detail = (
            "FPCA–VAR beat no-change with a positive date-clustered confidence "
            "interval, but the RMSE improvement remains below the configured 10% "
            "production threshold."
        )
    else:
        verdict = "Historical edge is inconclusive"
        verdict_detail = (
            "Point-estimate RMSE improved, but the date-clustered evidence does not "
            "yet establish a reliable forecasting advantage."
        )

    component_counts = Counter(item["component_count"] for item in observations)
    return {
        "available": True,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "observations": len(observations),
        "symbols": len(grouped_symbols),
        "target_sessions": len({item["target_date"] for item in observations}),
        "first_target_date": min(item["target_date"] for item in observations),
        "last_target_date": max(item["target_date"] for item in observations),
        "excluded_for_gaps": excluded_for_gaps,
        "model_rmse": model_rmse,
        "baseline_rmse": baseline_rmse,
        "improvement_over_baseline_percent": improvement,
        "improvement_confidence_interval_95": [lower, upper],
        "bootstrap_probability_model_beats_baseline_percent": probability_positive,
        "model_win_rate_percent": (
            sum(
                item["model_rmse"] < item["baseline_rmse"]
                for item in observations
            )
            / len(observations)
            * 100
        ),
        "directional_accuracy_percent": direction,
        "meaningful_directional_cells": directional_cells,
        "average_explained_variance_percent": float(
            np.mean([item["explained_variance_percent"] for item in observations])
        ),
        "average_reconstruction_rmse": float(
            np.mean([item["reconstruction_rmse"] for item in observations])
        ),
        "component_counts": {
            str(component_count): component_counts.get(component_count, 0)
            for component_count in range(3, 9)
        },
        "per_symbol": per_symbol,
        "source": "Official NSE F&O bhavcopy closing prices",
        "methodology": (
            "Expanding-window, one-observed-session-ahead forecasts with the target "
            "surface excluded from fitting; target sessions are cluster-bootstrapped."
        ),
        "limitation": (
            "This validates IV-surface prediction, not option-strategy P&L. Premium, "
            "spread, theta, delta and execution effects require contract-level replay."
        ),
    }


def cached_surface_histories() -> dict[str, dict[str, Any]]:
    cache = FileCache(get_settings().cache_path, "iv_surfaces")
    histories = {}
    for symbol in DEFAULT_SYMBOLS:
        history = cache.get(cache_key(SURFACE_DATA_VERSION, symbol), None)
        if history is not None:
            histories[symbol] = history
    return histories


def _history_fingerprint(histories: dict[str, dict[str, Any]]) -> str:
    return ",".join(
        f"{symbol}:{len(history.get('dates') or [])}:"
        f"{(history.get('dates') or [''])[0]}:{(history.get('dates') or [''])[-1]}"
        for symbol, history in sorted(histories.items())
    )


def cached_historical_backtest(*, force_refresh: bool = False) -> dict[str, Any]:
    histories = cached_surface_histories()
    cache = FileCache(get_settings().cache_path, "iv_model_evaluation")
    key = cache_key(
        MODEL_VERSION,
        HISTORICAL_BACKTEST_VERSION,
        "historical-backtest",
        _history_fingerprint(histories),
    )
    latest_key = cache_key(
        MODEL_VERSION,
        HISTORICAL_BACKTEST_VERSION,
        "historical-backtest-latest",
    )
    if not force_refresh:
        cached = cache.get(key, 6 * 60 * 60)
        if cached is not None:
            return cached
        latest = cache.get(latest_key, None)
        if latest is not None:
            return latest
    result = historical_walk_forward_backtest(histories)
    for cache_entry in (key, latest_key):
        cache.put(
            cache_entry,
            result,
            source="Official NSE F&O bhavcopy closing prices",
            model_name=MODEL_NAME,
        )
    return result


async def path_dependent_historical_backtest(
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    return await get_cached_path_dependent_backtest(
        cached_surface_histories(),
        force_refresh=force_refresh,
    )


async def _build_candidate(symbol: str, now: datetime) -> tuple[dict[str, Any] | None, str | None]:
    try:
        dates, surfaces = await load_historical_surfaces(symbol, force_refresh=True)
        if not dates:
            return None, "No valid surface history was available."
        source_date = date.fromisoformat(dates[-1])
        target_date = _next_weekday(source_date)
        today = now.astimezone(INDIA_TZ).date()
        local_time = now.astimezone(INDIA_TZ).time()
        if target_date < today:
            return None, f"Latest surface {source_date} is stale; target {target_date} has passed."
        if target_date == today and local_time >= time(9, 15):
            return None, "Target session has already opened; forecast was not recorded."

        fit = await asyncio.to_thread(fit_fpca_var, surfaces)
        component_count = int(fit["component_count"])
        baseline = _smooth_surface(np.asarray(surfaces[-1], dtype=float))
        return (
            {
                "ticker": symbol,
                "symbol": symbol,
                "model_version": MODEL_VERSION,
                "status": "pending",
                "generated_at": now,
                "source_as_of_date": source_date,
                "target_date": target_date,
                "component_count": component_count,
                "explained_variance_percent": round(
                    float(fit["explained_variance_percent"]), 4
                ),
                "reconstruction_rmse": round(float(fit["reconstruction_rmse"]), 6),
                "validation_sessions": int(fit["validation_sessions"]),
                "validation_model_rmse": float(
                    fit["validation_rmse_by_components"][str(component_count)]
                ),
                "validation_baseline_rmse": float(fit["validation_baseline_rmse"]),
                "validation_improvement_percent": float(
                    fit["validation_improvement_over_baseline_percent"]
                ),
                "validation_directional_accuracy_percent": fit[
                    "validation_directional_accuracy_percent"
                ],
                "forecast_surface": np.asarray(fit["forecast_surface"]).tolist(),
                "baseline_surface": baseline.tolist(),
            },
            None,
        )
    except Exception as exc:
        return None, str(exc)


async def _collect_forward_forecasts_unlocked(limit: int = 30) -> dict[str, Any]:
    """Persist only forecasts created before their target NSE session opens."""

    now = datetime.now(UTC)
    fno_symbols = await get_fno_underlyings()
    symbols = [symbol for symbol in DEFAULT_SYMBOLS if symbol in fno_symbols][:limit]
    semaphore = asyncio.Semaphore(2)

    async def build(symbol: str):
        async with semaphore:
            candidate, error = await _build_candidate(symbol, now)
            return symbol, candidate, error

    values = await asyncio.gather(*(build(symbol) for symbol in symbols))
    created = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    async with get_session_factory()() as db:
        for symbol, candidate, error in values:
            if candidate is None:
                skipped += 1
                if error:
                    errors.append({"ticker": symbol, "reason": error})
                continue
            existing = (
                await db.execute(
                    select(IVModelEvaluation.id).where(
                        IVModelEvaluation.ticker == symbol,
                        IVModelEvaluation.target_date == candidate["target_date"],
                        IVModelEvaluation.model_version == MODEL_VERSION,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                skipped += 1
                continue
            db.add(IVModelEvaluation(**candidate))
            created += 1
        await db.commit()
    return {
        "attempted": len(symbols),
        "created": created,
        "skipped": skipped,
        "errors": errors[:10],
        "generated_at": now,
    }


async def collect_forward_forecasts(limit: int = 30) -> dict[str, Any]:
    """Serialize collection so a manual run cannot race the daily recorder."""

    async with COLLECTION_LOCK:
        return await _collect_forward_forecasts_unlocked(limit)


async def score_pending_forecasts() -> dict[str, int]:
    """Score pending forecasts once the official target-session surface exists."""

    today = datetime.now(INDIA_TZ).date()
    async with get_session_factory()() as db:
        pending = list(
            (
                await db.execute(
                    select(IVModelEvaluation).where(
                        IVModelEvaluation.status == "pending",
                        IVModelEvaluation.target_date <= today,
                    )
                )
            )
            .scalars()
            .all()
        )
        semaphore = asyncio.Semaphore(4)

        async def actual_for(item: IVModelEvaluation):
            async with semaphore:
                surface = await _historical_surface_for_date(
                    item.symbol, item.target_date
                )
                return item, surface

        resolved = await asyncio.gather(*(actual_for(item) for item in pending))
        scored = 0
        for item, surface in resolved:
            if surface is None:
                continue
            actual = _smooth_surface(np.asarray(surface, dtype=float))
            forecast = np.asarray(item.forecast_surface, dtype=float)
            baseline = np.asarray(item.baseline_surface, dtype=float)
            metrics = _score_surfaces(forecast, baseline, actual)
            item.actual_surface = actual.tolist()
            item.model_rmse = metrics["model_rmse"]
            item.baseline_rmse = metrics["baseline_rmse"]
            item.improvement_over_baseline_percent = metrics[
                "improvement_over_baseline_percent"
            ]
            item.directional_accuracy_percent = metrics[
                "directional_accuracy_percent"
            ]
            item.bias_vol_points = metrics["bias_vol_points"]
            item.status = "scored"
            item.scored_at = datetime.now(UTC)
            scored += 1
        await db.commit()
    return {"pending_checked": len(pending), "scored": scored}


def _average(values: list[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


async def evaluation_report() -> dict[str, Any]:
    async with get_session_factory()() as db:
        records = list(
            (
                await db.execute(
                    select(IVModelEvaluation)
                    .where(IVModelEvaluation.model_version == MODEL_VERSION)
                    .order_by(desc(IVModelEvaluation.generated_at))
                )
            )
            .scalars()
            .all()
        )
    scored = [item for item in records if item.status == "scored"]
    model_rmse = _average([item.model_rmse for item in scored])
    baseline_rmse = _average([item.baseline_rmse for item in scored])
    improvement = (
        (baseline_rmse - model_rmse) / baseline_rmse * 100
        if model_rmse is not None and baseline_rmse not in (None, 0)
        else None
    )
    explained = _average([item.explained_variance_percent for item in records])
    reconstruction = _average([item.reconstruction_rmse for item in records])
    direction = _average([item.directional_accuracy_percent for item in scored])
    model_wins = sum(
        1
        for item in scored
        if item.model_rmse is not None
        and item.baseline_rmse is not None
        and item.model_rmse < item.baseline_rmse
    )
    histories = cached_surface_histories()
    history_counts = [len(item.get("dates") or []) for item in histories.values()]
    history_dates = [
        date.fromisoformat(str(value))
        for item in histories.values()
        for value in (item.get("dates") or [])
    ]
    surface_history_coverage = {
        "symbols": len(histories),
        "total_surfaces": sum(history_counts),
        "minimum_surfaces_per_symbol": min(history_counts) if history_counts else 0,
        "maximum_surfaces_per_symbol": max(history_counts) if history_counts else 0,
        "first_date": min(history_dates).isoformat() if history_dates else None,
        "last_date": max(history_dates).isoformat() if history_dates else None,
        "target_surfaces_per_symbol": TARGET_HISTORY_SURFACES,
        "source": "Official NSE current and legacy F&O bhavcopies",
    }
    historical_backtest, path_dependent_backtest = await asyncio.gather(
        asyncio.to_thread(cached_historical_backtest),
        path_dependent_historical_backtest(),
    )

    if len(scored) < EVIDENCE_TARGET:
        verdict = "Collecting evidence"
        verdict_detail = (
            f"{len(scored)} clean next-session forecasts are scored. Do not decide "
            f"whether to replace FPCA or VAR before at least {EVIDENCE_TARGET}."
        )
    elif (
        explained is not None
        and explained < EXPLAINED_VARIANCE_TARGET_PERCENT
    ):
        verdict = "Review FPCA representation"
        verdict_detail = (
            f"Average retained variance is below {EXPLAINED_VARIANCE_TARGET_PERCENT:.0f}%, "
            "so the surface compression or grid should be improved before blaming "
            "the VAR forecast."
        )
    elif improvement is not None and improvement <= 0:
        verdict = "VAR is not adding value"
        verdict_detail = (
            "FPCA retains the surface structure, but FPCA-VAR is not beating the "
            "no-change forecast. Test a different score-dynamics model."
        )
    elif improvement is not None and improvement >= 10 and (direction or 0) >= 55:
        verdict = "Promising forecasting edge"
        verdict_detail = (
            "The model clears the current RMSE and directional thresholds. Continue "
            "regime and transaction-cost validation before production use."
        )
    else:
        verdict = "Weak or inconclusive edge"
        verdict_detail = (
            "The model has not cleared both a 10% RMSE improvement and 55% direction "
            "accuracy. Keep it in research and compare alternative VAR specifications."
        )

    return {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "evidence_target": EVIDENCE_TARGET,
        "scored_forecasts": len(scored),
        "pending_forecasts": sum(item.status == "pending" for item in records),
        "covered_symbols": len({item.ticker for item in records}),
        "average_explained_variance_percent": explained,
        "average_reconstruction_rmse": reconstruction,
        "model_rmse": model_rmse,
        "baseline_rmse": baseline_rmse,
        "improvement_over_baseline_percent": improvement,
        "directional_accuracy_percent": direction,
        "model_win_rate_percent": model_wins / len(scored) * 100 if scored else None,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "surface_history_coverage": surface_history_coverage,
        "historical_backtest": historical_backtest,
        "path_dependent_backtest": path_dependent_backtest,
        "thresholds": {
            "fpca_explained_variance_healthy_percent": (
                EXPLAINED_VARIANCE_TARGET_PERCENT
            ),
            "minimum_rmse_improvement_percent": 10,
            "minimum_directional_accuracy_percent": 55,
            "minimum_scored_forecasts": EVIDENCE_TARGET,
        },
        "records": [
            {
                "id": str(item.id),
                "ticker": item.ticker,
                "status": item.status,
                "generated_at": item.generated_at,
                "source_as_of_date": item.source_as_of_date,
                "target_date": item.target_date,
                "component_count": item.component_count,
                "explained_variance_percent": item.explained_variance_percent,
                "reconstruction_rmse": item.reconstruction_rmse,
                "validation_sessions": item.validation_sessions,
                "validation_model_rmse": item.validation_model_rmse,
                "validation_baseline_rmse": item.validation_baseline_rmse,
                "validation_improvement_percent": item.validation_improvement_percent,
                "validation_directional_accuracy_percent": item.validation_directional_accuracy_percent,
                "model_rmse": item.model_rmse,
                "baseline_rmse": item.baseline_rmse,
                "improvement_over_baseline_percent": item.improvement_over_baseline_percent,
                "directional_accuracy_percent": item.directional_accuracy_percent,
                "bias_vol_points": item.bias_vol_points,
                "scored_at": item.scored_at,
            }
            for item in records[:250]
        ],
    }


async def run_iv_model_evaluation_recorder() -> None:
    """Once daily, score matured forecasts and record the next eligible session."""

    last_run_date: date | None = None
    while True:
        try:
            now = datetime.now(INDIA_TZ)
            eligible_time = now.time() >= time(18, 0) or now.time() < time(9, 0)
            if now.weekday() < 5 and eligible_time and last_run_date != now.date():
                await score_pending_forecasts()
                await collect_forward_forecasts()
                last_run_date = now.date()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("IV model evaluation recorder failed", exc_info=True)
        await asyncio.sleep(15 * 60)
