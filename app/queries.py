from geoalchemy2 import Geometry
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import City, Inspection, Restaurant

GRADES = ("A", "B", "C")


def _filters(stmt, borough: str | None, cuisine: str | None, grade: str | None):
    if borough:
        stmt = stmt.where(Restaurant.borough == borough)
    if cuisine:
        stmt = stmt.where(Restaurant.cuisine == cuisine)
    if grade:
        stmt = stmt.where(Restaurant.latest_grade == grade)
    return stmt


def search(
    session: Session,
    q: str = "",
    borough: str | None = None,
    cuisine: str | None = None,
    grade: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 30,
) -> list[dict]:
    distance = None
    stmt = select(
        Restaurant.id,
        Restaurant.name,
        Restaurant.address,
        Restaurant.borough,
        Restaurant.cuisine,
        Restaurant.latest_grade,
        Restaurant.latest_score,
        Restaurant.latest_inspected_at,
    )
    stmt = _filters(stmt, borough, cuisine, grade)
    if q:
        stmt = stmt.where(Restaurant.name.ilike(f"%{q}%") | Restaurant.name.op("%")(q))
        stmt = stmt.order_by(func.similarity(Restaurant.name, q).desc())
    if lat is not None and lon is not None:
        point = func.ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})")
        distance = func.ST_Distance(Restaurant.geom, point)
        stmt = stmt.add_columns(distance.label("meters"))
        stmt = stmt.where(func.ST_DWithin(Restaurant.geom, point, 2000)).order_by(distance)
    elif not q:
        stmt = stmt.order_by(Restaurant.latest_inspected_at.desc().nulls_last())
    return [dict(r._mapping) for r in session.execute(stmt.limit(limit))]


def points(
    session: Session,
    borough: str | None = None,
    cuisine: str | None = None,
    grade: str | None = None,
) -> list[list]:
    geom = Restaurant.geom.cast(Geometry)
    stmt = select(
        Restaurant.id,
        func.ST_Y(geom),
        func.ST_X(geom),
        Restaurant.latest_grade,
        Restaurant.name,
    ).where(Restaurant.geom.is_not(None))
    stmt = _filters(stmt, borough, cuisine, grade)
    return [[i, round(la, 5), round(lo, 5), g, n] for i, la, lo, g, n in session.execute(stmt)]


def restaurant(session: Session, rid: int) -> Restaurant | None:
    return session.scalar(
        select(Restaurant)
        .where(Restaurant.id == rid)
        .options(selectinload(Restaurant.inspections).selectinload(Inspection.violations))
    )


def city(session: Session, slug: str = "nyc") -> City | None:
    return session.scalar(select(City).where(City.slug == slug))


def coords(session: Session, rid: int) -> tuple[float, float] | None:
    row = session.execute(
        text(
            "SELECT ST_Y(geom::geometry), ST_X(geom::geometry) FROM restaurants "
            "WHERE id = :id AND geom IS NOT NULL"
        ),
        {"id": rid},
    ).first()
    return (row[0], row[1]) if row else None


def options(session: Session) -> dict:
    boroughs = session.scalars(
        select(Restaurant.borough)
        .where(Restaurant.borough.is_not(None))
        .distinct()
        .order_by(Restaurant.borough)
    ).all()
    cuisines = session.scalars(
        select(Restaurant.cuisine)
        .where(Restaurant.cuisine.is_not(None))
        .group_by(Restaurant.cuisine)
        .order_by(func.count().desc())
        .limit(60)
    ).all()
    return {"boroughs": boroughs, "cuisines": sorted(cuisines), "grades": GRADES}


GRADE_BY_BOROUGH = text("""
SELECT borough,
       count(*) FILTER (WHERE latest_grade = 'A') AS a,
       count(*) FILTER (WHERE latest_grade = 'B') AS b,
       count(*) FILTER (WHERE latest_grade = 'C') AS c,
       count(*) FILTER (WHERE latest_grade IN ('A', 'B', 'C')) AS graded
FROM restaurants
WHERE borough IS NOT NULL
GROUP BY borough
ORDER BY borough
""")

CUISINE_SCORES = text("""
SELECT cuisine,
       count(*) AS restaurants,
       round(avg(latest_score), 1) AS avg_score,
       round(100.0 * count(*) FILTER (WHERE latest_grade = 'A')
             / nullif(count(*) FILTER (WHERE latest_grade IN ('A','B','C')), 0), 1) AS pct_a
FROM restaurants
WHERE cuisine IS NOT NULL AND latest_score IS NOT NULL
GROUP BY cuisine
HAVING count(*) >= 100
ORDER BY avg_score
""")

TOP_VIOLATIONS = text("""
SELECT v.code, min(v.description) AS description, bool_or(v.critical) AS critical,
       count(*) AS times
FROM violations v
JOIN inspections i ON i.id = v.inspection_id
WHERE i.inspected_at >= (SELECT max(inspected_at) FROM inspections) - interval '12 months'
GROUP BY v.code
ORDER BY times DESC
LIMIT 10
""")

BIGGEST_DROPS = text("""
WITH scored AS (
    SELECT restaurant_id, inspected_at, raw_score,
           lag(raw_score) OVER (PARTITION BY restaurant_id ORDER BY inspected_at, id) AS prev
    FROM inspections
    WHERE raw_score IS NOT NULL
)
SELECT r.id, r.name, r.borough, s.inspected_at, s.prev, s.raw_score,
       s.raw_score - s.prev AS change
FROM scored s
JOIN restaurants r ON r.id = s.restaurant_id
WHERE s.prev IS NOT NULL
  AND s.inspected_at >= (SELECT max(inspected_at) FROM inspections) - interval '90 days'
ORDER BY change DESC
LIMIT 10
""")

TOTALS = text("""
SELECT (SELECT count(*) FROM restaurants) AS restaurants,
       (SELECT count(*) FROM inspections) AS inspections,
       (SELECT count(*) FROM violations) AS violations,
       (SELECT max(inspected_at) FROM inspections) AS latest
""")


def stats(session: Session) -> dict:
    def rows(q):
        return [dict(r._mapping) for r in session.execute(q)]

    cuisines = rows(CUISINE_SCORES)
    return {
        "totals": dict(session.execute(TOTALS).first()._mapping),
        "boroughs": rows(GRADE_BY_BOROUGH),
        "cleanest_cuisines": cuisines[:8],
        "worst_cuisines": cuisines[-8:][::-1],
        "violations": rows(TOP_VIOLATIONS),
        "drops": rows(BIGGEST_DROPS),
    }
