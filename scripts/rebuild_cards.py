"""Build (or rebuild) verified semantic company cards for the universe.

Usage:
  services/api/.venv/bin/python scripts/rebuild_cards.py            # all companies missing cards
  services/api/.venv/bin/python scripts/rebuild_cards.py --all      # rebuild everything
  services/api/.venv/bin/python scripts/rebuild_cards.py DLR VRT    # subset
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--all", action="store_true", help="Rebuild even if cards exist")
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--market", choices=("US", "IN", "ALL"), default="ALL")
    args = parser.parse_args()

    from sqlalchemy import func, select

    from app.core.db import get_session_factory
    from app.core.logging import setup_logging
    from app.models import Company, CompanyCard
    from app.services.semantic_search.cards import build_cards_for_company

    setup_logging("INFO")
    factory = get_session_factory()

    async with factory() as db:
        company_query = select(Company).order_by(Company.ticker)
        if args.market != "ALL":
            company_query = company_query.where(Company.country == args.market)
        companies = (await db.execute(company_query)).scalars().all()
        counts = dict(
            (
                await db.execute(
                    select(CompanyCard.company_id, func.count()).group_by(CompanyCard.company_id)
                )
            ).all()
        )

    targets = []
    for c in companies:
        if args.tickers and c.ticker not in [t.upper() for t in args.tickers]:
            continue
        if not args.tickers and not args.all and counts.get(c.id, 0) >= 10:
            continue
        targets.append(c)

    print(f"Building cards for {len(targets)} companies")
    sem = asyncio.Semaphore(args.concurrency)
    done = 0

    async def one(company_id, ticker):
        nonlocal done
        async with sem:
            start = time.monotonic()
            async with factory() as db:
                company = (
                    await db.execute(select(Company).where(Company.id == company_id))
                ).scalar_one()
                try:
                    n = await build_cards_for_company(db, company)
                    done += 1
                    print(
                        f"[{done}/{len(targets)}] {ticker}: {n} cards"
                        f" in {time.monotonic() - start:.0f}s"
                    )
                except Exception as exc:
                    done += 1
                    print(f"[{done}/{len(targets)}] {ticker} FAILED: {exc}")

    await asyncio.gather(*(one(c.id, c.ticker) for c in targets))


if __name__ == "__main__":
    asyncio.run(main())
