"""Embedding maintenance: (re)embed cards and filing chunks whose embeddings are
missing or were produced by a different embedding model."""

import logging
from typing import Any

from sqlalchemy import or_, select

from app.core.db import get_session_factory
from app.core.llm import get_provider
from app.models import CompanyCard, FilingChunk

logger = logging.getLogger(__name__)

BATCH = 32


async def rebuild_all_embeddings() -> dict:
    provider = get_provider()
    model = provider.embed_model_name
    counts = {"cards": 0, "chunks": 0}
    async with get_session_factory()() as db:
        tables: list[tuple[Any, str]] = [(CompanyCard, "cards"), (FilingChunk, "chunks")]
        for table, key in tables:
            while True:
                rows = (
                    (
                        await db.execute(
                            select(table)
                            .where(
                                or_(
                                    table.embedding.is_(None),
                                    table.embed_model != model,
                                )
                            )
                            .limit(BATCH)
                        )
                    )
                    .scalars()
                    .all()
                )
                if not rows:
                    break
                embeddings = await provider.embed([r.text for r in rows])
                for row, emb in zip(rows, embeddings, strict=True):
                    row.embedding = emb
                    row.embed_model = model
                await db.commit()
                counts[key] += len(rows)
    logger.info("Rebuilt embeddings: %s", counts)
    return counts
