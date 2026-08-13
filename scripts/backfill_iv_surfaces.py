#!/usr/bin/env python3
"""Backfill durable NSE option surfaces for the IV forecasting study."""

from __future__ import annotations

import argparse
import asyncio
import json

from app.services.iv_model_evaluation import DEFAULT_SYMBOLS
from app.services.market_data.iv_surface import (
    HISTORY_BACKFILL_YEARS,
    backfill_historical_surfaces,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download NSE derivatives bhavcopies once per date and build long IV histories."
    )
    parser.add_argument(
        "--years",
        type=int,
        default=HISTORY_BACKFILL_YEARS,
        choices=range(1, HISTORY_BACKFILL_YEARS + 1),
    )
    parser.add_argument("--limit", type=int, default=len(DEFAULT_SYMBOLS))
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def _progress(payload: dict) -> None:
    completed = int(payload["completed_dates"])
    pending = int(payload["pending_dates"])
    if completed == pending or completed % 20 == 0:
        print(
            f"processed {completed}/{pending} dates; "
            f"stored {int(payload['parsed_surfaces'])} new surfaces",
            flush=True,
        )


async def _run() -> None:
    args = _arguments()
    symbols = tuple(args.symbols or DEFAULT_SYMBOLS[: max(1, args.limit)])
    result = await backfill_historical_surfaces(
        symbols,
        years=args.years,
        force=args.force,
        progress=_progress,
    )
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(_run())
