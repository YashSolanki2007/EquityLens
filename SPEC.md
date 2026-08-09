# Claude Code Build Specification
## Local, Free-Model Semantic Equity Research Prototype

### 0. Goal

Build a local-first web application that lets a user:

1. Search a fixed universe of **100 large NYSE-listed companies** using natural language.
2. Combine relatively stable company attributes with current research conditions.
3. Retrieve an initial candidate set through precomputed semantic company cards.
4. Research the shortlisted companies in parallel using SEC filings and free public data.
5. Verify numeric conditions deterministically.
6. Return a ranked, cited result set.
7. Ask follow-up questions grounded in the saved research session.
8. Modify the original query conversationally and rerun only the affected stages.

The product is an information-retrieval and research tool. It must not provide buy/sell recommendations, price targets, expected returns, portfolio allocations, or “multibagger” rankings.

---

## 1. Prototype Scope

### Included

- Exactly 100 checked-in NYSE companies.
- Semantic search over:
  - Business activities
  - Products and services
  - Customer industries
  - Geographic exposure
  - Supply-chain role
  - Broad macro exposure
- Structured filters:
  - Ticker
  - Sector
  - Industry
  - Market-cap target/range
  - Latest revenue YoY growth
  - Latest net-income YoY growth
- Dynamic research:
  - Latest 10-Q/10-K financial values
  - Recent 8-K catalysts
  - Recent company filing descriptions
- Parallel research for shortlisted companies.
- Evidence links to SEC filings.
- Follow-up chat grounded in the current research workspace.
- Local open-weight models only.

### Excluded

- Brokerage execution
- Authentication and payments
- Mobile app
- Intraday market data
- Options, technical analysis, or predictions
- Portfolio recommendations
- Full NYSE/Nasdaq coverage
- General web crawling
- Paid APIs or paid model providers
- A complete historical financial warehouse

---

## 2. Required Technology Stack

### Frontend

- Next.js 15+
- TypeScript
- Tailwind CSS
- shadcn/ui
- TanStack Query
- Recharts
- Zod

### Backend

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- httpx
- asyncio
- tenacity
- PyMuPDF
- BeautifulSoup4
- pandas or Polars

### Storage

Use PostgreSQL with pgvector in Docker.

Tables store:

- Companies
- Semantic cards
- Embeddings
- SEC filing metadata
- Parsed filing chunks
- Cached financial facts
- Research sessions
- Candidate results
- Citations
- Follow-up messages

For the prototype, PostgreSQL is enough. Do not add Redis, Kafka, Airflow, OpenSearch, Neo4j, Celery, or Kubernetes.

### Local models

Run models through Ollama.

Use:

```text
Generation / routing / extraction:
qwen3:8b

Low-memory fallback:
qwen3:4b

Embeddings:
qwen3-embedding:0.6b
```

All model access must go through a provider interface so another Ollama model can be substituted through environment variables.

Required environment variables:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=qwen3:8b
OLLAMA_EMBED_MODEL=qwen3-embedding:0.6b
```

Do not call OpenAI, Anthropic, Moonshot, Alibaba Cloud, Together, Groq, Fireworks, or any other paid/hosted model API.

---

## 3. Free Data Sources

### SEC EDGAR

Use SEC public APIs and archives for:

- Company submissions
- 10-K filings
- 10-Q filings
- 8-K filings
- Company Facts XBRL data
- Filing HTML

Every request must include a descriptive `User-Agent` configured in `.env`.

```env
SEC_USER_AGENT=EquityResearchPrototype developer@example.com
```

Rate-limit SEC requests to no more than 8 requests per second to remain below the published maximum.

### Market data

Use `yfinance` only for prototype snapshots of:

- Latest share price
- Market capitalization
- Sector
- Industry
- Company summary

Cache results for 12 hours.

Treat this adapter as replaceable and clearly label market data with:

- `source`
- `retrieved_at`
- `as_of`
- `is_delayed_or_unverified=true`

The app must still function if market data is temporarily unavailable; affected filters should be marked “not verified.”

### Company universe

Create:

```text
data/companies.csv
```

with exactly 100 manually reviewed large NYSE-listed companies.

Required columns:

```csv
ticker,name,cik,exchange,sector,industry
```

The universe is fixed for the prototype. Do not scrape and dynamically change the 100-company list.

---

## 4. Core Product Flow

```text
User query
  -> Query planner
  -> Base semantic retrieval
  -> Cheap metadata filtering
  -> Top 10-15 candidates
  -> Parallel bounded research workers
  -> Deterministic financial verification
  -> Final ranking
  -> Saved research workspace
  -> Grounded follow-up chat
```

Target latency:

- Base semantic search: under 3 seconds
- Standard deep search: under 40 seconds
- Follow-up using existing facts: under 8 seconds
- Follow-up requiring new research: under 30 seconds

---

## 5. Query Model

The query planner must convert natural language into this schema:

```python
class SearchPlan(BaseModel):
    original_query: str

    universe: Literal["NYSE_100"]

    base_semantic_conditions: list[SemanticCondition]
    base_structured_conditions: list[StructuredCondition]
    research_conditions: list[ResearchCondition]

    exclusions: list[str]
    ambiguities: list[Ambiguity]
    candidate_limit: int = 15
    final_limit: int = 7
```

### Semantic condition

```python
class SemanticCondition(BaseModel):
    id: str
    concept: str
    card_types: list[
        Literal[
            "business_activity",
            "product_service",
            "customer_exposure",
            "geographic_exposure",
            "supply_chain_role",
            "macro_exposure"
        ]
    ]
    required: bool
    weight: float
    directness_required: Literal["any", "direct", "core"] = "any"
```

### Structured condition

```python
class StructuredCondition(BaseModel):
    field: Literal[
        "ticker",
        "sector",
        "industry",
        "market_cap_usd"
    ]
    operator: Literal["eq", "in", "gte", "lte", "between", "around"]
    value: str | float | list[str] | list[float]
    tolerance_percent: float | None = None
    required: bool = True
```

### Research condition

```python
class ResearchCondition(BaseModel):
    id: str
    type: Literal[
        "revenue_yoy_growth",
        "net_income_yoy_growth",
        "recent_sec_catalyst",
        "custom_filing_question"
    ]
    operator: Literal["gte", "lte", "eq", "exists", "semantic_match"]
    threshold: float | None = None
    lookback_days: int | None = None
    question: str | None = None
    required: bool = True
    weight: float
```

### Planner behavior

Example input:

> Find NYSE data-center companies around a $3B market cap with at least 20% latest-quarter revenue YoY growth and a recent expansion catalyst.

Expected plan:

```json
{
  "universe": "NYSE_100",
  "base_semantic_conditions": [
    {
      "id": "data_center",
      "concept": "material involvement in data-center infrastructure, operation, servers, networking, power, cooling, or cloud compute",
      "card_types": ["business_activity", "product_service", "supply_chain_role"],
      "required": true,
      "weight": 0.45,
      "directness_required": "direct"
    }
  ],
  "base_structured_conditions": [
    {
      "field": "market_cap_usd",
      "operator": "around",
      "value": 3000000000,
      "tolerance_percent": 40,
      "required": true
    }
  ],
  "research_conditions": [
    {
      "id": "revenue_growth",
      "type": "revenue_yoy_growth",
      "operator": "gte",
      "threshold": 20,
      "required": true,
      "weight": 0.30
    },
    {
      "id": "expansion",
      "type": "recent_sec_catalyst",
      "operator": "semantic_match",
      "lookback_days": 365,
      "question": "Has the company announced or completed a material capacity, facility, data-center, compute, or infrastructure expansion?",
      "required": true,
      "weight": 0.25
    }
  ],
  "candidate_limit": 15,
  "final_limit": 7
}
```

The frontend must display the interpreted conditions as editable chips before or alongside execution.

---

## 6. Offline Company-Card Pipeline

### Objective

Create a small theorem-search-style semantic index before the app is used.

For each company:

1. Download the latest 10-K.
2. Extract:
   - Business section
   - Products/services
   - Segments
   - Customers/end markets
   - Geographic exposure
   - Important inputs and dependencies
3. Generate atomic semantic cards.
4. Validate that each card is supported by a source passage.
5. Embed each card.
6. Store the card, metadata, evidence, and vector.

### Card format

```python
class CompanyCard(BaseModel):
    id: UUID
    company_id: UUID
    ticker: str

    card_type: Literal[
        "business_activity",
        "product_service",
        "customer_exposure",
        "geographic_exposure",
        "supply_chain_role",
        "macro_exposure"
    ]

    text: str
    directness: Literal["core", "direct", "indirect", "prospective"]
    materiality: Literal["major", "meaningful", "minor", "unknown"]

    source_filing_accession: str
    source_url: str
    source_section: str
    source_excerpt: str

    filing_date: date
    valid_from: date
    confidence: float
    embedding: list[float]
```

### Card-writing rules

- One atomic fact per card.
- One or two sentences.
- Target 20-50 words.
- Maximum 80 words.
- No investment opinion.
- No valuation language.
- No unsupported inference.
- Preserve qualifiers.
- Never write “the document says.”
- Generate 10-25 cards per company.
- Reject cards not entailed by the evidence excerpt.

### Example

```json
{
  "ticker": "EQIX",
  "card_type": "business_activity",
  "text": "Operates interconnected data centers that provide colocation and connectivity services to enterprises, cloud providers, and network operators.",
  "directness": "core",
  "materiality": "major"
}
```

### Generation workflow

Use two local-model passes:

1. `extract_cards`: generate candidate cards as structured JSON.
2. `verify_cards`: given the excerpt and each card, return:
   - `entailed`
   - `partially_entailed`
   - `not_entailed`

Store only `entailed` cards with confidence >= 0.75.

---

## 7. Semantic Retrieval

For each semantic condition:

1. Embed the condition using `qwen3-embedding:0.6b`.
2. Search pgvector independently.
3. Filter by requested card types and directness.
4. Retrieve top 100 cards.
5. Group by company.
6. Keep the best three cards per company per condition.
7. Compute a preliminary company score.

Use cosine distance.

### Preliminary score

```text
semantic_score =
  0.70 * best_card_similarity
  + 0.20 * directness_score
  + 0.10 * source_confidence
```

Directness mapping:

```text
core        1.00
direct      0.85
indirect    0.55
prospective 0.30
```

When there are multiple required semantic conditions, require a company to have evidence for every required condition.

Apply structured filters after semantic grouping.

Return no more than `candidate_limit` companies for dynamic research.

---

## 8. Dynamic Research Workers

Run one identical bounded worker per candidate using `asyncio.gather`.

Do not implement autonomous multi-agent frameworks.

Each worker receives:

```python
class CandidateResearchRequest(BaseModel):
    search_id: UUID
    company_id: UUID
    ticker: str
    research_conditions: list[ResearchCondition]
    deadline_seconds: int = 25
```

### Allowed tools

- `get_sec_submissions(cik)`
- `get_company_facts(cik)`
- `get_recent_filings(cik, forms, lookback_days)`
- `download_filing(accession)`
- `search_filing_chunks(filing_id, query)`
- `extract_financial_metric(cik, metric, periods)`
- `calculate_yoy(current, previous)`
- `classify_catalyst(excerpts, question)`
- `get_market_snapshot(ticker)`
- `get_company_cards(company_id)`

### Hard limits per worker

- Maximum 4 SEC filing downloads
- Maximum 3 model calls
- Maximum 25 seconds
- Maximum 12 retrieved chunks per model call
- Maximum 1 retry per failed tool call
- No arbitrary internet browsing

### Worker output

```python
class CandidateResearchResult(BaseModel):
    company_id: UUID
    ticker: str

    condition_results: list[ConditionResult]
    contradictions: list[str]
    limitations: list[str]

    completed: bool
    timed_out: bool
    overall_confidence: float
```

```python
class ConditionResult(BaseModel):
    condition_id: str
    status: Literal["pass", "partial", "fail", "unknown"]
    score: float

    measured_value: float | None
    unit: str | None
    current_period: str | None
    comparison_period: str | None

    explanation: str
    citations: list[Citation]
```

A timeout must not fail the entire search. Mark that candidate as incomplete.

---

## 9. Financial Verification

Never ask the language model to calculate growth.

Use SEC Company Facts XBRL data.

Supported metrics:

```text
Revenue:
us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax
fallback: us-gaap:Revenues

Net income:
us-gaap:NetIncomeLoss
```

### Comparison rules

For latest-quarter YoY:

- Use the latest available 10-Q fiscal quarter.
- Compare with the same fiscal quarter one year earlier.
- Use the same:
  - XBRL concept
  - Currency
  - Form
  - Period duration
  - Consolidation scope when available
- Prefer values from the latest filing when it includes comparative data.
- Reject mismatched durations.
- Do not annualize.
- Do not infer missing quarters.

### Formula

```python
growth_percent = ((current - previous) / abs(previous)) * 100
```

Special cases:

- `previous == 0`: status `unknown`, no percentage.
- Negative previous value for net income: calculate but label as “not directly comparable” and do not use a simple threshold automatically.
- Missing comparable period: status `unknown`.
- Restated values: prefer the latest restated value.

Store the raw facts and derived calculation in the session.

---

## 10. Catalyst Research

For the prototype, “recent catalysts” means information found in:

- 8-K filings
- Latest 10-Q
- Latest 10-K

Do not create a permanent market-wide event warehouse.

### Workflow

1. Retrieve recent relevant filings for the candidate.
2. Parse filing text once and cache it.
3. Retrieve chunks semantically related to the catalyst question.
4. Ask Qwen to classify the evidence.

### Catalyst output

```python
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
        "other"
    ]
    event_date: date | None
    summary: str
    state: Literal[
        "announced",
        "approved",
        "under_construction",
        "completed",
        "cancelled",
        "unknown"
    ]
    relevance_to_query: float
    citations: list[Citation]
    limitations: list[str]
```

The model must distinguish:

- Announced from completed
- Company-wide from segment-specific
- Direct from indirect relevance
- Confirmed fact from inference

---

## 11. Final Ranking

Only rank by query fit.

Do not rank by investment attractiveness.

### Eligibility

A company is eligible when:

- All required structured conditions pass.
- All required research conditions are `pass` or, if configured, `partial`.
- Required semantic conditions have evidence.

### Score

Normalize all components to `[0, 1]`.

```text
final_score =
  sum(condition_weight * condition_score)
  * evidence_multiplier
```

```text
evidence_multiplier =
  0.70 + 0.30 * overall_confidence
```

Do not allow the LLM to set or alter the arithmetic.

### Result display

Each company card must show:

- Company and ticker
- Final query-match percentage
- Current market cap and retrieval timestamp
- Semantic match classification
- Verified financial growth and comparison periods
- Recent catalyst summary
- Why it matched
- Limitations
- Citations
- “Direct / indirect / prospective” badge

Also show funnel counts:

```text
100 indexed companies
N semantic matches
N passed base filters
N researched
N fully qualified
```

---

## 12. Research Workspace and Follow-Up Chat

Every completed search creates a persistent workspace.

```python
class ResearchWorkspace(BaseModel):
    id: UUID
    original_query: str
    search_plan: SearchPlan

    candidates_considered: list[UUID]
    candidate_results: list[CandidateResearchResult]
    final_company_ids: list[UUID]

    created_at: datetime
    data_versions: dict[str, str]
```

### Follow-up intents

Implement a router with:

```text
explain_result
compare_results
show_evidence
clarify_metric
modify_filter
exclude_company
expand_candidate_limit
research_new_condition
general_financial_explanation
```

### Existing-data follow-up

Example:

> Why did the first company rank above the second?

Use only the workspace data and citations.

### New-research follow-up

Example:

> Which of these companies has discussed customer concentration?

Research only the selected companies, append results to the workspace, and answer with new citations.

### Search modification

Example:

> Increase the market-cap tolerance to 70%.

Update the structured plan and rerun:

- Structured filtering
- Candidate research only for newly admitted candidates
- Final ranking

Do not repeat unchanged work.

### Chat grounding rules

- Do not answer company-specific factual questions from model memory.
- Retrieve workspace facts or SEC evidence first.
- Every company-specific factual paragraph must include at least one citation.
- Clearly state when evidence is unavailable.
- Never convert the result into a buy/sell recommendation.

---

## 13. API Endpoints

```text
POST   /api/search/plan
POST   /api/search/run
GET    /api/search/{search_id}
GET    /api/search/{search_id}/stream
POST   /api/search/{search_id}/follow-up
PATCH  /api/search/{search_id}/plan

GET    /api/companies
GET    /api/companies/{ticker}
GET    /api/companies/{ticker}/cards
GET    /api/companies/{ticker}/filings

POST   /api/admin/bootstrap
POST   /api/admin/ingest/{ticker}
POST   /api/admin/rebuild-embeddings
GET    /api/admin/jobs/{job_id}
```

Use Server-Sent Events for search progress.

Progress events:

```text
planning_query
retrieving_semantic_candidates
applying_base_filters
researching_candidate
validating_financials
ranking_results
completed
```

---

## 14. Frontend Pages

### `/`

- Search box
- Example prompts
- Search mode:
  - Quick: top 5 candidates
  - Standard: top 15 candidates
- Recent research sessions

### `/search/[id]`

- Original query
- Editable interpretation chips
- Progress timeline
- Funnel counts
- Ranked company table/cards
- Side-by-side comparison
- Citation drawer
- Follow-up chat panel

### `/company/[ticker]`

- Company summary
- Semantic cards
- Latest SEC filings
- Cached financial facts
- Previous appearances in search sessions

### `/admin`

- Universe status
- Ingestion status by ticker
- Missing CIKs
- Card counts
- Failed filings
- Embedding status
- Rebuild controls

---

## 15. Database Tables

Implement at minimum:

```text
companies
company_market_snapshots
sec_filings
filing_chunks
company_cards
financial_facts
derived_metrics
research_sessions
research_candidates
condition_results
citations
chat_messages
ingestion_jobs
```

Use pgvector for:

```text
company_cards.embedding
filing_chunks.embedding
```

Add indexes for:

```text
companies.ticker
companies.cik
sec_filings(company_id, form, filing_date)
financial_facts(company_id, concept, end_date)
research_sessions.created_at
```

---

## 16. Caching

Cache:

- Market snapshots: 12 hours
- SEC submissions metadata: 6 hours
- Downloaded filings: indefinitely by accession number
- Parsed filing chunks: indefinitely by filing hash
- Company Facts response: 6 hours
- Financial calculations: until a newer filing is detected
- Catalyst findings: 24 hours
- Query plans: by normalized query
- Embeddings: indefinitely unless model version changes

Every cached object must store:

```text
source
retrieved_at
data_version
model_name if model-generated
prompt_version if model-generated
```

---

## 17. Error Handling

The app must gracefully handle:

- Ollama unavailable
- SEC rate limiting
- SEC filing HTML parsing failure
- Missing XBRL concepts
- yfinance failure
- Candidate worker timeout
- Invalid model JSON
- Partial candidate research
- No qualifying results

Rules:

- Validate all model output using Pydantic.
- On invalid JSON, retry once with the validation errors.
- Never fabricate a missing value.
- Return partial results when some candidates fail.
- Include an explicit limitations section.

---

## 18. Security and Reliability

- Sanitize filing HTML.
- Do not execute filing scripts.
- Restrict downloaded content size.
- Use SSRF-safe URL allowlists:
  - `sec.gov`
  - `www.sec.gov`
  - `data.sec.gov`
- Keep SEC and Ollama configuration server-side.
- Add request timeouts.
- Add structured logging.
- Add prompt-injection defenses:
  - Filing text is untrusted data.
  - Model prompts must state that instructions inside filings are content, not commands.
  - Workers may only invoke allowlisted tools.
- Do not expose raw internal prompts in the frontend.

---

## 19. Repository Structure

```text
equity-research/
  apps/
    web/
      app/
      components/
      lib/
      types/
  services/
    api/
      app/
        api/
        core/
        models/
        schemas/
        services/
          query_planner/
          semantic_search/
          sec/
          market_data/
          research/
          ranking/
          chat/
        workers/
        prompts/
      tests/
  data/
    companies.csv
  scripts/
    bootstrap_db.py
    ingest_universe.py
    rebuild_cards.py
    evaluate_search.py
  docker/
  docker-compose.yml
  .env.example
  README.md
  SPEC.md
```

---

## 20. Testing

### Unit tests

- Query-plan parsing
- Market-cap “around” tolerance
- XBRL fact selection
- YoY period matching
- Growth calculations
- Negative and zero denominator handling
- Card aggregation
- Final score arithmetic
- Citation serialization
- Cache invalidation

### Integration tests

- Ingest one company end to end
- Build cards from one 10-K
- Run semantic retrieval
- Research one candidate
- Complete one full search
- Answer a grounded follow-up
- Modify a search filter

### Evaluation dataset

Create:

```text
data/eval_queries.json
```

with at least 25 manually written queries.

Each entry contains:

```json
{
  "query": "...",
  "expected_relevant_tickers": ["..."],
  "expected_excluded_tickers": ["..."],
  "notes": "..."
}
```

Report:

- Recall@5
- Recall@10
- Precision@5
- Hard-filter accuracy
- Citation coverage
- Unsupported-claim count
- Median latency

---

## 21. Build Order

### Milestone 1: Infrastructure

- Docker Compose
- PostgreSQL + pgvector
- FastAPI
- Next.js
- Ollama connectivity
- Models and migrations

### Milestone 2: Universe ingestion

- Load `companies.csv`
- SEC adapter
- Market snapshot adapter
- Filing downloader
- Filing parser

### Milestone 3: Semantic index

- 10-K section extraction
- Card generation
- Card verification
- Embedding creation
- Vector retrieval

### Milestone 4: Search pipeline

- Query planner
- Structured filtering
- Candidate aggregation
- Search progress SSE

### Milestone 5: Dynamic research

- XBRL financial verification
- Recent filing retrieval
- Catalyst extraction
- Parallel bounded workers
- Final deterministic ranking

### Milestone 6: Results UI

- Funnel display
- Company result cards
- Comparison table
- Citation viewer
- Limitations

### Milestone 7: Follow-up chat

- Workspace persistence
- Intent router
- Existing-data follow-ups
- New-research follow-ups
- Conversational filter edits

### Milestone 8: Tests and evaluation

- Unit/integration tests
- Evaluation runner
- README setup instructions
- Seed demo queries

---

## 22. Definition of Done

The prototype is complete when it can:

1. Ingest all 100 configured companies.
2. Produce at least 10 verified semantic cards per company.
3. Accept a mixed natural-language query.
4. Display the parsed search plan.
5. Retrieve no more than 15 candidates from the semantic index.
6. Research candidates concurrently.
7. Verify revenue YoY using SEC XBRL facts.
8. Identify recent SEC-filing catalysts.
9. Return up to seven ranked companies.
10. Show primary-source citations and limitations.
11. Save the entire search workspace.
12. Answer grounded follow-up questions.
13. Modify filters conversationally.
14. Run without any paid model or paid data API.
15. Pass the automated test suite.

---

## 23. Claude Code Execution Instruction

Implement this specification milestone by milestone.

Before coding each milestone:

1. Inspect the current repository.
2. Write a brief implementation plan.
3. Implement the smallest complete vertical slice.
4. Add tests.
5. Run formatting, type checks, and tests.
6. Fix failures before proceeding.
7. Update `README.md` and `docs/progress.md`.

Do not add technologies outside this specification unless a documented blocker requires it.

Prefer clear deterministic code over agent-framework abstractions.

Do not leave mock data in the final main execution path, except for explicit test fixtures.
