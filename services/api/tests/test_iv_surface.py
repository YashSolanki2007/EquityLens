from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.schemas.trading import IVSurfaceForecastOut
from app.services.market_data.iv_surface import (
    DELTA_BUCKETS,
    EXPLAINED_VARIANCE_TARGET_PERCENT,
    MAXIMUM_COMPONENT_COUNT,
    MINIMUM_COMPONENT_COUNT,
    RIDGE_ALPHA_CANDIDATES,
    TENOR_DAYS,
    _black_scholes_price,
    _candidate_dates,
    _parse_market_lot_sizes,
    _select_component_count,
    build_iv_strategies,
    build_iv_strategy,
    compare_forecast_to_market,
    fit_fpca_var,
    implied_volatility_percent,
    surface_from_bhavcopy,
)
from app.services.market_data.paper_iv_trades import (
    calculate_paper_iv_mark,
    reconstruct_historical_leg_ivs,
)


def _synthetic_surfaces(count: int = 50) -> np.ndarray:
    base = np.asarray(
        [
            [31, 28, 25, 27, 30],
            [30, 27, 24, 26, 29],
            [29, 26, 23, 25, 28],
            [28, 25, 22, 24, 27],
        ],
        dtype=float,
    )
    level = np.ones_like(base)
    skew = np.tile(np.asarray([1.5, 0.7, 0.0, -0.5, -1.0]), (4, 1))
    term = np.tile(np.asarray([1.2, 0.4, -0.4, -0.8])[:, None], (1, 5))
    return np.asarray(
        [
            base
            + level * (0.035 * index + 0.7 * np.sin(index / 6))
            + skew * np.cos(index / 7)
            + term * np.sin(index / 9)
            for index in range(count)
        ]
    )


def test_implied_volatility_solver_recovers_black_scholes_input():
    price = _black_scholes_price("call", 100, 105, 45 / 365.25, 0.28)

    iv = implied_volatility_percent("call", price, 100, 105, 45 / 365.25)

    assert iv is not None
    assert abs(iv - 28) < 0.001


def test_daily_bhavcopy_is_mapped_to_fixed_delta_tenor_surface():
    as_of = date(2026, 7, 1)
    rows = []
    for days in (14, 45, 80):
        years = days / 365.25
        expiry = as_of + timedelta(days=days)
        for strike in range(70, 131, 5):
            for option_code, side in (("CE", "call"), ("PE", "put")):
                iv = 0.24 + abs(strike / 100 - 1) * 0.30 + days / 10000
                rows.append(
                    {
                        "FinInstrmTp": "STO",
                        "TckrSymb": "TEST",
                        "XpryDt": expiry.isoformat(),
                        "StrkPric": strike,
                        "OptnTp": option_code,
                        "ClsPric": _black_scholes_price(
                            side,
                            100,
                            strike,
                            years,
                            iv,
                        ),
                        "UndrlygPric": 100,
                        "OpnIntrst": 10_000,
                        "TtlTradgVol": 500,
                    }
                )

    surface = surface_from_bhavcopy(pd.DataFrame(rows), "TEST", as_of)

    assert surface is not None
    assert surface.shape == (len(TENOR_DAYS), len(DELTA_BUCKETS))
    assert np.isfinite(surface).all()
    assert 15 < surface.min() < surface.max() < 60


def test_fpca_var_forecast_retains_components_and_returns_error_surface():
    result = fit_fpca_var(_synthetic_surfaces())

    assert result["forecast_surface"].shape == (4, 5)
    assert result["rmse_surface"].shape == (4, 5)
    assert MINIMUM_COMPONENT_COUNT <= result["component_count"] <= MAXIMUM_COMPONENT_COUNT
    assert result["explained_variance_percent"] >= EXPLAINED_VARIANCE_TARGET_PERCENT
    assert result["validation_sessions"] == 10
    assert set(result["validation_rmse_by_components"]) == {
        str(value) for value in range(MINIMUM_COMPONENT_COUNT, MAXIMUM_COMPONENT_COUNT + 1)
    }
    assert result["ridge_alpha"] in RIDGE_ALPHA_CANDIDATES
    assert result["reconstruction_rmse"] >= 0
    assert result["validation_baseline_rmse"] >= 0
    assert np.isfinite(result["validation_improvement_over_baseline_percent"])
    assert 0 <= result["validation_directional_accuracy_percent"] <= 100
    assert result["component_selection_note"]
    assert np.isfinite(result["forecast_surface"]).all()
    assert np.all(result["rmse_surface"] >= 0)


def test_fpca_requires_a_surface_after_the_training_minimum_for_validation():
    with pytest.raises(ValueError, match="one-session-ahead validation observation"):
        fit_fpca_var(_synthetic_surfaces(35))

    result = fit_fpca_var(_synthetic_surfaces(36))

    assert result["validation_sessions"] == 1


def test_history_candidates_include_same_day_only_after_bhavcopy_window():
    before_publish = _candidate_dates(
        now=datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    )
    after_publish = _candidate_dates(
        now=datetime(2026, 8, 11, 13, 0, tzinfo=UTC)
    )

    assert before_publish[0] == date(2026, 8, 10)
    assert after_publish[0] == date(2026, 8, 11)


def test_component_selection_uses_smallest_model_reaching_99_percent():
    selected, retained = _select_component_count(
        np.asarray([60, 85, 93, 97, 98.7, 99.3, 99.7, 99.9])
    )
    assert selected == 6
    assert retained == 99.3

    selected, retained = _select_component_count(
        np.asarray([60, 85, 93, 97, 98.0, 98.4, 98.7, 98.9])
    )
    assert selected == MAXIMUM_COMPONENT_COUNT
    assert retained == 98.9


def test_market_lot_file_is_parsed_by_expiry_month():
    parsed = _parse_market_lot_sizes("UNDERLYING,SYMBOL,AUG-26,SEP-26\nTest Limited,TEST,500,250\n")

    assert parsed == {"TEST": {"AUG-26": 500, "SEP-26": 250}}


def test_cheap_atm_iv_builds_one_lot_long_straddle_payoff():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "underlying_value": 100,
        "strikes": [
            {
                "strike_price": 100,
                "call": {
                    "ask_price": 6,
                    "bid_price": 5.8,
                    "last_price": 5.9,
                    "implied_volatility": 20,
                },
                "put": {
                    "ask_price": 5,
                    "bid_price": 4.8,
                    "last_price": 4.9,
                    "implied_volatility": 20,
                },
            }
        ],
    }
    comparisons = [
        {
            "label": "ATM",
            "status": "cheap",
            "market_iv_percent": 20,
            "predicted_iv_percent": 25,
        }
    ]

    strategy = build_iv_strategy(chain, comparisons, lot_size=500)

    assert strategy["available"] is True
    assert strategy["signal"] == "long_volatility"
    assert strategy["lot_size"] == 500
    assert strategy["entry_premium_per_unit"] == 11
    assert strategy["maximum_loss_per_lot"] == 5_500
    assert strategy["lower_break_even"] == 89
    assert strategy["upper_break_even"] == 111
    assert len(strategy["legs"]) == 2
    at_strike = min(
        strategy["payoff_points"],
        key=lambda point: abs(point["underlying_price"] - 100),
    )
    assert at_strike["pnl_per_lot"] == -5_500
    assert np.isfinite(at_strike["next_session_pnl_per_lot"])


def test_expensive_atm_iv_builds_defined_risk_iron_butterfly():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "underlying_value": 100,
        "strikes": [
            {
                "strike_price": 90,
                "put": {
                    "ask_price": 1,
                    "last_price": 0.9,
                    "delta": -0.1,
                },
            },
            {
                "strike_price": 100,
                "call": {
                    "ask_price": 6.2,
                    "bid_price": 6,
                    "last_price": 6.1,
                    "implied_volatility": 30,
                },
                "put": {
                    "ask_price": 5.2,
                    "bid_price": 5,
                    "last_price": 5.1,
                    "implied_volatility": 30,
                },
            },
            {
                "strike_price": 110,
                "call": {
                    "ask_price": 1.5,
                    "last_price": 1.4,
                    "delta": 0.1,
                },
            },
        ],
    }
    comparisons = [
        {
            "label": "ATM",
            "status": "expensive",
            "market_iv_percent": 30,
            "predicted_iv_percent": 20,
        }
    ]

    strategy = build_iv_strategy(chain, comparisons, lot_size=500)

    assert strategy["available"] is True
    assert strategy["signal"] == "short_volatility_defined_risk"
    assert strategy["entry_premium_per_unit"] == 8.5
    assert strategy["maximum_profit_per_lot"] == 4_250
    assert strategy["maximum_loss_per_lot"] == 750
    assert strategy["lower_break_even"] == 91.5
    assert strategy["upper_break_even"] == 108.5
    assert len(strategy["legs"]) == 4
    assert all(
        np.isfinite(point["next_session_pnl_per_lot"]) for point in strategy["payoff_points"]
    )


def test_no_trade_explains_matched_atm_ivs_error_and_required_gap():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "underlying_value": 2472,
        "strikes": [
            {
                "strike_price": 2480,
                "call": {
                    "ask_price": 64.4,
                    "bid_price": 63.65,
                    "last_price": 63.8,
                    "implied_volatility": 23.07,
                },
                "put": {
                    "ask_price": 82.0,
                    "bid_price": 80.25,
                    "last_price": 81.0,
                    "implied_volatility": 33.85,
                },
            }
        ],
    }
    comparisons = [
        {
            "label": "ATM",
            "status": "in_line",
            "market_iv_percent": 28.46,
            "predicted_iv_percent": 25.65,
            "model_error_vol_points": 2.70,
            "material_threshold_vol_points": 4.05,
        }
    ]

    strategy = build_iv_strategy(chain, comparisons, lot_size=250)

    assert strategy["available"] is False
    assert "call IV is 23.07%" in strategy["rationale"]
    assert "put IV is 33.85%" in strategy["rationale"]
    assert "ATM forecast error is 2.70 points" in strategy["rationale"]
    assert "max(2.00, 1.5 × error) = 4.05 points" in strategy["rationale"]
    assert "Because 2.81 does not exceed 4.05" in strategy["rationale"]


def test_expensive_otm_put_builds_defined_risk_bull_put_spread():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "exchange_timestamp": "31-Jul-2026 15:30:00",
        "underlying_value": 100,
        "strikes": [
            {
                "strike_price": 80,
                "put": {"ask_price": 1, "bid_price": 0.8, "last_price": 0.9},
            },
            {
                "strike_price": 90,
                "put": {"ask_price": 5.2, "bid_price": 5, "last_price": 5.1},
            },
        ],
    }
    comparisons = [
        {
            "label": "10Δ put",
            "side": "put",
            "strike_price": 80,
            "market_iv_percent": 28,
            "predicted_iv_percent": 27,
            "difference_vol_points": 1,
            "material_threshold_vol_points": 4,
            "status": "in_line",
        },
        {
            "label": "25Δ put",
            "side": "put",
            "strike_price": 90,
            "market_iv_percent": 35,
            "predicted_iv_percent": 25,
            "difference_vol_points": 10,
            "material_threshold_vol_points": 4,
            "status": "expensive",
        },
    ]

    primary, strategies = build_iv_strategies(chain, comparisons, lot_size=100)
    spread = next(item for item in strategies if item["strategy_id"] == "25d-put-credit-spread")

    assert primary["available"] is True
    assert spread["strategy_name"] == "Illustrative bull put credit spread"
    assert spread["entry_premium_per_unit"] == 4
    assert spread["maximum_profit_per_lot"] == 400
    assert spread["maximum_loss_per_lot"] == 600
    assert spread["upper_break_even"] is None
    assert spread["lower_break_even"] == 86


def test_two_cheap_otm_wings_build_long_strangle():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "exchange_timestamp": "31-Jul-2026 15:30:00",
        "underlying_value": 100,
        "strikes": [
            {
                "strike_price": 90,
                "put": {"ask_price": 3, "bid_price": 2.8, "last_price": 2.9},
            },
            {
                "strike_price": 110,
                "call": {"ask_price": 4, "bid_price": 3.8, "last_price": 3.9},
            },
        ],
    }
    comparisons = [
        {
            "label": "25Δ put",
            "side": "put",
            "strike_price": 90,
            "market_iv_percent": 20,
            "predicted_iv_percent": 27,
            "difference_vol_points": -7,
            "material_threshold_vol_points": 4,
            "status": "cheap",
        },
        {
            "label": "25Δ call",
            "side": "call",
            "strike_price": 110,
            "market_iv_percent": 21,
            "predicted_iv_percent": 28,
            "difference_vol_points": -7,
            "material_threshold_vol_points": 4,
            "status": "cheap",
        },
    ]

    _, strategies = build_iv_strategies(chain, comparisons, lot_size=100)
    strangle = next(item for item in strategies if item["strategy_id"] == "long-25d-strangle")

    assert strangle["source_buckets"] == ["25Δ put", "25Δ call"]
    assert strangle["entry_premium_per_unit"] == 7
    assert strangle["maximum_loss_per_lot"] == 700
    assert strangle["lower_break_even"] == 83
    assert strangle["upper_break_even"] == 117


def test_two_expensive_otm_wings_build_defined_risk_iron_condor():
    chain = {
        "selected_expiry": "25-Aug-2026",
        "exchange_timestamp": "31-Jul-2026 15:30:00",
        "underlying_value": 100,
        "strikes": [
            {"strike_price": 80, "put": {"ask_price": 1, "last_price": 0.9}},
            {"strike_price": 90, "put": {"bid_price": 4, "last_price": 4.1}},
            {"strike_price": 110, "call": {"bid_price": 4, "last_price": 4.1}},
            {"strike_price": 120, "call": {"ask_price": 1, "last_price": 0.9}},
        ],
    }
    comparisons = [
        {
            "label": "10Δ put",
            "side": "put",
            "strike_price": 80,
            "market_iv_percent": 29,
            "predicted_iv_percent": 28,
            "difference_vol_points": 1,
            "material_threshold_vol_points": 4,
            "status": "in_line",
        },
        {
            "label": "25Δ put",
            "side": "put",
            "strike_price": 90,
            "market_iv_percent": 35,
            "predicted_iv_percent": 27,
            "difference_vol_points": 8,
            "material_threshold_vol_points": 4,
            "status": "expensive",
        },
        {
            "label": "25Δ call",
            "side": "call",
            "strike_price": 110,
            "market_iv_percent": 36,
            "predicted_iv_percent": 28,
            "difference_vol_points": 8,
            "material_threshold_vol_points": 4,
            "status": "expensive",
        },
        {
            "label": "10Δ call",
            "side": "call",
            "strike_price": 120,
            "market_iv_percent": 30,
            "predicted_iv_percent": 29,
            "difference_vol_points": 1,
            "material_threshold_vol_points": 4,
            "status": "in_line",
        },
    ]

    _, strategies = build_iv_strategies(chain, comparisons, lot_size=100)
    condor = next(item for item in strategies if item["strategy_id"] == "short-25d-iron-condor")

    assert len(condor["legs"]) == 4
    assert condor["entry_premium_per_unit"] == 6
    assert condor["maximum_profit_per_lot"] == 600
    assert condor["maximum_loss_per_lot"] == 400
    assert condor["lower_break_even"] == 84
    assert condor["upper_break_even"] == 116


def test_market_comparison_marks_large_positive_iv_gap_as_expensive():
    start = date(2026, 5, 1)
    dates = [(start + timedelta(days=index)).isoformat() for index in range(50)]
    strikes = [
        {
            "strike_price": 90,
            "put": {
                "implied_volatility": 65,
                "delta": -0.10,
                "volume": 100,
                "open_interest": 1000,
            },
        },
        {
            "strike_price": 95,
            "put": {
                "implied_volatility": 65,
                "delta": -0.25,
                "volume": 100,
                "open_interest": 1000,
            },
        },
        {
            "strike_price": 100,
            "call": {
                "implied_volatility": 65,
                "delta": 0.50,
                "volume": 100,
                "open_interest": 1000,
                "ask_price": 6,
                "bid_price": 5.8,
                "last_price": 5.9,
            },
            "put": {
                "implied_volatility": 65,
                "delta": -0.50,
                "volume": 100,
                "open_interest": 1000,
                "ask_price": 5,
                "bid_price": 4.8,
                "last_price": 4.9,
            },
        },
        {
            "strike_price": 105,
            "call": {
                "implied_volatility": 65,
                "delta": 0.25,
                "volume": 100,
                "open_interest": 1000,
            },
        },
        {
            "strike_price": 110,
            "call": {
                "implied_volatility": 65,
                "delta": 0.10,
                "volume": 100,
                "open_interest": 1000,
            },
        },
    ]
    chain = {
        "selected_expiry": "30-Sep-2026",
        "exchange_timestamp": "31-Jul-2026 15:30:00",
        "underlying_value": 100,
        "strikes": strikes,
        "source_url": "https://www.nseindia.com/option-chain?symbol=TEST",
    }

    raw = compare_forecast_to_market(
        ticker="TEST",
        symbol="TEST",
        chain=chain,
        history_dates=dates,
        history_surfaces=_synthetic_surfaces(),
    )
    parsed = IVSurfaceForecastOut.model_validate(raw)

    assert parsed.available is True
    assert parsed.overall_status == "expensive"
    assert len(parsed.comparisons) == 5
    assert all(item.status == "expensive" for item in parsed.comparisons)
    atm = next(item for item in parsed.comparisons if item.label == "ATM")
    assert atm.side == "call_put"
    assert atm.call_market_iv_percent == 65
    assert atm.put_market_iv_percent == 65
    assert atm.market_iv_percent == 65
    assert parsed.principal_components is not None


def test_paper_long_straddle_uses_exit_bids_and_reports_return():
    mark, limitation = calculate_paper_iv_mark(
        legs=[
            {
                "action": "buy",
                "option_type": "call",
                "strike_price": 100,
                "quantity_lots": 1,
                "premium_per_unit": 6,
                "price_source": "ask",
            },
            {
                "action": "buy",
                "option_type": "put",
                "strike_price": 100,
                "quantity_lots": 1,
                "premium_per_unit": 5,
                "price_source": "ask",
            },
        ],
        lot_size=500,
        quantity_lots=1,
        entry_premium_type="debit",
        entry_cash_flow_per_lot=5_500,
        capital_at_risk_per_lot=5_500,
        chain={
            "available": True,
            "underlying_value": 108,
            "exchange_timestamp": "31-Jul-2026 15:30:00",
            "strikes": [
                {
                    "strike_price": 100,
                    "call": {
                        "bid_price": 8,
                        "ask_price": 8.5,
                        "last_price": 8.2,
                        "implied_volatility": 24,
                    },
                    "put": {
                        "bid_price": 7,
                        "ask_price": 7.5,
                        "last_price": 7.2,
                        "implied_volatility": 26,
                    },
                }
            ],
        },
    )

    assert limitation is None
    assert mark is not None
    assert mark["close_cash_flow"] == 7_500
    assert mark["pnl"] == 2_000
    assert mark["pnl_percent"] == 36.36
    assert mark["price_quality"] == "executable"
    assert {leg["close_price_source"] for leg in mark["leg_marks"]} == {"bid"}
    assert [leg["current_iv_percent"] for leg in mark["leg_marks"]] == [24, 26]


def test_paper_mark_flags_last_traded_fallback_as_estimated():
    mark, limitation = calculate_paper_iv_mark(
        legs=[
            {
                "action": "buy",
                "option_type": "call",
                "strike_price": 375,
                "quantity_lots": 1,
                "premium_per_unit": 20,
                "price_source": "ask",
            }
        ],
        lot_size=1,
        quantity_lots=2,
        entry_premium_type="debit",
        entry_cash_flow_per_lot=20,
        capital_at_risk_per_lot=20,
        chain={
            "available": True,
            "underlying_value": 380,
            "strikes": [
                {
                    "strike_price": 375,
                    "call": {"bid_price": 0, "last_price": 24},
                }
            ],
        },
    )

    assert limitation is None
    assert mark is not None
    assert mark["close_cash_flow"] == 48
    assert mark["pnl"] == 8
    assert mark["pnl_percent"] == 20
    assert mark["price_quality"] == "estimated"


def test_paper_mark_derives_iv_from_exit_quote_when_exchange_iv_is_zero():
    mark, limitation = calculate_paper_iv_mark(
        legs=[
            {
                "action": "buy",
                "option_type": "call",
                "strike_price": 100,
                "quantity_lots": 1,
                "premium_per_unit": 5,
                "price_source": "ask",
            }
        ],
        lot_size=100,
        quantity_lots=1,
        entry_premium_type="debit",
        entry_cash_flow_per_lot=500,
        capital_at_risk_per_lot=500,
        chain={
            "available": True,
            "selected_expiry": "29-Sep-2026",
            "exchange_timestamp": "31-Aug-2026 15:30:00",
            "underlying_value": 100,
            "strikes": [
                {
                    "strike_price": 100,
                    "call": {
                        "bid_price": 5,
                        "last_price": 0,
                        "implied_volatility": 0,
                    },
                }
            ],
        },
    )

    assert limitation is None
    assert mark is not None
    assert mark["leg_marks"][0]["current_iv_percent"] is not None
    assert 20 < mark["leg_marks"][0]["current_iv_percent"] < 60
    assert mark["leg_marks"][0]["iv_source"] == "derived from close quote"


def test_old_paper_mark_iv_is_reconstructed_from_saved_observation():
    leg_marks = reconstruct_historical_leg_ivs(
        leg_marks=[
            {
                "original_action": "buy",
                "close_action": "sell",
                "option_type": "call",
                "strike_price": 100,
                "close_price_per_unit": 5,
                "current_iv_percent": None,
            }
        ],
        underlying_value=100,
        expiry=date(2026, 9, 29),
        source_timestamp=datetime(2026, 8, 31, 10, tzinfo=UTC),
        created_at=datetime(2026, 8, 31, 10, tzinfo=UTC),
    )

    assert leg_marks[0]["current_iv_percent"] is not None
    assert 20 < leg_marks[0]["current_iv_percent"] < 60
    assert leg_marks[0]["iv_source"] == "reconstructed from saved close quote"
