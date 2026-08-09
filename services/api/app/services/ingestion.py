"""NSE main-board universe and per-company ingestion.

- ensure_universe: upsert the official NSE main-board universe and prune removed rows.
- ingest_company: use the NSE/yfinance development adapters for Indian companies.
"""

import csv
import hashlib
import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import REPO_ROOT
from app.models import (
    Company,
    CompanyMarketSnapshot,
    FinancialFact,
    SecFiling,
)
from app.services.market_data.yahoo import get_market_snapshot
from app.services.market_data.yahoo_financials import get_financial_facts
from app.services.nse.client import NseClient, get_nse_client
from app.services.sec.client import SecClient, get_sec_client
from app.services.sec.facts import extract_facts

logger = logging.getLogger(__name__)

INDIA_UNIVERSE_CSV = REPO_ROOT / "data" / "companies_india.csv"

FILING_FORMS = ("10-K", "10-Q", "8-K")
FILING_LOOKBACK_DAYS = 800  # covers ~2 10-Ks, ~6 10-Qs, recent 8-Ks
OFFICIAL_INDIA_REPORT_FALLBACKS = {
    "GROWW": [
        {
            "fileName": (
                "https://resources.groww.in/web-assets/media-library/2025/9/"
                "BGV%20Annual%20Report%202024-25.pdf"
            ),
            "fromYr": 2024,
            "toYr": 2025,
            "broadcast_dttm": "-",
            "submission_type": "Issuer website",
        }
    ],
    "LENSKART": [
        {
            "fileName": (
                "https://static.lenskart.com/media/desktop/corporate/annualreports/ForFY2024-25.pdf"
            ),
            "fromYr": 2024,
            "toYr": 2025,
            "broadcast_dttm": "-",
            "submission_type": "Issuer website",
        }
    ],
    "LGEINDIA": [
        {
            "fileName": (
                "https://www.lg.com/content/dam/lge/in/migration/"
                "lginvestorrelations/IRPdf/FI/AnnualR/Annual-Report-2025.pdf"
            ),
            "fromYr": 2024,
            "toYr": 2025,
            "broadcast_dttm": "-",
            "submission_type": "Issuer website",
        }
    ],
    "MCX": [
        {
            "fileName": (
                "https://www.mcxindia.com/docs/default-source/investor-relations/"
                "agm-document/mcx-annual-report-fy-2024-25-%281%29.pdf"
            ),
            "fromYr": 2024,
            "toYr": 2025,
            "broadcast_dttm": "20-Aug-2025 00:00:00",
            "submission_type": "Issuer website",
        }
    ],
    # Tata Capital entered the equity universe before NSE's annual-report
    # endpoint exposed its history. This is the issuer-hosted FY2024-25 report.
    "TATACAP": [
        {
            "fileName": (
                "https://www.tatacapital.com/content/dam/tata-capital/pdf/"
                "investors-and-financial-reports/annual-reports/24-25/"
                "tata-capital-limited.pdf"
            ),
            "fromYr": 2024,
            "toYr": 2025,
            "broadcast_dttm": "03-Jul-2025 00:00:00",
            "submission_type": "Issuer website",
        }
    ],
}


async def ensure_universe(db: AsyncSession) -> int:
    """Upsert the checked-in NSE main-board list, then prune removed companies."""
    rows: list[dict] = []
    with INDIA_UNIVERSE_CSV.open() as f:
        rows.extend(csv.DictReader(f))
    existing = {c.ticker: c for c in (await db.execute(select(Company))).scalars().all()}

    csv_tickers = {row["ticker"].upper() for row in rows}
    removed_ids = [c.id for t, c in existing.items() if t not in csv_tickers]
    if removed_ids:
        from sqlalchemy import delete as sa_delete

        from app.models import (
            Citation,
            CompanyCard,
            CompanyMarketSnapshot,
            ConditionResult,
            DerivedMetric,
            FilingChunk,
            ResearchCandidate,
            SecFiling,
        )

        filing_ids = select(SecFiling.id).where(SecFiling.company_id.in_(removed_ids))
        await db.execute(sa_delete(FilingChunk).where(FilingChunk.filing_id.in_(filing_ids)))
        candidate_ids = select(ResearchCandidate.id).where(
            ResearchCandidate.company_id.in_(removed_ids)
        )
        result_ids = select(ConditionResult.id).where(
            ConditionResult.candidate_id.in_(candidate_ids)
        )
        await db.execute(sa_delete(Citation).where(Citation.condition_result_id.in_(result_ids)))
        await db.execute(
            sa_delete(ConditionResult).where(ConditionResult.candidate_id.in_(candidate_ids))
        )
        for table in (
            ResearchCandidate,
            CompanyCard,
            FinancialFact,
            DerivedMetric,
            CompanyMarketSnapshot,
            SecFiling,
        ):
            await db.execute(sa_delete(table).where(table.company_id.in_(removed_ids)))
        await db.execute(sa_delete(Company).where(Company.id.in_(removed_ids)))
        logger.info("Pruned %d companies no longer in the universe CSV", len(removed_ids))

    count = 0
    for row in rows:
        ticker = row["ticker"].upper()
        company = existing.get(ticker)
        if company is None:
            db.add(
                Company(
                    ticker=ticker,
                    name=row["name"],
                    cik=row.get("cik", "").zfill(10) or None,
                    isin=row.get("isin") or None,
                    country=row.get("country") or "US",
                    universe=row.get("universe") or "NSE_MAINBOARD",
                    market_data_ticker=row.get("market_data_ticker") or ticker,
                    reporting_currency=("INR" if (row.get("country") or "US") == "IN" else "USD"),
                    exchange=row["exchange"],
                    sector=row["sector"],
                    industry=row["industry"],
                )
            )
        else:
            company.name = row["name"]
            company.cik = row.get("cik", "").zfill(10) or None
            company.isin = row.get("isin") or None
            company.country = row.get("country") or "US"
            company.universe = row.get("universe") or "NSE_MAINBOARD"
            company.market_data_ticker = row.get("market_data_ticker") or ticker
            company.reporting_currency = "INR" if company.country == "IN" else "USD"
            company.exchange = row["exchange"]
            company.sector = row["sector"]
            company.industry = row["industry"]
        count += 1
    await db.commit()
    return count


async def sync_filings_metadata(db: AsyncSession, company: Company, sec: SecClient) -> int:
    """Store recent filing metadata from the submissions API. Returns rows upserted."""
    if not company.cik:
        return 0
    submissions = await sec.get_submissions(company.cik)
    recent = (submissions.get("filings") or {}).get("recent") or {}
    if not recent:
        return 0

    accessions = recent.get("accessionNumber", [])
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])
    items_list = recent.get("items", [])

    existing_accessions = {
        a
        for (a,) in (
            await db.execute(
                select(SecFiling.accession_number).where(SecFiling.company_id == company.id)
            )
        ).all()
    }

    cutoff = date.today() - timedelta(days=FILING_LOOKBACK_DAYS)
    upserted = 0
    for i, accession in enumerate(accessions):
        form = forms[i] if i < len(forms) else ""
        if form not in FILING_FORMS:
            continue
        f_date = datetime.strptime(filing_dates[i], "%Y-%m-%d").date()
        if f_date < cutoff:
            continue
        if accession in existing_accessions:
            continue
        primary_doc = primary_docs[i] if i < len(primary_docs) else None
        r_date_raw = report_dates[i] if i < len(report_dates) else ""
        db.add(
            SecFiling(
                company_id=company.id,
                accession_number=accession,
                form=form,
                filing_date=f_date,
                report_date=(
                    datetime.strptime(r_date_raw, "%Y-%m-%d").date() if r_date_raw else None
                ),
                primary_document=primary_doc,
                primary_doc_url=(
                    SecClient.filing_doc_url(company.cik, accession, primary_doc)
                    if primary_doc
                    else None
                ),
                description=descriptions[i] if i < len(descriptions) else None,
                items=items_list[i] if i < len(items_list) else None,
            )
        )
        upserted += 1
    await db.commit()
    return upserted


async def get_latest_filing(db: AsyncSession, company_id, form: str) -> SecFiling | None:
    return (
        await db.execute(
            select(SecFiling)
            .where(SecFiling.company_id == company_id, SecFiling.form == form)
            .order_by(SecFiling.filing_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def download_filing(
    db: AsyncSession, company: Company, filing: SecFiling, sec: SecClient
) -> str:
    """Download (or load cached) filing HTML, marking the row downloaded. Returns HTML."""
    if not filing.primary_document:
        raise ValueError(f"Filing {filing.accession_number} has no primary document")
    html, content_hash = await sec.download_filing_document(
        company.cik, filing.accession_number, filing.primary_document
    )
    if not filing.downloaded or filing.content_hash != content_hash:
        filing.downloaded = True
        filing.content_hash = content_hash
        await db.commit()
    return html


def _nse_external_id(url: str) -> str:
    return f"NSE-{hashlib.sha1(url.encode()).hexdigest()[:20]}"


def _nse_filing_date(raw: str, report_year: int) -> date:
    if raw and raw != "-":
        try:
            return datetime.strptime(raw, "%d-%b-%Y %H:%M:%S").date()
        except ValueError:
            pass
    return date(report_year, 3, 31)


async def sync_india_annual_reports(db: AsyncSession, company: Company, nse: NseClient) -> int:
    reports = await nse.get_annual_reports(company.ticker)
    if not reports:
        reports = OFFICIAL_INDIA_REPORT_FALLBACKS.get(company.ticker, [])
    existing = {
        accession
        for (accession,) in (
            await db.execute(
                select(SecFiling.accession_number).where(SecFiling.company_id == company.id)
            )
        ).all()
    }
    upserted = 0
    for report in reports[:8]:
        url = str(report.get("fileName") or "")
        if not url:
            continue
        accession = _nse_external_id(url)
        if accession in existing:
            continue
        # NSE occasionally returns the same annual-report URL more than once in
        # one response (for example, duplicate "New" submissions). Track rows
        # queued in this transaction as well as rows already in the database.
        existing.add(accession)
        try:
            report_year = int(report.get("toYr") or date.today().year)
        except (TypeError, ValueError):
            report_year = date.today().year
        db.add(
            SecFiling(
                company_id=company.id,
                accession_number=accession,
                form="ANNUAL_REPORT",
                filing_date=_nse_filing_date(str(report.get("broadcast_dttm") or ""), report_year),
                report_date=date(report_year, 3, 31),
                primary_document=url.rsplit("/", 1)[-1],
                primary_doc_url=url,
                description=(
                    f"NSE annual report FY {report.get('fromYr')}-{report.get('toYr')} "
                    f"({report.get('submission_type') or 'submission'})"
                ),
            )
        )
        upserted += 1
    await db.commit()
    return upserted


async def download_india_filing(db: AsyncSession, filing: SecFiling, nse: NseClient) -> bytes:
    """Fetch an NSE filing transiently and record that the source was reachable."""

    if not filing.primary_doc_url:
        raise ValueError(f"Filing {filing.accession_number} has no source URL")
    content, content_hash = await nse.download_document(
        filing.primary_doc_url, filing.accession_number
    )
    if not filing.downloaded or filing.content_hash != content_hash:
        filing.downloaded = True
        filing.content_hash = content_hash
        await db.commit()
    return content


async def refresh_financial_facts(db: AsyncSession, company: Company, sec: SecClient) -> int:
    """Replace cached XBRL facts for the supported concepts from Company Facts."""
    if not company.cik:
        return 0
    try:
        facts_json = await sec.get_company_facts(company.cik)
    except Exception as exc:
        logger.warning("Company Facts unavailable for %s: %s", company.ticker, exc)
        return 0
    facts = extract_facts(facts_json)
    cutoff = date.today() - timedelta(days=5 * 365)
    facts = [f for f in facts if f["end_date"] >= cutoff]

    await db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
    for f in facts:
        db.add(
            FinancialFact(
                company_id=company.id,
                concept=f["concept"],
                unit=f["unit"],
                value=f["value"],
                start_date=f["start_date"],
                end_date=f["end_date"],
                fiscal_year=f["fiscal_year"],
                fiscal_period=f["fiscal_period"],
                form=f["form"],
                frame=f["frame"],
                accession=f["accession"],
                filed_date=f["filed_date"],
            )
        )
    await db.commit()
    return len(facts)


async def refresh_india_financial_facts(db: AsyncSession, company: Company) -> int:
    ticker = company.market_data_ticker or f"{company.ticker}.NS"
    facts = await get_financial_facts(ticker)
    if not facts:
        return 0
    await db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
    for fact in facts:
        db.add(FinancialFact(company_id=company.id, **fact))
    await db.commit()
    return len(facts)


async def refresh_market_snapshot(
    db: AsyncSession, company: Company
) -> CompanyMarketSnapshot | None:
    snapshot = await get_market_snapshot(company.market_data_ticker or company.ticker)
    if snapshot is None:
        return None
    row = CompanyMarketSnapshot(
        company_id=company.id,
        price=snapshot.get("price"),
        market_cap_usd=snapshot.get("market_cap_usd"),
        market_cap_native=snapshot.get("market_cap_native"),
        sector=snapshot.get("sector"),
        industry=snapshot.get("industry"),
        summary=snapshot.get("summary"),
        currency=snapshot.get("currency"),
        source=snapshot.get("source", "yfinance"),
        retrieved_at=datetime.now(UTC),
        as_of=datetime.fromisoformat(snapshot["as_of"]) if snapshot.get("as_of") else None,
        is_delayed_or_unverified=True,
    )
    db.add(row)
    await db.commit()
    return row


async def ingest_company(db: AsyncSession, company: Company) -> dict:
    """Ingest one company: filing metadata, facts, and a market snapshot.

    Indian annual reports are intentionally not downloaded here. Card generation and
    evidence workflows fetch them only while parsing, then release the in-memory bytes.
    """
    if company.country == "IN":
        nse = get_nse_client()
        result: dict = {"ticker": company.ticker, "market": "IN"}
        result["filings_added"] = await sync_india_annual_reports(db, company, nse)
        latest_report = await get_latest_filing(db, company.id, "ANNUAL_REPORT")
        result["latest_annual_report"] = (
            latest_report.accession_number if latest_report is not None else None
        )
        result["annual_report_storage"] = "remote_source_only"
        result["facts"] = await refresh_india_financial_facts(db, company)
        snapshot = await refresh_market_snapshot(db, company)
        result["market_snapshot"] = snapshot is not None
        return result

    sec = get_sec_client()
    result: dict = {"ticker": company.ticker}
    result["filings_added"] = await sync_filings_metadata(db, company, sec)

    latest_10k = await get_latest_filing(db, company.id, "10-K")
    if latest_10k is not None:
        try:
            await download_filing(db, company, latest_10k, sec)
            result["latest_10k"] = latest_10k.accession_number
        except Exception as exc:
            logger.warning("10-K download failed for %s: %s", company.ticker, exc)
            result["latest_10k_error"] = str(exc)
    else:
        result["latest_10k"] = None

    result["facts"] = await refresh_financial_facts(db, company, sec)
    snapshot = await refresh_market_snapshot(db, company)
    result["market_snapshot"] = snapshot is not None
    return result
