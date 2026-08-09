"""Remove deterministic filing boilerplate that should not enter semantic search.

This is useful after a prompt/filter upgrade because it cleans already-materialized
cards without paying to regenerate valid cards.

Usage:
  services/api/.venv/bin/python scripts/clean_card_noise.py --market IN
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
    parser.add_argument("--market", choices=("US", "IN", "ALL"), default="ALL")
    args = parser.parse_args()

    from sqlalchemy import delete, select

    from app.core.db import get_session_factory
    from app.models import Company, CompanyCard
    from app.services.semantic_search.cards import ExtractedCard, _acceptable

    factory = get_session_factory()
    async with factory() as db:
        query = select(CompanyCard).join(
            Company, Company.id == CompanyCard.company_id
        )
        if args.market != "ALL":
            query = query.where(Company.country == args.market)
        rows = (await db.execute(query)).scalars().all()

        rejected_ids = []
        for row in rows:
            card = ExtractedCard(
                card_type=row.card_type,
                text=row.text,
                directness=row.directness,
                materiality=row.materiality,
            )
            if not _acceptable(card):
                rejected_ids.append(row.id)

        if rejected_ids:
            await db.execute(
                delete(CompanyCard).where(CompanyCard.id.in_(rejected_ids))
            )
            await db.commit()
        print(
            f"Removed {len(rejected_ids)} boilerplate cards from "
            f"{len(rows)} inspected cards ({args.market})."
        )


if __name__ == "__main__":
    asyncio.run(main())
