import pytest

from app.food import DEFAULT_ESTIMATE, estimate, infer_cuisine, report_score


@pytest.mark.parametrize(
    ("cuisine", "name", "expected"),
    [
        ("American", "McDonald's", 30),
        ("Salads", "Green Leaf", 86),
        ("Italian", "Bar Pitti", 60),
        (None, "Taqueria El Sol", 52),
        (None, "Golden Wok", 48),
        (None, "Smith & Sons", DEFAULT_ESTIMATE),
    ],
)
def test_estimate(cuisine, name, expected):
    assert estimate(cuisine, name) == expected


def test_infer_cuisine():
    assert infer_cuisine("Lou Malnati's Pizzeria") == "Pizza"
    assert infer_cuisine("Smith & Sons") is None


def test_report_score_penalizes_seed_oils():
    assert report_score("olive", "fresh", "many") == 95
    assert report_score("seed", "fresh", "many") == 58
    assert report_score("seed", None, None) == 20
    assert report_score(None, "processed", "few") == 30
    assert report_score(None, None, None) is None
