"""Menu-based food scores: OSM matches, fetched menus, Claude analyses

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("restaurants", "food_estimate")
    op.alter_column("restaurants", "food_source", type_=sa.String(20))
    op.add_column("restaurants", sa.Column("osm_id", sa.String(30)))
    op.add_column("restaurants", sa.Column("osm_cuisine", sa.String(100)))
    op.add_column("restaurants", sa.Column("diet_tags", sa.String(200)))
    op.add_column("restaurants", sa.Column("website", sa.String(500)))
    op.execute("UPDATE restaurants SET food_score = NULL, food_source = NULL")

    op.create_table(
        "menus",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer,
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("url", sa.String(1000)),
        sa.Column("text", sa.Text),
        sa.Column("text_hash", sa.String(64)),
        sa.Column("detail", sa.String(300)),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_menus_status", "menus", ["status"])

    op.create_table(
        "menu_analyses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer,
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("model", sa.String(50), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("score", sa.Integer),
        sa.Column("cuisine", sa.String(100)),
        sa.Column("summary", sa.Text),
        sa.Column("data", JSONB, nullable=False),
        sa.Column(
            "analyzed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("menu_analyses")
    op.drop_table("menus")
    for name in ("website", "diet_tags", "osm_cuisine", "osm_id"):
        op.drop_column("restaurants", name)
    op.add_column("restaurants", sa.Column("food_estimate", sa.Integer))
