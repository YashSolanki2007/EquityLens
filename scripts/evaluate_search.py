"""Evaluation runner over data/eval_queries.json (spec §20).

Default mode evaluates the retrieval core (planner + semantic retrieval + structured
filters) for every query and reports Recall@5/10, Precision@5, hard-filter accuracy,
and median latency. With --full it also runs bounded research for the top candidates
and reports citation coverage and an unsupported-claim count.

Usage:
  services/api/.venv/bin/python scripts/evaluate_search.py
  services/api/.venv/bin/python scripts/evaluate_search.py --limit 5 --full
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

EVAL_FILE = REPO_ROOT / "data" / "eval_queries.json"


async def evaluate(limit: int | None, full: bool) -> None:
    from sqlalchemy import select

    from app.core.db import get_session_factory
    from app.models import Company
    from app.services.query_planner.planner import plan_query
    from app.services.ranking.filters import CompanyFilterInput, apply_structured_filters
    from app.services.semantic_search.retrieval import semantic_retrieval

    queries = json.loads(EVAL_FILE.read_text())
    if limit:
        queries = queries[:limit]

    factory = get_session_factory()
    async with factory() as db:
        companies = (await db.execute(select(Company))).scalars().all()
    ticker_by_company = {c.id: c.ticker for c in companies}
    universe_tickers = set(ticker_by_company.values())

    recalls5, recalls10, precisions5, latencies = [], [], [], []
    hard_filter_checks: list[bool] = []
    citation_covered = 0
    citation_total = 0
    unsupported_claims = 0
    per_query_rows = []

    for entry in queries:
        query = entry["query"]
        expected = [t for t in entry["expected_relevant_tickers"] if t in universe_tickers]
        excluded = [t for t in entry["expected_excluded_tickers"] if t in universe_tickers]
        start = time.monotonic()
        async with factory() as db:
            try:
                plan = await plan_query(query)
            except Exception as exc:
                print(f"PLANNER FAILED: {query[:60]} -> {exc}")
                continue
            results = await semantic_retrieval(
                db, plan.base_semantic_conditions, ticker_by_company
            )
            # Hard-filter accuracy: structured conditions must never leak violations.
            from sqlalchemy import desc

            from app.models import CompanyMarketSnapshot

            snapshots = {}
            rows = (
                (
                    await db.execute(
                        select(CompanyMarketSnapshot).order_by(
                            CompanyMarketSnapshot.company_id,
                            desc(CompanyMarketSnapshot.retrieved_at),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in rows:
                snapshots.setdefault(row.company_id, row)
            company_by_id = {c.id: c for c in companies}
            kept = []
            for r in results:
                company = company_by_id[r.company_id]
                snap = snapshots.get(r.company_id)
                keep, details = apply_structured_filters(
                    CompanyFilterInput(
                        ticker=company.ticker,
                        sector=company.sector,
                        industry=company.industry,
                        market_cap_usd=snap.market_cap_usd if snap else None,
                    ),
                    plan.base_structured_conditions,
                )
                for d in details:
                    if d.required and d.status == "fail":
                        hard_filter_checks.append(not keep)  # must have been dropped
                if keep:
                    kept.append(r)
        latency = time.monotonic() - start
        latencies.append(latency)

        top = [r.ticker for r in kept]
        top5, top10 = set(top[:5]), set(top[:10])
        if expected:
            recalls5.append(len(top5 & set(expected)) / len(expected))
            recalls10.append(len(top10 & set(expected)) / len(expected))
            precisions5.append(len(top5 & set(expected)) / max(len(top[:5]), 1))
        leaked = top5 & set(excluded)
        per_query_rows.append(
            f"  {'OK ' if not leaked else 'LEAK'} r@5={recalls5[-1] if expected else '-':.2f} "
            f"[{', '.join(top[:5])}] <- {query[:70]}"
            if expected
            else f"  ---- [{', '.join(top[:5])}] <- {query[:70]}"
        )

        if full and kept:
            from uuid import uuid4

            from app.schemas.search import CandidateResearchRequest
            from app.workers.candidate_worker import research_candidate

            async with factory() as db:
                request = CandidateResearchRequest(
                    search_id=uuid4(),
                    company_id=kept[0].company_id,
                    ticker=kept[0].ticker,
                    research_conditions=plan.research_conditions,
                )
                result = await research_candidate(db, request)
                for cond in result.condition_results:
                    if cond.status in ("pass", "partial"):
                        citation_total += 1
                        if cond.citations:
                            citation_covered += 1
                        else:
                            unsupported_claims += 1

    print("\nPer-query results:")
    for row in per_query_rows:
        print(row)

    print("\n=== Evaluation report ===")
    print(f"Queries evaluated:    {len(latencies)}")
    if recalls5:
        print(f"Recall@5:             {statistics.mean(recalls5):.3f}")
        print(f"Recall@10:            {statistics.mean(recalls10):.3f}")
        print(f"Precision@5:          {statistics.mean(precisions5):.3f}")
    if hard_filter_checks:
        print(
            f"Hard-filter accuracy: {sum(hard_filter_checks) / len(hard_filter_checks):.3f} "
            f"({len(hard_filter_checks)} checks)"
        )
    else:
        print("Hard-filter accuracy: n/a (no required structured conditions failed)")
    if full:
        coverage = citation_covered / citation_total if citation_total else float("nan")
        print(f"Citation coverage:    {coverage:.3f} ({citation_covered}/{citation_total})")
        print(f"Unsupported claims:   {unsupported_claims}")
    print(f"Median latency:       {statistics.median(latencies):.2f}s per query")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--full", action="store_true", help="Also run bounded research")
    args = parser.parse_args()
    asyncio.run(evaluate(args.limit, args.full))
