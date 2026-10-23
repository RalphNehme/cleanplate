from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal, engine
from app.food import MenuReport, refresh_food
from app.main import app
from pipeline.adapters.base import InspectionRecord, RestaurantRecord, ViolationRecord
from pipeline.analyze import save as save_analysis
from pipeline.load import load
from pipeline.menus import MenuResult
from pipeline.menus import save as save_menu

TEST_ID = "test-0001"
MEAL = {
    "name": "Kale salad",
    "described": True,
    "vegetables": 1,
    "whole_grains_legumes": 0.5,
    "healthy_protein": 0.5,
    "unsaturated_fats": 0,
    "deep_fried": 0,
    "processed_meat": 0,
    "added_sugar": 0,
    "saturated_fat": 0,
    "sodium_mg": None,
    "note": "Greens and grains",
}
REPORT = MenuReport.model_validate(
    {
        "is_restaurant_menu": True,
        "cuisine": "Testing",
        "summary": "Mostly vegetable dishes cooked in olive oil.",
        "meals": [MEAL] * 5,
        "dessert_count": 1,
        "sugary_drink_count": 0,
        "oil": {"stated": "olive", "evidence": "cooked in olive oil"},
        "quality_markers": ["house-made"],
    }
)
MENU_SCORE = 100


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
        save_menu(session, rid, MenuResult("ok", "https://example.com/menu", "Kale salad $12"))
        save_analysis(session, rid, "hash", REPORT)
        refresh_food(session, restaurant_id=rid)
        session.commit()
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
    home = c.get("/")
    assert home.status_code == 200 and "New York City" in home.text and "Chicago" in home.text
    assert c.get("/nyc").status_code == 200
    assert c.get("/chicago").status_code == 200
    assert c.get("/atlantis").status_code == 404
    for name in ("Washington", "Boston", "Miami", "Philadelphia"):
        assert name in home.text
    assert "Coming soon" in home.text
    boston = c.get("/boston")
    assert boston.status_code == 200 and "Coming soon" in boston.text
    assert c.get("/boston/stats").status_code == 200
    assert "Zzyzx Test Kitchen" in c.get("/nyc/search", params={"q": "Zzyzx"}).text
    blank = c.get(
        "/nyc/search", params={"q": "Zzyzx", "area": "", "hygiene": "", "lat": "", "lon": ""}
    )
    assert "Zzyzx Test Kitchen" in blank.text
    assert (
        "Zzyzx Test Kitchen"
        in c.get("/nyc/search", params={"q": "Zzyzx", "hygiene": "excellent"}).text
    )
    assert (
        "Zzyzx Test Kitchen"
        not in c.get("/nyc/search", params={"q": "Zzyzx", "hygiene": "poor"}).text
    )
    page = c.get(f"/r/{rid}")
    assert "Zzyzx" in page.text and "Kale salad" in page.text and "olive oil" in page.text
    assert c.get("/nyc/stats").status_code == 200
    assert c.get("/scores").status_code == 200
    assert c.get("/nyc/chains/999999999").status_code == 404
    assert c.get("/r/999999999").status_code == 404


def test_api(client):
    c, rid = client
    data = c.get(f"/api/restaurants/{rid}").json()
    assert (data["city"], data["official"], data["hygiene_score"]) == ("nyc", "A", 90)
    assert (data["food_source"], data["food_score"]) == ("menu", MENU_SCORE)
    assert data["menu"]["report"]["oil"]["stated"] == "olive"
    assert data["inspections"][1]["violations"][0]["critical"] is True
    near = c.get("/api/nyc/search", params={"lat": 40.75, "lon": -73.94}).json()
    assert near[0]["name"] == "Zzyzx Test Kitchen"
    points = c.get("/api/nyc/points", params={"cuisine": "Testing"}).json()
    assert any(p[0] == rid and p[3] == MENU_SCORE and p[4] == 90 for p in points)
    assert not c.get("/api/chicago/points", params={"cuisine": "Testing"}).json()


def test_food_reports_blend_with_menu_score(client):
    c, rid = client
    with SessionLocal() as session:
        for i in range(2):
            session.execute(
                text(
                    "INSERT INTO food_reports (restaurant_id, oil, score, reporter_hash) "
                    "VALUES (:r, 'olive', 95, :h)"
                ),
                {"r": rid, "h": f"seed-{i}"},
            )
        session.commit()

    empty = c.post(f"/r/{rid}/report", data={})
    assert "Pick at least one answer" in empty.text

    first = c.post(f"/r/{rid}/report", data={"oil": "olive", "ingredients": "mixed"})
    assert "Thanks" in first.text
    assert "Menu + 3 visitor reports" in first.text
    assert "Visitors report: Olive oil" in first.text

    again = c.post(f"/r/{rid}/report", data={"oil": "seed"})
    assert "already reported" in again.text

    data = c.get(f"/api/restaurants/{rid}").json()
    assert data["food_source"] == "menu+reports"
    assert data["food_score"] == int((MENU_SCORE + round((95 + 95 + 65) / 3)) / 2 + 0.5)
