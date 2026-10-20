"""Add Washington DC, Boston, Miami and Philadelphia (no data yet)

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-19
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

CITIES = [
    (
        "washington-dc",
        "Washington",
        "DC",
        "DC Health result",
        38.9072,
        -77.0369,
        11.6,
        "DC Health, Food Safety and Hygiene Inspection Services",
        "https://dc.healthinspections.us/",
    ),
    (
        "boston",
        "Boston",
        "MA",
        "Boston result",
        42.3401,
        -71.0789,
        11.8,
        "City of Boston Inspectional Services",
        "https://data.boston.gov/dataset/food-establishment-inspections",
    ),
    (
        "miami",
        "Miami",
        "FL",
        "Florida inspection",
        25.7817,
        -80.2118,
        11.4,
        "Florida DBPR, Division of Hotels and Restaurants",
        "https://www2.myfloridalicense.com/hotels-restaurants/",
    ),
    (
        "philadelphia",
        "Philadelphia",
        "PA",
        "Philadelphia inspection",
        39.9726,
        -75.1652,
        11.4,
        "Philadelphia Department of Public Health",
        "https://www.phila.gov/departments/department-of-public-health/",
    ),
]


def upgrade() -> None:
    conn = op.get_bind()
    for slug, name, state, label, lat, lon, zoom, source, url in CITIES:
        conn.exec_driver_sql(
            "INSERT INTO cities (slug, name, state, score_scale, official_label, center_lat, "
            "center_lon, zoom, source_name, source_url) "
            "VALUES (%s, %s, %s, 'Not loaded yet', %s, %s, %s, %s, %s, %s)",
            (slug, name, state, label, lat, lon, zoom, source, url),
        )


def downgrade() -> None:
    slugs = ", ".join(f"'{c[0]}'" for c in CITIES)
    op.execute(f"DELETE FROM cities WHERE slug IN ({slugs})")
