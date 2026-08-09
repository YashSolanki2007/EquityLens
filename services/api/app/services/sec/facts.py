"""Extraction of supported XBRL facts from SEC Company Facts JSON (spec §9).

Only extraction/normalization lives here; deterministic YoY math lives in
app/services/research/financials.py and is never delegated to a language model.
"""

from datetime import date, datetime
from typing import TypedDict

REVENUE_CONCEPTS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",  # fallback
)
NET_INCOME_CONCEPTS = ("NetIncomeLoss",)

SUPPORTED_CONCEPTS = REVENUE_CONCEPTS + NET_INCOME_CONCEPTS


class XbrlFact(TypedDict):
    concept: str
    unit: str
    value: float
    start_date: date | None
    end_date: date
    fiscal_year: int | None
    fiscal_period: str | None
    form: str | None
    frame: str | None
    accession: str | None
    filed_date: date | None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def extract_facts(
    company_facts_json: dict, concepts: tuple[str, ...] = SUPPORTED_CONCEPTS
) -> list[XbrlFact]:
    """Flatten us-gaap facts for the supported concepts (USD units only)."""
    out: list[XbrlFact] = []
    gaap = (company_facts_json.get("facts") or {}).get("us-gaap") or {}
    for concept in concepts:
        node = gaap.get(concept)
        if not node:
            continue
        units = node.get("units") or {}
        for unit_name, entries in units.items():
            if unit_name != "USD":
                continue
            for entry in entries:
                end = _parse_date(entry.get("end"))
                value = entry.get("val")
                if end is None or value is None:
                    continue
                out.append(
                    XbrlFact(
                        concept=f"us-gaap:{concept}",
                        unit=unit_name,
                        value=float(value),
                        start_date=_parse_date(entry.get("start")),
                        end_date=end,
                        fiscal_year=entry.get("fy"),
                        fiscal_period=entry.get("fp"),
                        form=entry.get("form"),
                        frame=entry.get("frame"),
                        accession=entry.get("accn"),
                        filed_date=_parse_date(entry.get("filed")),
                    )
                )
    return out
