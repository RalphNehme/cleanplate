"""Chains: detect brands with many locations and score them from their national menu

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chains",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("brand", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(200), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("menu_url", sa.String(1000)),
        sa.Column("detail", sa.String(300)),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "restaurants",
        sa.Column("chain_id", sa.Integer, sa.ForeignKey("chains.id", ondelete="SET NULL")),
    )
    op.create_index("ix_restaurants_chain_id", "restaurants", ["chain_id"])


def downgrade() -> None:
    op.drop_index("ix_restaurants_chain_id", "restaurants")
    op.drop_column("restaurants", "chain_id")
    op.drop_table("chains")
