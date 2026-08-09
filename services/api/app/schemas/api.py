"""Request/response bodies for the HTTP API."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.search import SearchPlan


class PlanRequest(BaseModel):
    query: str
    mode: Literal["quick", "standard"] = "standard"
    market: Literal["US", "IN"] = "IN"


class RunRequest(BaseModel):
    query: str | None = None
    plan: SearchPlan | None = None
    mode: Literal["quick", "standard"] = "standard"
    market: Literal["US", "IN"] = "IN"


class PlanPatchRequest(BaseModel):
    instruction: str | None = None  # natural-language modification
    plan: SearchPlan | None = None  # or a directly edited plan
    rerun: bool = True


class FollowUpRequest(BaseModel):
    message: str


class CompanyOut(BaseModel):
    id: UUID
    ticker: str
    name: str
    cik: str | None = None
    isin: str | None = None
    country: str
    universe: str
    reporting_currency: str
    exchange: str
    sector: str
    industry: str

    model_config = {"from_attributes": True}


class MarketSnapshotOut(BaseModel):
    price: float | None = None
    market_cap_usd: float | None = None
    market_cap_native: float | None = None
    currency: str | None = None
    summary: str | None = None
    source: str
    retrieved_at: datetime
    as_of: datetime | None = None
    is_delayed_or_unverified: bool = True

    model_config = {"from_attributes": True}


class CardOut(BaseModel):
    id: UUID
    ticker: str
    card_type: str
    text: str
    directness: str
    materiality: str
    source_url: str
    source_section: str
    source_excerpt: str
    filing_date: date
    confidence: float

    model_config = {"from_attributes": True}


class FilingOut(BaseModel):
    id: UUID
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None = None
    primary_doc_url: str | None = None
    description: str | None = None
    downloaded: bool

    model_config = {"from_attributes": True}


class FunnelOut(BaseModel):
    indexed: int = 0
    semantic_matches: int = 0
    passed_base_filters: int = 0
    researched: int = 0
    fully_qualified: int = 0


class CitationOut(BaseModel):
    source_type: str
    url: str
    accession: str | None = None
    description: str | None = None
    excerpt: str | None = None
    filing_date: date | None = None


class ConditionResultOut(BaseModel):
    condition_id: str
    condition_type: str | None = None
    status: str
    score: float
    measured_value: float | None = None
    unit: str | None = None
    current_period: str | None = None
    comparison_period: str | None = None
    explanation: str
    citations: list[CitationOut] = Field(default_factory=list)


class ResultCandidateOut(BaseModel):
    company_id: UUID
    ticker: str
    name: str | None = None
    country: str | None = None
    exchange: str | None = None
    currency: str | None = None
    stage: str
    rank: int | None = None
    eligible: bool | None = None
    final_score: float | None = None
    match_percent: float | None = None
    semantic_score: float | None = None
    semantic_matches: dict | None = None
    market_cap_usd: float | None = None
    market_cap_native: float | None = None
    market_cap_retrieved_at: datetime | None = None
    completed: bool = False
    timed_out: bool = False
    overall_confidence: float | None = None
    why_matched: str | None = None
    limitations: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    condition_results: list[ConditionResultOut] = Field(default_factory=list)
    directness_badge: str | None = None


class SessionOut(BaseModel):
    id: UUID
    original_query: str
    status: str
    mode: str
    market: str
    search_plan: SearchPlan | None = None
    funnel: FunnelOut | None = None
    error: str | None = None
    created_at: datetime
    results: list[ResultCandidateOut] = Field(default_factory=list)


class SessionSummaryOut(BaseModel):
    id: UUID
    original_query: str
    status: str
    mode: str
    market: str
    created_at: datetime


class ChatMessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    intent: str | None = None
    citations: list[CitationOut] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    created_at: datetime


class JobOut(BaseModel):
    id: UUID
    job_type: str
    ticker: str | None = None
    status: str
    detail: dict | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    model_config = {"from_attributes": True}
