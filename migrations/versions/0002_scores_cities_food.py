"""1-100 scores, city map settings, food reports, Chicago

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("cities", "score_scale", type_=sa.String(300))
    for name, column in [
        ("official_label", sa.String(50)),
        ("center_lat", sa.Float),
        ("center_lon", sa.Float),
        ("zoom", sa.Float),
        ("source_name", sa.String(200)),
        ("source_url", sa.String(300)),
    ]:
        op.add_column("cities", sa.Column(name, column))
    op.execute("""
        UPDATE cities SET
            score_scale = 'Official letter grade from points per violation: '
                          'A: 0-13, B: 14-27, C: 28+',
            official_label = 'NYC grade',
            center_lat = 40.73, center_lon = -73.95, zoom = 10.5,
            source_name = 'NYC Department of Health and Mental Hygiene',
            source_url = 'https://data.cityofnewyork.us/Health/'
                         'DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j'
        WHERE slug = 'nyc'
    """)
    op.execute("""
        INSERT INTO cities (slug, name, state, score_scale, official_label,
                            center_lat, center_lon, zoom, source_name, source_url)
        VALUES ('chicago', 'Chicago', 'IL',
                'Official result: Pass, Pass w/ Conditions or Fail',
                'Chicago result', 41.88, -87.68, 10.3,
                'Chicago Department of Public Health',
                'https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5')
    """)
    for name in ("official_label", "center_lat", "center_lon", "zoom", "source_name", "source_url"):
        op.alter_column("cities", name, nullable=False)

    op.alter_column("inspections", "raw_grade", type_=sa.String(30))
    op.add_column("inspections", sa.Column("hygiene_score", sa.Integer))

    op.alter_column("restaurants", "latest_grade", type_=sa.String(30))
    op.add_column(
        "restaurants", sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true())
    )
    op.add_column("restaurants", sa.Column("hygiene_score", sa.Integer))
    op.add_column("restaurants", sa.Column("food_estimate", sa.Integer))
    op.add_column("restaurants", sa.Column("food_score", sa.Integer))
    op.add_column("restaurants", sa.Column("food_source", sa.String(10)))
    op.add_column(
        "restaurants",
        sa.Column("food_reports_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column("restaurants", sa.Column("reported_oil", sa.String(20)))
    op.create_index("ix_restaurants_city_id", "restaurants", ["city_id"])
    op.create_index("ix_restaurants_hygiene_score", "restaurants", ["hygiene_score"])
    op.create_index("ix_restaurants_food_score", "restaurants", ["food_score"])

    op.create_table(
        "food_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "restaurant_id",
            sa.Integer,
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("oil", sa.String(20)),
        sa.Column("ingredients", sa.String(20)),
        sa.Column("healthy_options", sa.String(20)),
        sa.Column("score", sa.Integer, nullable=False),
        sa.Column("reporter_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_food_reports_restaurant_id", "food_reports", ["restaurant_id"])


def downgrade() -> None:
    op.drop_table("food_reports")
    op.drop_index("ix_restaurants_food_score", "restaurants")
    op.drop_index("ix_restaurants_hygiene_score", "restaurants")
    op.drop_index("ix_restaurants_city_id", "restaurants")
    for name in (
        "reported_oil",
        "food_reports_count",
        "food_source",
        "food_score",
        "food_estimate",
        "hygiene_score",
        "active",
    ):
        op.drop_column("restaurants", name)
    op.drop_column("inspections", "hygiene_score")
    op.execute("DELETE FROM cities WHERE slug = 'chicago'")
    for name in ("source_url", "source_name", "zoom", "center_lon", "center_lat", "official_label"):
        op.drop_column("cities", name)
