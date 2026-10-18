from datetime import date

from pipeline.adapters.nyc import parse_restaurant


def row(**kw):
    base = {
        "camis": "123",
        "dba": "JOE'S PIZZA",
        "boro": "Manhattan",
        "building": "7",
        "street": "CARMINE   STREET",
        "zipcode": "10014",
        "cuisine_description": "Pizza",
        "inspection_date": "2025-03-01T00:00:00.000",
        "inspection_type": "Cycle Inspection",
        "latitude": "40.7305",
        "longitude": "-74.0021",
    }
    return {**base, **kw}


def test_groups_violation_rows_into_inspections():
    rows = [
        row(
            violation_code="04L",
            violation_description="Mice",
            critical_flag="Critical",
            score="12",
            grade="A",
        ),
        row(
            violation_code="10F",
            violation_description="Surfaces",
            critical_flag="Not Critical",
            score="12",
            grade="A",
        ),
        row(
            violation_code="10F",
            violation_description="Surfaces",
            critical_flag="Not Critical",
            score="12",
            grade="A",
        ),
        row(
            inspection_date="2024-01-05T00:00:00.000",
            violation_code="02B",
            score="30",
            critical_flag="Critical",
            action="Establishment Closed by DOHMH.",
        ),
    ]
    r = parse_restaurant(rows)

    assert r.name == "Joe's Pizza"
    assert r.address == "7 Carmine Street"
    assert (r.lat, r.lon) == (40.7305, -74.0021)
    assert len(r.inspections) == 2

    old, new = r.inspections
    assert new.inspected_at == date(2025, 3, 1)
    assert (new.raw_score, new.raw_grade, new.rating) == (12, "A", "good")
    assert [v.code for v in new.violations] == ["04L", "10F"]
    assert new.violations[0].critical and not new.violations[1].critical
    assert old.rating == "concerning"


def test_skips_uninspected_and_bad_coordinates():
    r = parse_restaurant(
        [row(inspection_date="1900-01-01T00:00:00.000", latitude="0", longitude="0")]
    )
    assert r.inspections == []
    assert r.lat is None and r.lon is None
