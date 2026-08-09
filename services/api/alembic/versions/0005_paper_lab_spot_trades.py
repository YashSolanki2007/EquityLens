"""Add development-only paper-method spot proxy tracking.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-06
"""

from alembic import op

from app.models import PaperLabSpotTrade, PaperLabSpotTradeMark

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PaperLabSpotTrade.__table__.create(bind=bind)
    PaperLabSpotTradeMark.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    PaperLabSpotTradeMark.__table__.drop(bind=bind)
    PaperLabSpotTrade.__table__.drop(bind=bind)
