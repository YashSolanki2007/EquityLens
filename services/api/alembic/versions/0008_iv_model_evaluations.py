"""Persist genuinely forward IV model evaluations.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-07
"""

from alembic import op

from app.models import IVModelEvaluation

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    IVModelEvaluation.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    IVModelEvaluation.__table__.drop(bind=op.get_bind(), checkfirst=True)
