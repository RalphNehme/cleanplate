import pytest
from sqlalchemy import text

from app.db import SessionLocal, engine
from pipeline.chains import belongs, domain_of, normalize
from pipeline.menus import CANDIDATES


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://locations.tacobell.com/il/chicago/123.html", "tacobell.com"),
        ("www.subway.com/en-us", "subway.com"),
        ("http://order.chipotle.com:443/menu", "chipotle.com"),
        ("localhost", None),
    ],
)
def test_domain_of(url, expected):
    assert domain_of(url) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Subway #24453", "subway"),
        ("Raising Cane's 861", "raising cane s"),
        ("787 Coffee", "787 coffee"),
        ("The Sushi & Co", "sushi co"),
        ("Taco Bell Restaurant", "taco bell"),
    ],
)
def test_normalize_keeps_brand_and_drops_store_numbers(name, expected):
    assert normalize(name) == expected


def test_belongs():
    assert belongs("Subway Sandwiches", "subway")
    assert belongs("KFC / Taco Bell", "taco bell")
    assert not belongs("KFC / Taco Bell", "taco bell", anywhere=False)
    assert not belongs("Subwayz Deli", "subway")
    assert not belongs("Bell's Tacos", "taco bell")


@pytest.fixture
def db():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1 FROM chains"))
    except Exception:
        pytest.skip("database not available")
    with SessionLocal() as session:
        yield session
        session.rollback()


def test_locations_keep_their_own_menus_until_the_chain_menu_works(db):
    cid = db.scalar(text("SELECT id FROM cities WHERE slug = 'nyc'"))
    chain = db.scalar(
        text(
            "INSERT INTO chains (brand, name, domain, status) "
            "VALUES ('zzyzx test', 'Zzyzx Test', 'zzyzx.test', 'not_found') RETURNING id"
        )
    )
    rid = db.scalar(
        text(
            "INSERT INTO restaurants (city_id, source_id, name, website, active, chain_id) "
            "VALUES (:c, 'chain-test-1', 'Zzyzx Test #1', 'https://zzyzx.test/1', true, :ch) "
            "RETURNING id"
        ),
        {"c": cid, "ch": chain},
    )

    def candidate_ids():
        return {r.id for r in db.execute(CANDIDATES, {"cid": cid, "limit": 10_000_000})}

    assert rid in candidate_ids()
    db.execute(text("UPDATE chains SET status = 'ok' WHERE id = :id"), {"id": chain})
    assert rid not in candidate_ids()
