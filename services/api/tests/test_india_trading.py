from app.schemas.trading import OptionsChainOut, PriceHistoryOut
from app.services.market_data.india_trading import (
    _black_scholes_greeks,
    _build_probability_distribution,
    _decreasing_isotonic,
    _number,
    _option_leg,
    _percentage,
    _time_to_expiry,
)


def test_market_number_cleaning_rejects_non_finite_values():
    assert _number("42.5") == 42.5
    assert _number(float("nan")) is None
    assert _number(None) is None
    assert _percentage(0.19636) == 19.636


def test_nse_option_leg_is_normalized_without_exchange_field_names():
    leg = _option_leg(
        {
            "lastPrice": 32.7,
            "pChange": -17.0,
            "openInterest": 9139,
            "changeinOpenInterest": -1411,
            "totalTradedVolume": 12691,
            "impliedVolatility": 22.8,
            "buyPrice1": 32.55,
            "sellPrice1": 32.85,
        }
    )

    assert leg is not None
    assert leg["last_price"] == 32.7
    assert leg["percent_change"] == -17.0
    assert leg["open_interest"] == 9139
    assert leg["volume"] == 12691
    assert leg["bid_price"] == 32.55
    assert leg["ask_price"] == 32.85
    assert leg["delta"] is None


def test_black_scholes_greeks_match_reference_values():
    call = _black_scholes_greeks(
        "call",
        100,
        100,
        20,
        1,
        risk_free_rate=0.05,
        dividend_yield=0,
    )
    put = _black_scholes_greeks(
        "put",
        100,
        100,
        20,
        1,
        risk_free_rate=0.05,
        dividend_yield=0,
    )

    assert call["delta"] == 0.636831
    assert call["gamma"] == 0.018762
    assert call["vega"] == 0.37524
    assert call["rho"] == 0.532325
    assert put["delta"] == -0.363169
    assert put["rho"] == -0.418905


def test_time_to_expiry_uses_nse_exchange_timestamp():
    years = _time_to_expiry("28-Jul-2026", "20-Jul-2026 15:30:00")

    assert years is not None
    assert round(years * 365.25) == 8


def test_isotonic_fit_removes_probability_increases():
    fitted = _decreasing_isotonic([0.8, 0.6, 0.7, 0.2], [1, 1, 1, 1])

    assert [round(value, 6) for value in fitted] == [0.8, 0.65, 0.65, 0.2]
    assert all(left >= right for left, right in zip(fitted, fitted[1:], strict=False))


def test_probability_distribution_sums_to_one_and_has_nonnegative_buckets():
    rows = []
    for strike, call_iv, put_iv in [
        (80, 32, 30),
        (90, 28, 27),
        (100, 25, 25),
        (110, 27, 28),
        (120, 30, 32),
    ]:
        rows.append(
            {
                "strike_price": strike,
                "call": {
                    "implied_volatility": call_iv,
                    "volume": 100,
                    "open_interest": 1000,
                    "bid_price": 4.9,
                    "ask_price": 5.1,
                },
                "put": {
                    "implied_volatility": put_iv,
                    "volume": 120,
                    "open_interest": 900,
                    "bid_price": 4.8,
                    "ask_price": 5.2,
                },
            }
        )

    distribution = _build_probability_distribution(rows, spot=100, years_to_expiry=0.1)

    assert distribution["available"] is True
    assert distribution["strikes_used"] == 5
    assert len(distribution["curve"]) == 5
    assert all(
        left["probability_above"] >= right["probability_above"]
        for left, right in zip(
            distribution["curve"],
            distribution["curve"][1:],
            strict=False,
        )
    )
    assert round(sum(bucket["probability"] for bucket in distribution["buckets"]), 5) == 1
    assert all(bucket["probability"] >= 0 for bucket in distribution["buckets"])
    assert distribution["range_80_low"] <= distribution["median_price"]
    assert distribution["median_price"] <= distribution["range_80_high"]


def test_empty_market_payloads_are_valid_and_explicit():
    history = PriceHistoryOut(
        ticker="TEST",
        market_data_ticker="TEST.NS",
        range="1Y",
        interval="1d",
        candles=[],
        source="yfinance",
        source_url="https://example.com",
        retrieved_at="2026-07-20T12:00:00Z",
    )
    chain = OptionsChainOut(
        ticker="TEST",
        symbol="TEST",
        available=False,
        source_url="https://www.nseindia.com/option-chain?symbol=TEST",
        retrieved_at="2026-07-20T12:00:00Z",
        limitation="NSE does not list an equity option chain for this stock.",
    )

    assert history.candles == []
    assert chain.available is False
    assert chain.strikes == []
    assert chain.distribution.available is False
