"""Track return-qualified entries and durable zero-crossing exits.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-06
"""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {
        column["name"]
        for column in inspector.get_columns("paper_lab_spot_trades")
    }
    if "entry_expected_return_percent" not in columns:
        op.add_column(
            "paper_lab_spot_trades",
            sa.Column("entry_expected_return_percent", sa.Float(), nullable=True),
        )
    if "exit_reason" not in columns:
        op.add_column(
            "paper_lab_spot_trades",
            sa.Column("exit_reason", sa.String(length=64), nullable=True),
        )
    if "exit_zscore" not in columns:
        op.add_column(
            "paper_lab_spot_trades",
            sa.Column("exit_zscore", sa.Float(), nullable=True),
        )

    op.execute(
        """
        UPDATE paper_lab_spot_trades
        SET entry_expected_return_percent = NULLIF(
            suggestion_snapshot ->> 'potential_convergence_return_percent', ''
        )::double precision
        WHERE entry_expected_return_percent IS NULL
        """
    )

    unique_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("paper_lab_spot_trades")
    }
    if "uq_paper_lab_spot_trades_portfolio_pair" in unique_constraints:
        op.drop_constraint(
            "uq_paper_lab_spot_trades_portfolio_pair",
            "paper_lab_spot_trades",
            type_="unique",
        )

    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("paper_lab_spot_trades")
    }
    if "uq_paper_lab_spot_trades_open_portfolio_pair" not in indexes:
        op.create_index(
            "uq_paper_lab_spot_trades_open_portfolio_pair",
            "paper_lab_spot_trades",
            ["portfolio_id", "pair_id"],
            unique=True,
            postgresql_where=sa.text("status = 'open'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("paper_lab_spot_trades")
    }
    if "uq_paper_lab_spot_trades_open_portfolio_pair" in indexes:
        op.drop_index(
            "uq_paper_lab_spot_trades_open_portfolio_pair",
            table_name="paper_lab_spot_trades",
        )
    op.create_unique_constraint(
        "uq_paper_lab_spot_trades_portfolio_pair",
        "paper_lab_spot_trades",
        ["portfolio_id", "pair_id"],
    )
    op.drop_column("paper_lab_spot_trades", "exit_zscore")
    op.drop_column("paper_lab_spot_trades", "exit_reason")
    op.drop_column("paper_lab_spot_trades", "entry_expected_return_percent")
