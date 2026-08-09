"""Add persistent paper tracking for IV strategies.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31
"""

from alembic import op

from app.models import PaperIVTrade, PaperIVTradeMark

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PaperIVTrade.__table__.create(bind=bind)
    PaperIVTradeMark.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    PaperIVTradeMark.__table__.drop(bind=bind)
    PaperIVTrade.__table__.drop(bind=bind)
