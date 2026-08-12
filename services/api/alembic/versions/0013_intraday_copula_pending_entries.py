"""Queue after-hours copula signals for the next NSE open.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-11
"""

from alembic import op
from app.models import PaperIntradayCopulaPendingEntry

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    PaperIntradayCopulaPendingEntry.__table__.create(bind=op.get_bind())


def downgrade() -> None:
    PaperIntradayCopulaPendingEntry.__table__.drop(bind=op.get_bind())
