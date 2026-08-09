"""Ingest SEC filings metadata, latest 10-K, XBRL facts, and market snapshots
for the universe (or a subset).

Usage:
  services/api/.venv/bin/python scripts/ingest_universe.py            # all 300
  services/api/.venv/bin/python scripts/ingest_universe.py DLR VRT    # subset
  services/api/.venv/bin/python scripts/ingest_universe.py --concurrency 4
  services/api/.venv/bin/python scripts/ingest_universe.py --market IN --missing
"""

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*", help="Optional ticker subset")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--market", choices=("US", "IN", "ALL"), default="ALL")
    parser.add_argument(
        "--missing",
        action="store_true",
        help="Only ingest companies that do not have filing metadata yet",
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from app.core.db import get_session_factory
    from app.core.logging import setup_logging
    from app.models import Company, SecFiling
    from app.services.ingestion import ensure_universe, ingest_company

    setup_logging("INFO")
    factory = get_session_factory()

    async with factory() as db:
        await ensure_universe(db)
        query = select(Company).order_by(Company.ticker)
        if args.market != "ALL":
            query = query.where(Company.country == args.market)
        if args.tickers:
            query = query.where(Company.ticker.in_([t.upper() for t in args.tickers]))
        if args.missing:
            query = query.where(
                ~select(SecFiling.id).where(SecFiling.company_id == Company.id).exists()
            )
        companies = (await db.execute(query)).scalars().all()

    sem = asyncio.Semaphore(args.concurrency)
    results: list[dict] = []

    async def run_one(company_id, ticker):
        async with sem:
            async with factory() as db:
                company = (
                    await db.execute(select(Company).where(Company.id == company_id))
                ).scalar_one()
                try:
                    res = await ingest_company(db, company)
                except Exception as exc:  # keep going; report at the end
                    res = {"ticker": ticker, "error": str(exc)}
                results.append(res)
                print(res)

    await asyncio.gather(*(run_one(c.id, c.ticker) for c in companies))

    failed = [r for r in results if "error" in r]
    print(
        f"\nIngested {len(results) - len(failed)}/{len(results)} companies; {len(failed)} failed"
    )
    for r in failed:
        print("FAILED:", r)


if __name__ == "__main__":
    asyncio.run(main())
