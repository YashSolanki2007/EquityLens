import uuid
from datetime import UTC, date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Must match qwen3-embedding:0.6b output size and the EMBED_DIM env var.
EMBED_DIM = 1024


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticker: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    cik: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    isin: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    country: Mapped[str] = mapped_column(String(2), default="US", index=True)
    universe: Mapped[str] = mapped_column(String(32), default="NSE_MAINBOARD", index=True)
    market_data_ticker: Mapped[str | None] = mapped_column(String(24), nullable=True)
    reporting_currency: Mapped[str] = mapped_column(String(8), default="USD")
    exchange: Mapped[str] = mapped_column(String(16), default="NYSE")
    sector: Mapped[str] = mapped_column(String(64))
    industry: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    cards: Mapped[list["CompanyCard"]] = relationship(back_populates="company")
    filings: Mapped[list["SecFiling"]] = relationship(back_populates="company")


class CompanyMarketSnapshot(Base):
    __tablename__ = "company_market_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    price: Mapped[float | None] = mapped_column(Float)
    market_cap_usd: Mapped[float | None] = mapped_column(Float)
    market_cap_native: Mapped[float | None] = mapped_column(Float)
    sector: Mapped[str | None] = mapped_column(String(64))
    industry: Mapped[str | None] = mapped_column(String(128))
    summary: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str | None] = mapped_column(String(8))
    source: Mapped[str] = mapped_column(String(32), default="yfinance")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_delayed_or_unverified: Mapped[bool] = mapped_column(Boolean, default=True)


class SecFiling(Base):
    __tablename__ = "sec_filings"
    __table_args__ = (
        UniqueConstraint("accession_number", name="uq_sec_filings_accession"),
        Index("ix_sec_filings_company_form_date", "company_id", "form", "filing_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    accession_number: Mapped[str] = mapped_column(String(25))
    form: Mapped[str] = mapped_column(String(16))
    filing_date: Mapped[date] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    primary_document: Mapped[str | None] = mapped_column(String(255))
    primary_doc_url: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    items: Mapped[str | None] = mapped_column(String(255))  # 8-K item codes
    downloaded: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="filings")
    chunks: Mapped[list["FilingChunk"]] = relationship(back_populates="filing")


class FilingChunk(Base):
    __tablename__ = "filing_chunks"
    __table_args__ = (
        UniqueConstraint("filing_id", "chunk_index", name="uq_filing_chunks_filing_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filing_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sec_filings.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    filing: Mapped[SecFiling] = relationship(back_populates="chunks")


class CompanyCard(Base):
    __tablename__ = "company_cards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    card_type: Mapped[str] = mapped_column(String(32), index=True)
    text: Mapped[str] = mapped_column(Text)
    directness: Mapped[str] = mapped_column(String(16))
    materiality: Mapped[str] = mapped_column(String(16))
    source_filing_accession: Mapped[str] = mapped_column(String(25))
    source_url: Mapped[str] = mapped_column(String(512))
    source_section: Mapped[str] = mapped_column(String(128))
    source_excerpt: Mapped[str] = mapped_column(Text)
    filing_date: Mapped[date] = mapped_column(Date)
    valid_from: Mapped[date] = mapped_column(Date)
    confidence: Mapped[float] = mapped_column(Float)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    embed_model: Mapped[str | None] = mapped_column(String(64))
    model_name: Mapped[str | None] = mapped_column(String(64))
    prompt_version: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    company: Mapped[Company] = relationship(back_populates="cards")


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        Index("ix_financial_facts_company_concept_end", "company_id", "concept", "end_date"),
        UniqueConstraint(
            "company_id",
            "concept",
            "unit",
            "start_date",
            "end_date",
            "accession",
            name="uq_financial_facts_period",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    concept: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16))
    value: Mapped[float] = mapped_column(Float)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(8))
    form: Mapped[str | None] = mapped_column(String(16))
    frame: Mapped[str | None] = mapped_column(String(32))
    accession: Mapped[str | None] = mapped_column(String(25))
    filed_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(32), default="sec_company_facts")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DerivedMetric(Base):
    __tablename__ = "derived_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    metric: Mapped[str] = mapped_column(String(64), index=True)
    value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))  # ok | unknown | not_directly_comparable
    current_value: Mapped[float | None] = mapped_column(Float)
    previous_value: Mapped[float | None] = mapped_column(Float)
    current_period: Mapped[str | None] = mapped_column(String(32))
    comparison_period: Mapped[str | None] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    source_facts: Mapped[dict | None] = mapped_column(JSONB)
    latest_accession: Mapped[str | None] = mapped_column(String(25))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ResearchSession(Base):
    __tablename__ = "research_sessions"
    __table_args__ = (Index("ix_research_sessions_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_query: Mapped[str] = mapped_column(Text)
    market: Mapped[str] = mapped_column(String(2), default="US", index=True)
    search_plan: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(32), default="created")
    mode: Mapped[str] = mapped_column(String(16), default="standard")  # quick | standard
    funnel: Mapped[dict | None] = mapped_column(JSONB)
    data_versions: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    candidates: Mapped[list["ResearchCandidate"]] = relationship(back_populates="session")
    messages: Mapped[list["ChatMessage"]] = relationship(back_populates="session")


class ResearchCandidate(Base):
    __tablename__ = "research_candidates"
    __table_args__ = (
        UniqueConstraint("session_id", "company_id", name="uq_research_candidates_session_company"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_sessions.id"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), index=True)
    ticker: Mapped[str] = mapped_column(String(12))
    stage: Mapped[str] = mapped_column(String(24), default="semantic")
    semantic_score: Mapped[float | None] = mapped_column(Float)
    semantic_matches: Mapped[dict | None] = mapped_column(JSONB)
    structured_filter_results: Mapped[dict | None] = mapped_column(JSONB)
    final_score: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    eligible: Mapped[bool | None] = mapped_column(Boolean)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    timed_out: Mapped[bool] = mapped_column(Boolean, default=False)
    overall_confidence: Mapped[float | None] = mapped_column(Float)
    why_matched: Mapped[str | None] = mapped_column(Text)
    contradictions: Mapped[list | None] = mapped_column(JSONB)
    limitations: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ResearchSession] = relationship(back_populates="candidates")
    company: Mapped[Company] = relationship()
    condition_results: Mapped[list["ConditionResult"]] = relationship(back_populates="candidate")


class ConditionResult(Base):
    __tablename__ = "condition_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("research_candidates.id"), index=True
    )
    condition_id: Mapped[str] = mapped_column(String(64))
    condition_type: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16))  # pass | partial | fail | unknown
    score: Mapped[float] = mapped_column(Float, default=0.0)
    measured_value: Mapped[float | None] = mapped_column(Float)
    unit: Mapped[str | None] = mapped_column(String(16))
    current_period: Mapped[str | None] = mapped_column(String(32))
    comparison_period: Mapped[str | None] = mapped_column(String(32))
    explanation: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    candidate: Mapped[ResearchCandidate] = relationship(back_populates="condition_results")
    citations: Mapped[list["Citation"]] = relationship(back_populates="condition_result")


class Citation(Base):
    __tablename__ = "citations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    condition_result_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("condition_results.id"), index=True, nullable=True
    )
    chat_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("chat_messages.id"), index=True, nullable=True
    )
    source_type: Mapped[str] = mapped_column(
        String(32)
    )  # sec_filing | sec_xbrl | market_data | company_card | news
    url: Mapped[str] = mapped_column(String(512))
    accession: Mapped[str | None] = mapped_column(String(25))
    description: Mapped[str | None] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    filing_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    condition_result: Mapped[ConditionResult | None] = relationship(back_populates="citations")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("research_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(String(48))
    citations: Mapped[list | None] = mapped_column(JSONB)
    limitations: Mapped[list | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    session: Mapped[ResearchSession] = relationship(back_populates="messages")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(
        String(48)
    )  # bootstrap | ingest_company | rebuild_embeddings
    ticker: Mapped[str | None] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending | running | done | failed
    detail: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PaperIVTrade(Base):
    __tablename__ = "paper_iv_trades"
    __table_args__ = (
        Index(
            "ix_paper_iv_trades_portfolio_ticker_status",
            "portfolio_id",
            "ticker",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id"), index=True
    )
    ticker: Mapped[str] = mapped_column(String(12), index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    strategy_name: Mapped[str] = mapped_column(String(128))
    signal: Mapped[str] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    expiry: Mapped[date] = mapped_column(Date, index=True)
    lot_size: Mapped[int] = mapped_column(Integer)
    quantity_lots: Mapped[int] = mapped_column(Integer, default=1)
    entry_underlying_value: Mapped[float | None] = mapped_column(Float)
    entry_market_iv_percent: Mapped[float | None] = mapped_column(Float)
    entry_predicted_iv_percent: Mapped[float | None] = mapped_column(Float)
    entry_premium_type: Mapped[str] = mapped_column(String(16))
    entry_cash_flow_per_lot: Mapped[float] = mapped_column(Float)
    capital_at_risk_per_lot: Mapped[float] = mapped_column(Float)
    legs: Mapped[list] = mapped_column(JSONB)
    forecast_snapshot: Mapped[dict] = mapped_column(JSONB)
    entry_exchange_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[float | None] = mapped_column(Float)

    company: Mapped[Company] = relationship()
    marks: Mapped[list["PaperIVTradeMark"]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
    )


class PaperIVTradeMark(Base):
    __tablename__ = "paper_iv_trade_marks"
    __table_args__ = (
        Index("ix_paper_iv_trade_marks_trade_created", "trade_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_iv_trades.id"), index=True
    )
    underlying_value: Mapped[float | None] = mapped_column(Float)
    close_cash_flow: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    pnl_percent: Mapped[float] = mapped_column(Float)
    leg_marks: Mapped[list] = mapped_column(JSONB)
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    price_quality: Mapped[str] = mapped_column(String(24), default="executable")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    trade: Mapped[PaperIVTrade] = relationship(back_populates="marks")


class IVModelEvaluation(Base):
    __tablename__ = "iv_model_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "target_date",
            "model_version",
            name="uq_iv_model_evaluation_ticker_target_version",
        ),
        Index("ix_iv_model_evaluations_status_target", "status", "target_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ticker: Mapped[str] = mapped_column(String(24), index=True)
    symbol: Mapped[str] = mapped_column(String(24))
    model_version: Mapped[str] = mapped_column(String(96))
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    source_as_of_date: Mapped[date] = mapped_column(Date)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    component_count: Mapped[int] = mapped_column(Integer)
    explained_variance_percent: Mapped[float] = mapped_column(Float)
    reconstruction_rmse: Mapped[float] = mapped_column(Float)
    validation_sessions: Mapped[int] = mapped_column(Integer)
    validation_model_rmse: Mapped[float] = mapped_column(Float)
    validation_baseline_rmse: Mapped[float] = mapped_column(Float)
    validation_improvement_percent: Mapped[float] = mapped_column(Float)
    validation_directional_accuracy_percent: Mapped[float | None] = mapped_column(Float)
    forecast_surface: Mapped[list] = mapped_column(JSONB)
    baseline_surface: Mapped[list] = mapped_column(JSONB)
    actual_surface: Mapped[list | None] = mapped_column(JSONB)
    model_rmse: Mapped[float | None] = mapped_column(Float)
    baseline_rmse: Mapped[float | None] = mapped_column(Float)
    improvement_over_baseline_percent: Mapped[float | None] = mapped_column(Float)
    directional_accuracy_percent: Mapped[float | None] = mapped_column(Float)
    bias_vol_points: Mapped[float | None] = mapped_column(Float)
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


class PaperPairTrade(Base):
    __tablename__ = "paper_pair_trades"
    __table_args__ = (
        Index(
            "ix_paper_pair_trades_portfolio_status",
            "portfolio_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    pair_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    long_ticker: Mapped[str] = mapped_column(String(24))
    short_ticker: Mapped[str] = mapped_column(String(24))
    expiry: Mapped[date] = mapped_column(Date, index=True)
    estimated_reversion_date: Mapped[date | None] = mapped_column(Date)
    requires_rollover: Mapped[bool] = mapped_column(Boolean, default=False)
    long_contract_name: Mapped[str] = mapped_column(String(128))
    short_contract_name: Mapped[str] = mapped_column(String(128))
    long_contracts: Mapped[int] = mapped_column(Integer)
    short_contracts: Mapped[int] = mapped_column(Integer)
    long_lot_size: Mapped[int] = mapped_column(Integer)
    short_lot_size: Mapped[int] = mapped_column(Integer)
    long_units: Mapped[int] = mapped_column(Integer)
    short_units: Mapped[int] = mapped_column(Integer)
    entry_long_price: Mapped[float] = mapped_column(Float)
    entry_short_price: Mapped[float] = mapped_column(Float)
    entry_long_notional: Mapped[float] = mapped_column(Float)
    entry_short_notional: Mapped[float] = mapped_column(Float)
    entry_combined_notional: Mapped[float] = mapped_column(Float)
    hedge_ratio: Mapped[float] = mapped_column(Float)
    hedge_fit_percent: Mapped[float] = mapped_column(Float)
    entry_zscore: Mapped[float] = mapped_column(Float)
    entry_q_value: Mapped[float] = mapped_column(Float)
    entry_price_date: Mapped[date] = mapped_column(Date)
    suggestion_snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[float | None] = mapped_column(Float)

    marks: Mapped[list["PaperPairTradeMark"]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
    )


class PaperPairTradeMark(Base):
    __tablename__ = "paper_pair_trade_marks"
    __table_args__ = (
        Index("ix_paper_pair_trade_marks_trade_date", "trade_id", "price_date"),
        UniqueConstraint(
            "trade_id",
            "price_date",
            name="uq_paper_pair_trade_marks_trade_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_pair_trades.id"), index=True
    )
    price_date: Mapped[date] = mapped_column(Date)
    long_price: Mapped[float] = mapped_column(Float)
    short_price: Mapped[float] = mapped_column(Float)
    long_pnl: Mapped[float] = mapped_column(Float)
    short_pnl: Mapped[float] = mapped_column(Float)
    total_pnl: Mapped[float] = mapped_column(Float)
    return_percent: Mapped[float] = mapped_column(Float)
    current_gross_notional: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    trade: Mapped[PaperPairTrade] = relationship(back_populates="marks")


class PaperLabSpotTrade(Base):
    """Development-only spot proxy for a dual-test pair-method observation."""

    __tablename__ = "paper_lab_spot_trades"
    __table_args__ = (
        Index(
            "uq_paper_lab_spot_trades_open_portfolio_pair",
            "portfolio_id",
            "pair_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index(
            "ix_paper_lab_spot_trades_portfolio_status",
            "portfolio_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    pair_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    long_ticker: Mapped[str] = mapped_column(String(24))
    short_ticker: Mapped[str] = mapped_column(String(24))
    long_units: Mapped[float] = mapped_column(Float)
    short_units: Mapped[float] = mapped_column(Float)
    entry_long_price: Mapped[float] = mapped_column(Float)
    entry_short_price: Mapped[float] = mapped_column(Float)
    entry_long_notional: Mapped[float] = mapped_column(Float)
    entry_short_notional: Mapped[float] = mapped_column(Float)
    entry_combined_notional: Mapped[float] = mapped_column(Float)
    hedge_ratio: Mapped[float] = mapped_column(Float)
    entry_zscore: Mapped[float] = mapped_column(Float)
    entry_p_value: Mapped[float] = mapped_column(Float)
    entry_kss_statistic: Mapped[float] = mapped_column(Float)
    entry_q_value: Mapped[float] = mapped_column(Float)
    entry_expected_return_percent: Mapped[float | None] = mapped_column(Float)
    formal_entry_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_price_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_price_source: Mapped[str] = mapped_column(String(128))
    suggestion_snapshot: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realized_pnl: Mapped[float | None] = mapped_column(Float)
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    exit_zscore: Mapped[float | None] = mapped_column(Float)
    exit_p_value: Mapped[float | None] = mapped_column(Float)

    marks: Mapped[list["PaperLabSpotTradeMark"]] = relationship(
        back_populates="trade",
        cascade="all, delete-orphan",
    )


class PaperLabSpotTradeMark(Base):
    __tablename__ = "paper_lab_spot_trade_marks"
    __table_args__ = (
        Index(
            "ix_paper_lab_spot_trade_marks_trade_created",
            "trade_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("paper_lab_spot_trades.id"), index=True
    )
    long_price: Mapped[float] = mapped_column(Float)
    short_price: Mapped[float] = mapped_column(Float)
    long_pnl: Mapped[float] = mapped_column(Float)
    short_pnl: Mapped[float] = mapped_column(Float)
    total_pnl: Mapped[float] = mapped_column(Float)
    return_percent: Mapped[float] = mapped_column(Float)
    current_long_notional: Mapped[float] = mapped_column(Float)
    current_short_notional: Mapped[float] = mapped_column(Float)
    current_gross_notional: Mapped[float] = mapped_column(Float)
    estimated_p_value: Mapped[float | None] = mapped_column(Float)
    quote_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price_source: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    trade: Mapped[PaperLabSpotTrade] = relationship(back_populates="marks")
