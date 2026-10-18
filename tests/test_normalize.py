import pytest

from pipeline.normalize import clean_text, nyc_rating, title_name


@pytest.mark.parametrize(
    ("score", "grade", "action", "expected"),
    [
        (5, "A", None, "good"),
        (20, "B", None, "ok"),
        (40, "C", None, "concerning"),
        (10, None, None, "good"),
        (27, "Z", None, "ok"),
        (30, None, None, "concerning"),
        (None, None, None, None),
        (10, "A", "Establishment Closed by DOHMH. Violations were cited.", "concerning"),
        (0, None, "Establishment re-opened by DOHMH.", "good"),
    ],
)
def test_nyc_rating(score, grade, action, expected):
    assert nyc_rating(score, grade, action) == expected


def test_clean_text():
    assert clean_text("  A   B ") == "A B"
    assert clean_text("   ") is None
    assert clean_text(None) is None


def test_title_name():
    assert title_name("JOE'S PIZZA") == "Joe's Pizza"
    assert title_name("McDonald's") == "McDonald's"
    assert title_name("EL CASTILLO DE JAGUA II") == "El Castillo De Jagua II"
    assert title_name("BAKERY ON 3RD CAFE") == "Bakery On 3rd Cafe"
