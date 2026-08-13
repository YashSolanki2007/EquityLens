"""Development market-data adapters for the NSE company workspace.

Prices and ratios come from yfinance and are explicitly labeled delayed/unverified.
Listed-equity option chains come from NSE's public option-chain endpoints.
"""

import asyncio
import logging
import math
from datetime import UTC, datetime, time
from typing import Any, Literal
from urllib.parse import quote

from app.core.cache import FileCache, cache_key
from app.core.config import get_settings
from app.services.nse.client import get_nse_client

logger = logging.getLogger(__name__)

RATIO_TTL_SECONDS = 30 * 60
HISTORY_TTL_SECONDS = 30 * 60
OPTION_TTL_SECONDS = 5 * 60
GREEKS_RISK_FREE_RATE = 0.065
GREEKS_DIVIDEND_YIELD = 0.0
HistoryRange = Literal["1M", "3M", "6M", "1Y", "5Y", "10Y", "FULL_DAILY", "MAX"]
HISTORY_PARAMETERS: dict[HistoryRange, tuple[str, str]] = {
    "1M": ("1mo", "1d"),
    "3M": ("3mo", "1d"),
    "6M": ("6mo", "1d"),
    "1Y": ("1y", "1d"),
    "5Y": ("5y", "1d"),
    "10Y": ("10y", "1d"),
    # Internal research range. Unlike the chart-facing MAX range, this keeps
    # daily observations so long-memory path features have a genuine pre-sample.
    "FULL_DAILY": ("max", "1d"),
    "MAX": ("max", "1wk"),
}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _percentage(value: Any) -> float | None:
    parsed = _number(value)
    return round(parsed * 100, 4) if parsed is not None else None


def _fetch_ratios_sync(ticker: str, market_data_ticker: str) -> dict:
    import yfinance as yf

    stock = yf.Ticker(market_data_ticker)
    info = stock.info or {}
    now = datetime.now(UTC).isoformat()
    return {
        "ticker": ticker,
        "market_data_ticker": market_data_ticker,
        "currency": info.get("currency") or "INR",
        "current_price": _number(info.get("regularMarketPrice")),
        "previous_close": _number(info.get("previousClose")),
        "market_cap": _number(info.get("marketCap")),
        "trailing_pe": _number(info.get("trailingPE")),
        "forward_pe": _number(info.get("forwardPE")),
        "trailing_eps": _number(info.get("trailingEps")),
        "forward_eps": _number(info.get("forwardEps")),
        "price_to_book": _number(info.get("priceToBook")),
        "peg_ratio": _number(info.get("pegRatio")),
        "book_value": _number(info.get("bookValue")),
        "profit_margin_percent": _percentage(info.get("profitMargins")),
        "operating_margin_percent": _percentage(info.get("operatingMargins")),
        "gross_margin_percent": _percentage(info.get("grossMargins")),
        "return_on_equity_percent": _percentage(info.get("returnOnEquity")),
        "return_on_assets_percent": _percentage(info.get("returnOnAssets")),
        "revenue_growth_percent": _percentage(info.get("revenueGrowth")),
        "earnings_growth_percent": _percentage(info.get("earningsGrowth")),
        "debt_to_equity_percent": _number(info.get("debtToEquity")),
        "current_ratio": _number(info.get("currentRatio")),
        "quick_ratio": _number(info.get("quickRatio")),
        # Yahoo's quoteSummary reports this field in percentage points.
        "dividend_yield_percent": _number(info.get("dividendYield")),
        "payout_ratio_percent": _percentage(info.get("payoutRatio")),
        "beta": _number(info.get("beta")),
        "fifty_two_week_high": _number(info.get("fiftyTwoWeekHigh")),
        "fifty_two_week_low": _number(info.get("fiftyTwoWeekLow")),
        "volume": _number(info.get("volume") or info.get("regularMarketVolume")),
        "average_volume": _number(info.get("averageVolume")),
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{quote(market_data_ticker)}",
        "retrieved_at": now,
        "is_delayed_or_unverified": True,
    }


def _fetch_history_sync(
    ticker: str,
    market_data_ticker: str,
    history_range: HistoryRange,
) -> dict:
    import pandas as pd
    import yfinance as yf

    period, interval = HISTORY_PARAMETERS[history_range]
    stock = yf.Ticker(market_data_ticker)
    frame = stock.history(period=period, interval=interval, auto_adjust=False, actions=False)
    candles: list[dict] = []
    if frame is not None and not frame.empty:
        for timestamp, row in frame.iterrows():
            required = [row.get("Open"), row.get("High"), row.get("Low"), row.get("Close")]
            if any(pd.isna(value) for value in required):
                continue
            candles.append(
                {
                    "time": timestamp.date().isoformat(),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": float(row.get("Volume") or 0),
                }
            )
    currency = "INR"
    try:
        currency = getattr(stock.fast_info, "currency", None) or "INR"
    except Exception:
        pass
    return {
        "ticker": ticker,
        "market_data_ticker": market_data_ticker,
        "range": history_range,
        "interval": interval,
        "currency": currency,
        "candles": candles,
        "source": "yfinance",
        "source_url": f"https://finance.yahoo.com/quote/{quote(market_data_ticker)}/history",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
    }


async def get_trading_ratios(ticker: str, market_data_ticker: str) -> dict:
    cache = FileCache(get_settings().cache_path, "india_trading")
    key = cache_key("ratios", market_data_ticker.upper())
    cached = cache.get(key, RATIO_TTL_SECONDS)
    if cached is not None:
        return cached
    data = await asyncio.to_thread(
        _fetch_ratios_sync,
        ticker.upper(),
        market_data_ticker.upper(),
    )
    cache.put(key, data, source="yfinance")
    return data


async def get_price_history(
    ticker: str,
    market_data_ticker: str,
    history_range: HistoryRange,
) -> dict:
    cache = FileCache(get_settings().cache_path, "india_trading")
    key = cache_key("history", market_data_ticker.upper(), history_range)
    cached = cache.get(key, HISTORY_TTL_SECONDS)
    if cached is not None:
        return cached
    data = await asyncio.to_thread(
        _fetch_history_sync,
        ticker.upper(),
        market_data_ticker.upper(),
        history_range,
    )
    cache.put(key, data, source="yfinance")
    return data


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _normal_pdf(value: float) -> float:
    return math.exp(-(value**2) / 2) / math.sqrt(2 * math.pi)


def _time_to_expiry(expiry: str, exchange_timestamp: str | None) -> float | None:
    try:
        expiry_at = datetime.combine(
            datetime.strptime(expiry, "%d-%b-%Y").date(),
            time(hour=15, minute=30),
        )
        as_of = (
            datetime.strptime(exchange_timestamp, "%d-%b-%Y %H:%M:%S")
            if exchange_timestamp
            else datetime.now()
        )
        seconds = (expiry_at - as_of).total_seconds()
        return seconds / (365.25 * 24 * 60 * 60) if seconds > 0 else None
    except ValueError:
        return None


def _black_scholes_greeks(
    option_type: str,
    spot: float | None,
    strike: float | None,
    implied_volatility_percent: float | None,
    years_to_expiry: float | None,
    *,
    risk_free_rate: float = GREEKS_RISK_FREE_RATE,
    dividend_yield: float = GREEKS_DIVIDEND_YIELD,
) -> dict[str, float | None]:
    empty = {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}
    if (
        spot is None
        or strike is None
        or implied_volatility_percent is None
        or years_to_expiry is None
        or spot <= 0
        or strike <= 0
        or implied_volatility_percent <= 0
        or years_to_expiry <= 0
    ):
        return empty

    volatility = implied_volatility_percent / 100
    root_time = math.sqrt(years_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + volatility**2 / 2) * years_to_expiry
    ) / (volatility * root_time)
    d2 = d1 - volatility * root_time
    discount_rate = math.exp(-risk_free_rate * years_to_expiry)
    discount_dividend = math.exp(-dividend_yield * years_to_expiry)
    density = _normal_pdf(d1)

    gamma = discount_dividend * density / (spot * volatility * root_time)
    vega = spot * discount_dividend * density * root_time / 100
    shared_theta = -(spot * discount_dividend * density * volatility) / (2 * root_time)
    if option_type == "call":
        delta = discount_dividend * _normal_cdf(d1)
        theta = (
            shared_theta
            - risk_free_rate * strike * discount_rate * _normal_cdf(d2)
            + dividend_yield * spot * discount_dividend * _normal_cdf(d1)
        ) / 365
        rho = strike * years_to_expiry * discount_rate * _normal_cdf(d2) / 100
    else:
        delta = discount_dividend * (_normal_cdf(d1) - 1)
        theta = (
            shared_theta
            + risk_free_rate * strike * discount_rate * _normal_cdf(-d2)
            - dividend_yield * spot * discount_dividend * _normal_cdf(-d1)
        ) / 365
        rho = -strike * years_to_expiry * discount_rate * _normal_cdf(-d2) / 100
    return {
        "delta": round(delta, 6),
        "gamma": round(gamma, 6),
        "theta": round(theta, 6),
        "vega": round(vega, 6),
        "rho": round(rho, 6),
    }


def _risk_neutral_probability_above(
    spot: float,
    strike: float,
    implied_volatility_percent: float,
    years_to_expiry: float,
) -> float:
    volatility = implied_volatility_percent / 100
    root_time = math.sqrt(years_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (
            GREEKS_RISK_FREE_RATE
            - GREEKS_DIVIDEND_YIELD
            + volatility**2 / 2
        )
        * years_to_expiry
    ) / (volatility * root_time)
    d2 = d1 - volatility * root_time
    return _normal_cdf(d2)


def _decreasing_isotonic(values: list[float], weights: list[float]) -> list[float]:
    """Weighted pool-adjacent-violators fit constrained to be non-increasing."""

    blocks: list[dict] = []
    for index, (value, weight) in enumerate(zip(values, weights, strict=True)):
        blocks.append(
            {
                "start": index,
                "end": index,
                "weight": max(weight, 1e-6),
                "value": value,
            }
        )
        while len(blocks) >= 2 and blocks[-2]["value"] < blocks[-1]["value"]:
            right = blocks.pop()
            left = blocks.pop()
            combined_weight = left["weight"] + right["weight"]
            blocks.append(
                {
                    "start": left["start"],
                    "end": right["end"],
                    "weight": combined_weight,
                    "value": (
                        left["value"] * left["weight"]
                        + right["value"] * right["weight"]
                    )
                    / combined_weight,
                }
            )
    fitted = [0.0] * len(values)
    for block in blocks:
        for index in range(block["start"], block["end"] + 1):
            fitted[index] = min(1.0, max(0.0, block["value"]))
    return fitted


def _interpolate_exceedance(
    strikes: list[float],
    exceedance: list[float],
    price: float,
) -> float:
    if price <= strikes[0]:
        return exceedance[0]
    if price >= strikes[-1]:
        return exceedance[-1]
    for index in range(len(strikes) - 1):
        low_strike, high_strike = strikes[index], strikes[index + 1]
        if low_strike <= price <= high_strike:
            width = high_strike - low_strike
            fraction = (price - low_strike) / width if width else 0
            return exceedance[index] + fraction * (
                exceedance[index + 1] - exceedance[index]
            )
    return exceedance[-1]


def _distribution_quantile(
    strikes: list[float],
    exceedance: list[float],
    percentile: float,
) -> float:
    target = 1 - percentile
    if target >= exceedance[0]:
        return strikes[0]
    if target <= exceedance[-1]:
        return strikes[-1]
    for index in range(len(strikes) - 1):
        high_q, low_q = exceedance[index], exceedance[index + 1]
        if high_q >= target >= low_q:
            q_width = high_q - low_q
            fraction = (high_q - target) / q_width if q_width else 0.5
            return strikes[index] + fraction * (strikes[index + 1] - strikes[index])
    return strikes[-1]


def _relative_spread(leg: dict) -> float | None:
    bid = _number(leg.get("bid_price"))
    ask = _number(leg.get("ask_price"))
    if bid is None or ask is None or bid < 0 or ask <= 0 or ask < bid:
        return None
    midpoint = (bid + ask) / 2
    return (ask - bid) / midpoint if midpoint > 0 else None


def _empty_distribution(total_strikes: int, limitation: str) -> dict:
    return {
        "available": False,
        "quality_label": "unavailable",
        "total_strikes": total_strikes,
        "limitation": limitation,
    }


def _build_probability_distribution(
    strikes_data: list[dict],
    spot: float | None,
    years_to_expiry: float | None,
) -> dict:
    total = len(strikes_data)
    if spot is None or years_to_expiry is None or total < 3:
        return _empty_distribution(
            total,
            "Insufficient spot, expiry, or strike data to model a distribution.",
        )

    valid_iv_count = 0
    active_count = 0
    observations: list[dict] = []
    for row in strikes_data:
        strike = _number(row.get("strike_price"))
        if strike is None:
            continue
        # Prefer the out-of-the-money contract, whose quote and IV are usually cleaner.
        preferred = row.get("put") if strike < spot else row.get("call")
        fallback = row.get("call") if strike < spot else row.get("put")
        selected = None
        for leg in (preferred, fallback):
            iv = _number((leg or {}).get("implied_volatility"))
            if leg and iv is not None and 0 < iv <= 200:
                selected = leg
                break
        if selected is None:
            continue
        valid_iv_count += 1
        volume = _number(selected.get("volume")) or 0
        open_interest = _number(selected.get("open_interest")) or 0
        if volume <= 0 and open_interest <= 0:
            continue
        active_count += 1
        spread = _relative_spread(selected)
        if spread is not None and spread > 0.5:
            continue
        iv = float(selected["implied_volatility"])
        probability = _risk_neutral_probability_above(
            spot,
            strike,
            iv,
            years_to_expiry,
        )
        liquidity_weight = math.log1p(volume + open_interest)
        spread_weight = 1 / (1 + 4 * (spread or 0))
        observations.append(
            {
                "strike": strike,
                "probability": probability,
                "weight": max(liquidity_weight * spread_weight, 0.1),
                "spread": spread,
            }
        )

    observations.sort(key=lambda item: item["strike"])
    if len(observations) < 3:
        distribution = _empty_distribution(
            total,
            "Fewer than three liquid strikes had usable implied volatility.",
        )
        distribution.update(
            {
                "valid_iv_coverage_percent": round(valid_iv_count / total * 100, 2),
                "active_contract_coverage_percent": round(active_count / total * 100, 2),
                "strikes_used": len(observations),
            }
        )
        return distribution

    strikes = [item["strike"] for item in observations]
    raw_probabilities = [item["probability"] for item in observations]
    probabilities = _decreasing_isotonic(
        raw_probabilities,
        [item["weight"] for item in observations],
    )
    adjustments = sum(
        abs(raw - fitted) > 1e-8
        for raw, fitted in zip(raw_probabilities, probabilities, strict=True)
    )
    step_sizes = [
        strikes[index + 1] - strikes[index] for index in range(len(strikes) - 1)
    ]
    typical_step = sorted(step_sizes)[len(step_sizes) // 2]

    buckets = [
        {
            "label": f"Below ₹{strikes[0]:,.0f}",
            "lower_bound": None,
            "upper_bound": strikes[0],
            "chart_price": strikes[0] - typical_step / 2,
            "probability": round(1 - probabilities[0], 6),
        }
    ]
    for index in range(len(strikes) - 1):
        low, high = strikes[index], strikes[index + 1]
        buckets.append(
            {
                "label": f"₹{low:,.0f}–₹{high:,.0f}",
                "lower_bound": low,
                "upper_bound": high,
                "chart_price": (low + high) / 2,
                "probability": round(
                    max(0.0, probabilities[index] - probabilities[index + 1]),
                    6,
                ),
            }
        )
    buckets.append(
        {
            "label": f"Above ₹{strikes[-1]:,.0f}",
            "lower_bound": strikes[-1],
            "upper_bound": None,
            "chart_price": strikes[-1] + typical_step / 2,
            "probability": round(probabilities[-1], 6),
        }
    )

    spread_values = sorted(
        item["spread"] for item in observations if item["spread"] is not None
    )
    median_spread = (
        spread_values[len(spread_values) // 2] if spread_values else None
    )
    iv_coverage = valid_iv_count / total
    active_coverage = active_count / total
    spread_score = max(0.0, 1 - min(median_spread or 0.5, 1.0))
    quality_score = round(
        100 * (0.4 * iv_coverage + 0.35 * active_coverage + 0.25 * spread_score),
        1,
    )
    quality_label = "high" if quality_score >= 75 else "medium" if quality_score >= 50 else "low"
    most_likely = max(buckets, key=lambda bucket: bucket["probability"])
    probability_above_spot = _interpolate_exceedance(strikes, probabilities, spot)

    return {
        "available": True,
        "method": "Black-Scholes N(d2), liquidity-filtered and monotonic-adjusted",
        "buckets": buckets,
        "curve": [
            {
                "strike_price": strike,
                "probability_above": round(probability, 6),
            }
            for strike, probability in zip(strikes, probabilities, strict=True)
        ],
        "most_likely_range": most_likely["label"],
        "median_price": round(_distribution_quantile(strikes, probabilities, 0.5), 2),
        "range_50_low": round(_distribution_quantile(strikes, probabilities, 0.25), 2),
        "range_50_high": round(_distribution_quantile(strikes, probabilities, 0.75), 2),
        "range_80_low": round(_distribution_quantile(strikes, probabilities, 0.1), 2),
        "range_80_high": round(_distribution_quantile(strikes, probabilities, 0.9), 2),
        "probability_above_spot": round(probability_above_spot, 6),
        "probability_below_spot": round(1 - probability_above_spot, 6),
        "quality_score": quality_score,
        "quality_label": quality_label,
        "valid_iv_coverage_percent": round(iv_coverage * 100, 2),
        "active_contract_coverage_percent": round(active_coverage * 100, 2),
        "median_relative_spread_percent": (
            round(median_spread * 100, 2) if median_spread is not None else None
        ),
        "strikes_used": len(observations),
        "total_strikes": total,
        "monotonic_adjustments": adjustments,
        "limitation": (
            "Tail buckets extend beyond the displayed strike range; probabilities are "
            "risk-neutral model estimates, not real-world forecasts."
        ),
    }


def _option_leg(
    raw: dict | None,
    *,
    option_type: str | None = None,
    spot: float | None = None,
    strike: float | None = None,
    years_to_expiry: float | None = None,
) -> dict | None:
    if not raw:
        return None
    implied_volatility = _number(raw.get("impliedVolatility"))
    leg = {
        "last_price": _number(raw.get("lastPrice")),
        "change": _number(raw.get("change")),
        "percent_change": _number(raw.get("pChange") or raw.get("PChange")),
        "open_interest": _number(raw.get("openInterest")),
        "change_in_open_interest": _number(raw.get("changeinOpenInterest")),
        "percent_change_in_open_interest": _number(raw.get("pchangeinOpenInterest")),
        "volume": _number(raw.get("totalTradedVolume")),
        "implied_volatility": implied_volatility,
        "bid_price": _number(raw.get("buyPrice1")),
        "bid_quantity": _number(raw.get("buyQuantity1")),
        "ask_price": _number(raw.get("sellPrice1")),
        "ask_quantity": _number(raw.get("sellQuantity1")),
    }
    leg.update(
        _black_scholes_greeks(
            option_type or "",
            spot,
            strike,
            implied_volatility,
            years_to_expiry,
        )
    )
    return leg


def _empty_chain(ticker: str, symbol: str, *, limitation: str) -> dict:
    return {
        "ticker": ticker,
        "symbol": symbol,
        "available": False,
        "selected_expiry": None,
        "expiry_dates": [],
        "underlying_value": None,
        "exchange_timestamp": None,
        "greeks_model": "Black-Scholes",
        "greeks_are_modeled": True,
        "risk_free_rate_percent": GREEKS_RISK_FREE_RATE * 100,
        "dividend_yield_percent": GREEKS_DIVIDEND_YIELD * 100,
        "strikes": [],
        "distribution": _empty_distribution(0, limitation),
        "source": "NSE India",
        "source_url": f"https://www.nseindia.com/option-chain?symbol={quote(symbol)}",
        "retrieved_at": datetime.now(UTC).isoformat(),
        "is_delayed_or_unverified": True,
        "limitation": limitation,
        "scanner_summary": {},
    }


def _options_scanner_summary(strikes: list[dict]) -> dict:
    """Build full-chain OI metrics and compact active-contract delta indexes."""

    def active_legs(side: str) -> list[dict]:
        legs = []
        for row in strikes:
            leg = row.get(side) or {}
            open_interest = _number(leg.get("open_interest")) or 0.0
            change = _number(leg.get("change_in_open_interest")) or 0.0
            delta = _number(leg.get("delta"))
            volume = _number(leg.get("volume")) or 0.0
            if open_interest <= 0 and volume <= 0:
                continue
            legs.append(
                {
                    "strike_price": row["strike_price"],
                    "delta": abs(delta) if delta is not None else None,
                    "open_interest": open_interest,
                    "change_in_open_interest": change,
                }
            )
        return legs

    calls = active_legs("call")
    puts = active_legs("put")
    call_oi = sum(leg["open_interest"] for leg in calls)
    put_oi = sum(leg["open_interest"] for leg in puts)
    call_change = sum(leg["change_in_open_interest"] for leg in calls)
    put_change = sum(leg["change_in_open_interest"] for leg in puts)

    def change_percent(current: float, change: float) -> float | None:
        previous = current - change
        return round(change / previous * 100, 4) if previous > 0 else None

    return {
        "call_open_interest": call_oi,
        "put_open_interest": put_oi,
        "call_oi_change_percent": change_percent(call_oi, call_change),
        "put_oi_change_percent": change_percent(put_oi, put_change),
        "put_call_oi_ratio": round(put_oi / call_oi, 6) if call_oi > 0 else None,
        "call_delta_contracts": [
            leg for leg in calls if leg["delta"] is not None
        ],
        "put_delta_contracts": [
            leg for leg in puts if leg["delta"] is not None
        ],
    }


async def get_options_chain(ticker: str, symbol: str, expiry: str | None = None) -> dict:
    """Return the requested expiry and at most 25 strikes centered around spot."""

    symbol = symbol.upper()
    cache = FileCache(get_settings().cache_path, "india_trading")
    key = cache_key("options_v5", symbol, expiry or "nearest")
    cached = cache.get(key, OPTION_TTL_SECONDS)
    if cached is not None:
        return cached

    client = get_nse_client()
    try:
        contract_response = await client._get(
            "https://www.nseindia.com/api/option-chain-contract-info",
            params={"symbol": symbol},
        )
        contract_info = contract_response.json() or {}
        expiry_dates = list(contract_info.get("expiryDates") or [])
        if not expiry_dates:
            data = _empty_chain(
                ticker,
                symbol,
                limitation="NSE does not list an equity option chain for this stock.",
            )
            cache.put(key, data, source=str(contract_response.url))
            return data
        selected_expiry = expiry if expiry in expiry_dates else expiry_dates[0]
        chain_response = await client._get(
            "https://www.nseindia.com/api/option-chain-v3",
            params={"type": "Equity", "symbol": symbol, "expiry": selected_expiry},
        )
        records = (chain_response.json() or {}).get("records") or {}
        rows = list(records.get("data") or [])
        underlying = _number(records.get("underlyingValue"))
        exchange_timestamp = records.get("timestamp")
        years_to_expiry = _time_to_expiry(selected_expiry, exchange_timestamp)
        parsed = [
            {
                "strike_price": _number(row.get("strikePrice")),
                "call": _option_leg(
                    row.get("CE"),
                    option_type="call",
                    spot=underlying,
                    strike=_number(row.get("strikePrice")),
                    years_to_expiry=years_to_expiry,
                ),
                "put": _option_leg(
                    row.get("PE"),
                    option_type="put",
                    spot=underlying,
                    strike=_number(row.get("strikePrice")),
                    years_to_expiry=years_to_expiry,
                ),
            }
            for row in rows
            if _number(row.get("strikePrice")) is not None
        ]
        parsed.sort(key=lambda row: row["strike_price"])
        scanner_summary = _options_scanner_summary(parsed)
        distribution = _build_probability_distribution(
            parsed,
            underlying,
            years_to_expiry,
        )
        if len(parsed) > 25:
            center = min(
                range(len(parsed)),
                key=lambda index: abs(parsed[index]["strike_price"] - (underlying or 0)),
            )
            start = max(0, min(center - 12, len(parsed) - 25))
            parsed = parsed[start : start + 25]
        data = {
            "ticker": ticker,
            "symbol": symbol,
            "available": bool(parsed),
            "selected_expiry": selected_expiry,
            "expiry_dates": expiry_dates,
            "underlying_value": underlying,
            "exchange_timestamp": exchange_timestamp,
            "greeks_model": "Black-Scholes",
            "greeks_are_modeled": True,
            "risk_free_rate_percent": GREEKS_RISK_FREE_RATE * 100,
            "dividend_yield_percent": GREEKS_DIVIDEND_YIELD * 100,
            "strikes": parsed,
            "distribution": distribution,
            "source": "NSE India",
            "source_url": f"https://www.nseindia.com/option-chain?symbol={quote(symbol)}",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "is_delayed_or_unverified": True,
            "limitation": (
                None if parsed else "NSE returned no contracts for the selected expiry."
            ),
            "scanner_summary": scanner_summary,
        }
        cache.put(key, data, source=str(chain_response.url))
        return data
    except Exception as exc:
        logger.warning("NSE option chain failed for %s: %s", symbol, exc)
        return _empty_chain(
            ticker,
            symbol,
            limitation="The NSE option-chain feed is temporarily unavailable.",
        )
