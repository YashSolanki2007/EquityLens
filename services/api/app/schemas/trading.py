"""NSE-only market, price-history, and derivatives response models."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class TradingRatiosOut(BaseModel):
    ticker: str
    market_data_ticker: str
    currency: str = "INR"
    current_price: float | None = None
    previous_close: float | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    trailing_eps: float | None = None
    forward_eps: float | None = None
    price_to_book: float | None = None
    peg_ratio: float | None = None
    book_value: float | None = None
    profit_margin_percent: float | None = None
    operating_margin_percent: float | None = None
    gross_margin_percent: float | None = None
    return_on_equity_percent: float | None = None
    return_on_assets_percent: float | None = None
    revenue_growth_percent: float | None = None
    earnings_growth_percent: float | None = None
    debt_to_equity_percent: float | None = None
    current_ratio: float | None = None
    quick_ratio: float | None = None
    dividend_yield_percent: float | None = None
    payout_ratio_percent: float | None = None
    beta: float | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None
    volume: float | None = None
    average_volume: float | None = None
    source: str
    source_url: str
    retrieved_at: datetime
    is_delayed_or_unverified: bool = True


class PriceCandleOut(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceHistoryOut(BaseModel):
    ticker: str
    market_data_ticker: str
    range: Literal["1M", "3M", "6M", "1Y", "5Y", "MAX"]
    interval: str
    currency: str = "INR"
    candles: list[PriceCandleOut] = Field(default_factory=list)
    source: str
    source_url: str
    retrieved_at: datetime
    is_delayed_or_unverified: bool = True


class ForecastPointOut(BaseModel):
    date: str
    p05: float
    p10: float
    p25: float
    median: float
    p75: float
    p90: float
    p95: float
    annualized_volatility_percent: float


class ForecastPathPointOut(BaseModel):
    date: str
    price: float


class ForecastSamplePathOut(BaseModel):
    id: int
    points: list[ForecastPathPointOut] = Field(default_factory=list)


class RegressionForecastPointOut(BaseModel):
    date: str
    predicted_price: float
    predicted_return_percent: float


class PriceForecastOut(BaseModel):
    ticker: str
    market_data_ticker: str
    currency: str
    available: bool
    model: str = "ARIMA(1,1,1) drift + GARCH(1,1)-t volatility + Monte Carlo"
    horizon_days: int
    simulations: int
    observations: int = 0
    fit_start: str | None = None
    fit_end: str | None = None
    last_price: float | None = None
    median_terminal_price: float | None = None
    terminal_range_80_low: float | None = None
    terminal_range_80_high: float | None = None
    probability_finish_above_last: float | None = None
    annualized_arima_drift_percent: float | None = None
    current_annualized_volatility_percent: float | None = None
    long_run_annualized_volatility_percent: float | None = None
    arima_ar1: float | None = None
    arima_ma1: float | None = None
    garch_omega: float | None = None
    garch_alpha1: float | None = None
    garch_beta1: float | None = None
    student_t_degrees_of_freedom: float | None = None
    points: list[ForecastPointOut] = Field(default_factory=list)
    sample_paths: list[ForecastSamplePathOut] = Field(default_factory=list)
    regression_available: bool = False
    regression_model: str | None = None
    regression_terminal_price: float | None = None
    regression_terminal_return_percent: float | None = None
    regression_points: list[RegressionForecastPointOut] = Field(default_factory=list)
    regression_observations: int = 0
    regression_validation_r_squared: float | None = None
    regression_validation_mae_percent: float | None = None
    regression_standardized_coefficients: dict[str, float] = Field(default_factory=dict)
    regression_latest_features: dict[str, float] = Field(default_factory=dict)
    regression_limitations: list[str] = Field(default_factory=list)
    source: str
    source_url: str
    generated_at: datetime
    is_delayed_or_unverified: bool = True
    limitations: list[str] = Field(default_factory=list)


class OptionLegOut(BaseModel):
    last_price: float | None = None
    change: float | None = None
    percent_change: float | None = None
    open_interest: float | None = None
    change_in_open_interest: float | None = None
    percent_change_in_open_interest: float | None = None
    volume: float | None = None
    implied_volatility: float | None = None
    bid_price: float | None = None
    bid_quantity: float | None = None
    ask_price: float | None = None
    ask_quantity: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    rho: float | None = None


class OptionStrikeOut(BaseModel):
    strike_price: float
    call: OptionLegOut | None = None
    put: OptionLegOut | None = None


class ImpliedProbabilityBucketOut(BaseModel):
    label: str
    lower_bound: float | None = None
    upper_bound: float | None = None
    chart_price: float
    probability: float


class ImpliedProbabilityPointOut(BaseModel):
    strike_price: float
    probability_above: float


class OptionsDistributionOut(BaseModel):
    available: bool = False
    method: str = "Black-Scholes N(d2), liquidity-filtered and monotonic-adjusted"
    buckets: list[ImpliedProbabilityBucketOut] = Field(default_factory=list)
    curve: list[ImpliedProbabilityPointOut] = Field(default_factory=list)
    most_likely_range: str | None = None
    median_price: float | None = None
    range_50_low: float | None = None
    range_50_high: float | None = None
    range_80_low: float | None = None
    range_80_high: float | None = None
    probability_above_spot: float | None = None
    probability_below_spot: float | None = None
    quality_score: float = 0
    quality_label: Literal["high", "medium", "low", "unavailable"] = "unavailable"
    valid_iv_coverage_percent: float = 0
    active_contract_coverage_percent: float = 0
    median_relative_spread_percent: float | None = None
    strikes_used: int = 0
    total_strikes: int = 0
    monotonic_adjustments: int = 0
    limitation: str | None = None


class OptionsChainOut(BaseModel):
    ticker: str
    symbol: str
    available: bool
    selected_expiry: str | None = None
    expiry_dates: list[str] = Field(default_factory=list)
    underlying_value: float | None = None
    exchange_timestamp: str | None = None
    greeks_model: str = "Black-Scholes"
    greeks_are_modeled: bool = True
    risk_free_rate_percent: float = 6.5
    dividend_yield_percent: float = 0.0
    strikes: list[OptionStrikeOut] = Field(default_factory=list)
    distribution: OptionsDistributionOut = Field(default_factory=OptionsDistributionOut)
    source: str = "NSE India"
    source_url: str
    retrieved_at: datetime
    is_delayed_or_unverified: bool = True
    limitation: str | None = None


class IVSurfaceComparisonOut(BaseModel):
    label: str
    side: Literal["call", "put", "call_put"]
    strike_price: float
    market_iv_percent: float
    call_market_iv_percent: float | None = None
    put_market_iv_percent: float | None = None
    predicted_iv_percent: float
    difference_vol_points: float
    model_error_vol_points: float
    material_threshold_vol_points: float
    standardized_gap: float | None = None
    significant: bool | None = None
    status: Literal["cheap", "expensive", "in_line"]
    explanation: str


class IVStrategyLegOut(BaseModel):
    action: Literal["buy", "sell"]
    option_type: Literal["call", "put"]
    strike_price: float
    quantity_lots: int = 1
    premium_per_unit: float
    price_source: str


class IVStrategyPayoffPointOut(BaseModel):
    underlying_price: float
    pnl_per_lot: float
    next_session_pnl_per_lot: float
    pnl_percent_of_capital_at_risk: float


class IVStrategyOut(BaseModel):
    strategy_id: str | None = None
    available: bool
    signal: Literal[
        "long_volatility",
        "short_volatility_defined_risk",
        "directional_defined_risk",
        "no_trade",
    ]
    strategy_name: str
    rationale: str
    source_buckets: list[str] = Field(default_factory=list)
    expiry: str | None = None
    lot_size: int | None = None
    underlying_value: float | None = None
    atm_market_iv_percent: float | None = None
    atm_predicted_iv_percent: float | None = None
    market_iv_percent: float | None = None
    predicted_iv_percent: float | None = None
    iv_difference_vol_points: float | None = None
    legs: list[IVStrategyLegOut] = Field(default_factory=list)
    entry_premium_type: Literal["debit", "credit"] | None = None
    entry_premium_per_unit: float | None = None
    entry_cash_flow_per_lot: float | None = None
    capital_at_risk_per_lot: float | None = None
    maximum_profit_per_lot: float | None = None
    maximum_loss_per_lot: float | None = None
    lower_break_even: float | None = None
    upper_break_even: float | None = None
    payoff_points: list[IVStrategyPayoffPointOut] = Field(default_factory=list)
    payoff_horizon: str | None = None
    limitations: list[str] = Field(default_factory=list)


class IVSurfaceForecastOut(BaseModel):
    ticker: str
    symbol: str
    available: bool
    selected_expiry: str | None = None
    days_to_expiry: int | None = None
    forecast_for_date: str | None = None
    model: str
    model_version: str
    model_family: Literal["fpca_var", "path_dependent_ssvi"] = "fpca_var"
    observations: int = 0
    fit_start: str | None = None
    fit_end: str | None = None
    principal_components: int | None = None
    explained_variance_percent: float | None = None
    validation_sessions: int = 0
    validation_rmse_by_components: dict[str, float] = Field(default_factory=dict)
    fourth_component_improvement_percent: float | None = None
    component_selection_note: str
    validation_model_rmse: float | None = None
    validation_baseline_rmse: float | None = None
    validation_improvement_over_baseline_percent: float | None = None
    validation_directional_accuracy_percent: float | None = None
    ssvi_parameters: dict[str, float] | None = None
    path_features: dict[str, dict[str, float]] | None = None
    static_arbitrage_checks: dict[str, float | bool] | None = None
    tenor_grid_days: list[int] = Field(default_factory=list)
    comparisons: list[IVSurfaceComparisonOut] = Field(default_factory=list)
    strategy: IVStrategyOut
    strategies: list[IVStrategyOut] = Field(default_factory=list)
    overall_status: Literal["cheap", "expensive", "in_line", "unavailable"]
    summary: str
    method_note: str
    adaptation_note: str
    source: str
    source_url: str
    paper_url: str
    generated_at: datetime
    is_delayed_or_unverified: bool = True
    is_carried_forward: bool = False
    refresh_limitation: str | None = None
    limitation: str | None = None


class PaperIVTradeCreate(BaseModel):
    portfolio_id: UUID
    expiry: str
    strategy_id: str | None = None
    model_family: Literal["fpca_var", "path_dependent_ssvi"] = "fpca_var"
    quantity_lots: int = Field(default=1, ge=1, le=20)


class PaperIVTradeClose(BaseModel):
    portfolio_id: UUID


class PaperIVLegMarkOut(BaseModel):
    original_action: Literal["buy", "sell"]
    close_action: Literal["buy", "sell"]
    option_type: Literal["call", "put"]
    strike_price: float
    quantity_lots: int
    quantity_units: int
    entry_price_per_unit: float
    close_price_per_unit: float
    close_price_source: str
    close_cash_flow: float
    current_iv_percent: float | None = None
    iv_source: str | None = None


class PaperIVTradeMarkOut(BaseModel):
    id: UUID
    underlying_value: float | None = None
    close_cash_flow: float
    pnl: float
    pnl_percent: float
    leg_marks: list[PaperIVLegMarkOut] = Field(default_factory=list)
    source_timestamp: datetime | None = None
    price_quality: Literal["executable", "estimated"]
    current_market_iv_percent: float | None = None
    created_at: datetime


class PaperIVTradeOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    ticker: str
    symbol: str
    strategy_name: str
    signal: str
    status: Literal["open", "closed"]
    expiry: str
    lot_size: int
    quantity_lots: int
    entry_underlying_value: float | None = None
    entry_market_iv_percent: float | None = None
    entry_predicted_iv_percent: float | None = None
    forecast_generated_at: datetime | None = None
    forecast_for_date: str | None = None
    entry_premium_type: Literal["debit", "credit"]
    entry_cash_flow: float
    capital_at_risk: float
    legs: list[IVStrategyLegOut] = Field(default_factory=list)
    created_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float | None = None
    latest_mark: PaperIVTradeMarkOut | None = None
    marks: list[PaperIVTradeMarkOut] = Field(default_factory=list)
    valuation_limitation: str | None = None
