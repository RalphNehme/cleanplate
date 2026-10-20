from types import SimpleNamespace

from bs4 import BeautifulSoup

from app.food import MenuReport, breakdown, meal_score, menu_score, report_score
from pipeline.analyze import json_schema, parse_message
from pipeline.menus import Fetcher, choose, menu_links, menu_signal

FACTORS = (
    "vegetables",
    "whole_grains_legumes",
    "healthy_protein",
    "unsaturated_fats",
    "deep_fried",
    "processed_meat",
    "added_sugar",
    "saturated_fat",
)


def meal(name="Dish", sodium_mg=None, described=True, **levels):
    return {
        "name": name,
        "described": described,
        **{f: levels.get(f, 0) for f in FACTORS},
        "sodium_mg": sodium_mg,
        "note": "",
    }


SALAD = meal(
    "Kale salad", vegetables=1, whole_grains_legumes=0.5, healthy_protein=1, unsaturated_fats=0.5
)
BURGER = meal("Cheeseburger & fries", deep_fried=0.5, saturated_fat=1)
PLAIN = meal("Plain plate")


def report(**kw) -> MenuReport:
    base = {
        "is_restaurant_menu": True,
        "cuisine": "Mediterranean",
        "summary": "",
        "meals": [PLAIN] * 5,
        "dessert_count": 0,
        "sugary_drink_count": 0,
        "oil": {"stated": "not_stated", "evidence": ""},
        "quality_markers": [],
    }
    return MenuReport.model_validate({**base, **kw})


def meal_of(**kw):
    return report(meals=[meal(**kw)] * 5).meals[0]


def test_meal_scores_follow_the_formula_on_the_calibrated_scale():
    assert meal_score(report(meals=[SALAD] * 5).meals[0]) == 100
    assert meal_score(meal_of()) == 70
    assert meal_score(report(meals=[BURGER] * 5).meals[0]) == 30


def test_levels_snap_to_zero_half_or_one():
    assert meal_score(meal_of(vegetables=0.3)) == meal_score(meal_of(vegetables=0.5))


def test_sodium_counts_only_when_published():
    assert meal_score(meal_of(sodium_mg=500)) == 70
    assert meal_score(meal_of(sodium_mg=700)) == 55
    assert meal_score(meal_of(sodium_mg=1200)) == 40


def test_restaurant_score_averages_meals_and_rounds_to_five():
    assert menu_score(report()) == 70
    assert menu_score(report(meals=[SALAD, BURGER, PLAIN, PLAIN, PLAIN])) == 80


def test_oil_and_claims_do_not_change_the_score():
    seed = report(oil={"stated": "seed", "evidence": "fried in canola"})
    tallow = report(oil={"stated": "animal", "evidence": "beef tallow"}, quality_markers=["local"])
    assert menu_score(seed) == menu_score(tallow) == menu_score(report())


def test_menu_score_skips_non_menus_and_tiny_menus():
    assert menu_score(report(is_restaurant_menu=False)) is None
    assert menu_score(report(meals=[PLAIN] * 4)) is None


def test_breakdown_ranks_meals_and_reports_confidence():
    b = breakdown(report(meals=[BURGER, SALAD, PLAIN, PLAIN, PLAIN]).model_dump())
    names = [m["meal"].name for m in b["meals"]]
    assert names[0] == "Kale salad" and names[-1] == "Cheeseburger & fries"
    assert b["share_good"] == 80
    assert b["confidence"] == "medium"
    assert breakdown({"summary": "old format"}) is None


def test_report_score_ignores_cooking_oil():
    assert report_score("fresh", "many") == 95
    assert report_score("processed", None) == 30
    assert report_score(None, None) is None


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


def test_make_client_uses_env_file_key_and_drops_empty_env_key(monkeypatch):
    from pipeline import analyze

    monkeypatch.setattr(analyze.settings, "anthropic_api_key", "sk-test")
    assert analyze.make_client().api_key == "sk-test"

    monkeypatch.setattr(analyze.settings, "anthropic_api_key", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "token-from-login")
    analyze.make_client()
    assert "ANTHROPIC_API_KEY" not in analyze.os.environ


def test_clean_strips_nul_bytes():
    from pipeline.menus import _clean

    assert _clean("menu\x00 text") == "menu text"
    assert _clean(None) is None
