"""Schemas for the condensed company financial overview and grounded AI analysis."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class FinancialSeriesPoint(BaseModel):
    period: str
    end_date: str
    revenue: float | None = None
    net_income: float | None = None
    net_margin_percent: float | None = None
    revenue_yoy_percent: float | None = None
    net_income_yoy_percent: float | None = None
    accessions: list[str] = Field(default_factory=list)


class FinancialHeadline(BaseModel):
    period: str
    revenue: float | None = None
    net_income: float | None = None
    net_margin_percent: float | None = None
    revenue_yoy_percent: float | None = None


class RevenueMovement(BaseModel):
    id: str
    period: str
    end_date: str
    revenue: float
    change_percent: float
    direction: Literal["increase", "decline", "stable"]
    frequency: Literal["annual", "quarterly"]


class FinancialOverviewOut(BaseModel):
    ticker: str
    currency: str = "USD"
    annual: list[FinancialSeriesPoint] = Field(default_factory=list)
    quarterly: list[FinancialSeriesPoint] = Field(default_factory=list)
    headline: FinancialHeadline | None = None
    notable_movements: list[RevenueMovement] = Field(default_factory=list)
    source_url: str
    limitations: list[str] = Field(default_factory=list)


class BusinessAnalysisPoint(BaseModel):
    title: str
    explanation: str
    evidence_card_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class RevenueExplanation(BaseModel):
    movement_id: str
    period: str
    change_percent: float
    driver_type: Literal[
        "company_reported_catalyst",
        "business_context",
        "normal_variation",
        "unexplained",
    ] = "unexplained"
    explanation: str
    evidence_card_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "low"


class RevenueEvidence(BaseModel):
    id: str
    movement_id: str
    url: str
    description: str
    excerpt: str


class CompanyAnalysisOut(BaseModel):
    ticker: str
    strengths: list[BusinessAnalysisPoint] = Field(default_factory=list)
    weaknesses: list[BusinessAnalysisPoint] = Field(default_factory=list)
    revenue_explanations: list[RevenueExplanation] = Field(default_factory=list)
    revenue_evidence: list[RevenueEvidence] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    model_name: str
    generated_at: datetime
    cached: bool = False


class CompanyChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=6_000)


class CompanyChatRequest(BaseModel):
    message: str = Field(min_length=2, max_length=2_000)
    history: list[CompanyChatTurn] = Field(default_factory=list, max_length=8)


class CompanyChatResponse(BaseModel):
    ticker: str
    intent: Literal[
        "company_facts",
        "ratios",
        "technical",
        "options",
        "deep_research",
        "decision_support",
        "out_of_scope",
    ]
    answer: str
    citations: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_used: list[str] = Field(default_factory=list)
    confidence_label: Literal["high", "medium", "low"] | None = None
    confidence_percent: int | None = Field(default=None, ge=0, le=100)
    short_term_view: Literal["positive", "mixed", "negative"] | None = None
    medium_term_view: Literal["positive", "mixed", "negative", "unavailable"] | None = None
    model_name: str
    generated_at: datetime


class HorizonOutlook(BaseModel):
    horizon: str
    direction: Literal["positive", "mixed", "negative", "unavailable"]
    summary: str


class CompanyOutlookOut(BaseModel):
    ticker: str
    short_term: HorizonOutlook
    medium_term: HorizonOutlook
    confidence_label: Literal["high", "medium", "low"]
    confidence_percent: int = Field(ge=0, le=100)
    citations: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    data_used: list[str] = Field(default_factory=list)
    model_name: str
    generated_at: datetime
    cached: bool = False


class PeerMetricDefinition(BaseModel):
    key: str
    label: str
    category: str
    format: Literal["currency_compact", "multiple", "percent", "number"]
    higher_is_better: bool | None = None
    description: str


class PeerCompanyOut(BaseModel):
    ticker: str
    name: str
    sector: str
    industry: str
    currency: str
    is_subject: bool = False
    selection_reason: str
    similarity_percent: float | None = None
    data_completeness_percent: float
    metrics: dict[str, float | None] = Field(default_factory=dict)
    percentiles: dict[str, float | None] = Field(default_factory=dict)
    source: str
    source_url: str | None = None
    retrieved_at: datetime | None = None


class PeerComparisonOut(BaseModel):
    ticker: str
    peer_group_label: str
    selection_method: str
    is_manual: bool
    metric_definitions: list[PeerMetricDefinition] = Field(default_factory=list)
    companies: list[PeerCompanyOut] = Field(default_factory=list)
    subject_strengths: list[str] = Field(default_factory=list)
    subject_watch_items: list[str] = Field(default_factory=list)
    source: str
    data_as_of: datetime
    limitations: list[str] = Field(default_factory=list)


class FinancialStatementRow(BaseModel):
    key: str
    label: str
    value_type: Literal["currency", "percent", "per_share", "shares"]
    is_total: bool = False
    values: dict[str, float | None] = Field(default_factory=dict)


class FinancialStatementTable(BaseModel):
    statement_type: Literal["income", "balance_sheet", "cash_flow"]
    title: str
    frequency: Literal["annual", "quarterly"]
    periods: list[str] = Field(default_factory=list)
    rows: list[FinancialStatementRow] = Field(default_factory=list)


class FinancialStatementsOut(BaseModel):
    ticker: str
    market_data_ticker: str
    currency: str
    available: bool
    statements: list[FinancialStatementTable] = Field(default_factory=list)
    source: str
    source_url: str
    retrieved_at: datetime
    is_delayed_or_unverified: bool = True
    limitations: list[str] = Field(default_factory=list)
