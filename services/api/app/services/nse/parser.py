"""Text extraction and business-section selection for Indian annual-report PDFs."""

import re
from io import BytesIO
from zipfile import ZipFile

import fitz

from app.services.sec.parser import MULTI_NEWLINE_RE, WHITESPACE_RE

SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Business Overview": (
        "business overview",
        "our business",
        "company overview",
        "what we do",
        "business model",
        "products and services",
        "operations",
        "manufacturing",
        "capabilities",
    ),
    "Management Discussion & Analysis": (
        "management discussion",
        "industry structure",
        "opportunities and threats",
        "business environment",
        "outlook",
        "strategy",
        "competitive",
        "market position",
    ),
    "Customers, Segments & Geography": (
        "customer",
        "end market",
        "segment information",
        "business segment",
        "geographical",
        "geographic",
        "export",
        "international operations",
        "revenue mix",
    ),
    "Supply Chain & Business Risks": (
        "supply chain",
        "raw material",
        "supplier",
        "vendor",
        "import",
        "commodity price",
        "foreign exchange",
        "risk and concern",
        "key risks",
    ),
}


def pdf_to_pages(content: bytes, *, max_pages: int = 220) -> list[str]:
    if content.startswith(b"PK"):
        with ZipFile(BytesIO(content)) as archive:
            pdf_names = [
                name
                for name in archive.namelist()
                if name.lower().endswith(".pdf") and not name.startswith("__MACOSX/")
            ]
            if not pdf_names:
                return []
            content = archive.read(max(pdf_names, key=lambda name: archive.getinfo(name).file_size))
    document = fitz.open(stream=content, filetype="pdf")
    pages: list[str] = []
    try:
        for page in document[:max_pages]:
            text = page.get_text("text")
            text = WHITESPACE_RE.sub(" ", text)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            pages.append(MULTI_NEWLINE_RE.sub("\n\n", "\n".join(lines)).strip())
    finally:
        document.close()
    return pages


def _page_score(text: str, keywords: tuple[str, ...]) -> int:
    lowered = text.lower()
    score = sum(3 if phrase in lowered[:500] else lowered.count(phrase) for phrase in keywords)
    financial_noise = sum(
        lowered.count(term)
        for term in (
            "balance sheet",
            "statement of profit and loss",
            "cash flow statement",
            "notes to the financial statements",
        )
    )
    governance_noise = sum(
        lowered.count(term)
        for term in (
            "corporate governance",
            "board of directors",
            "board meeting",
            "independent director",
            "resignation",
            "nomination and remuneration",
            "shareholders meeting",
            "secretarial audit",
            "committee meetings",
        )
    )
    sustainability_noise = sum(
        lowered.count(term)
        for term in (
            "business responsibility and sustainability",
            "environment social and governance",
            "scope 1 emissions",
            "scope 2 emissions",
            "carbon neutrality",
            "waste generated",
            "water consumption",
            "energy consumption",
            "life cycle assessment",
            "corporate social responsibility",
            "employee training",
            "remuneration policy",
        )
    )
    return (
        score
        - min(financial_noise, 3)
        - min(governance_noise * 2, 10)
        - min(sustainability_noise * 3, 15)
    )


def _is_non_business_page(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "business responsibility and sustainability report",
            "business responsibility and sustainability reporting",
            "about this report",
            "reporting scope and boundary",
            "independent reasonable assurance",
            "general shareholder information",
            "unclaimed suspense account",
            "independent auditor’s report",
            "independent auditor's report",
            "key audit matter",
            "secretarial audit report",
            "section b: management and process disclosures",
            "occupational health and safety",
            "employees and workers",
            "essential indicators",
            "leadership indicators",
            "p1 p2 p3 p4 p5 p6 p7 p8 p9",
        )
    )


def extract_annual_report_business_sections(pages: list[str]) -> dict[str, str]:
    """Select evidence-rich pages without assuming a standardized 10-K layout."""
    sections: dict[str, str] = {}
    used_pages: set[int] = set()
    for label, keywords in SECTION_KEYWORDS.items():
        ranked = sorted(
            (
                (_page_score(text, keywords), index, text)
                for index, text in enumerate(pages)
                if len(text) >= 250 and not _is_non_business_page(text)
            ),
            reverse=True,
        )
        selected: list[tuple[int, str]] = []
        for score, index, text in ranked:
            if score < 2 or index in used_pages:
                continue
            selected.append((index, text))
            used_pages.add(index)
            if len(selected) == 8:
                break
        if selected:
            selected.sort()
            sections[label] = "\n\n".join(
                f"[Annual report page {index + 1}]\n{text}" for index, text in selected
            )

    # Some issuers use branded headings that do not match the conventional annual
    # report labels above. If the primary pass is too sparse, add high-density pages
    # based on general operating vocabulary instead of returning a nearly empty index.
    if sum(len(text) for text in sections.values()) < 8_000:
        fallback_terms = (
            "products",
            "services",
            "customers",
            "business",
            "operations",
            "market segments",
            "revenue",
            "manufacturing",
            "capacity",
            "distribution network",
            "branches",
            "loans",
            "deposits",
            "digital banking",
            "retail banking",
            "corporate banking",
            "msme",
        )
        ranked_fallback = sorted(
            (
                (
                    sum(text.lower().count(term) for term in fallback_terms),
                    index,
                    text,
                )
                for index, text in enumerate(pages)
                if (
                    len(text) >= 250
                    and index not in used_pages
                    and not _is_non_business_page(text)
                )
            ),
            reverse=True,
        )
        selected_fallback = [
            (index, text)
            for score, index, text in ranked_fallback
            if score >= 5
        ][:8]
        if selected_fallback:
            selected_fallback.sort()
            sections["Additional Business Evidence"] = "\n\n".join(
                f"[Annual report page {index + 1}]\n{text}"
                for index, text in selected_fallback
            )

    if not sections:
        fallback = [
            f"[Annual report page {index + 1}]\n{text}"
            for index, text in enumerate(pages[:40])
            if len(text) >= 250 and re.search(r"\b(business|operations|products|services)\b", text, re.I)
        ][:12]
        if fallback:
            sections["Annual Report"] = "\n\n".join(fallback)
    return sections
