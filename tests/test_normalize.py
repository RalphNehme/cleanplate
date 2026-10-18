import pytest

from pipeline.normalize import clean_text, nyc_hygiene, points_to_score, rating, title_name


@pytest.mark.parametrize(
    ("points", "expected"),
    [(0, 100), (13, 85), (14, 84), (27, 70), (28, 69), (100, 1), (250, 1), (-3, 100)],
)
def test_points_to_score_lines_up_with_nyc_grades(points, expected):
    assert points_to_score(points) == expected


def test_scores_never_increase_with_more_points():
    scores = [points_to_score(p) for p in range(150)]
    assert scores == sorted(scores, reverse=True)


def test_nyc_hygiene_caps_closures():
    assert nyc_hygiene(None, None) is None
    assert nyc_hygiene(10, "Violations were cited.") == points_to_score(10)
    assert nyc_hygiene(10, "Establishment Closed by DOHMH. Violations were cited.") == 30
    assert nyc_hygiene(0, "Establishment re-opened by DOHMH.") == 100


@pytest.mark.parametrize(
    ("score", "expected"),
    [(100, "good"), (85, "good"), (84, "ok"), (70, "ok"), (69, "concerning"), (None, None)],
)
def test_rating(score, expected):
    assert rating(score) == expected


def test_clean_text():
    assert clean_text("  A   B ") == "A B"
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_title_name():
    assert title_name("JOE'S PIZZA") == "Joe's Pizza"
    assert title_name("McDonald's") == "McDonald's"
    assert title_name("EL CASTILLO DE JAGUA II") == "El Castillo De Jagua II"
    assert title_name("BAKERY ON 3RD CAFE") == "Bakery On 3rd Cafe"
