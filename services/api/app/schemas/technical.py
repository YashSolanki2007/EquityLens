"""Schemas for the natural-language NSE technical scanner."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

TechnicalIndicator = Literal[
    "rsi_14",
    "macd_histogram",
    "price_vs_vwap_percent",
    "ema_9_vs_ema_21_percent",
    "return_5c_percent",
    "return_15c_percent",
    "return_60c_percent",
    "relative_volume",
    "atr_percent",
    "bollinger_position_percent",
    "call_oi_change_percent",
    "put_oi_change_percent",
    "put_call_oi_ratio",
    "call_delta",
    "put_delta",
]
TechnicalOperator = Literal["gt", "gte", "lt", "lte", "between"]
TechnicalCandleInterval = Literal["1m", "5m", "15m", "30m", "1h", "1d"]


class TechnicalCondition(BaseModel):
    indicator: TechnicalIndicator
    operator: TechnicalOperator
    value: float | list[float]
    required: bool = True

    @model_validator(mode="after")
    def validate_value_shape(self):
        if self.operator == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires exactly two numeric values")
            self.value = sorted(float(value) for value in self.value)
        elif isinstance(self.value, list):
            raise ValueError(f"{self.operator} requires one numeric value")
        return self


class TechnicalScanPlan(BaseModel):
    original_query: str
    semantic_concept: str | None = None
    conditions: list[TechnicalCondition] = Field(default_factory=list)
    sort_by: TechnicalIndicator | None = None
    sort_direction: Literal["asc", "desc"] = "desc"
    result_limit: int = Field(default=20, ge=1, le=50)

    @field_validator("sort_direction", mode="before")
    @classmethod
    def default_missing_sort_direction(cls, value):
        return value or "desc"


class TechnicalScanRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    result_limit: int = Field(default=20, ge=1, le=50)
    candle_interval: TechnicalCandleInterval = "1m"
    candle_count: int = Field(default=70, ge=35, le=70)


class IntradayTechnicalSnapshot(BaseModel):
    ticker: str
    name: str
    sector: str
    industry: str
    price: float | None = None
    candle_time: datetime
    candle_interval: TechnicalCandleInterval
    candles_used: int
    rsi_14: float | None = None
    macd_histogram: float | None = None
    price_vs_vwap_percent: float | None = None
    ema_9_vs_ema_21_percent: float | None = None
    return_5c_percent: float | None = None
    return_15c_percent: float | None = None
    return_60c_percent: float | None = None
    relative_volume: float | None = None
    atr_percent: float | None = None
    bollinger_position_percent: float | None = None
    source: str
    source_url: str
    is_delayed_or_unverified: bool = True
    options_available: bool = False
    option_expiry: str | None = None
    call_open_interest: float | None = None
    put_open_interest: float | None = None
    call_oi_change_percent: float | None = None
    put_oi_change_percent: float | None = None
    put_call_oi_ratio: float | None = None
    call_delta: float | None = None
    call_delta_strike: float | None = None
    put_delta: float | None = None
    put_delta_strike: float | None = None
    option_source_url: str | None = None


class TechnicalScanResult(IntradayTechnicalSnapshot):
    technical_score: float
    semantic_score: float | None = None
    combined_score: float
    matched_conditions: list[str] = Field(default_factory=list)
    semantic_evidence: str | None = None


class TechnicalScanResponse(BaseModel):
    query: str
    plan: TechnicalScanPlan
    universe: str = "NSE_MAINBOARD"
    universe_size: int
    semantic_candidates: int
    scanned: int
    failed: int
    candle_scan_skipped: bool = False
    option_candidates: int = 0
    options_scanned: int = 0
    options_available: int = 0
    options_failed: int = 0
    returned: int
    candle_interval: TechnicalCandleInterval
    candle_limit: int
    generated_at: datetime
    data_source: str
    results: list[TechnicalScanResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
