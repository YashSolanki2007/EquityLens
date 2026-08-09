"""Live progress view for the semantic card build.

One-shot snapshot by default; --watch redraws every few seconds until complete.

Usage:
  services/api/.venv/bin/python scripts/card_progress.py
  services/api/.venv/bin/python scripts/card_progress.py --watch
"""

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "services" / "api"
sys.path.insert(0, str(API_DIR))

BAR_WIDTH = 50
TARGET_CARDS = 10  # a company counts as indexed at >=10 verified cards (spec DoD)


def build_running() -> bool:
    return (
        subprocess.run(
            ["pgrep", "-f", "rebuild_cards.py"], capture_output=True
        ).returncode
        == 0
    )


async def snapshot() -> dict:
    from sqlalchemy import func, select

    from app.core.db import get_session_factory
    from app.models import Company, CompanyCard

    async with get_session_factory()() as db:
        companies = (
            (await db.execute(select(Company.ticker).order_by(Company.ticker))).scalars().all()
        )
        counts = dict(
            (
                await db.execute(
                    select(CompanyCard.ticker, func.count()).group_by(CompanyCard.ticker)
                )
            ).all()
        )
    done = [t for t in companies if counts.get(t, 0) >= TARGET_CARDS]
    pending = [t for t in companies if counts.get(t, 0) < TARGET_CARDS]
    # The build walks tickers alphabetically with concurrency 2, so the first
    # pending tickers are the ones being generated right now.
    in_flight = pending[:2] if build_running() else []
    return {
        "total": len(companies),
        "done": done,
        "pending": pending,
        "in_flight": in_flight,
        "cards_total": sum(counts.values()),
    }


def render(s: dict) -> str:
    total, n_done = s["total"], len(s["done"])
    filled = int(BAR_WIDTH * n_done / max(total, 1))
    bar = "█" * filled + "░" * (BAR_WIDTH - filled)
    lines = [
        f"Semantic card index  [{bar}]  {n_done}/{total} companies  "
        f"({s['cards_total']} cards)",
    ]
    if s["in_flight"]:
        lines.append(f"Building now : {', '.join(s['in_flight'])}")
    elif s["pending"]:
        lines.append("Build process: NOT RUNNING  "
                     "(resume: services/api/.venv/bin/python scripts/rebuild_cards.py)")
    if s["pending"]:
        upcoming = ", ".join(s["pending"][2:12]) or "-"
        lines.append(f"Up next      : {upcoming}")
        # ~6 min/company on this machine with concurrency 2 -> ~3 min each effective
        eta_min = len(s["pending"]) * 3
        lines.append(f"Rough ETA    : ~{eta_min // 60}h {eta_min % 60:02d}m if left running")
    else:
        lines.append("All companies indexed ✔")
    lines.append(f"Done         : {', '.join(s['done']) or '-'}")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="Redraw every 10s until done")
    args = parser.parse_args()

    while True:
        s = await snapshot()
        output = render(s)
        if args.watch:
            print("\033[2J\033[H" + time.strftime("%H:%M:%S") + "\n" + output, flush=True)
            if not s["pending"]:
                break
            await asyncio.sleep(10)
        else:
            print(output)
            break


if __name__ == "__main__":
    asyncio.run(main())
