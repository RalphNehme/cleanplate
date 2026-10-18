from collections.abc import Iterable

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import City, Inspection, Restaurant, Violation
from pipeline.adapters.base import RestaurantRecord

REFRESH_LATEST = text("""
WITH last_rated AS (
    SELECT DISTINCT ON (i.restaurant_id)
           i.restaurant_id, i.inspected_at, i.raw_score, i.rating
    FROM inspections i JOIN restaurants r ON r.id = i.restaurant_id
    WHERE r.city_id = :city_id AND i.rating IS NOT NULL
    ORDER BY i.restaurant_id, i.inspected_at DESC, i.id DESC
),
last_graded AS (
    SELECT DISTINCT ON (i.restaurant_id) i.restaurant_id, i.raw_grade
    FROM inspections i JOIN restaurants r ON r.id = i.restaurant_id
    WHERE r.city_id = :city_id AND i.raw_grade IS NOT NULL
    ORDER BY i.restaurant_id, i.inspected_at DESC, i.id DESC
)
UPDATE restaurants r
SET latest_score = lr.raw_score,
    latest_rating = CASE lg.raw_grade
        WHEN 'A' THEN 'good' WHEN 'B' THEN 'ok' WHEN 'C' THEN 'concerning'
        ELSE lr.rating END,
    latest_inspected_at = lr.inspected_at,
    latest_grade = lg.raw_grade
FROM restaurants r2
LEFT JOIN last_rated lr ON lr.restaurant_id = r2.id
LEFT JOIN last_graded lg ON lg.restaurant_id = r2.id
WHERE r.id = r2.id AND r.city_id = :city_id
""")


def city_id(session: Session, slug: str) -> int:
    return session.scalar(select(City.id).where(City.slug == slug))


def load_batch(session: Session, cid: int, batch: list[RestaurantRecord]) -> None:
    rows = [
        {
            "city_id": cid,
            "source_id": r.source_id,
            "name": r.name[:200],
            "address": r.address,
            "borough": r.borough,
            "zip": r.zip,
            "cuisine": r.cuisine,
            "phone": r.phone,
            "geom": f"SRID=4326;POINT({r.lon} {r.lat})" if r.lat is not None else None,
        }
        for r in batch
    ]
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
                }
            )
    if not insp_rows:
        return
    stmt = insert(Inspection).values(insp_rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["restaurant_id", "inspected_at", "type"],
        set_={c: stmt.excluded[c] for c in ("action", "raw_score", "raw_grade", "rating")},
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
    session.commit()
    return count
