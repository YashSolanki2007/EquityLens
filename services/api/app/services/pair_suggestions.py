"""Exhaustive, cached Engle-Granger scan over liquid NSE F&O stocks."""

import asyncio
import io
import logging
import math
import warnings
import zipfile
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from statsmodels.tools.sm_exceptions import CollinearityWarning
from statsmodels.tsa.stattools import coint

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.models import Company, CompanyMarketSnapshot
from app.schemas.pairs import PairChartPoint, PairSuggestion, PairSuggestionsResponse
from app.services.market_data.yahoo import get_market_snapshot
from app.services.nse.client import get_nse_client
from app.services.technical_scanner import get_fno_underlyings

logger = logging.getLogger(__name__)

MINIMUM_MARKET_CAP_INR = 500 * 10_000_000
PAIR_HISTORY_PERIOD = "2y"
PAIR_FORMATION_DAYS = 250
MINIMUM_OBSERVATIONS = PAIR_FORMATION_DAYS
PAIR_SCAN_CACHE_TTL_SECONDS = 6 * 60 * 60
ROLLING_ZSCORE_DAYS = 60
MAX_RESULTS_TO_CACHE = 200
EXAMPLE_MAX_LEG_VALUE_INR = 100_000
MAX_FUTURES_CONTRACTS_PER_LEG = 12
FUTURES_HEDGE_TOLERANCE = 0.15
DEFAULT_P_VALUE_THRESHOLD = 0.001
MIN_P_VALUE_THRESHOLD = 0.0001
MAX_P_VALUE_THRESHOLD = 0.05
P_VALUE_THRESHOLDS = (0.0001, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05)
FNO_INDEXES = {
    "NIFTY": ("NIFTY 50", "^NSEI"),
    "BANKNIFTY": ("NIFTY Bank", "^NSEBANK"),
    "FINNIFTY": ("NIFTY Financial Services", "NIFTY_FIN_SERVICE.NS"),
    "MIDCPNIFTY": ("NIFTY Midcap Select", "NIFTY_MID_SELECT.NS"),
    "NIFTYNXT50": ("NIFTY Next 50", "^NSMIDCP"),
}


@dataclass(frozen=True)
class PairUniverseMember:
    ticker: str
    name: str
    sector: str
    market_data_ticker: str
    market_cap_native: float | None
    instrument_type: str = "stock"


@dataclass(frozen=True)
class PairTest:
    stock_a_index: int
    stock_b_index: int
    p_value: float
    alpha: float
    beta: float
    correlation: float
    observations: int


@dataclass(frozen=True)
class FuturesContract:
    ticker: str
    contract_name: str
    expiry: date
    price: float
    lot_size: int
    traded_volume: int


def _futures_contract_counts(
    hedge_ratio: float,
    stock_a_contract_notional: float,
    stock_b_contract_notional: float,
) -> tuple[int, int, float]:
    """Choose the smallest whole-lot combination with an acceptable hedge fit."""

    candidates: list[tuple[float, int, int, int]] = []
    for stock_a_contracts in range(1, MAX_FUTURES_CONTRACTS_PER_LEG + 1):
        for stock_b_contracts in range(1, MAX_FUTURES_CONTRACTS_PER_LEG + 1):
            realized_ratio = (
                stock_b_contracts
                * stock_b_contract_notional
                / (stock_a_contracts * stock_a_contract_notional)
            )
            relative_error = abs(realized_ratio - hedge_ratio) / hedge_ratio
            candidates.append(
                (
                    relative_error,
                    stock_a_contracts + stock_b_contracts,
                    stock_a_contracts,
                    stock_b_contracts,
                )
            )
    acceptable = [
        candidate for candidate in candidates if candidate[0] <= FUTURES_HEDGE_TOLERANCE
    ]
    if acceptable:
        relative_error, _, contracts_a, contracts_b = min(
            acceptable,
            key=lambda candidate: (candidate[1], candidate[0]),
        )
    else:
        relative_error, _, contracts_a, contracts_b = min(
            candidates,
            key=lambda candidate: (candidate[0], candidate[1]),
        )
    hedge_fit_percent = max(0.0, 100 * (1 - relative_error))
    return contracts_a, contracts_b, hedge_fit_percent


def _parse_positive_number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0 else None


async def _latest_futures_contracts(
    symbols: set[str],
) -> tuple[dict[str, list[FuturesContract]], date | None]:
    """Load the latest available official NSE F&O bhavcopy futures rows."""

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    client = get_nse_client()
    for days_back in range(10):
        report_date = today - timedelta(days=days_back)
        if report_date.weekday() >= 5:
            continue
        url = (
            "https://nsearchives.nseindia.com/content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_{report_date:%Y%m%d}_F_0000.csv.zip"
        )
        try:
            response = await client._get(url)
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                names = archive.namelist()
                if not names:
                    continue
                frame = pd.read_csv(archive.open(names[0]))
        except (httpx.HTTPError, zipfile.BadZipFile, ValueError, KeyError):
            continue

        required_columns = {
            "FinInstrmTp",
            "TckrSymb",
            "FinInstrmNm",
            "XpryDt",
            "ClsPric",
            "SttlmPric",
            "NewBrdLotQty",
            "TtlTradgVol",
        }
        if not required_columns.issubset(frame.columns):
            continue
        futures_rows = frame[
            frame["FinInstrmTp"].isin(["STF", "IDF"])
            & frame["TckrSymb"].astype(str).str.upper().isin(symbols)
        ]
        contracts: dict[str, list[FuturesContract]] = {}
        for _, row in futures_rows.iterrows():
            ticker = str(row["TckrSymb"]).strip().upper()
            try:
                expiry = pd.Timestamp(row["XpryDt"]).date()
            except (TypeError, ValueError):
                continue
            price = _parse_positive_number(row["ClsPric"]) or _parse_positive_number(
                row["SttlmPric"]
            )
            lot_size_value = _parse_positive_number(row["NewBrdLotQty"])
            if price is None or lot_size_value is None:
                continue
            contracts.setdefault(ticker, []).append(
                FuturesContract(
                    ticker=ticker,
                    contract_name=str(row["FinInstrmNm"]).strip(),
                    expiry=expiry,
                    price=price,
                    lot_size=int(lot_size_value),
                    traded_volume=int(_parse_positive_number(row["TtlTradgVol"]) or 0),
                )
            )
        if contracts:
            for ticker_contracts in contracts.values():
                ticker_contracts.sort(key=lambda contract: contract.expiry)
            return contracts, report_date
    return {}, None


def _attach_futures_plans(
    suggestions: list[PairSuggestion],
    contracts_by_ticker: dict[str, list[FuturesContract]],
    futures_price_date: date | None,
) -> list[PairSuggestion]:
    """Attach whole-contract NSE futures orders sized near the statistical hedge."""

    enriched: list[PairSuggestion] = []
    for suggestion in suggestions:
        price_date = futures_price_date or datetime.now(ZoneInfo("Asia/Kolkata")).date()
        reversion_date = (
            pd.Timestamp(price_date)
            + pd.offsets.BDay(max(1, math.ceil(suggestion.half_life_days)))
        ).date()
        base_update: dict[str, object] = {
            "futures_price_date": futures_price_date.isoformat()
            if futures_price_date
            else None,
            "estimated_reversion_date": reversion_date.isoformat(),
        }
        contracts_a = {
            contract.expiry: contract
            for contract in contracts_by_ticker.get(suggestion.stock_a, [])
        }
        contracts_b = {
            contract.expiry: contract
            for contract in contracts_by_ticker.get(suggestion.stock_b, [])
        }
        common_expiries = sorted(set(contracts_a) & set(contracts_b))
        if not common_expiries:
            base_update.update(
                {
                    "futures_plan_available": False,
                    "futures_requires_rollover": False,
                    "futures_plan_note": (
                        "Official futures prices for a common expiry were unavailable "
                        "for one or both legs."
                    ),
                }
            )
            enriched.append(suggestion.model_copy(update=base_update))
            continue

        expiry = common_expiries[0]
        requires_rollover = expiry < reversion_date
        contract_a = contracts_a[expiry]
        contract_b = contracts_b[expiry]
        notional_per_contract_a = contract_a.price * contract_a.lot_size
        notional_per_contract_b = contract_b.price * contract_b.lot_size
        count_a, count_b, hedge_fit = _futures_contract_counts(
            suggestion.hedge_ratio,
            notional_per_contract_a,
            notional_per_contract_b,
        )

        if suggestion.long_ticker == suggestion.stock_a:
            long_contract, short_contract = contract_a, contract_b
            long_count, short_count = count_a, count_b
        else:
            long_contract, short_contract = contract_b, contract_a
            long_count, short_count = count_b, count_a
        long_units = long_count * long_contract.lot_size
        short_units = short_count * short_contract.lot_size
        long_notional = long_units * long_contract.price
        short_notional = short_units * short_contract.price
        long_target = long_contract.price * (
            suggestion.example_target_long_price / suggestion.example_long_price
        )
        short_target = short_contract.price * (
            suggestion.example_target_short_price / suggestion.example_short_price
        )
        gross_profit = max(
            0.0,
            long_units * (long_target - long_contract.price)
            + short_units * (short_contract.price - short_target),
        )
        gross_return_percent = gross_profit / (long_notional + short_notional) * 100

        base_update.update(
            {
                "futures_plan_available": True,
                "futures_plan_note": (
                    "The nearest common futures expiry is used. It falls before the "
                    "estimated reversion date, so continuing the trade may require a "
                    "rollover."
                    if requires_rollover
                    else "The nearest common futures expiry is used; actual broker "
                    "margin is variable and must be checked in the order preview."
                ),
                "futures_expiry": expiry.isoformat(),
                "futures_requires_rollover": requires_rollover,
                "long_futures_contract_name": long_contract.contract_name,
                "short_futures_contract_name": short_contract.contract_name,
                "long_futures_price": round(long_contract.price, 2),
                "short_futures_price": round(short_contract.price, 2),
                "long_futures_target_price": round(long_target, 2),
                "short_futures_target_price": round(short_target, 2),
                "long_futures_lot_size": long_contract.lot_size,
                "short_futures_lot_size": short_contract.lot_size,
                "long_futures_contracts": long_count,
                "short_futures_contracts": short_count,
                "long_futures_units": long_units,
                "short_futures_units": short_units,
                "long_futures_notional_inr": round(long_notional, 2),
                "short_futures_notional_inr": round(short_notional, 2),
                "futures_hedge_fit_percent": round(hedge_fit, 1),
                "example_gross_return_percent": round(gross_return_percent, 2),
            }
        )
        enriched.append(suggestion.model_copy(update=base_update))
    return enriched


def benjamini_hochberg(p_values: list[float]) -> np.ndarray:
    """Return monotonic Benjamini-Hochberg adjusted p-values."""

    if not p_values:
        return np.array([], dtype=float)
    values = np.asarray(p_values, dtype=float)
    order = np.argsort(values)
    ranked = values[order]
    adjusted_ranked = ranked * len(values) / np.arange(1, len(values) + 1)
    adjusted_ranked = np.minimum.accumulate(adjusted_ranked[::-1])[::-1]
    adjusted = np.empty_like(adjusted_ranked)
    adjusted[order] = np.clip(adjusted_ranked, 0, 1)
    return adjusted


def _download_pair_history_sync(
    members: list[PairUniverseMember],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    symbols = [member.market_data_ticker for member in members]
    frame = yf.download(
        symbols,
        period=PAIR_HISTORY_PERIOD,
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


def _test_pair(
    stock_a_index: int,
    stock_b_index: int,
    log_prices: np.ndarray,
) -> PairTest | None:
    stock_a = log_prices[:, stock_a_index]
    stock_b = log_prices[:, stock_b_index]
    valid = np.isfinite(stock_a) & np.isfinite(stock_b)
    observations = int(valid.sum())
    if observations < MINIMUM_OBSERVATIONS:
        return None

    # Download a wider buffer so holidays and occasional missing quotes do not
    # make an otherwise eligible pair disappear, but fit every production pair
    # on exactly the latest 250 common trading observations.
    a = stock_a[valid][-PAIR_FORMATION_DAYS:]
    b = stock_b[valid][-PAIR_FORMATION_DAYS:]
    observations = len(a)
    design = np.column_stack((np.ones(observations), b))
    alpha, beta = np.linalg.lstsq(design, a, rcond=None)[0]
    if not math.isfinite(beta):
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", CollinearityWarning)
        try:
            _, p_value, _ = coint(
                a,
                b,
                trend="c",
                maxlag=1,
                autolag=None,
            )
        except (ValueError, np.linalg.LinAlgError):
            return None
    if not math.isfinite(p_value):
        return None

    returns_a = np.diff(a)
    returns_b = np.diff(b)
    correlation = float(np.corrcoef(returns_a, returns_b)[0, 1])
    if not math.isfinite(correlation):
        return None
    return PairTest(
        stock_a_index=stock_a_index,
        stock_b_index=stock_b_index,
        p_value=float(p_value),
        alpha=float(alpha),
        beta=float(beta),
        correlation=correlation,
        observations=observations,
    )


def _spread_half_life(spread: np.ndarray) -> float | None:
    if len(spread) < 30:
        return None
    previous = spread[:-1]
    current = spread[1:]
    design = np.column_stack((np.ones(len(previous)), previous))
    _, phi = np.linalg.lstsq(design, current, rcond=None)[0]
    if not math.isfinite(phi) or phi <= 0 or phi >= 1:
        return None
    half_life = math.log(0.5) / math.log(phi)
    return float(half_life) if math.isfinite(half_life) else None


def _median_daily_value_crore(
    closes: pd.Series,
    volumes: pd.Series,
) -> float | None:
    values = (closes * volumes).dropna().tail(60)
    if values.empty:
        return None
    value = float(values.median() / 10_000_000)
    return round(value, 2) if math.isfinite(value) else None


def _build_suggestion(
    test: PairTest,
    q_value: float,
    members: list[PairUniverseMember],
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
) -> PairSuggestion | None:
    member_a = members[test.stock_a_index]
    member_b = members[test.stock_b_index]
    aligned = pd.concat(
        [closes[member_a.ticker], closes[member_b.ticker]],
        axis=1,
        keys=["a", "b"],
    ).dropna()
    aligned = aligned[(aligned["a"] > 0) & (aligned["b"] > 0)]
    if len(aligned) < MINIMUM_OBSERVATIONS:
        return None
    aligned = aligned.tail(PAIR_FORMATION_DAYS)

    log_a = np.log(aligned["a"].to_numpy(dtype=float))
    log_b = np.log(aligned["b"].to_numpy(dtype=float))
    spread = log_a - test.alpha - test.beta * log_b
    half_life = _spread_half_life(spread)
    if half_life is None or not 2 <= half_life <= 90:
        return None

    spread_series = pd.Series(spread, index=aligned.index)
    rolling_mean = spread_series.rolling(ROLLING_ZSCORE_DAYS).mean()
    rolling_std = spread_series.rolling(ROLLING_ZSCORE_DAYS).std(ddof=1)
    zscores = (spread_series - rolling_mean) / rolling_std.replace(0, np.nan)
    current_zscore = float(zscores.iloc[-1])
    if not math.isfinite(current_zscore):
        return None
    current_spread_gap = float(spread_series.iloc[-1] - rolling_mean.iloc[-1])

    if current_zscore > 0:
        signal = "short_a_long_b" if current_zscore >= 2 else "watch"
        long_ticker, short_ticker = member_b.ticker, member_a.ticker
        direction = f"{member_a.ticker} is rich relative to {member_b.ticker}"
    else:
        signal = "long_a_short_b" if current_zscore <= -2 else "watch"
        long_ticker, short_ticker = member_a.ticker, member_b.ticker
        direction = f"{member_a.ticker} is cheap relative to {member_b.ticker}"

    latest_price_a = float(aligned["a"].iloc[-1])
    latest_price_b = float(aligned["b"].iloc[-1])
    target_value_a = EXAMPLE_MAX_LEG_VALUE_INR / max(1, test.beta)
    target_value_b = test.beta * target_value_a
    quantity_a = max(1, round(target_value_a / latest_price_a))
    quantity_b = max(1, round(target_value_b / latest_price_b))
    if long_ticker == member_a.ticker:
        example_long_quantity = quantity_a
        example_short_quantity = quantity_b
        example_long_price = latest_price_a
        example_short_price = latest_price_b
    else:
        example_long_quantity = quantity_b
        example_short_quantity = quantity_a
        example_long_price = latest_price_b
        example_short_price = latest_price_a

    # There are infinitely many price paths that can return the spread to its
    # rolling centre. Use the minimum-total-log-move path so both legs contribute
    # in the proportions implied by the fitted relationship.
    correction_denominator = 1 + test.beta**2
    target_return_a = -current_spread_gap / correction_denominator
    target_return_b = test.beta * current_spread_gap / correction_denominator
    target_price_a = latest_price_a * math.exp(target_return_a)
    target_price_b = latest_price_b * math.exp(target_return_b)
    if long_ticker == member_a.ticker:
        example_target_long_price = target_price_a
        example_target_short_price = target_price_b
    else:
        example_target_long_price = target_price_b
        example_target_short_price = target_price_a
    example_long_value = example_long_quantity * example_long_price
    example_short_value = example_short_quantity * example_short_price
    example_gross_profit = (
        example_long_quantity * (example_target_long_price - example_long_price)
        + example_short_quantity * (example_short_price - example_target_short_price)
    )
    example_gross_profit = max(0.0, example_gross_profit)
    example_gross_return_percent = (
        example_gross_profit / (example_long_value + example_short_value) * 100
    )

    chart_frame = aligned.tail(126)
    chart_zscores = zscores.reindex(chart_frame.index)
    base_a = float(chart_frame["a"].iloc[0])
    base_b = float(chart_frame["b"].iloc[0])
    chart = [
        PairChartPoint(
            date=pd.Timestamp(index).date().isoformat(),
            stock_a_indexed=round(float(row["a"]) / base_a * 100, 2),
            stock_b_indexed=round(float(row["b"]) / base_b * 100, 2),
            spread_zscore=(
                round(float(chart_zscores.loc[index]), 3)
                if math.isfinite(float(chart_zscores.loc[index]))
                else None
            ),
        )
        for index, row in chart_frame.iterrows()
    ]

    sector = (
        member_a.sector
        if member_a.sector == member_b.sector
        else f"{member_a.sector} · {member_b.sector}"
    )
    return PairSuggestion(
        pair_id=f"{member_a.ticker}-{member_b.ticker}",
        stock_a=member_a.ticker,
        stock_a_name=member_a.name,
        stock_a_type=member_a.instrument_type,
        stock_b=member_b.ticker,
        stock_b_name=member_b.name,
        stock_b_type=member_b.instrument_type,
        sector=sector,
        signal=signal,
        long_ticker=long_ticker,
        short_ticker=short_ticker,
        example_long_quantity=example_long_quantity,
        example_short_quantity=example_short_quantity,
        example_long_price=round(example_long_price, 2),
        example_short_price=round(example_short_price, 2),
        example_long_value_inr=round(example_long_value, 2),
        example_short_value_inr=round(example_short_value, 2),
        example_target_long_price=round(example_target_long_price, 2),
        example_target_short_price=round(example_target_short_price, 2),
        example_gross_return_percent=round(example_gross_return_percent, 2),
        explanation=(
            f"{direction}. Their historical relationship has usually moved back "
            f"toward normal in about {half_life:.0f} trading days."
        ),
        hedge_ratio=round(test.beta, 4),
        current_zscore=round(current_zscore, 3),
        # Preserve the test precision. Rounding a small, non-zero p-value to
        # 0.0000 made large day-to-day FDR changes look mathematically
        # inconsistent in the UI.
        cointegration_p_value=float(test.p_value),
        fdr_q_value=float(q_value),
        half_life_days=round(half_life, 1),
        return_correlation=round(test.correlation, 3),
        observations=test.observations,
        stock_a_market_cap_crore=(
            round(member_a.market_cap_native / 10_000_000, 1)
            if member_a.market_cap_native is not None
            else None
        ),
        stock_b_market_cap_crore=(
            round(member_b.market_cap_native / 10_000_000, 1)
            if member_b.market_cap_native is not None
            else None
        ),
        stock_a_median_daily_value_crore=_median_daily_value_crore(
            aligned["a"], volumes[member_a.ticker]
        ),
        stock_b_median_daily_value_crore=_median_daily_value_crore(
            aligned["b"], volumes[member_b.ticker]
        ),
        chart=chart,
    )


def scan_pair_matrix(
    members: list[PairUniverseMember],
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
) -> tuple[list[PairSuggestion], int, list[dict[str, int | float]], int]:
    """Test every available pair and return ranked, FDR-controlled suggestions."""

    if closes.empty or len(members) < 2:
        return [], 0, [], 0
    closes = closes.reindex(columns=[member.ticker for member in members])
    volumes = volumes.reindex(index=closes.index, columns=closes.columns)
    price_eligible_universe = int(
        (closes.where(closes > 0).count(axis=0) >= MINIMUM_OBSERVATIONS).sum()
    )
    log_prices = np.log(closes.where(closes > 0).to_numpy(dtype=float))

    tests: list[PairTest] = []
    for stock_a_index in range(len(members) - 1):
        for stock_b_index in range(stock_a_index + 1, len(members)):
            result = _test_pair(stock_a_index, stock_b_index, log_prices)
            if result is not None:
                tests.append(result)

    q_values = benjamini_hochberg([test.p_value for test in tests])
    suggestions = []
    for test, q_value in zip(tests, q_values, strict=True):
        if test.p_value > MAX_P_VALUE_THRESHOLD or test.beta <= 0:
            continue
        suggestion = _build_suggestion(test, float(q_value), members, closes, volumes)
        if suggestion is not None:
            suggestions.append(suggestion)

    suggestions.sort(
        key=lambda item: (
            item.signal == "watch",
            -abs(item.current_zscore),
            item.half_life_days,
            -item.return_correlation,
            item.pair_id,
        )
    )
    threshold_counts = [
        {
            "threshold": threshold,
            "p_significant_pairs": sum(
                suggestion.cointegration_p_value <= threshold
                for suggestion in suggestions
            ),
        }
        for threshold in P_VALUE_THRESHOLDS
    ]
    # Keep enough of the best-ranked candidates for every selectable cutoff.
    # A single global slice can otherwise be dominated by looser-p candidates
    # and leave a stricter dropdown value with too few results.
    cached_suggestions: list[PairSuggestion] = []
    cached_pair_ids: set[str] = set()
    for threshold in P_VALUE_THRESHOLDS:
        eligible_at_threshold = 0
        for suggestion in suggestions:
            if suggestion.cointegration_p_value > threshold:
                continue
            eligible_at_threshold += 1
            if suggestion.pair_id not in cached_pair_ids:
                cached_pair_ids.add(suggestion.pair_id)
                cached_suggestions.append(suggestion)
            if eligible_at_threshold >= MAX_RESULTS_TO_CACHE:
                break
    cached_suggestions.sort(
        key=lambda item: (
            item.signal == "watch",
            -abs(item.current_zscore),
            item.half_life_days,
            -item.return_correlation,
            item.pair_id,
        )
    )
    return (
        cached_suggestions,
        len(tests),
        threshold_counts,
        price_eligible_universe,
    )


async def _eligible_fno_members(
    db: AsyncSession,
) -> tuple[list[PairUniverseMember], dict[str, int]]:
    fno_symbols = await get_fno_underlyings()
    fno_symbols.discard("SYMBOL")
    index_symbols = set(FNO_INDEXES) & fno_symbols
    stock_symbols = fno_symbols - index_symbols
    companies = (
        (
            await db.execute(
                select(Company)
                .where(
                    Company.universe == "NSE_MAINBOARD",
                    Company.ticker.in_(stock_symbols),
                )
                .order_by(Company.ticker)
            )
        )
        .scalars()
        .all()
    )
    company_ids = [company.id for company in companies]
    latest_snapshot = (
        select(
            CompanyMarketSnapshot.company_id,
            func.max(CompanyMarketSnapshot.retrieved_at).label("retrieved_at"),
        )
        .where(CompanyMarketSnapshot.company_id.in_(company_ids))
        .group_by(CompanyMarketSnapshot.company_id)
        .subquery()
    )
    snapshots = (
        (
            await db.execute(
                select(CompanyMarketSnapshot).join(
                    latest_snapshot,
                    (CompanyMarketSnapshot.company_id == latest_snapshot.c.company_id)
                    & (CompanyMarketSnapshot.retrieved_at == latest_snapshot.c.retrieved_at),
                )
            )
        )
        .scalars()
        .all()
    )
    market_caps = {
        snapshot.company_id: float(snapshot.market_cap_native)
        for snapshot in snapshots
        if snapshot.market_cap_native is not None
    }

    missing = [company for company in companies if company.id not in market_caps]
    semaphore = asyncio.Semaphore(8)

    async def fetch_missing_market_cap(company: Company) -> tuple[object, float | None]:
        async with semaphore:
            snapshot = await get_market_snapshot(
                company.market_data_ticker or f"{company.ticker}.NS"
            )
        value = (snapshot or {}).get("market_cap_native")
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = None
        return company.id, parsed

    if missing:
        fetched = await asyncio.gather(*(fetch_missing_market_cap(company) for company in missing))
        market_caps.update(
            {company_id: market_cap for company_id, market_cap in fetched if market_cap is not None}
        )

    members = [
        PairUniverseMember(
            ticker=company.ticker,
            name=company.name,
            sector=company.sector,
            market_data_ticker=company.market_data_ticker or f"{company.ticker}.NS",
            market_cap_native=market_caps[company.id],
            instrument_type="stock",
        )
        for company in companies
        if market_caps.get(company.id, 0) >= MINIMUM_MARKET_CAP_INR
    ]
    members.extend(
        PairUniverseMember(
            ticker=symbol,
            name=FNO_INDEXES[symbol][0],
            sector="Market index",
            market_data_ticker=FNO_INDEXES[symbol][1],
            market_cap_native=None,
            instrument_type="index",
        )
        for symbol in sorted(index_symbols)
    )
    members.sort(key=lambda member: member.ticker)
    counts = {
        "official_underlyings": len(fno_symbols),
        "stock_underlyings": len(stock_symbols),
        "index_underlyings": len(index_symbols),
        "missing_company_rows": len(stock_symbols) - len(companies),
        "excluded_missing_market_cap": sum(company.id not in market_caps for company in companies),
        "excluded_below_market_cap": sum(
            company.id in market_caps and market_caps[company.id] < MINIMUM_MARKET_CAP_INR
            for company in companies
        ),
    }
    return members, counts


def _filter_cached_payload(
    payload: dict,
    *,
    p_value_threshold: float,
    limit: int,
    cached: bool,
) -> dict:
    selected_counts = next(
        (
            item
            for item in payload.get("threshold_counts", [])
            if item.get("threshold") == p_value_threshold
        ),
        {"p_significant_pairs": 0},
    )
    payload["cached"] = cached
    payload["p_value_threshold"] = p_value_threshold
    payload["p_significant_pairs"] = selected_counts["p_significant_pairs"]
    selected_results = [
        result
        for result in payload.get("results", [])
        if result.get("cointegration_p_value", 1) <= p_value_threshold
    ]
    # Statistical significance controls admission, but it is not a measure of
    # how attractive the current trade is. Rank eligible pairs by current gap
    # and reversion characteristics instead.
    selected_results.sort(
        key=lambda result: (
            result.get("signal") == "watch",
            -abs(float(result.get("current_zscore", 0))),
            float(result.get("half_life_days", math.inf)),
            -float(result.get("return_correlation", 0)),
            str(result.get("pair_id", "")),
        )
    )
    payload["results"] = selected_results[:limit]
    payload["returned"] = len(payload["results"])
    return payload


async def get_pair_suggestions(
    db: AsyncSession,
    *,
    limit: int = 12,
    refresh: bool = False,
    p_value_threshold: float = DEFAULT_P_VALUE_THRESHOLD,
) -> PairSuggestionsResponse:
    p_value_threshold = round(
        min(max(p_value_threshold, MIN_P_VALUE_THRESHOLD), MAX_P_VALUE_THRESHOLD),
        4,
    )
    members, counts = await _eligible_fno_members(db)
    if len(members) < 2:
        return PairSuggestionsResponse(
            official_underlyings=counts["official_underlyings"],
            stock_underlyings=counts["stock_underlyings"],
            index_underlyings=counts["index_underlyings"],
            universe_size=len(members),
            price_eligible_universe=0,
            pairs_tested=0,
            p_value_threshold=p_value_threshold,
            p_significant_pairs=0,
            returned=0,
            generated_at=datetime.now(UTC),
            data_source="NSE F&O universe + stored company market snapshots",
            results=[],
            limitations=[
                "Fewer than two current F&O companies had a stored market capitalization of at least ₹500 crore.",
                "Suggestions are statistical research signals, not investment advice.",
            ],
        )
    fingerprint = ",".join(
        f"{member.ticker}:{round(member.market_cap_native) if member.market_cap_native is not None else 'index'}"
        for member in members
    )
    cache = FileCache(get_settings().cache_path, "pair_suggestions")
    key = cache_key("nse-fno-pairs-v14-250d-window", fingerprint)
    cached = None if refresh else cache.get(key, PAIR_SCAN_CACHE_TTL_SECONDS)
    if cached is not None:
        return PairSuggestionsResponse.model_validate(
            _filter_cached_payload(
                cached,
                p_value_threshold=p_value_threshold,
                limit=limit,
                cached=True,
            )
        )

    closes, volumes = await asyncio.to_thread(_download_pair_history_sync, members)
    (
        suggestions,
        pairs_tested,
        threshold_counts,
        price_eligible_universe,
    ) = await asyncio.to_thread(scan_pair_matrix, members, closes, volumes)
    futures_contracts, futures_price_date = await _latest_futures_contracts(
        {member.ticker for member in members}
    )
    suggestions = _attach_futures_plans(
        suggestions,
        futures_contracts,
        futures_price_date,
    )
    if not threshold_counts:
        threshold_counts = [
            {
                "threshold": threshold,
                "p_significant_pairs": 0,
            }
            for threshold in P_VALUE_THRESHOLDS
        ]
    response = PairSuggestionsResponse(
        official_underlyings=counts["official_underlyings"],
        stock_underlyings=counts["stock_underlyings"],
        index_underlyings=counts["index_underlyings"],
        universe_size=len(members),
        price_eligible_universe=price_eligible_universe,
        pairs_tested=pairs_tested,
        p_value_threshold=MAX_P_VALUE_THRESHOLD,
        p_significant_pairs=int(threshold_counts[-1]["p_significant_pairs"]),
        threshold_counts=threshold_counts,
        returned=len(suggestions),
        generated_at=datetime.now(UTC),
        data_source=(
            "Yahoo Finance adjusted daily history + NSE F&O universe and official "
            "NSE equity-derivatives bhavcopy"
        ),
        results=suggestions,
        limitations=[
            "Suggestions are statistical research signals, not investment advice.",
            "Futures prices are official NSE end-of-day closes, not live executable quotes.",
            "Contract notional is shown, but actual SPAN/exposure margin is calculated by the broker and changes with market risk.",
            "Brokerage, taxes, slippage, daily mark-to-market funding, rollover cost, and execution costs are not included.",
            "Stocks require a verified market capitalization of at least ₹500 crore; indices are included without a market-cap test.",
            (
                f"{counts['excluded_missing_market_cap']} F&O stock(s) were excluded because "
                "market capitalization could not be verified."
            ),
            "Every production pair is fitted on exactly the latest 250 aligned daily adjusted closes. An instrument can be absent when fewer than 250 common observations are available.",
            "The selected p-value cutoff is not adjusted for the number of pairs tested; the displayed FDR q-value provides that additional context.",
        ],
    )
    payload = response.model_dump(mode="json")
    payload["results"] = [suggestion.model_dump(mode="json") for suggestion in suggestions]
    payload["returned"] = len(suggestions)
    cache.put(key, payload, source=response.data_source)
    return PairSuggestionsResponse.model_validate(
        _filter_cached_payload(
            payload,
            p_value_threshold=p_value_threshold,
            limit=limit,
            cached=False,
        )
    )
