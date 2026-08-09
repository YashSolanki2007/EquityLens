"""Query model per spec §5 plus research/worker schemas per §8 and §10."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CardType = Literal[
    "business_activity",
    "product_service",
    "customer_exposure",
    "geographic_exposure",
    "supply_chain_role",
    "macro_exposure",
]

CARD_TYPES: tuple[str, ...] = (
    "business_activity",
    "product_service",
    "customer_exposure",
    "geographic_exposure",
    "supply_chain_role",
    "macro_exposure",
)


class SemanticCondition(BaseModel):
    id: str
    concept: str
    card_types: list[CardType]
    required: bool = True
    weight: float = 0.5
    directness_required: Literal["any", "direct", "core"] = "any"


class StructuredCondition(BaseModel):
    field: Literal[
        "ticker",
        "sector",
        "industry",
        "market_cap_usd",
        "market_cap_native",
    ]
    operator: Literal["eq", "in", "gte", "lte", "between", "around"]
    value: str | float | list[str] | list[float]
    tolerance_percent: float | None = None
    required: bool = True


class ResearchCondition(BaseModel):
    id: str
    type: Literal[
        "revenue_yoy_growth",
        "net_income_yoy_growth",
        "recent_sec_catalyst",
        "custom_filing_question",
    ]
    operator: Literal["gte", "lte", "eq", "exists", "semantic_match"]
    threshold: float | None = None
    lookback_days: int | None = None
    question: str | None = None
    required: bool = True
    weight: float = 0.5


class Ambiguity(BaseModel):
    term: str
    interpretation: str
    alternatives: list[str] = Field(default_factory=list)


class SearchPlan(BaseModel):
    original_query: str
    # Legacy universes remain accepted so persisted sessions can still be opened.
    universe: Literal["NYSE_100", "NIFTY_100", "NIFTY_200", "NSE_MAINBOARD"] = (
        "NSE_MAINBOARD"
    )
    base_semantic_conditions: list[SemanticCondition] = Field(default_factory=list)
    base_structured_conditions: list[StructuredCondition] = Field(default_factory=list)
    research_conditions: list[ResearchCondition] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    candidate_limit: int = 15
    final_limit: int = 7


class Citation(BaseModel):
    source_type: Literal[
        "sec_filing",
        "exchange_filing",
        "sec_xbrl",
        "market_data",
        "company_card",
        "news",
    ] = "sec_filing"
    url: str
    accession: str | None = None
    description: str | None = None
    excerpt: str | None = None
    filing_date: date | None = None


class ConditionResult(BaseModel):
    condition_id: str
    status: Literal["pass", "partial", "fail", "unknown"]
    score: float

    measured_value: float | None = None
    unit: str | None = None
    current_period: str | None = None
    comparison_period: str | None = None

    explanation: str
    citations: list[Citation] = Field(default_factory=list)


class CandidateResearchRequest(BaseModel):
    search_id: UUID
    company_id: UUID
    ticker: str
    research_conditions: list[ResearchCondition]
    deadline_seconds: int = 25


class CandidateResearchResult(BaseModel):
    company_id: UUID
    ticker: str

    condition_results: list[ConditionResult] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    completed: bool = False
    timed_out: bool = False
    overall_confidence: float = 0.0


class CatalystFinding(BaseModel):
    status: Literal["pass", "partial", "fail", "unknown"]
    category: Literal[
        "capacity_expansion",
        "facility_opening",
        "capital_investment",
        "acquisition",
        "major_contract",
        "product_launch",
        "partnership",
        "regulatory_development",
        "other",
    ] = "other"
    event_date: date | None = None
    summary: str = ""
    state: Literal[
        "announced", "approved", "under_construction", "completed", "cancelled", "unknown"
    ] = "unknown"
    relevance_to_query: float = 0.0
    citations: list[Citation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ResearchWorkspace(BaseModel):
    id: UUID
    original_query: str
    search_plan: SearchPlan

    candidates_considered: list[UUID] = Field(default_factory=list)
    candidate_results: list[CandidateResearchResult] = Field(default_factory=list)
    final_company_ids: list[UUID] = Field(default_factory=list)

    created_at: datetime
    data_versions: dict[str, str] = Field(default_factory=dict)
