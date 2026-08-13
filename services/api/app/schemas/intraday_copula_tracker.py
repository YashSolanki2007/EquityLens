"""Schemas for the development-only five-minute copula tracker."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class IntradayCopulaHistoryPoint(BaseModel):
    timestamp: datetime
    h_a_given_b: float
    h_b_given_a: float
    stock_a_price: float
    stock_b_price: float


class IntradayCopulaCandidate(BaseModel):
    pair_id: str
    stock_a: str
    stock_a_name: str
    stock_b: str
    stock_b_name: str
    sector: str
    engle_granger_p_value: float
    fdr_q_value: float
    kss_statistic: float
    regression_days: int
    intraday_sessions: int
    formation_bars: int
    reference_beta_a: float
    reference_beta_b: float
    marginal_a: Literal["Gaussian", "Student-t", "Cauchy"]
    marginal_b: Literal["Gaussian", "Student-t", "Cauchy"]
    copula_family: Literal["Gaussian", "Student-t", "Clayton", "Frank", "Gumbel"]
    copula_parameter: float
    copula_degrees_of_freedom: float | None = None
    copula_aic: float
    h_a_given_b: float
    h_b_given_a: float
    signal: Literal[
        "enter_long_a_short_b",
        "enter_short_a_long_b",
        "exit",
        "watch",
    ]
    long_ticker: str | None = None
    short_ticker: str | None = None
    long_weight: float | None = None
    short_weight: float | None = None
    stock_a_price: float
    stock_b_price: float
    session_open_a: float
    session_open_b: float
    session_open_timestamp: datetime
    latest_bar_end: datetime
    can_enter: bool
    entry_block_reason: str | None = None
    history: list[IntradayCopulaHistoryPoint] = Field(default_factory=list)


class IntradayCopulaTradeMarkOut(BaseModel):
    id: UUID | None = None
    long_price: float
    short_price: float
    long_pnl: float
    short_pnl: float
    total_pnl: float
    return_percent: float
    current_gross_notional: float
    h_a_given_b: float
    h_b_given_a: float
    quote_timestamp: datetime
    price_source: str
    created_at: datetime


class IntradayCopulaTradeOut(BaseModel):
    id: UUID
    portfolio_id: UUID
    pair_id: str
    session_date: date
    status: Literal["open", "closed"]
    stock_a: str
    stock_b: str
    long_ticker: str
    short_ticker: str
    long_units: float
    short_units: float
    entry_long_price: float
    entry_short_price: float
    entry_long_notional: float
    entry_short_notional: float
    entry_combined_notional: float
    entry_h_a_given_b: float
    entry_h_b_given_a: float
    entry_q_value: float
    entry_kss_statistic: float
    copula_family: str
    profit_target_percent: float
    stop_loss_percent: float
    entry_price_timestamp: datetime
    entry_price_source: str
    created_at: datetime
    closed_at: datetime | None = None
    realized_pnl: float | None = None
    exit_reason: str | None = None
    exit_h_a_given_b: float | None = None
    exit_h_b_given_a: float | None = None
    latest_mark: IntradayCopulaTradeMarkOut | None = None
    marks: list[IntradayCopulaTradeMarkOut] = Field(default_factory=list)


class IntradayCopulaPendingEntryOut(BaseModel):
    id: UUID
    pair_id: str
    signal_session_date: date
    status: Literal["queued", "entered", "cancelled"]
    stock_a: str
    stock_b: str
    long_ticker: str
    short_ticker: str
    observed_h_a_given_b: float
    observed_h_b_given_a: float
    entry_q_value: float
    copula_family: str
    signal_observed_at: datetime
    entered_trade_id: UUID | None = None
    created_at: datetime


class IntradayCopulaTrackerSync(BaseModel):
    portfolio_id: UUID
    candidate_limit: int = Field(default=12, ge=1, le=160)


class IntradayCopulaTrackerResponse(BaseModel):
    development_only: bool = True
    bar_minutes: int
    daily_regression_days: int
    intraday_history_period: str
    entry_threshold: float
    exit_band_low: float
    exit_band_high: float
    profit_target_percent: float
    entry_start_ist: str
    last_entry_ist: str
    forced_exit_ist: str
    eligible_pairs: int
    returned_candidates: int
    entry_signals: int
    created_trades: int
    queued_entries_created: int
    generated_at: datetime
    snapshot_bar_end: datetime | None = None
    cached: bool = False
    refreshing: bool = False
    data_source: str
    candidates: list[IntradayCopulaCandidate] = Field(default_factory=list)
    pending_entries: list[IntradayCopulaPendingEntryOut] = Field(default_factory=list)
    trades: list[IntradayCopulaTradeOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
