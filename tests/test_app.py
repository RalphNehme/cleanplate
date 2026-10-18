from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.main import app
from pipeline.adapters.base import InspectionRecord, RestaurantRecord, ViolationRecord
from pipeline.load import load

TEST_ID = "test-0001"


@pytest.fixture(scope="module")
def client():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM cities"))
    except Exception:
        pytest.skip("database not available")

    record = RestaurantRecord(
        source_id=TEST_ID,
        name="Zzyzx Test Kitchen",
        address="1 Test St",
        borough="Queens",
        zip="11101",
        cuisine="Testing",
        phone=None,
        lat=40.75,
        lon=-73.94,
        inspections=[
            InspectionRecord(
                date(2024, 5, 1),
                "Cycle Inspection",
                None,
                30,
                "C",
                "concerning",
                [ViolationRecord("04L", "Mice", True)],
                hygiene_score=67,
            ),
            InspectionRecord(
                date(2024, 6, 1), "Re-inspection", None, 9, "A", "good", [], hygiene_score=90
            ),
        ],
    )
    with SessionLocal() as session:
        load(session, "nyc", [record])
        load(session, "nyc", [record])
        rid = session.scalar(
            text("SELECT id FROM restaurants WHERE source_id = :s"), {"s": TEST_ID}
        )
    yield TestClient(app), rid
    with SessionLocal() as session:
        session.execute(text("DELETE FROM restaurants WHERE source_id = :s"), {"s": TEST_ID})
        session.commit()


def test_load_is_idempotent_and_sets_latest(client):
    _, rid = client
    with SessionLocal() as session:
        n = session.scalar(
            text("SELECT count(*) FROM inspections WHERE restaurant_id = :r"), {"r": rid}
        )
        latest = session.execute(
            text(
                "SELECT latest_grade, latest_score, hygiene_score, latest_rating, active "
                "FROM restaurants WHERE id = :r"
            ),
            {"r": rid},
        ).one()
    assert n == 2
    assert tuple(latest) == ("A", 9, 90, "good", True)


def test_pages(client):
    c, rid = client
    assert c.get("/").status_code == 200
    assert "Zzyzx Test Kitchen" in c.get("/search", params={"q": "Zzyzx"}).text
    blank = c.get("/search", params={"q": "Zzyzx", "borough": "", "lat": "", "lon": ""})
    assert "Zzyzx Test Kitchen" in blank.text
    assert "Zzyzx" in c.get(f"/r/{rid}").text
    assert c.get("/stats").status_code == 200
    assert c.get("/r/999999999").status_code == 404


def test_api(client):
    c, rid = client
    data = c.get(f"/api/restaurants/{rid}").json()
    assert data["grade"] == "A"
    assert data["inspections"][1]["violations"][0]["critical"] is True
    near = c.get("/api/search", params={"lat": 40.75, "lon": -73.94}).json()
    assert near[0]["name"] == "Zzyzx Test Kitchen"
    assert any(p[0] == rid for p in c.get("/api/points", params={"cuisine": "Testing"}).json())
