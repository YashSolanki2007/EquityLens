"""Filing HTML parsing: sanitization, text extraction, 10-K section splitting, chunking.

Filing content is untrusted data — scripts/styles are stripped, never executed,
and the extracted text is always treated as content, not instructions.
"""

import re
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

WHITESPACE_RE = re.compile(r"[ \t\xa0]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")

# Matches 10-K item headings like "Item 1. Business", "ITEM 1A. RISK FACTORS", "Item 7A.",
# and combined headings like "Items 1. and 2. Business and Properties" (keyed by the first number).
ITEM_HEADING_RE = re.compile(
    r"^\s*items?\s+(\d{1,2}[a-c]?)\s*[\.\:—\-]?(?:\s*and\s+\d{1,2}[a-c]?\s*[\.\:—\-]?)?\s*(.{0,120})$",
    re.IGNORECASE,
)

SECTION_LABELS = {
    "1": "Item 1 - Business",
    "1a": "Item 1A - Risk Factors",
    "2": "Item 2 - Properties",
    "7": "Item 7 - MD&A",
    "8": "Item 8 - Financial Statements",
}


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "embed", "head"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = WHITESPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    return MULTI_NEWLINE_RE.sub("\n\n", text).strip()


def split_10k_items(text: str) -> dict[str, str]:
    """Split 10-K text into item sections keyed by lowercase item number ('1', '1a', ...).

    An item heading can appear several times: in the table of contents, as the real
    section heading, and as line-start cross-references ("Item 7." in signatures or
    MD&A). For each occurrence the candidate body runs to the next heading occurrence
    of ANY item; for each item the occurrence with the LARGEST body wins — TOC rows
    and cross-references are followed almost immediately by another heading, while
    the real section heading is followed by its full text.
    """
    matches: list[tuple[str, int]] = []
    for m in re.finditer(r"^.*$", text, re.MULTILINE):
        heading = ITEM_HEADING_RE.match(m.group(0))
        if heading:
            matches.append((heading.group(1).lower(), m.start()))

    if not matches:
        return {}

    best: dict[str, tuple[int, str]] = {}  # item -> (body_len, body)
    for i, (item, pos) in enumerate(matches):
        end = matches[i + 1][1] if i + 1 < len(matches) else len(text)
        body = text[pos:end].strip()
        if len(body) > best.get(item, (0, ""))[0]:
            best[item] = (len(body), body)

    return {item: body for item, (length, body) in best.items() if length > 200}


def extract_10k_business_sections(text: str) -> dict[str, str]:
    """Return the sections relevant to card generation, keyed by human-readable label."""
    items = split_10k_items(text)
    out: dict[str, str] = {}
    for key in ("1", "1a", "2", "7"):
        if key in items:
            out[SECTION_LABELS[key]] = items[key]
    if not out and text:
        out["Document"] = text
    return out


def chunk_text(
    text: str, *, target_chars: int = 1800, overlap_chars: int = 200, max_chunks: int = 400
) -> list[str]:
    """Paragraph-aware chunking with overlap."""
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= target_chars:
            current = f"{current}\n\n{para}" if current else para
            continue
        if current:
            chunks.append(current)
            tail = current[-overlap_chars:]
            current = f"{tail}\n\n{para}" if tail else para
        else:
            # single paragraph longer than target: hard-split
            for i in range(0, len(para), target_chars):
                chunks.append(para[i : i + target_chars])
            current = ""
        if len(chunks) >= max_chunks:
            return chunks
    if current:
        chunks.append(current)
    return chunks[:max_chunks]
