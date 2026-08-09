"""Grounded answering over the saved research workspace (spec §12).

Evidence is assembled from persisted workspace data (semantic cards, verified
metrics, catalyst findings, citations). The model may only cite these numbered
items; company-specific answers without evidence are refused by prompt design.
"""

import re
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm import get_provider
from app.models import ResearchSession
from app.prompts.chat import GROUNDED_SYSTEM, GROUNDED_USER
from app.schemas.api import CitationOut, SessionOut
from app.services.serializers import build_session_out

CITATION_REF_RE = re.compile(r"\[(\d+)\]")


@dataclass
class EvidenceItem:
    index: int
    ticker: str
    text: str
    citation: CitationOut | None = None


@dataclass
class EvidenceBundle:
    items: list[EvidenceItem] = field(default_factory=list)

    def add(self, ticker: str, text: str, citation: CitationOut | None = None) -> None:
        self.items.append(EvidenceItem(len(self.items) + 1, ticker, text, citation))

    def render(self) -> str:
        return "\n".join(f"[{i.index}] ({i.ticker}) {i.text}" for i in self.items)


def _score_breakdown(result, plan) -> str | None:
    """Decompose final_score into its weighted per-condition components so the
    model can explain rank differences instead of restating the percentages."""
    if plan is None or result.final_score is None:
        return None
    parts: list[str] = []
    matches = result.semantic_matches or {}
    for cond in plan.base_semantic_conditions:
        m = matches.get(cond.id)
        best = (m.get("best_cards") or [{}])[0] if m else {}
        if m:
            parts.append(
                f"semantic '{cond.id}' scored {m.get('score', 0.0):.2f} of 1"
                f" (weight {cond.weight}; top filing-card similarity"
                f" {best.get('similarity', 0.0):.2f}, directness"
                f" {best.get('directness', 'unknown')})"
            )
        else:
            parts.append(
                f"semantic '{cond.id}' scored 0.00 (weight {cond.weight}; no matching filing card)"
            )
    research_by_id = {c.condition_id: c for c in result.condition_results}
    for rcond in plan.research_conditions:
        res = research_by_id.get(rcond.id)
        if res:
            measured = (
                f", measured {res.measured_value}{(' ' + res.unit) if res.unit else ''}"
                if res.measured_value is not None
                else ""
            )
            parts.append(
                f"research '{rcond.id}' [{res.status}] scored {res.score:.2f}"
                f" (weight {rcond.weight}{measured})"
            )
        else:
            parts.append(f"research '{rcond.id}' scored 0.00 (weight {rcond.weight}; not measured)")
    conf = result.overall_confidence or 0.0
    return (
        "Score breakdown — " + "; ".join(parts) + ". Final = weighted average of these "
        f"condition scores x evidence multiplier (0.70 + 0.30 x confidence {conf:.2f}) "
        f"= {result.match_percent}%."
    )


def build_evidence(out: SessionOut, target_tickers: list[str] | None = None) -> EvidenceBundle:
    bundle = EvidenceBundle()
    targets = {t.upper() for t in target_tickers or []}
    for result in out.results:
        if targets and result.ticker not in targets:
            continue
        prefix = f"rank {result.rank}" if result.rank else f"stage {result.stage}"
        score = (
            f"query-match {result.match_percent}%"
            if result.match_percent is not None
            else "unscored"
        )
        bundle.add(
            result.ticker,
            f"{result.name or result.ticker}: {prefix}, {score}, "
            f"confidence {result.overall_confidence}, eligible={result.eligible}.",
        )
        breakdown = _score_breakdown(result, out.search_plan)
        if breakdown:
            bundle.add(result.ticker, breakdown)
        if result.market_cap_native and result.currency == "INR":
            bundle.add(
                result.ticker,
                f"Market cap ₹{result.market_cap_native / 10_000_000:.0f} crore "
                f"(delayed yfinance snapshot, retrieved {result.market_cap_retrieved_at}).",
            )
        elif result.market_cap_usd:
            bundle.add(
                result.ticker,
                f"Market cap ${result.market_cap_usd / 1e9:.1f}B "
                f"(delayed yfinance snapshot, retrieved {result.market_cap_retrieved_at}).",
            )
        for m in (result.semantic_matches or {}).values():
            for card in m.get("best_cards", [])[:2]:
                bundle.add(
                    result.ticker,
                    f"Verified filing card ({card.get('card_type')}, "
                    f"{card.get('directness')}): {card.get('text')}",
                    CitationOut(
                        source_type="company_card",
                        url=card.get("source_url", ""),
                        accession=card.get("source_accession"),
                        description=f"Verified {card.get('card_type')} filing card",
                        excerpt=card.get("source_excerpt", "")[:400],
                    ),
                )
        for cond in result.condition_results:
            citation = cond.citations[0] if cond.citations else None
            bundle.add(
                result.ticker,
                f"Condition '{cond.condition_id}' [{cond.status}]: {cond.explanation}",
                citation,
            )
        for lim in result.limitations[:4]:
            bundle.add(result.ticker, f"Limitation: {lim}")
    return bundle


def summarize_workspace(out: SessionOut) -> str:
    lines = []
    if out.funnel:
        f = out.funnel
        lines.append(
            f"Funnel: {f.indexed} indexed, {f.semantic_matches} semantic matches, "
            f"{f.passed_base_filters} passed filters, {f.researched} researched, "
            f"{f.fully_qualified} fully qualified."
        )
    ranked = [r for r in out.results if r.rank]
    lines.append(
        "Ranked results: "
        + (
            ", ".join(f"#{r.rank} {r.ticker} ({r.match_percent}%)" for r in ranked)
            if ranked
            else "none qualified"
        )
    )
    return "\n".join(lines)


async def answer_grounded(
    db: AsyncSession,
    session: ResearchSession,
    message: str,
    target_tickers: list[str] | None = None,
) -> tuple[str, list[CitationOut], list[str]]:
    """Return (answer, citations_used, limitations)."""
    out = await build_session_out(db, session)
    bundle = build_evidence(out, target_tickers)
    limitations: list[str] = []
    if not bundle.items:
        return (
            "No research evidence is available in this workspace for that question.",
            [],
            ["Workspace contains no candidate evidence."],
        )

    provider = get_provider()
    answer = await provider.chat(
        [
            {"role": "system", "content": GROUNDED_SYSTEM},
            {
                "role": "user",
                "content": GROUNDED_USER.format(
                    query=out.original_query,
                    summary=summarize_workspace(out),
                    evidence=bundle.render(),
                    message=message,
                ),
            },
        ],
        temperature=0.1,
    )

    cited: list[CitationOut] = []
    seen: set[int] = set()
    for ref in CITATION_REF_RE.findall(answer):
        idx = int(ref)
        if idx in seen:
            continue
        seen.add(idx)
        item = next((i for i in bundle.items if i.index == idx), None)
        if item and item.citation:
            cited.append(item.citation)
    if not seen:
        limitations.append("The answer did not reference specific evidence items.")
    return answer, cited, limitations
