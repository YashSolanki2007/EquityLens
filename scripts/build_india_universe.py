"""Regenerate the Indian universe from NSE's official main-board security list.

Usage: services/api/.venv/bin/python scripts/build_india_universe.py
"""

import csv
import io
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "companies_india.csv"
CONSTITUENTS_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
ALLOWED_SERIES = {"EQ", "BE", "BZ"}


def main() -> None:
    existing: dict[str, dict[str, str]] = {}
    if OUT.exists():
        with OUT.open() as file:
            existing = {row["ticker"]: row for row in csv.DictReader(file)}

    response = httpx.get(
        CONSTITUENTS_URL,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.nseindia.com/market-data/securities-available-for-trading",
        },
        timeout=30,
        follow_redirects=True,
    )
    response.raise_for_status()
    source_rows = list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))
    rows = []
    for source in source_rows:
        normalized = {key.strip(): value.strip() for key, value in source.items()}
        ticker = normalized["SYMBOL"].upper()
        if normalized["SERIES"].upper() not in ALLOWED_SERIES:
            continue
        previous = existing.get(ticker, {})
        sector = previous.get("sector") or "Unclassified"
        industry = previous.get("industry") or sector
        rows.append(
            {
                "ticker": ticker,
                "name": normalized["NAME OF COMPANY"],
                "isin": normalized["ISIN NUMBER"].upper(),
                "exchange": "NSE",
                "sector": sector,
                "industry": industry,
                "market_data_ticker": f"{ticker}.NS",
                "country": "IN",
                "universe": "NSE_MAINBOARD",
            }
        )

    if len(rows) < 2_000:
        raise RuntimeError(f"Official NSE file returned only {len(rows)} main-board companies")
    if len({row["ticker"] for row in rows}) != len(rows):
        raise RuntimeError("Official NSE file contains duplicate tickers")
    if len({row["isin"] for row in rows}) != len(rows):
        raise RuntimeError("Official NSE file contains duplicate ISINs")

    with OUT.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} official NSE main-board companies to {OUT}")


if __name__ == "__main__":
    main()
