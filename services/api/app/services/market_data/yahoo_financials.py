"""Normalized annual and quarterly financial facts from yfinance.

This is a development adapter for Indian companies until a licensed fundamentals
provider is configured. Values retain their reported currency and are never calculated
by a language model.
"""

import asyncio
import hashlib
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

ROW_TO_CONCEPT = {
    "Total Revenue": "normalized:Revenue",
    "Net Income": "normalized:NetIncome",
}


def _accession(ticker: str, frequency: str, end_date: date) -> str:
    raw = f"{ticker}:{frequency}:{end_date.isoformat()}"
    return f"YF-{hashlib.sha1(raw.encode()).hexdigest()[:20]}"


def _fetch_financial_facts_sync(ticker: str) -> list[dict]:
    import pandas as pd
    import yfinance as yf

    stock = yf.Ticker(ticker)
    currency = getattr(stock.fast_info, "currency", None) or "INR"
    out: list[dict] = []
    frames = (
        ("ANNUAL", stock.financials, 364),
        ("QUARTERLY", stock.quarterly_financials, 89),
    )
    for form, frame, duration_days in frames:
        if frame is None or frame.empty:
            continue
        for raw_name, concept in ROW_TO_CONCEPT.items():
            if raw_name not in frame.index:
                continue
            series = frame.loc[raw_name]
            for timestamp, raw_value in series.items():
                if pd.isna(raw_value):
                    continue
                end_date = timestamp.date()
                out.append(
                    {
                        "concept": concept,
                        "unit": currency,
                        "value": float(raw_value),
                        "start_date": end_date - timedelta(days=duration_days),
                        "end_date": end_date,
                        "fiscal_year": end_date.year,
                        "fiscal_period": "FY" if form == "ANNUAL" else None,
                        "form": form,
                        "frame": None,
                        "accession": _accession(ticker, form, end_date),
                        "filed_date": None,
                        "source": "yfinance_financials",
                    }
                )
    return out


async def get_financial_facts(ticker: str) -> list[dict]:
    try:
        return await asyncio.to_thread(_fetch_financial_facts_sync, ticker)
    except Exception as exc:
        logger.warning("yfinance financials failed for %s: %s", ticker, exc)
        return []
