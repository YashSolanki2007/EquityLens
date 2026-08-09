"""Add persistent paper tracking for futures pair trades.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-31
"""

from alembic import op

from app.models import PaperPairTrade, PaperPairTradeMark

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PaperPairTrade.__table__.create(bind=bind)
    PaperPairTradeMark.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    PaperPairTradeMark.__table__.drop(bind=bind)
    PaperPairTrade.__table__.drop(bind=bind)
