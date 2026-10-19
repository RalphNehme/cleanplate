from geoalchemy2 import Geometry
from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import City, Inspection, MenuAnalysis, Restaurant

BANDS = {
    "excellent": (90, 100),
    "good": (85, 100),
    "fair": (70, 84),
    "poor": (1, 69),
}
NO_SEED_OILS = ("olive", "avocado", "animal")


def cities(session: Session) -> list[City]:
    return session.scalars(select(City).order_by(City.id)).all()


def city(session: Session, slug: str) -> City | None:
    return session.scalar(select(City).where(City.slug == slug))


def city_cards(session: Session) -> list[dict]:
    rows = session.execute(
        text("""
        SELECT c.slug, count(r.id) AS restaurants,
               round(avg(r.food_score)) AS avg_food,
               round(100.0 * count(*) FILTER (WHERE r.food_score >= 70)
                     / nullif(count(r.food_score), 0)) AS pct_good
        FROM cities c
        LEFT JOIN restaurants r ON r.city_id = c.id AND r.active AND r.food_score IS NOT NULL
        GROUP BY c.slug
        """)
    )
    stats = {r.slug: dict(r._mapping) for r in rows}
    return [{"city": c, **stats.get(c.slug, {})} for c in cities(session)]


def _filters(stmt, city_id: int, area=None, cuisine=None, hygiene=None, food=None, oil=None):
    stmt = stmt.where(
        Restaurant.city_id == city_id, Restaurant.active, Restaurant.food_score.is_not(None)
    )
    if area:
        stmt = stmt.where(func.coalesce(Restaurant.borough, Restaurant.zip) == area)
    if cuisine:
        stmt = stmt.where(Restaurant.cuisine == cuisine)
    if hygiene in BANDS:
        lo, hi = BANDS[hygiene]
        stmt = stmt.where(Restaurant.hygiene_score.between(lo, hi))
    if food in BANDS:
        lo, hi = BANDS[food]
        stmt = stmt.where(Restaurant.food_score.between(lo, hi))
    if oil == "no-seed":
        menu_says = exists().where(
            MenuAnalysis.restaurant_id == Restaurant.id,
            MenuAnalysis.data["oil"]["stated"].astext.in_(NO_SEED_OILS),
        )
        stmt = stmt.where(Restaurant.reported_oil.in_(NO_SEED_OILS) | menu_says)
    return stmt


def search(
    session: Session,
    city_id: int,
    q: str = "",
    lat: float | None = None,
    lon: float | None = None,
    limit: int = 30,
    **filters,
) -> list[dict]:
    stmt = select(
        Restaurant.id,
        Restaurant.name,
        Restaurant.address,
        Restaurant.borough,
        Restaurant.cuisine,
        Restaurant.hygiene_score,
        Restaurant.food_score,
        Restaurant.food_source,
        Restaurant.latest_grade,
        Restaurant.latest_inspected_at,
    )
    stmt = _filters(stmt, city_id, **filters)
    if q:
        stmt = stmt.where(Restaurant.name.ilike(f"%{q}%") | Restaurant.name.op("%")(q))
        stmt = stmt.order_by(
            Restaurant.name.istartswith(q).desc(), func.similarity(Restaurant.name, q).desc()
        )
    if lat is not None and lon is not None:
        point = func.ST_GeogFromText(f"SRID=4326;POINT({lon} {lat})")
        distance = func.ST_Distance(Restaurant.geom, point)
        stmt = stmt.add_columns(distance.label("meters"))
        stmt = stmt.where(func.ST_DWithin(Restaurant.geom, point, 2000)).order_by(distance)
    elif not q:
        stmt = stmt.order_by(Restaurant.food_score.desc(), Restaurant.name)
    return [dict(r._mapping) for r in session.execute(stmt.limit(limit))]


def points(session: Session, city_id: int, **filters) -> list[list]:
    geom = Restaurant.geom.cast(Geometry)
    stmt = select(
        Restaurant.id,
        func.ST_Y(geom),
        func.ST_X(geom),
        Restaurant.food_score,
        Restaurant.hygiene_score,
        Restaurant.name,
    ).where(Restaurant.geom.is_not(None))
    stmt = _filters(stmt, city_id, **filters)
    return [
        [i, round(la, 5), round(lo, 5), f, h, n] for i, la, lo, f, h, n in session.execute(stmt)
    ]


def options(session: Session, city_id: int) -> dict:
    area = func.coalesce(Restaurant.borough, Restaurant.zip)
    base = select().where(
        Restaurant.city_id == city_id, Restaurant.active, Restaurant.food_score.is_not(None)
    )
    areas = session.scalars(
        base.add_columns(area).where(area.is_not(None)).group_by(area).order_by(area)
    ).all()
    cuisines = session.scalars(
        base.add_columns(Restaurant.cuisine)
        .where(Restaurant.cuisine.is_not(None))
        .group_by(Restaurant.cuisine)
        .order_by(func.count().desc())
        .limit(60)
    ).all()
    return {"areas": areas, "cuisines": sorted(cuisines)}


def restaurant(session: Session, rid: int) -> Restaurant | None:
    return session.scalar(
        select(Restaurant)
        .where(Restaurant.id == rid)
        .options(
            selectinload(Restaurant.city),
            selectinload(Restaurant.menu),
            selectinload(Restaurant.analysis),
            selectinload(Restaurant.inspections).selectinload(Inspection.violations),
        )
    )


def coords(session: Session, rid: int) -> tuple[float, float] | None:
    row = session.execute(
        text(
            "SELECT ST_Y(geom::geometry), ST_X(geom::geometry) FROM restaurants "
            "WHERE id = :id AND geom IS NOT NULL"
        ),
        {"id": rid},
    ).first()
    return (row[0], row[1]) if row else None


SCORED = "city_id = :cid AND active AND food_score IS NOT NULL"
R_SCORED = "r.city_id = :cid AND r.active AND r.food_score IS NOT NULL"

AREA_SCORES = text(f"""
SELECT coalesce(borough, zip) AS area, count(*) AS restaurants,
       round(avg(food_score)) AS avg_food,
       count(*) FILTER (WHERE food_score >= 90) AS excellent,
       count(*) FILTER (WHERE food_score BETWEEN 85 AND 89) AS good,
       count(*) FILTER (WHERE food_score BETWEEN 70 AND 84) AS fair,
       count(*) FILTER (WHERE food_score < 70) AS poor
FROM restaurants
WHERE {SCORED} AND coalesce(borough, zip) IS NOT NULL
GROUP BY 1
ORDER BY restaurants DESC
LIMIT 10
""")

CUISINE_SCORES = text(f"""
SELECT cuisine, count(*) AS restaurants, round(avg(food_score)) AS avg_food
FROM restaurants
WHERE {SCORED} AND cuisine IS NOT NULL
GROUP BY cuisine
HAVING count(*) >= :min_count
ORDER BY avg(food_score) DESC
""")

OILS = text(f"""
SELECT a.data->'oil'->>'stated' AS oil, count(*) AS restaurants
FROM menu_analyses a JOIN restaurants r ON r.id = a.restaurant_id
WHERE {R_SCORED}
GROUP BY 1
ORDER BY 2 DESC
""")

MARKERS = text(f"""
SELECT lower(m) AS marker, count(DISTINCT r.id) AS restaurants
FROM menu_analyses a
JOIN restaurants r ON r.id = a.restaurant_id
CROSS JOIN LATERAL jsonb_array_elements_text(a.data->'quality_markers') AS m
WHERE {R_SCORED}
GROUP BY 1
ORDER BY 2 DESC
LIMIT 10
""")

TOTALS = text(f"""
SELECT count(*) AS restaurants,
       round(avg(food_score)) AS avg_food,
       round(avg(hygiene_score)) AS avg_hygiene,
       count(*) FILTER (WHERE food_source = 'menu+reports') AS with_reports
FROM restaurants
WHERE {SCORED}
""")


def stats(session: Session, city_id: int) -> dict:
    params = {"cid": city_id}

    def rows(q, **extra):
        return [dict(r._mapping) for r in session.execute(q, {**params, **extra})]

    totals = dict(session.execute(TOTALS, params).first()._mapping)
    cuisines = rows(CUISINE_SCORES, min_count=10 if totals["restaurants"] > 500 else 3)
    return {
        "totals": totals,
        "areas": rows(AREA_SCORES),
        "healthiest_cuisines": cuisines[:8],
        "least_healthy_cuisines": cuisines[-8:][::-1],
        "oils": rows(OILS),
        "markers": rows(MARKERS),
    }
