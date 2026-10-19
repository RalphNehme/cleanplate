from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.food import MenuReport, menu_score, report_score
from pipeline.analyze import json_schema, parse_message
from pipeline.menus import Fetcher, choose, menu_links, menu_signal


def report(**kw) -> MenuReport:
    base = {
        "is_restaurant_menu": True,
        "cuisine": "Mediterranean",
        "item_count": 30,
        "fried_share": 0.0,
        "whole_food_share": 0.0,
        "ultra_processed_share": 0.0,
        "vegetable_forward_share": 0.0,
        "sweets_share": 0.0,
        "quality_markers": [],
        "oil": {"stated": "not_stated", "evidence": ""},
        "highlights": [],
        "summary": "",
    }
    return MenuReport.model_validate({**base, **kw})


def test_menu_score_rewards_whole_foods_and_named_good_fats():
    healthy = report(
        whole_food_share=0.8,
        vegetable_forward_share=0.6,
        quality_markers=["organic", "wild-caught", "house-made"],
        oil={"stated": "olive", "evidence": "extra virgin olive oil"},
    )
    assert menu_score(healthy) == 98


def test_menu_score_penalizes_fried_processed_and_seed_oil():
    junk = report(fried_share=0.7, ultra_processed_share=0.6, sweets_share=0.3)
    assert menu_score(junk) == 12
    seed = report(oil={"stated": "seed", "evidence": "fried in canola oil"})
    assert menu_score(seed) == 35


def test_menu_score_skips_non_menus():
    assert menu_score(report(is_restaurant_menu=False)) is None
    assert menu_score(report(item_count=2)) is None


def test_shares_are_clamped():
    assert menu_score(report(whole_food_share=4.0)) == 80


def test_report_score_penalizes_seed_oils():
    assert report_score("olive", "fresh", "many") == 95
    assert report_score("seed", None, None) == 20
    assert report_score(None, None, None) is None


def test_menu_links_skip_social_delivery_and_reservations():
    soup = BeautifulSoup(
        """
        <a href="/menu">Menu</a>
        <a href="https://www.ubereats.com/store/x">Order</a>
        <a href="https://instagram.com/x">Menu on Instagram</a>
        <a href="/reservations">Book dinner</a>
        <a href="https://other.example.com/dinner-menu.pdf">Dinner menu</a>
        """,
        "html.parser",
    )
    assert menu_links(soup, "https://www.example.com/") == [
        "https://www.example.com/menu",
        "https://other.example.com/dinner-menu.pdf",
    ]


def test_choose_requires_menu_like_text():
    menu = "\n".join(f"Grilled chicken salad with avocado $12.{i:02d}" for i in range(10))
    assert menu_signal(menu) >= 30
    assert choose([("https://a/menu", menu)], "https://a", []).status == "ok"
    miss = choose([("https://a", "Welcome! Book a table.")], "https://a", ["https://a"])
    assert miss.status == "not_found" and miss.render == ["https://a"]


def test_delivery_sites_are_never_fetched():
    assert not Fetcher().allowed("https://www.doordash.com/store/123")


def test_json_schema_is_strict():
    schema = json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["$defs"]["OilInfo"]["additionalProperties"] is False


def test_parse_message_handles_refusals_and_bad_json():
    good = report().model_dump_json()
    ok = SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=good)])
    assert parse_message(ok).cuisine == "Mediterranean"
    refused = SimpleNamespace(stop_reason="refusal", content=[])
    assert parse_message(refused) is None
    broken = SimpleNamespace(
        stop_reason="end_turn", content=[SimpleNamespace(type="text", text="{oops")]
    )
    assert parse_message(broken) is None
