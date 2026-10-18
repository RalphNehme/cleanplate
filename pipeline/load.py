from collections.abc import Iterable

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.food import estimate, infer_cuisine, refresh_food
from app.models import City, Inspection, Restaurant, Violation
from pipeline.adapters.base import RestaurantRecord

REFRESH_LATEST = text("""
WITH city_inspections AS (
    SELECT i.* FROM inspections i JOIN restaurants r ON r.id = i.restaurant_id
    WHERE r.city_id = :city_id
),
last_scored AS (
    SELECT DISTINCT ON (restaurant_id) restaurant_id, raw_score, hygiene_score
    FROM city_inspections WHERE hygiene_score IS NOT NULL
    ORDER BY restaurant_id, inspected_at DESC, id DESC
),
last_graded AS (
    SELECT DISTINCT ON (restaurant_id) restaurant_id, raw_grade
    FROM city_inspections WHERE raw_grade IS NOT NULL
    ORDER BY restaurant_id, inspected_at DESC, id DESC
),
last_any AS (
    SELECT DISTINCT ON (restaurant_id) restaurant_id, inspected_at, action
    FROM city_inspections
    ORDER BY restaurant_id, inspected_at DESC, id DESC
)
UPDATE restaurants r
SET hygiene_score = ls.hygiene_score,
    latest_score = ls.raw_score,
    latest_rating = CASE WHEN ls.hygiene_score >= 85 THEN 'good'
                         WHEN ls.hygiene_score >= 70 THEN 'ok'
                         WHEN ls.hygiene_score IS NOT NULL THEN 'concerning' END,
    latest_grade = lg.raw_grade,
    latest_inspected_at = la.inspected_at,
    active = la.restaurant_id IS NULL OR (
        la.inspected_at >= current_date - interval '3 years'
        AND coalesce(la.action, '') NOT IN ('Out of Business', 'Business Not Located'))
FROM restaurants r2
LEFT JOIN last_scored ls ON ls.restaurant_id = r2.id
LEFT JOIN last_graded lg ON lg.restaurant_id = r2.id
LEFT JOIN last_any la ON la.restaurant_id = r2.id
WHERE r.id = r2.id AND r.city_id = :city_id
""")


def city_id(session: Session, slug: str) -> int:
    return session.scalar(select(City.id).where(City.slug == slug))


def restaurant_row(cid: int, r: RestaurantRecord) -> dict:
    cuisine = r.cuisine or infer_cuisine(r.name)
    return {
        "city_id": cid,
        "source_id": r.source_id,
        "name": r.name[:200],
        "address": r.address,
        "borough": r.borough,
        "zip": r.zip,
        "cuisine": cuisine,
        "phone": r.phone,
        "geom": f"SRID=4326;POINT({r.lon} {r.lat})" if r.lat is not None else None,
        "food_estimate": estimate(cuisine, r.name),
    }


def load_batch(session: Session, cid: int, batch: list[RestaurantRecord]) -> None:
    rows = [restaurant_row(cid, r) for r in batch]
    stmt = insert(Restaurant).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["city_id", "source_id"],
        set_={c: stmt.excluded[c] for c in rows[0] if c not in ("city_id", "source_id")},
    ).returning(Restaurant.id, Restaurant.source_id)
    ids = {sid: rid for rid, sid in session.execute(stmt)}

    insp_rows, by_key = [], {}
    for r in batch:
        for i in r.inspections:
            key = (ids[r.source_id], i.inspected_at, i.type)
            by_key[key] = i
            insp_rows.append(
                {
                    "restaurant_id": key[0],
                    "inspected_at": i.inspected_at,
                    "type": i.type,
                    "action": i.action,
                    "raw_score": i.raw_score,
                    "raw_grade": i.raw_grade,
                    "rating": i.rating,
                    "hygiene_score": i.hygiene_score,
                }
            )
    if not insp_rows:
        return
    stmt = insert(Inspection).values(insp_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["restaurant_id", "inspected_at", "type"],
        set_={
            c: stmt.excluded[c]
            for c in ("action", "raw_score", "raw_grade", "rating", "hygiene_score")
        },
    ).returning(Inspection.id, Inspection.restaurant_id, Inspection.inspected_at, Inspection.type)
    insp_ids = {(rid, d, t): iid for iid, rid, d, t in session.execute(stmt)}

    session.execute(delete(Violation).where(Violation.inspection_id.in_(insp_ids.values())))
    viol_rows = [
        {"inspection_id": iid, "code": v.code, "description": v.description, "critical": v.critical}
        for key, iid in insp_ids.items()
        for v in by_key[key].violations
    ]
    if viol_rows:
        session.execute(insert(Violation), viol_rows)


def load(
    session: Session, slug: str, records: Iterable[RestaurantRecord], batch_size: int = 1000
) -> int:
    cid = city_id(session, slug)
    count, batch = 0, []
    for record in records:
        batch.append(record)
        if len(batch) >= batch_size:
            load_batch(session, cid, batch)
            session.commit()
            count += len(batch)
            batch = []
    if batch:
        load_batch(session, cid, batch)
        count += len(batch)
    session.execute(REFRESH_LATEST, {"city_id": cid})
    refresh_food(session, city_id=cid)
    session.commit()
    return count
