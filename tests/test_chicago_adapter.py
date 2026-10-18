from datetime import date

from pipeline.adapters.chicago import parse_restaurant, parse_violations

VIOLATIONS = (
    "10. ADEQUATE HANDWASHING SINKS PROPERLY SUPPLIED AND ACCESSIBLE - Comments: NO HOT WATER. "
    "PRIORITY VIOLATION. #7-38-030 (C). | "
    "16. FOOD-CONTACT SURFACES: CLEANED & SANITIZED - Comments: SLIME IN ICE MACHINE. "
    "PRIORITY FOUNDATION VIOLATION. #7-38-005. | "
    "40. PERSONAL CLEANLINESS - Comments: NO HAIR RESTRAINT."
)


def row(**kw):
    base = {
        "inspection_id": "1",
        "dba_name": "CHIYA CHAI CAFE LLC",
        "aka_name": "CHIYA CHAI CAFE",
        "license_": "2432644",
        "address": "2770 N MILWAUKEE AVE ",
        "zip": "60647",
        "inspection_date": "2026-01-06T00:00:00.000",
        "inspection_type": "Canvass",
        "results": "Pass",
        "latitude": "41.93",
        "longitude": "-87.71",
    }
    return {**base, **kw}


def test_parse_violations_reads_severity_tags():
    v = parse_violations(VIOLATIONS)
    assert [x.code for x in v] == ["10", "16", "40"]
    assert [x.critical for x in v] == [True, True, False]
    assert v[0].description.startswith("Adequate handwashing sinks")
    assert "No hot water" in v[0].description


def test_scores_and_result_caps():
    r = parse_restaurant(
        [
            row(inspection_id="5", results="Fail", violations=VIOLATIONS),
            row(inspection_id="6", inspection_date="2026-02-01T00:00:00.000", results="Pass"),
            row(
                inspection_id="7",
                inspection_date="2026-03-01T00:00:00.000",
                results="Out of Business",
            ),
        ]
    )
    assert r.name == "Chiya Chai Cafe"
    assert r.address == "2770 N Milwaukee Ave"
    fail, clean, closed = r.inspections
    assert fail.hygiene_score == 60
    assert fail.raw_grade == "Fail" and fail.rating == "concerning"
    assert (clean.hygiene_score, clean.rating) == (100, "good")
    assert closed.hygiene_score is None and closed.raw_grade is None
    assert closed.action == "Out of Business"
    assert closed.inspected_at == date(2026, 3, 1)


def test_pass_with_conditions_is_capped_below_good():
    r = parse_restaurant([row(results="Pass w/ Conditions", violations="40. X - Comments: Y")])
    assert r.inspections[0].hygiene_score == 84


def test_duplicate_same_day_inspections_keep_latest():
    r = parse_restaurant(
        [row(inspection_id="1", results="Fail"), row(inspection_id="2", results="Pass")]
    )
    assert len(r.inspections) == 1
    assert r.inspections[0].raw_grade == "Pass"
