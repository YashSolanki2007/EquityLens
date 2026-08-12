"""Add stock-price paper pair portfolios.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-10
"""

from alembic import op
from app.models import PaperPairPortfolio

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    PaperPairPortfolio.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    PaperPairPortfolio.__table__.drop(bind=op.get_bind())
