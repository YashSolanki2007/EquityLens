#!/usr/bin/env python3
"""Run and cache the Shang-Kearney exact-design NSE replication."""

from __future__ import annotations

import json

from app.services.iv_model_evaluation import cached_surface_histories
from app.services.market_data.dynamic_functional_iv import get_cached_nse_replication


def _progress(payload: dict) -> None:
    completed = int(payload["completed_origins"])
    if completed == int(payload["total_origins"]) or completed % 10 == 0:
        print(
            f"{payload['ticker']} ({payload['symbol_index']}/{payload['total_symbols']}): "
            f"origin {completed}/{payload['total_origins']}",
            flush=True,
        )


def main() -> None:
    result = get_cached_nse_replication(
        cached_surface_histories(),
        force_refresh=True,
        progress=_progress,
    )
    print(
        json.dumps(
            {
                "available": result["available"],
                "verdict": result["verdict"],
                "completed_symbols": result["completed_symbols"],
                "eligibility": result["eligibility"],
                "failures": result["failures"],
                "leaderboard": result["leaderboard"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
