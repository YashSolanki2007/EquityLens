"""Add country-aware company universes and search sessions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("companies", "cik", existing_type=sa.String(length=10), nullable=True)
    op.add_column("companies", sa.Column("isin", sa.String(length=16), nullable=True))
    op.add_column(
        "companies",
        sa.Column("country", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.add_column(
        "companies",
        sa.Column(
            "universe", sa.String(length=32), nullable=False, server_default="NYSE_100"
        ),
    )
    op.add_column(
        "companies", sa.Column("market_data_ticker", sa.String(length=24), nullable=True)
    )
    op.add_column(
        "companies",
        sa.Column(
            "reporting_currency", sa.String(length=8), nullable=False, server_default="USD"
        ),
    )
    op.create_index("ix_companies_isin", "companies", ["isin"], unique=False)
    op.create_index("ix_companies_country", "companies", ["country"], unique=False)
    op.create_index("ix_companies_universe", "companies", ["universe"], unique=False)
    op.add_column(
        "company_market_snapshots",
        sa.Column("market_cap_native", sa.Float(), nullable=True),
    )

    op.add_column(
        "research_sessions",
        sa.Column("market", sa.String(length=2), nullable=False, server_default="US"),
    )
    op.create_index(
        "ix_research_sessions_market", "research_sessions", ["market"], unique=False
    )


def downgrade() -> None:
    op.drop_column("company_market_snapshots", "market_cap_native")
    op.drop_index("ix_research_sessions_market", table_name="research_sessions")
    op.drop_column("research_sessions", "market")
    op.drop_index("ix_companies_universe", table_name="companies")
    op.drop_index("ix_companies_country", table_name="companies")
    op.drop_index("ix_companies_isin", table_name="companies")
    op.drop_column("companies", "reporting_currency")
    op.drop_column("companies", "market_data_ticker")
    op.drop_column("companies", "universe")
    op.drop_column("companies", "country")
    op.drop_column("companies", "isin")
    op.alter_column("companies", "cik", existing_type=sa.String(length=10), nullable=False)
