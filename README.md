# EquityLens

A semantic equity research tool over the official NSE main-board equity universe.
Natural-language queries are parsed into a
structured plan, matched against verified cards built from SEC 10-Ks or Indian annual
reports, researched against structured financial data and recent filings, and returned
as a ranked, cited result set with grounded follow-up chat.

**This is an information-retrieval and scenario-analysis tool.** It never provides
buy/sell recommendations, price targets, or portfolio advice. Ranking reflects *query
fit* only. Stock-page forecasts are explicitly labeled statistical scenarios rather
than targets: they exclude fundamentals, news, corporate actions, and regime changes.
PostgreSQL + pgvector and embeddings run locally. Generation uses the configured
NVIDIA-hosted Llama model. Source data comes from SEC EDGAR, NSE/issuer annual reports,
and yfinance development adapters, including a best-effort Yahoo live quote stream.

See `SPEC.md` for the full build specification and `docs/progress.md` for status.

## Architecture

```text
User query
  -> NSE main-board universe
  -> Query planner            (Llama -> structured SearchPlan, editable chips in UI)
  -> Semantic retrieval       (pgvector over market-filtered verified filing cards)
  -> Structured filters       (ticker/sector/industry/market cap, deterministic)
  -> Parallel bounded workers (asyncio.gather; hard limits, 25s deadline each)
       - Revenue / net-income YoY computed from normalized facts (never by the LLM)
       - Catalyst research over recent official filing chunks
  -> Deterministic ranking    (weighted scores x evidence multiplier)
  -> Persisted workspace      (grounded follow-up chat, conversational plan edits)
```

- `services/api` — FastAPI backend (Python 3.12, SQLAlchemy 2, Alembic, pgvector)
- `apps/web` — Next.js 16 frontend (TypeScript, Tailwind, shadcn/ui, TanStack Query, Recharts, Zod)
- `data/companies_india.csv` — the official NSE main-board equity universe
- `scripts/` — bootstrap, ingestion, card building, evaluation

## Prerequisites

- Docker (any runtime; e.g. Docker Desktop or colima)
- Python 3.12+
- Node.js 20+
- An NVIDIA API key for hosted Llama generation
- [Ollama](https://ollama.com) for the local embedding model:

```bash
ollama pull qwen3-embedding:0.6b   # embeddings (1024 dims)
```

## Setup

```bash
cp .env.example .env               # set SEC_USER_AGENT and NVIDIA_API_KEY

# 1. Database (PostgreSQL + pgvector)
docker compose up -d db

# 2. Backend
cd services/api
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cd ../..

# 3. Migrations + load the NSE main-board universe
services/api/.venv/bin/python scripts/bootstrap_db.py

# 4. Ingest NSE companies
services/api/.venv/bin/python scripts/ingest_universe.py --market IN

# 5. Build missing verified semantic cards
services/api/.venv/bin/python scripts/rebuild_cards.py            # all companies
services/api/.venv/bin/python scripts/rebuild_cards.py --market IN
services/api/.venv/bin/python scripts/rebuild_cards.py DLR VRT ANET DELL HPE   # or subset

# Or resumably materialize annual-report metadata and verified cards for the
# complete NSE main board (PDFs remain transient)
services/api/.venv/bin/python -u scripts/materialize_india.py
```

## Run

```bash
# API (http://localhost:8000)
cd services/api && .venv/bin/uvicorn app.main:app --port 8000

# Web (http://localhost:3000)
cd apps/web && npm install && npm run dev
```

Pages: `/` (search), `/search/[id]` (results, funnel, comparison, citations, chat),
`/company/[ticker]` (market chart, ratios, options, price scenarios, cards,
filings, facts), `/technical` (semantic and indicator scanner), and `/admin`
(ingestion/card status).

Implemented research features that are intentionally absent from the website are
recorded in [`docs/dormant-features.txt`](docs/dormant-features.txt). Their source,
data, and tests remain in the repository for possible future reuse.

### Signal research

The original custom signal remains intact as the version-control baseline. The
alternative model removes its next-day PDF interpretation and annualized-slope versus
daily-volatility comparison. It uses a 21-session and 63-session EMA crossover, with
the EMA distance normalized by 21-session EWMA volatility for a scale-free diagnostic
score. The sign alone determines long or cash.

Both reports use the same conservative execution assumption (signal after close `t`,
trade at close `t+1`, first earned return `t+1` to `t+2`), 10 bps one-way costs, zero
cash yield, and price-only index returns. Regenerate the reports from the repository
root:

```bash
services/api/.venv/bin/python -m scripts.generate_custom_signal
services/api/.venv/bin/python -m scripts.generate_alternative_signal
services/api/.venv/bin/python -m scripts.generate_robust_signal
```

The alternative report compares the frozen rule with the original over identical
windows, discloses neighboring-window sensitivity, and transfers the unchanged
parameters to Indian indices and a survivorship-biased large-cap diagnostic panel.
The robust report adds a 15/45 EMA regime, conservative two-timescale volatility
budget, the longest available crisis-inclusive window, volatility-only and
exposure-matched controls, paired stationary-bootstrap intervals, HAC inference,
Deflated Sharpe, a trial ledger, and explicit promotion gates. It is a defensive
paper-trading candidate—not validated alpha—and its frozen forward test begins on
11 August 2026. Same-calendar-day Yahoo bars are excluded so an incomplete live
session cannot enter the historical report. Full formulas and limitations are in
[`docs/robust-signal-methodology.md`](docs/robust-signal-methodology.md).

None of the reports is evidence of a live, tradeable alpha until it passes genuinely
unseen forward testing with a licensed total-return data source.

### Intraday algorithmic scanner

The **Algo scanner** accepts natural-language combinations such as “renewable power
companies with RSI below 35 and price above VWAP.” Stable business concepts are matched
against verified annual-report cards, while technical conditions are calculated
deterministically from 35–70 candles at the selected 1m, 5m, 15m, 30m, 1h, or 1d
interval. The indicator pass is vectorized with pandas and includes RSI(14),
MACD(12,26,9), EMA(9/21), VWAP, 5/15/60-candle returns, relative volume, ATR(14), and
Bollinger position. Candle requests use a bounded concurrent fan-out and a short cache.

Without credentials, bounded Yahoo WebSocket shards subscribe to up to 200 already-indexed
NSE symbols, aggregate live ticks into the forming candle, and relay displayed-result
prices to the browser. The cap avoids opening dozens of unofficial streaming connections;
yfinance history backfills the rest of the selected candle window. Set
`UPSTOX_ACCESS_TOKEN` to replace this with Upstox V3 candles. Market-closed scans use
the latest available session. Yahoo is best-effort and has no exchange-grade SLA; this
scanner is descriptive and does not execute trades.

### Stock-page price scenarios

Every covered U.S. and Indian stock has a **Price scenarios** tab. It fits an
ARIMA(1,1,1) process to five years of daily log prices, fits GARCH(1,1) with
Student-t innovations to the ARIMA residuals, and advances both conditional drift
and conditional variance inside each Monte Carlo path. The UI exposes 5, 10, or 15
modeled trading-day horizons, 1,000–5,000 paths, percentile bands, sample paths, the conditional
volatility trajectory, and fitted-model diagnostics. Results are reproducible for the
same input history and cached for 30 minutes. The 15-day maximum limits extrapolation;
it does not guarantee forecast accuracy.

## Example queries

- *NSE-listed companies whose customers are hospitals or health systems, with positive
  latest-quarter net income growth.*
- *Indian companies operating renewable power assets with direct exposure to
  electricity demand growth.*

Follow-ups in the chat panel: *"Why did the first company rank above the second?"*,
*"Which of these companies has discussed customer concentration?"*,
*"Increase the market-cap tolerance to 70%."* (edits the plan and reruns only the
affected stages), or *"Could the first result be affected by the latest semiconductor
export restrictions? Research the evidence and counter-case."*

### Follow-up deep research

Current-event and macro-impact follow-ups are routed to a separate deep-research
workflow; they never alter the initial semantic search or its ranking. Llama first
creates three bounded angles (transmission mechanism, recent evidence, and
counter-case), Tavily retrieves current news, the filing pipeline retrieves
recent official evidence, and three parallel Llama workers produce a final cited
impact assessment. Configure `TAVILY_API_KEY` in `.env` to enable current-news
retrieval. Without it, the report runs against company cards and official filings and
prominently reports that it is filing-only.

## Tests and evaluation

```bash
cd services/api
.venv/bin/ruff check app tests
.venv/bin/pytest -m "not integration"     # unit tests (no services needed)
.venv/bin/pytest -m integration           # needs Postgres + Ollama + network

# Retrieval evaluation over data/eval_queries.json (25 labeled queries)
cd ../..
services/api/.venv/bin/python scripts/evaluate_search.py
services/api/.venv/bin/python scripts/evaluate_search.py --full   # adds citation coverage

# Signal-model unit tests
services/api/.venv/bin/python -m unittest \
  scripts.test_custom_signal scripts.test_alternative_signal
```

## Data sources, caching, and limits

- **SEC EDGAR** (submissions, Company Facts XBRL, filing HTML) — descriptive
  `User-Agent` required, global rate limit kept below 8 req/s, host allowlist
  (`sec.gov`, `www.sec.gov`, `data.sec.gov`), response size caps. Filings cached
  indefinitely by accession under `data/filings/`; JSON responses cached 6h under
  `data/cache/`.
- **NSE and issuer annual reports** — official Indian filing metadata and source URLs
  are retained, while report bytes are fetched only during parsing and are not saved
  locally. Verified cards, source excerpts, citations, and embeddings remain in
  PostgreSQL.
- **Yahoo/yfinance** — prototype-only live NSE WebSocket quotes plus historical candle,
  snapshot, market-cap, and Indian statement adapters. Non-streaming snapshots are
  cached, and Yahoo-derived records remain labeled `is_delayed_or_unverified` because
  there is no contractual freshness SLA. Replace it with a licensed feed before
  production.
- **Financial verification** — YoY growth is computed deterministically from XBRL
  facts (same concept, duration, and fiscal quarter one year apart; restatements
  preferred; zero/negative denominators handled per spec). The LLM never does math.
- **Workers** — per candidate: max 4 filing downloads, 3 model calls, 12 chunks per
  call, 25s deadline. Timeouts mark a candidate incomplete without failing the search.
- **Prompt-injection defenses** — filing text is always framed as untrusted quoted
  data; workers can only call allowlisted tools; model output is Pydantic-validated
  with one retry on invalid JSON.

## Notes

- Hosted chat and local embeddings are configured via `.env`
  (`NVIDIA_MODEL`, `OLLAMA_EMBED_MODEL`).
