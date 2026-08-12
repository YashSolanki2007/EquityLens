"""Persist portfolios enrolled in the intraday copula tracker.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-11
"""

from alembic import op
from app.models import PaperIntradayCopulaTrackerSubscription

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    PaperIntradayCopulaTrackerSubscription.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    PaperIntradayCopulaTrackerSubscription.__table__.drop(bind=op.get_bind())
