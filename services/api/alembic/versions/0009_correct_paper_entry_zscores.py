"""Correct paper-method entry Z-scores at their actual saved entry prices.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-08
"""

from __future__ import annotations

import math
from typing import Any

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def _entry_zscore(row: Any) -> float | None:
    snapshot = row.suggestion_snapshot or {}
    try:
        stock_a = str(snapshot["stock_a"])
        stock_b = str(snapshot["stock_b"])
        prices = {
            str(row.long_ticker): float(row.entry_long_price),
            str(row.short_ticker): float(row.entry_short_price),
        }
        base_price_a = float(snapshot["latest_price_a"])
        base_price_b = float(snapshot["latest_price_b"])
        base_gap = float(snapshot["spread_gap_to_mean"])
        beta = float(snapshot["hedge_ratio"])
        signal_zscore = float(snapshot["current_zscore"])
    except (KeyError, TypeError, ValueError):
        return None
    if stock_a not in prices or stock_b not in prices or abs(base_gap) < 1e-12:
        return None
    entry_gap = (
        base_gap
        + (prices[stock_a] - base_price_a)
        - beta * (prices[stock_b] - base_price_b)
    )
    zscore = signal_zscore * entry_gap / base_gap
    return zscore if math.isfinite(zscore) else None


def upgrade() -> None:
    bind = op.get_bind()
    trades = sa.table(
        "paper_lab_spot_trades",
        sa.column("id"),
        sa.column("long_ticker"),
        sa.column("short_ticker"),
        sa.column("entry_long_price"),
        sa.column("entry_short_price"),
        sa.column("entry_zscore"),
        sa.column("suggestion_snapshot"),
    )
    rows = bind.execute(sa.select(trades)).fetchall()
    for row in rows:
        entry_zscore = _entry_zscore(row)
        if entry_zscore is None:
            continue
        bind.execute(
            sa.update(trades)
            .where(trades.c.id == row.id)
            .values(entry_zscore=entry_zscore)
        )


def downgrade() -> None:
    bind = op.get_bind()
    trades = sa.table(
        "paper_lab_spot_trades",
        sa.column("id"),
        sa.column("entry_zscore"),
        sa.column("suggestion_snapshot"),
    )
    rows = bind.execute(sa.select(trades)).fetchall()
    for row in rows:
        snapshot = row.suggestion_snapshot or {}
        try:
            signal_zscore = float(snapshot["current_zscore"])
        except (KeyError, TypeError, ValueError):
            continue
        bind.execute(
            sa.update(trades)
            .where(trades.c.id == row.id)
            .values(entry_zscore=signal_zscore)
        )
