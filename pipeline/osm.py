import logging
import time

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

OVERPASS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
USER_AGENT = "CleanPlate/0.1 (+https://github.com/RalphNehme/cleanplate)"
AMENITIES = "restaurant|fast_food|cafe|bar|pub|ice_cream|food_court"
MATCH_METERS = 80
MIN_SIMILARITY = 0.35

log = logging.getLogger("pipeline.osm")

MATCH = text("""
UPDATE restaurants r
SET osm_id = m.osm_id, osm_cuisine = m.cuisine, diet_tags = m.diet,
    website = coalesce(m.website, r.website)
FROM (
    SELECT r2.id, best.*
    FROM restaurants r2
    CROSS JOIN LATERAL (
        SELECT o.osm_id, o.cuisine, o.diet, o.website
        FROM osm_places o
        WHERE ST_DWithin(o.geom, r2.geom, :meters)
          AND similarity(o.name, lower(r2.name)) >= :min_sim
        ORDER BY similarity(o.name, lower(r2.name)) DESC, o.geom <-> r2.geom
        LIMIT 1
    ) best
    WHERE r2.city_id = :cid AND r2.geom IS NOT NULL
) m
WHERE r.id = m.id
""")


def bbox(session: Session, city_id: int) -> tuple[float, float, float, float]:
    row = session.execute(
        text("""
        SELECT percentile_cont(0.001) WITHIN GROUP (ORDER BY ST_Y(geom::geometry)),
               percentile_cont(0.001) WITHIN GROUP (ORDER BY ST_X(geom::geometry)),
               percentile_cont(0.999) WITHIN GROUP (ORDER BY ST_Y(geom::geometry)),
               percentile_cont(0.999) WITHIN GROUP (ORDER BY ST_X(geom::geometry))
        FROM restaurants WHERE city_id = :cid AND geom IS NOT NULL
        """),
        {"cid": city_id},
    ).one()
    return tuple(round(v, 4) for v in row)


def fetch_places(box: tuple[float, float, float, float]) -> list[dict]:
    s, w, n, e = box
    query = (
        f'[out:json][timeout:300];nwr["amenity"~"^({AMENITIES})$"]["name"]({s},{w},{n},{e});'
        "out center tags;"
    )
    for attempt in range(6):
        url = OVERPASS[attempt % len(OVERPASS)]
        try:
            resp = httpx.post(
                url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=360
            )
            resp.raise_for_status()
            return [p for p in (parse_element(el) for el in resp.json()["elements"]) if p]
        except httpx.HTTPError as exc:
            log.warning("Overpass %s failed (%s), retrying", url, exc)
            time.sleep(15 * (attempt + 1))
    raise RuntimeError("OpenStreetMap Overpass API unavailable")


def format_cuisine(value: str | None) -> str | None:
    if not value:
        return None
    first = value.split(";")[0].strip().replace("_", " ")
    return first.title()[:100] if first else None


def parse_element(el: dict) -> dict | None:
    tags = el.get("tags", {})
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lon is None or not tags.get("name"):
        return None
    diet = sorted(
        k.removeprefix("diet:")
        for k, v in tags.items()
        if k.startswith("diet:") and v in ("yes", "only")
    )
    website = tags.get("website") or tags.get("contact:website")
    return {
        "osm_id": f"{el['type'][0]}{el['id']}",
        "name": tags["name"].lower()[:200],
        "cuisine": format_cuisine(tags.get("cuisine")),
        "diet": ",".join(diet)[:200] or None,
        "website": website[:500] if website else None,
        "lon": lon,
        "lat": lat,
    }


def match_city(session: Session, city_id: int) -> int:
    places = fetch_places(bbox(session, city_id))
    log.info("Fetched %d OpenStreetMap places", len(places))
    session.execute(
        text("""
        CREATE TEMP TABLE osm_places (
            osm_id text, name text, cuisine text, diet text, website text,
            geom geography(Point, 4326)
        ) ON COMMIT DROP
        """)
    )
    session.execute(
        text("""
        INSERT INTO osm_places
        VALUES (:osm_id, :name, :cuisine, :diet, :website,
                ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography)
        """),
        places,
    )
    session.execute(text("CREATE INDEX ON osm_places USING gist (geom)"))
    session.execute(
        text(
            "UPDATE restaurants SET osm_id = NULL, osm_cuisine = NULL, diet_tags = NULL "
            "WHERE city_id = :cid"
        ),
        {"cid": city_id},
    )
    matched = session.execute(
        MATCH, {"cid": city_id, "meters": MATCH_METERS, "min_sim": MIN_SIMILARITY}
    ).rowcount
    session.commit()
    return matched
