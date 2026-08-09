"""Public response models for a country-specific market-news pulse."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class MarketPulseArticle(BaseModel):
    id: str
    title: str
    url: str
    domain: str
    published_date: date
    category: Literal[
        "monetary_policy",
        "economy",
        "geopolitics",
        "energy_trade",
        "technology_regulation",
        "other",
    ] = "other"
    summary_lines: list[str] = Field(default_factory=list)
    market_relevance: str
    impact_direction: Literal["positive", "negative", "mixed", "unclear"] = "unclear"
    affected_areas: list[str] = Field(default_factory=list)


class MarketPulseOut(BaseModel):
    market: Literal["IN"] = "IN"
    as_of: datetime
    lookback_days: int
    oldest_allowed_date: date
    overview: str
    key_themes: list[str] = Field(default_factory=list)
    articles: list[MarketPulseArticle] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_name: str
    cached: bool = False


class BlockDealOut(BaseModel):
    trade_date: date
    symbol: str
    company_name: str
    client_name: str
    side: Literal["BUY", "SELL"]
    quantity: float
    weighted_average_price: float
    trade_value_inr: float


class BlockDealsOut(BaseModel):
    market: Literal["IN"] = "IN"
    exchange: Literal["NSE"] = "NSE"
    from_date: date
    to_date: date
    retrieved_at: datetime
    source: str
    source_url: str
    used_latest_snapshot: bool = False
    limitation: str
    deals: list[BlockDealOut] = Field(default_factory=list)
