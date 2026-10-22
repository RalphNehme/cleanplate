"""Chains keep their own menu text (national or merged from location pages)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chains", sa.Column("menu_text", sa.Text))
    op.add_column("chains", sa.Column("menu_hash", sa.String(64)))
    op.add_column("chains", sa.Column("source_pages", sa.Integer))


def downgrade() -> None:
    for name in ("source_pages", "menu_hash", "menu_text"):
        op.drop_column("chains", name)
