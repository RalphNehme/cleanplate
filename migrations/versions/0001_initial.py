"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "cities",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("score_scale", sa.String(200), nullable=False),
    )

    op.create_table(
        "restaurants",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("city_id", sa.Integer, sa.ForeignKey("cities.id"), nullable=False),
        sa.Column("source_id", sa.String(50), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(300)),
        sa.Column("borough", sa.String(50)),
        sa.Column("zip", sa.String(10)),
        sa.Column("cuisine", sa.String(100)),
        sa.Column("phone", sa.String(30)),
        sa.Column("geom", Geography("POINT", srid=4326, spatial_index=False)),
        sa.Column("latest_grade", sa.String(5)),
        sa.Column("latest_score", sa.Integer),
        sa.Column("latest_rating", sa.String(20)),
        sa.Column("latest_inspected_at", sa.Date),
        sa.UniqueConstraint("city_id", "source_id"),
    )
    op.create_index("ix_restaurants_geom", "restaurants", ["geom"], postgresql_using="gist")
    op.create_index(
        "ix_restaurants_name_trgm",
        "restaurants",
        ["name"],
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index("ix_restaurants_borough", "restaurants", ["borough"])
    op.create_index("ix_restaurants_cuisine", "restaurants", ["cuisine"])
    op.create_index("ix_restaurants_latest_grade", "restaurants", ["latest_grade"])

    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer,
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("inspected_at", sa.Date, nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("action", sa.Text),
        sa.Column("raw_score", sa.Integer),
        sa.Column("raw_grade", sa.String(5)),
        sa.Column("rating", sa.String(20)),
        sa.UniqueConstraint("restaurant_id", "inspected_at", "type"),
    )
    op.create_index("ix_inspections_restaurant_id", "inspections", ["restaurant_id"])
    op.create_index("ix_inspections_inspected_at", "inspections", ["inspected_at"])

    op.create_table(
        "violations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "inspection_id",
            sa.Integer,
            sa.ForeignKey("inspections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(10)),
        sa.Column("description", sa.Text),
        sa.Column("critical", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_violations_inspection_id", "violations", ["inspection_id"])
    op.create_index("ix_violations_code", "violations", ["code"])

    op.execute(
        "INSERT INTO cities (slug, name, state, score_scale) VALUES "
        "('nyc', 'New York City', 'NY', 'Points per violation, lower is better. "
        "A: 0-13, B: 14-27, C: 28+')"
    )


def downgrade() -> None:
    op.drop_table("violations")
    op.drop_table("inspections")
    op.drop_table("restaurants")
    op.drop_table("cities")
