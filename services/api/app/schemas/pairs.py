"""Response models for statistically screened NSE pair-trade suggestions."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PairChartPoint(BaseModel):
    date: str
    stock_a_indexed: float
    stock_b_indexed: float
    spread_zscore: float | None = None


class PairSuggestion(BaseModel):
    pair_id: str
    stock_a: str
    stock_a_name: str
    stock_a_type: Literal["stock", "index"]
    stock_b: str
    stock_b_name: str
    stock_b_type: Literal["stock", "index"]
    sector: str
    signal: Literal["long_a_short_b", "short_a_long_b", "watch"]
    long_ticker: str
    short_ticker: str
    example_long_quantity: int
    example_short_quantity: int
    example_long_price: float
    example_short_price: float
    example_long_value_inr: float
    example_short_value_inr: float
    example_target_long_price: float
    example_target_short_price: float
    example_gross_return_percent: float
    futures_plan_available: bool = False
    futures_plan_note: str | None = None
    futures_price_date: str | None = None
    estimated_reversion_date: str | None = None
    futures_expiry: str | None = None
    futures_requires_rollover: bool = False
    long_futures_contract_name: str | None = None
    short_futures_contract_name: str | None = None
    long_futures_price: float | None = None
    short_futures_price: float | None = None
    long_futures_target_price: float | None = None
    short_futures_target_price: float | None = None
    long_futures_lot_size: int | None = None
    short_futures_lot_size: int | None = None
    long_futures_contracts: int | None = None
    short_futures_contracts: int | None = None
    long_futures_units: int | None = None
    short_futures_units: int | None = None
    long_futures_notional_inr: float | None = None
    short_futures_notional_inr: float | None = None
    futures_hedge_fit_percent: float | None = None
    explanation: str
    hedge_ratio: float
    current_zscore: float
    cointegration_p_value: float
    fdr_q_value: float
    half_life_days: float
    return_correlation: float
    observations: int
    stock_a_market_cap_crore: float | None = None
    stock_b_market_cap_crore: float | None = None
    stock_a_median_daily_value_crore: float | None = None
    stock_b_median_daily_value_crore: float | None = None
    chart: list[PairChartPoint] = Field(default_factory=list)


class PairThresholdCount(BaseModel):
    threshold: float
    p_significant_pairs: int


class PairSuggestionsResponse(BaseModel):
    universe: str = "NSE_FNO"
    minimum_market_cap_crore: float = 500
    official_underlyings: int
    stock_underlyings: int
    index_underlyings: int
    universe_size: int
    price_eligible_universe: int
    pairs_tested: int
    p_value_threshold: float = 0.001
    p_significant_pairs: int
    threshold_counts: list[PairThresholdCount] = Field(default_factory=list)
    returned: int
    generated_at: datetime
    data_source: str
    cached: bool = False
    results: list[PairSuggestion] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PaperPairTradeCreate(BaseModel):
    portfolio_id: UUID
    pair_id: str = Field(min_length=3, max_length=32)
    p_value_threshold: float = Field(default=0.001, ge=0.0001, le=0.05)


class PaperPairTradeClose(BaseModel):
    portfolio_id: UUID


class PaperPairTradeMarkOut(BaseModel):
    id: UUID | None = None
    price_date: str
    long_price: float
    short_price: float
    long_pnl: float
    short_pnl: float
    current_long_notional: float
    current_short_notional: float
    quote_timestamp: datetime
    price_source: str
    is_live: bool = False
    total_pnl: float
    return_percent: float
    current_gross_notional: float
    created_at: datetime


class PaperPairTradeOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    pair_id: str
    status: Literal["open", "closed"]
    entry_signal: Literal["active", "watch"]
    long_ticker: str
    short_ticker: str
    expiry: str
    estimated_reversion_date: str | None = None
    requires_rollover: bool
    long_contract_name: str
    short_contract_name: str
    long_contracts: int
    short_contracts: int
    long_lot_size: int
    short_lot_size: int
    long_units: int
    short_units: int
    entry_long_price: float
    entry_short_price: float
    entry_long_notional: float
    entry_short_notional: float
    entry_combined_notional: float
    hedge_ratio: float
    hedge_fit_percent: float
    entry_zscore: float
    entry_q_value: float
    entry_price_date: str
    entry_price_source: str
    entry_price_timestamp: datetime | None = None
    created_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float | None = None
    latest_mark: PaperPairTradeMarkOut | None = None
    live_mark: PaperPairTradeMarkOut | None = None
    marks: list[PaperPairTradeMarkOut] = Field(default_factory=list)
    valuation_limitation: str | None = None
