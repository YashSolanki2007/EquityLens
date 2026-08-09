"""Regression coverage for the NSE main-board market boundary."""

import csv
import hashlib
import json
from pathlib import Path

import httpx

from app.core.llm import set_provider
from app.services.nse.client import MAX_DOCUMENT_BYTES, NseClient, NseError
from app.services.nse.parser import extract_annual_report_business_sections
from app.services.query_planner.planner import plan_query
from app.services.semantic_search.cards import (
    ExtractCardsOutput,
    ExtractedCard,
    _acceptable,
    verify_card_groups,
)
from tests.conftest import FakeProvider
from tests.test_planner import VALID_PLAN


class _TransientDocumentClient(NseClient):
    def __init__(self, content: bytes):
        self.content = content
        self.requests: list[str] = []

    async def _get(self, url: str, *, params: dict | None = None) -> httpx.Response:
        self.requests.append(url)
        request = httpx.Request("GET", url)
        return httpx.Response(200, request=request, content=self.content)


async def test_india_planning_forces_nse_mainboard():
    provider = FakeProvider([json.dumps(VALID_PLAN)])

    plan = await plan_query(
        "Indian data-centre operators",
        market="IN",
        provider=provider,
        use_cache=False,
    )

    assert plan.universe == "NSE_MAINBOARD"
    assert "Indian" in provider.chat_calls[0][0]["content"]


def test_checked_in_india_universe_contains_unique_mainboard_companies():
    path = Path(__file__).resolve().parents[3] / "data" / "companies_india.csv"
    with path.open() as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) >= 2_000
    assert len({row["ticker"] for row in rows}) == len(rows)
    assert len({row["isin"] for row in rows}) == len(rows)
    assert {row["country"] for row in rows} == {"IN"}
    assert {row["universe"] for row in rows} == {"NSE_MAINBOARD"}


async def test_nse_documents_are_fetched_transiently_without_creating_a_file(tmp_path):
    content = b"%PDF-1.7 transient annual report"
    client = _TransientDocumentClient(content)

    downloaded, digest = await client.download_document(
        "https://nsearchives.nseindia.com/example/report.pdf",
        "NSE-example",
    )

    assert downloaded == content
    assert digest == hashlib.sha256(content).hexdigest()
    assert client.requests == ["https://nsearchives.nseindia.com/example/report.pdf"]
    assert list(tmp_path.iterdir()) == []


async def test_transient_nse_document_download_keeps_size_limit():
    client = _TransientDocumentClient(b"x" * (MAX_DOCUMENT_BYTES + 1))

    try:
        await client.download_document(
            "https://nsearchives.nseindia.com/example/oversized.pdf",
            "NSE-oversized",
        )
    except NseError as exc:
        assert "exceeds" in str(exc)
    else:
        raise AssertionError("Oversized NSE documents must be rejected")


def test_card_batch_drops_unknown_types_and_caps_verbose_model_output():
    output = ExtractCardsOutput.model_validate(
        {
            "cards": [
                {
                    "card_type": card_type,
                    "text": f"A sufficiently specific company fact number {index}.",
                    "directness": "direct",
                    "materiality": "meaningful",
                }
                for index, card_type in enumerate(
                    [
                        "business_activity",
                        "brand",
                        "product_service",
                        "customer_exposure",
                        "geographic_exposure",
                        "macro_exposure",
                    ]
                )
            ]
        }
    )

    assert len(output.cards) == 4
    assert all(card.card_type != "brand" for card in output.cards)


def test_esg_and_governance_boilerplate_is_not_a_semantic_business_card():
    boilerplate = ExtractedCard(
        card_type="business_activity",
        text="The company aims to achieve carbon neutrality for Scope 1 emissions.",
        directness="core",
        materiality="major",
    )
    business_fact = ExtractedCard(
        card_type="business_activity",
        text="The company operates life and general insurance businesses across India.",
        directness="core",
        materiality="major",
    )

    assert not _acceptable(boilerplate)
    assert _acceptable(business_fact)


def test_india_parser_excludes_brsr_pages_from_business_sections():
    business_page = (
        "Business Overview " * 20
        + "The company operates hospitals and provides diagnostic services to patients."
    )
    brsr_page = (
        "Business Responsibility and Sustainability Report "
        + "P1 P2 P3 P4 P5 P6 P7 P8 P9 "
        + "products and services " * 30
    )

    sections = extract_annual_report_business_sections([business_page, brsr_page])

    rendered = "\n".join(sections.values())
    assert "operates hospitals" in rendered
    assert "P1 P2 P3" not in rendered


async def test_batched_verification_preserves_each_cards_exact_source():
    provider = FakeProvider(
        [
            json.dumps(
                {
                    "verdicts": [
                        {"index": 0, "verdict": "entailed", "confidence": 0.95},
                        {"index": 1, "verdict": "not_entailed", "confidence": 0.99},
                    ]
                }
            )
        ]
    )
    set_provider(provider)
    try:
        accepted = await verify_card_groups(
            [
                (
                    "Business",
                    "The company operates hospitals.",
                    [
                        ExtractedCard(
                            card_type="business_activity",
                            text="The company operates a network of hospitals.",
                            directness="core",
                            materiality="major",
                        )
                    ],
                ),
                (
                    "Products",
                    "The company manufactures paint.",
                    [
                        ExtractedCard(
                            card_type="product_service",
                            text="The company manufactures decorative paint products.",
                            directness="core",
                            materiality="major",
                        )
                    ],
                ),
            ]
        )
    finally:
        set_provider(None)

    assert len(accepted) == 1
    assert accepted[0][2:] == (
        "Business",
        "The company operates hospitals.",
    )
    rendered_prompt = provider.chat_calls[0][-1]["content"]
    assert "source_excerpt=0" in rendered_prompt
    assert "source_excerpt=1" in rendered_prompt
