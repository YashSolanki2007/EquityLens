# Progress

Implementation status against `SPEC.md` plus the U.S./India expansion (updated 2026-07-21).

## Milestones

| Milestone | Status | Notes |
| --- | --- | --- |
| M1 Infrastructure | ✅ done | docker-compose (pgvector/pg16), FastAPI, Next.js 16, Alembic initial migration (13 tables + hnsw vector indexes), Ollama provider interface, `.env.example` |
| M2 Universe ingestion | ✅ done | The active universe is the official NSE main-board equity list. Annual reports are fetched transiently from NSE/issuer URLs and are not retained locally. |
| M3 Semantic index | 🔄 expanding | U.S. 10-K and Indian annual-report parsing; two-pass card generation (`extract_cards` → batched `verify_cards`, entailed-only ≥0.75); ESG/governance noise suppression; qwen3-embedding 1024-dim vectors; market-filtered pgvector retrieval. Verified-card generation is running for the 100-company India expansion. |
| M4 Search pipeline | ✅ done | Hosted Llama query planner with an `NSE_MAINBOARD` boundary applied before top-K retrieval; structured filters; orchestrator with SSE progress events. |
| M5 Dynamic research | ✅ done | Deterministic XBRL YoY (§9 rules incl. restatements, zero/negative denominators, duration matching); catalyst research over 8-K/10-Q/10-K chunks; bounded workers (asyncio.gather, 25s deadline, download/model-call budgets); §11 deterministic ranking |
| M6 Results UI | ✅ done | Home market dropdown and market-specific examples; search page with visible market badge; INR-aware result/comparison/company views; official NSE annual-report links; country-aware admin coverage. |
| M7 Follow-up chat | ✅ done | Intent router (9 intents), grounded QA over workspace evidence with numbered citations, exclude+rerank, plan patch via LLM with incremental rerun (verified: only new candidates researched), new-research follow-ups appended to workspace |
| M8 Tests & evaluation | ✅ done | Unit and integration coverage includes the NSE main-board universe boundary, parser noise, batching, and market isolation; frontend lint and production build are part of the verification suite. |

## Verified end-to-end (real data, local models)

- DLR search: planner → semantic retrieval → structured filters → worker → ranking →
  SSE → persisted workspace. Revenue YoY 16.2% verified from XBRL (Q1 FY2026 vs Q1
  FY2025); catalyst step correctly marked incomplete on worker timeout.
- Grounded follow-up produced a cited, correct explanation of why DLR was not fully
  qualified (intent `explain_result`, SEC XBRL citation).
- Conversational plan edit ("lower revenue threshold to 5%, make catalyst optional")
  updated the plan and reran only the affected stages, reusing DLR's prior research.

## Outstanding

- Full NSE main-board verified-card materialization is a long-running,
  rate-limited development operation. Incremental refreshes only rebuild affected
  companies.
- India structured financials use a delayed yfinance adapter during development;
  replace it with a licensed market/fundamental feed before production.

## Known deviations / decisions

- SEC ticker file maps XOM to a new holding-company registrant with no filing history;
  the universe pins the operating company CIK (0000034088) — documented in
  `scripts/build_universe.py`.
- WMT is listed as NASDAQ in current SEC data and was replaced by the reviewed spare
  (TGT) to keep the universe NYSE-only.
- Integration tests require live Postgres/Ollama/network and are opt-in via
  `pytest -m integration`.
