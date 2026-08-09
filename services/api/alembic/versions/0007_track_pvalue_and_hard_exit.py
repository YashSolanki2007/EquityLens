"""Persist paper-lab p-value marks and hard-exit diagnostics.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-06
"""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    trade_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("paper_lab_spot_trades")
    }
    if "exit_p_value" not in trade_columns:
        op.add_column(
            "paper_lab_spot_trades",
            sa.Column("exit_p_value", sa.Float(), nullable=True),
        )

    mark_columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("paper_lab_spot_trade_marks")
    }
    if "estimated_p_value" not in mark_columns:
        op.add_column(
            "paper_lab_spot_trade_marks",
            sa.Column("estimated_p_value", sa.Float(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("paper_lab_spot_trade_marks", "estimated_p_value")
    op.drop_column("paper_lab_spot_trades", "exit_p_value")
