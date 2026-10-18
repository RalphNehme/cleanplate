from collections.abc import Iterable, Iterator
from datetime import date, datetime
from itertools import groupby

import httpx

from pipeline.adapters.base import InspectionRecord, RestaurantRecord, ViolationRecord
from pipeline.normalize import clean_text, nyc_rating, title_name

URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
FIELDS = (
    "camis,dba,boro,building,street,zipcode,phone,cuisine_description,inspection_date,"
    "inspection_type,action,violation_code,violation_description,critical_flag,score,grade,"
    "latitude,longitude"
)
NOT_INSPECTED = "1900-01-01"
PAGE_SIZE = 50_000


class NYCAdapter:
    slug = "nyc"

    def __init__(self, app_token: str = "", client: httpx.Client | None = None):
        headers = {"X-App-Token": app_token} if app_token else {}
        self.client = client or httpx.Client(headers=headers, timeout=120)

    def rows(self, since: date | None = None) -> Iterator[dict]:
        params = {"$select": FIELDS, "$order": "camis,inspection_date,:id", "$limit": PAGE_SIZE}
        if since:
            params["$where"] = (
                f"inspection_date >= '{since.isoformat()}T00:00:00' "
                f"OR inspection_date = '{NOT_INSPECTED}T00:00:00'"
            )
        offset = 0
        while True:
            resp = self.client.get(URL, params={**params, "$offset": offset})
            resp.raise_for_status()
            page = resp.json()
            yield from page
            if len(page) < PAGE_SIZE:
                return
            offset += PAGE_SIZE

    def restaurants(self, since: date | None = None) -> Iterator[RestaurantRecord]:
        for _, rows in groupby(self.rows(since), key=lambda r: r["camis"]):
            yield parse_restaurant(list(rows))


def _int(value: str | None) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except ValueError:
        return None


def _coord(value: str | None) -> float | None:
    try:
        v = float(value) if value else None
    except ValueError:
        return None
    return v if v else None


def parse_restaurant(rows: list[dict]) -> RestaurantRecord:
    latest = rows[-1]
    building = clean_text(latest.get("building"))
    street = clean_text(latest.get("street"))
    address = " ".join(p for p in (building, street.title() if street else None) if p) or None
    lat, lon = _coord(latest.get("latitude")), _coord(latest.get("longitude"))
    return RestaurantRecord(
        source_id=latest["camis"],
        name=title_name(clean_text(latest.get("dba")) or "Unknown"),
        address=address,
        borough=None if latest.get("boro") in (None, "0") else latest["boro"],
        zip=clean_text(latest.get("zipcode")),
        cuisine=clean_text(latest.get("cuisine_description")),
        phone=clean_text(latest.get("phone")),
        lat=lat if lat and lon else None,
        lon=lon if lat and lon else None,
        inspections=parse_inspections(rows),
    )


def parse_inspections(rows: Iterable[dict]) -> list[InspectionRecord]:
    def key(r: dict) -> tuple[str, str]:
        return r["inspection_date"][:10], r.get("inspection_type") or "Unknown"

    inspections = []
    for (day, itype), group in groupby(sorted(rows, key=key), key=key):
        if day == NOT_INSPECTED:
            continue
        group = list(group)
        score = next((s for r in group if (s := _int(r.get("score"))) is not None), None)
        grade = next((r["grade"] for r in group if r.get("grade")), None)
        action = next((r["action"] for r in group if r.get("action")), None)
        seen, violations = set(), []
        for r in group:
            code = r.get("violation_code")
            if not code or code in seen:
                continue
            seen.add(code)
            violations.append(
                ViolationRecord(
                    code=code,
                    description=clean_text(r.get("violation_description")),
                    critical=r.get("critical_flag") == "Critical",
                )
            )
        inspections.append(
            InspectionRecord(
                inspected_at=datetime.fromisoformat(day).date(),
                type=itype,
                action=action,
                raw_score=score,
                raw_grade=grade,
                rating=nyc_rating(score, grade, action),
                violations=violations,
            )
        )
    return inspections
