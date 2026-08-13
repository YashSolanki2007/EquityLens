"""Add five-minute intraday copula paper tracking.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-11
"""

from alembic import op
from app.models import PaperIntradayCopulaTrade, PaperIntradayCopulaTradeMark

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    PaperIntradayCopulaTrade.__table__.create(bind=bind)
    PaperIntradayCopulaTradeMark.__table__.create(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    PaperIntradayCopulaTradeMark.__table__.drop(bind=bind)
    PaperIntradayCopulaTrade.__table__.drop(bind=bind)
