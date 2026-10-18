import re
from collections.abc import Iterator
from datetime import date, datetime
from itertools import groupby

import httpx

from pipeline.adapters.base import InspectionRecord, RestaurantRecord, ViolationRecord
from pipeline.normalize import clean_text, points_to_score, rating, title_name

URL = "https://data.cityofchicago.org/resource/4ijn-s7e5.json"
FIELDS = (
    "inspection_id,dba_name,aka_name,license_,facility_type,address,zip,inspection_date,"
    "inspection_type,results,violations,latitude,longitude"
)
# Chicago switched to the current inspection form (Priority / Priority Foundation / Core).
START = date(2018, 7, 1)
FACILITY_TYPES = ("Restaurant", "Bakery", "Coffee Shop", "Tavern")
PAGE_SIZE = 50_000

SCORED_RESULTS = {"Pass", "Pass w/ Conditions", "Fail"}
RESULT_CAPS = {"Fail": 60, "Pass w/ Conditions": 84}
POINTS = {"priority": 7, "foundation": 4, "core": 2}
VIOLATION_RE = re.compile(r"^(\d+)\.\s*(.*?)(?:\s+-\s+Comments:\s*(.*))?$", re.S)


class ChicagoAdapter:
    slug = "chicago"

    def __init__(self, app_token: str = "", client: httpx.Client | None = None):
        headers = {"X-App-Token": app_token} if app_token else {}
        self.client = client or httpx.Client(headers=headers, timeout=180)

    def rows(self, since: date | None = None) -> Iterator[dict]:
        start = max(since, START) if since else START
        types = ",".join(f"'{t}'" for t in FACILITY_TYPES)
        params = {
            "$select": FIELDS,
            "$where": (
                f"inspection_date >= '{start.isoformat()}T00:00:00' "
                f"AND facility_type in ({types}) AND license_ IS NOT NULL AND license_ != '0'"
            ),
            "$order": "license_,inspection_date,inspection_id",
            "$limit": PAGE_SIZE,
        }
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
        for _, rows in groupby(self.rows(since), key=lambda r: r["license_"]):
            yield parse_restaurant(list(rows))


def _coord(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _sentence(value: str) -> str:
    value = value.strip().lower()
    return value[:1].upper() + value[1:]


def parse_restaurant(rows: list[dict]) -> RestaurantRecord:
    latest = rows[-1]
    name = clean_text(latest.get("aka_name")) or clean_text(latest.get("dba_name")) or "Unknown"
    address = clean_text(latest.get("address"))
    lat, lon = _coord(latest.get("latitude")), _coord(latest.get("longitude"))
    return RestaurantRecord(
        source_id=latest["license_"],
        name=title_name(name),
        address=title_name(address) if address else None,
        borough=None,
        zip=clean_text(latest.get("zip")),
        cuisine=None,
        phone=None,
        lat=lat if lat and lon else None,
        lon=lon if lat and lon else None,
        inspections=parse_inspections(rows),
    )


def parse_violations(text: str | None) -> list[ViolationRecord]:
    violations, seen = [], set()
    for part in (text or "").split(" | "):
        m = VIOLATION_RE.match(part.strip())
        if not m or m[1] in seen:
            continue
        seen.add(m[1])
        title, comment = m[2].strip(), (m[3] or "").strip()
        description = _sentence(title)
        if comment:
            short = comment if len(comment) <= 400 else comment[:400].rsplit(" ", 1)[0] + "…"
            description += f". {_sentence(short)}"
        level = severity(comment, int(m[1]))
        violations.append(
            ViolationRecord(code=m[1], description=description, critical=level != "core")
        )
    return violations


def severity(comment: str, number: int) -> str:
    upper = comment.upper()
    if "PRIORITY FOUNDATION" in upper:
        return "foundation"
    if "PRIORITY VIOLATION" in upper:
        return "priority"
    if "CORE VIOLATION" in upper:
        return "core"
    return "foundation" if number <= 29 else "core"


def hygiene(result: str | None, violations_text: str | None) -> int | None:
    if result not in SCORED_RESULTS:
        return None
    points = 0
    for part in (violations_text or "").split(" | "):
        m = VIOLATION_RE.match(part.strip())
        if m:
            points += POINTS[severity(m[3] or "", int(m[1]))]
    score = points_to_score(points)
    return min(score, RESULT_CAPS.get(result, 100))


def parse_inspections(rows: list[dict]) -> list[InspectionRecord]:
    def key(r: dict) -> tuple[str, str]:
        return r["inspection_date"][:10], r.get("inspection_type") or "Unknown"

    inspections = []
    for (day, itype), group in groupby(sorted(rows, key=key), key=key):
        r = max(group, key=lambda x: int(x.get("inspection_id") or 0))
        result = r.get("results")
        score = hygiene(result, r.get("violations"))
        inspections.append(
            InspectionRecord(
                inspected_at=datetime.fromisoformat(day).date(),
                type=itype,
                action=result,
                raw_score=None,
                raw_grade=result if result in SCORED_RESULTS else None,
                rating=rating(score),
                violations=parse_violations(r.get("violations")),
                hygiene_score=score,
            )
        )
    return inspections
