"""Integration tests (spec §20). Require running Postgres (+ ingested data), Ollama,
and network access to official filing sources. Run explicitly with:

    pytest -m integration
"""

import pytest
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    """Fresh engine per test: pytest-asyncio uses one event loop per test, so the
    process-global cached engine cannot be reused across tests here."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool

    import app.core.db as core_db
    import app.core.llm as core_llm
    import app.services.sec.client as sec_client
    from app.core.config import get_settings

    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    old_engine, old_factory = core_db._engine, core_db._session_factory
    core_db._engine, core_db._session_factory = engine, factory
    # Cached HTTP clients are bound to the previous test's event loop.
    sec_client._client = None
    core_llm.set_provider(None)
    yield engine
    core_db._engine, core_db._session_factory = old_engine, old_factory
    await engine.dispose()


@pytest.fixture
async def db(engine):
    from app.core.db import get_session_factory

    async with get_session_factory()() as session:
        yield session


@pytest.fixture
async def dlr(db):
    from app.models import Company

    company = (
        await db.execute(select(Company).where(Company.ticker == "DLR"))
    ).scalar_one_or_none()
    if company is None:
        pytest.skip("Universe not ingested; run scripts/bootstrap_db.py first")
    return company


class TestIngestion:
    async def test_ingest_one_company_end_to_end(self, db, dlr):
        from app.services.ingestion import ingest_company

        result = await ingest_company(db, dlr)
        assert result["latest_10k"]
        assert result["facts"] > 0


class TestCards:
    async def test_cards_exist_and_are_verified(self, db, dlr):
        from app.models import CompanyCard

        cards = (
            (await db.execute(select(CompanyCard).where(CompanyCard.company_id == dlr.id)))
            .scalars()
            .all()
        )
        if not cards:
            pytest.skip("Cards not built for DLR; run scripts/rebuild_cards.py DLR")
        assert all(c.confidence >= 0.75 for c in cards)
        assert all(c.source_excerpt for c in cards)
        assert all(c.embedding is not None for c in cards)


class TestRetrieval:
    async def test_semantic_retrieval_finds_data_center_company(self, db):
        from app.models import Company
        from app.schemas.search import SemanticCondition
        from app.services.semantic_search.retrieval import semantic_retrieval

        companies = (
            (
                await db.execute(
                    select(Company).where(Company.universe == "NYSE_100")
                )
            )
            .scalars()
            .all()
        )
        results = await semantic_retrieval(
            db,
            [
                SemanticCondition(
                    id="dc",
                    concept="operates data centers providing colocation and interconnection",
                    card_types=["business_activity", "product_service"],
                    required=True,
                    weight=1.0,
                    directness_required="direct",
                )
            ],
            {c.id: c.ticker for c in companies},
            company_ids=[c.id for c in companies],
        )
        if not results:
            pytest.skip("No cards indexed yet")
        assert any(r.ticker in ("DLR", "IRM", "VRT", "DELL", "HPE", "ANET") for r in results[:5])


class TestFinancialVerification:
    async def test_revenue_yoy_from_real_xbrl(self, db, dlr):
        from app.services.research.financials import compute_yoy_metric

        result = await compute_yoy_metric(db, dlr.id, "revenue_yoy_growth")
        assert result.status in ("ok", "unknown", "not_directly_comparable")
        if result.status == "ok":
            assert result.current is not None and result.previous is not None
            # Same fiscal quarter compared one year apart.
            delta = abs((result.current.end_date - result.previous.end_date).days - 365)
            assert delta <= 21


class TestFullSearch:
    async def test_complete_search_via_orchestrator(self, db):
        import asyncio

        from app.models import ResearchSession
        from app.schemas.search import ResearchCondition, SearchPlan, SemanticCondition
        from app.services import search_service

        plan = SearchPlan(
            original_query="integration test: data center companies with revenue growth",
            base_semantic_conditions=[
                SemanticCondition(
                    id="dc",
                    concept="data center operations and infrastructure",
                    card_types=["business_activity"],
                    required=True,
                    weight=0.6,
                )
            ],
            research_conditions=[
                ResearchCondition(
                    id="growth",
                    type="revenue_yoy_growth",
                    operator="gte",
                    threshold=0,
                    required=False,
                    weight=0.4,
                )
            ],
            candidate_limit=3,
            final_limit=3,
        )
        session = await search_service.create_session(db, plan.original_query, "quick", plan)
        await asyncio.wait_for(search_service.run_search(session.id), timeout=300)
        refreshed = (
            await db.execute(select(ResearchSession).where(ResearchSession.id == session.id))
        ).scalar_one()
        await db.refresh(refreshed)
        assert refreshed.status == "completed"
        assert refreshed.funnel["researched"] >= 1
