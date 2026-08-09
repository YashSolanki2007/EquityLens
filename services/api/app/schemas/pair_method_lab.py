"""Development-only response models for the dynamic pairs-method lab."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class PairMethodLabChartPoint(BaseModel):
    date: str
    stock_a_indexed: float
    stock_b_indexed: float
    paper_zscore: float | None = None


class PairMethodLabCandidate(BaseModel):
    pair_id: str
    stock_a: str
    stock_a_name: str
    stock_a_type: Literal["stock", "index"]
    stock_b: str
    stock_b_name: str
    stock_b_type: Literal["stock", "index"]
    sector: str
    hedge_ratio: float
    return_correlation: float
    observations: int

    engle_granger_p_value: float
    fdr_q_value: float
    engle_granger_pass: bool
    kss_statistic: float
    kss_critical_value: float
    kss_pass: bool

    half_life_days: float
    adaptive_lookback_days: int
    current_zscore: float
    latest_price_a: float
    latest_price_b: float
    spread_gap_to_mean: float
    potential_convergence_return_percent: float
    futures_capital_available: bool = False
    futures_price_date: str | None = None
    futures_expiry: str | None = None
    capital_plan_is_active: bool = False
    capital_long_ticker: str | None = None
    capital_short_ticker: str | None = None
    long_futures_contracts: int | None = None
    short_futures_contracts: int | None = None
    long_futures_units: int | None = None
    short_futures_units: int | None = None
    long_futures_price: float | None = None
    short_futures_price: float | None = None
    long_futures_notional_inr: float | None = None
    short_futures_notional_inr: float | None = None
    combined_futures_notional_inr: float | None = None
    futures_hedge_fit_percent: float | None = None
    futures_capital_note: str | None = None
    paper_signal: Literal[
        "long_a_short_b",
        "short_a_long_b",
        "inside_entry_band",
    ]
    long_ticker: str | None = None
    short_ticker: str | None = None

    rolling_windows: int
    stability_passed_windows: int
    stability_score_percent: float
    stability_band: Literal[
        "strong",
        "moderate",
        "unstable",
        "insufficient_history",
    ]
    engle_granger_stability_percent: float
    kss_stability_percent: float
    entry_events: int
    reversion_success_rate_percent: float | None = None
    median_five_day_z_change: float | None = None

    current_method_p_value: float | None = None
    current_method_half_life_days: float | None = None
    current_method_zscore: float | None = None
    current_method_pass: bool = False
    current_method_signal: Literal[
        "long_a_short_b",
        "short_a_long_b",
        "watch",
        "not_eligible",
    ] = "not_eligible"
    comparison: Literal[
        "both_methods",
        "paper_only",
        "current_only",
        "neither",
    ]
    chart: list[PairMethodLabChartPoint] = Field(default_factory=list)


class PairMethodLabResponse(BaseModel):
    development_only: bool = True
    paper_title: str
    paper_url: str
    universe: str = "NSE_FNO"
    minimum_market_cap_crore: float = 500
    official_underlyings: int
    universe_size: int
    price_eligible_universe: int
    pairs_tested: int
    formation_days: int
    current_comparison_days: int
    trading_days: int
    rolling_validation_windows: int
    engle_granger_cutoff: float
    kss_critical_value: float
    engle_granger_candidates: int
    kss_candidates: int
    either_test_candidates: int
    returned: int
    generated_at: datetime
    data_source: str
    cached: bool = False
    results: list[PairMethodLabCandidate] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PaperLabSpotTradeSync(BaseModel):
    portfolio_id: UUID


class PaperLabSpotTradeClose(BaseModel):
    portfolio_id: UUID


class PaperLabSpotTradeMarkOut(BaseModel):
    id: UUID | None = None
    long_price: float
    short_price: float
    long_pnl: float
    short_pnl: float
    total_pnl: float
    return_percent: float
    current_long_notional: float
    current_short_notional: float
    current_gross_notional: float
    estimated_zscore: float | None
    estimated_p_value: float | None = None
    quote_timestamp: datetime
    price_source: str
    is_live: bool = False
    created_at: datetime


class PaperLabSpotTradeOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    pair_id: str
    status: Literal["open", "closed"]
    long_ticker: str
    short_ticker: str
    long_units: float
    short_units: float
    entry_long_price: float
    entry_short_price: float
    entry_long_notional: float
    entry_short_notional: float
    entry_combined_notional: float
    hedge_ratio: float
    entry_zscore: float
    entry_p_value: float
    entry_kss_statistic: float
    entry_q_value: float
    entry_expected_return_percent: float | None = None
    formal_entry_signal: bool
    entry_price_timestamp: datetime
    entry_price_source: str
    created_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float | None = None
    exit_reason: str | None = None
    exit_zscore: float | None = None
    exit_p_value: float | None = None
    latest_mark: PaperLabSpotTradeMarkOut | None = None
    live_mark: PaperLabSpotTradeMarkOut | None = None
    marks: list[PaperLabSpotTradeMarkOut] = Field(default_factory=list)
    valuation_limitation: str | None = None


class PaperLabSpotTradeSyncOut(BaseModel):
    eligible_pairs: int
    created_trades: int
    trades: list[PaperLabSpotTradeOut] = Field(default_factory=list)
