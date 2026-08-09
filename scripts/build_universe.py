"""Build data/companies.csv: exactly 100 manually reviewed large NYSE-listed companies.

The candidate list below is hand-curated (large caps, US SEC 10-K filers, sector-diverse,
with deliberate coverage of data-center / infrastructure themes). This script validates each
candidate against the SEC's official company_tickers_exchange.json (NYSE listing + CIK),
fills the official name and zero-padded CIK, and writes the first 100 that validate.

The resulting CSV is checked in and fixed for the prototype; rerun only to regenerate it.

Usage:  python scripts/build_universe.py
"""

import csv
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT = REPO_ROOT / "data" / "companies.csv"

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# (ticker, sector, industry) — reviewed by hand. A few spares beyond 100 in case a
# listing has moved exchanges; validation keeps the first 100 confirmed NYSE names.
CANDIDATES: list[tuple[str, str, str]] = [
    # Financials
    ("JPM", "Financials", "Diversified Banks"),
    ("BAC", "Financials", "Diversified Banks"),
    ("WFC", "Financials", "Diversified Banks"),
    ("C", "Financials", "Diversified Banks"),
    ("GS", "Financials", "Investment Banking & Brokerage"),
    ("MS", "Financials", "Investment Banking & Brokerage"),
    ("SCHW", "Financials", "Investment Banking & Brokerage"),
    ("BLK", "Financials", "Asset Management"),
    ("AXP", "Financials", "Consumer Finance"),
    ("V", "Financials", "Payments & Transaction Processing"),
    ("MA", "Financials", "Payments & Transaction Processing"),
    ("SPGI", "Financials", "Financial Data & Ratings"),
    ("ICE", "Financials", "Securities Exchanges"),
    ("CB", "Financials", "Property & Casualty Insurance"),
    # Information technology / digital infrastructure
    ("ORCL", "Information Technology", "Enterprise Software & Cloud Infrastructure"),
    ("CRM", "Information Technology", "Application Software"),
    ("IBM", "Information Technology", "IT Services & Hybrid Cloud"),
    ("ACN", "Information Technology", "IT Consulting & Services"),
    ("NOW", "Information Technology", "Application Software"),
    ("ANET", "Information Technology", "Data Center Networking Equipment"),
    ("DELL", "Information Technology", "Servers & IT Hardware"),
    ("HPE", "Information Technology", "Servers & IT Hardware"),
    ("VRT", "Information Technology", "Data Center Power & Cooling Equipment"),
    ("MSI", "Information Technology", "Communications Equipment"),
    ("GLW", "Information Technology", "Optical Components & Specialty Glass"),
    ("APH", "Information Technology", "Electronic Connectors & Interconnects"),
    ("TEL", "Information Technology", "Electronic Connectors & Sensors"),
    ("IT", "Information Technology", "Technology Research & Advisory"),
    ("FIS", "Financials", "Payments & Financial Technology"),
    # REITs / digital & physical infrastructure
    ("DLR", "Real Estate", "Data Center REIT"),
    ("AMT", "Real Estate", "Communications Tower REIT"),
    ("CCI", "Real Estate", "Communications Tower REIT"),
    ("IRM", "Real Estate", "Records Management & Data Center REIT"),
    ("PLD", "Real Estate", "Industrial Logistics REIT"),
    ("SPG", "Real Estate", "Retail REIT"),
    # Industrials
    ("GE", "Industrials", "Aerospace Engines & Systems"),
    ("CAT", "Industrials", "Construction & Mining Machinery"),
    ("DE", "Industrials", "Agricultural Machinery"),
    ("MMM", "Industrials", "Diversified Industrials"),
    ("ETN", "Industrials", "Electrical Power Management"),
    ("EMR", "Industrials", "Industrial Automation"),
    ("PH", "Industrials", "Motion & Control Technologies"),
    ("ROK", "Industrials", "Industrial Automation Software & Hardware"),
    ("CMI", "Industrials", "Engines & Power Generation"),
    ("PWR", "Industrials", "Infrastructure & Electric Power Construction"),
    ("URI", "Industrials", "Equipment Rental"),
    ("JCI", "Industrials", "Building Controls & HVAC"),
    ("TT", "Industrials", "HVAC & Climate Solutions"),
    ("OTIS", "Industrials", "Elevators & Escalators"),
    ("WM", "Industrials", "Waste Management & Environmental Services"),
    ("UPS", "Industrials", "Parcel Delivery & Logistics"),
    ("FDX", "Industrials", "Parcel Delivery & Logistics"),
    ("UNP", "Industrials", "Railroads"),
    ("BA", "Industrials", "Commercial Aircraft & Defense"),
    ("RTX", "Industrials", "Aerospace & Defense"),
    ("LMT", "Industrials", "Defense Systems"),
    ("NOC", "Industrials", "Defense Systems"),
    ("GD", "Industrials", "Defense & Business Aviation"),
    # Health care
    ("UNH", "Health Care", "Managed Health Care"),
    ("JNJ", "Health Care", "Pharmaceuticals & MedTech"),
    ("LLY", "Health Care", "Pharmaceuticals"),
    ("PFE", "Health Care", "Pharmaceuticals"),
    ("MRK", "Health Care", "Pharmaceuticals"),
    ("ABBV", "Health Care", "Biopharmaceuticals"),
    ("BMY", "Health Care", "Pharmaceuticals"),
    ("TMO", "Health Care", "Life Sciences Tools & Diagnostics"),
    ("ABT", "Health Care", "Medical Devices & Diagnostics"),
    ("DHR", "Health Care", "Life Sciences & Bioprocessing"),
    ("CVS", "Health Care", "Pharmacy & Health Services"),
    ("HCA", "Health Care", "Hospitals"),
    # Energy
    ("XOM", "Energy", "Integrated Oil & Gas"),
    ("CVX", "Energy", "Integrated Oil & Gas"),
    ("COP", "Energy", "Oil & Gas Exploration & Production"),
    ("EOG", "Energy", "Oil & Gas Exploration & Production"),
    ("SLB", "Energy", "Oilfield Services & Technology"),
    ("PSX", "Energy", "Refining & Midstream"),
    ("MPC", "Energy", "Refining & Marketing"),
    ("KMI", "Energy", "Midstream Pipelines"),
    # Utilities
    ("NEE", "Utilities", "Electric Utility & Renewables"),
    ("DUK", "Utilities", "Electric & Gas Utility"),
    ("SO", "Utilities", "Electric & Gas Utility"),
    ("D", "Utilities", "Electric & Gas Utility"),
    ("SRE", "Utilities", "Energy Infrastructure & Utility"),
    ("VST", "Utilities", "Independent Power & Retail Electricity"),
    # Consumer
    ("WMT", "Consumer Staples", "Mass Merchandise Retail"),
    ("PG", "Consumer Staples", "Household & Personal Products"),
    ("KO", "Consumer Staples", "Beverages"),
    ("MCD", "Consumer Discretionary", "Restaurants"),
    ("NKE", "Consumer Discretionary", "Athletic Footwear & Apparel"),
    ("HD", "Consumer Discretionary", "Home Improvement Retail"),
    ("LOW", "Consumer Discretionary", "Home Improvement Retail"),
    ("TJX", "Consumer Discretionary", "Off-Price Retail"),
    ("DIS", "Communication Services", "Media & Entertainment"),
    ("F", "Consumer Discretionary", "Automobiles"),
    ("GM", "Consumer Discretionary", "Automobiles"),
    # Materials
    ("SHW", "Materials", "Paints & Coatings"),
    ("APD", "Materials", "Industrial Gases"),
    ("FCX", "Materials", "Copper Mining"),
    ("NUE", "Materials", "Steel Production"),
    # Communication services
    ("VZ", "Communication Services", "Telecom Carriers"),
    ("T", "Communication Services", "Telecom Carriers"),
    ("OMC", "Communication Services", "Advertising & Marketing Services"),
    # Spares (kept only if an earlier candidate fails NYSE validation)
    ("TGT", "Consumer Discretionary", "General Merchandise Retail"),
    ("DAL", "Industrials", "Airlines"),
    ("HPQ", "Information Technology", "Personal Computers & Printing"),
    ("PLTR", "Information Technology", "Data Analytics Software"),
]


# Manually reviewed overrides. The SEC ticker file maps XOM to a newly created
# holding-company registrant (CIK 2115436) that has no 10-K or XBRL history yet;
# the operating company below is the registrant that files the 10-K and Company Facts.
CIK_OVERRIDES: dict[str, tuple[str, str]] = {
    "XOM": ("0000034088", "EXXON MOBIL CORP"),
}


def main() -> None:
    ua = os.environ.get("SEC_USER_AGENT", "EquityResearchPrototype developer@example.com")
    resp = httpx.get(SEC_TICKERS_URL, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    fields = data["fields"]  # ["cik", "name", "ticker", "exchange"]
    idx = {f: i for i, f in enumerate(fields)}
    # The SEC file can contain several registrants for one ticker (e.g. a newly
    # created holding/merger shell alongside the operating company). Prefer the
    # lowest CIK: the long-established registrant that actually files the 10-K.
    by_ticker: dict[str, dict] = {}
    for row in data["data"]:
        ticker = row[idx["ticker"]].upper()
        rec = {
            "cik": row[idx["cik"]],
            "name": row[idx["name"]],
            "exchange": (row[idx["exchange"]] or "").upper(),
        }
        current = by_ticker.get(ticker)
        if current is None or int(rec["cik"]) < int(current["cik"]):
            by_ticker[ticker] = rec

    rows: list[dict] = []
    dropped: list[str] = []
    seen: set[str] = set()
    for ticker, sector, industry in CANDIDATES:
        if ticker in seen:
            continue
        seen.add(ticker)
        rec = by_ticker.get(ticker)
        if rec is None or rec["exchange"] != "NYSE":
            dropped.append(f"{ticker} ({'missing' if rec is None else rec['exchange']})")
            continue
        if ticker in CIK_OVERRIDES:
            cik, name = CIK_OVERRIDES[ticker]
            rec = {**rec, "cik": cik, "name": name}
        rows.append(
            {
                "ticker": ticker,
                "name": rec["name"],
                "cik": str(rec["cik"]).zfill(10),
                "exchange": "NYSE",
                "sector": sector,
                "industry": industry,
            }
        )
        if len(rows) == 100:
            break

    if len(rows) < 100:
        print(f"ERROR: only {len(rows)} validated NYSE companies; add more candidates.")
        print("Dropped:", ", ".join(dropped))
        sys.exit(1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "name", "cik", "exchange", "sector", "industry"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} companies to {OUT}")
    if dropped:
        print("Dropped (not NYSE per SEC):", ", ".join(dropped))


if __name__ == "__main__":
    main()
