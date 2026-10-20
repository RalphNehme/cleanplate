"""Visitor reports may answer only the cooking-oil question (no score)

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-19
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("food_reports", "score", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM food_reports WHERE score IS NULL")
    op.alter_column("food_reports", "score", nullable=False)
