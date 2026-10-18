import re

GOOD, OK, CONCERNING = "good", "ok", "concerning"
CLOSED_CAP = 30


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def title_name(value: str) -> str:
    if not (value.isupper() or value.islower()):
        return value
    value = value.title()
    value = re.sub(r"(?<=[A-Za-z])'S\b", "'s", value)
    value = re.sub(r"(?<=\d)(St|Nd|Rd|Th)\b", lambda m: m[1].lower(), value)
    return re.sub(r"\b(Ii|Iii|Iv|Vi|Vii|Viii|Ix|Nyc|Bbq|Usa)\b", lambda m: m[1].upper(), value)


def points_to_score(points: int) -> int:
    """Violation points (0 = perfect) to a 1-100 score aligned with NYC grades:
    A (0-13) -> 85-100, B (14-27) -> 70-84, C (28+) -> below 70."""
    p = max(points, 0)
    if p <= 13:
        s = 100 - p * 15 / 13
    elif p <= 27:
        s = 85 - (p - 13) * 15 / 14
    else:
        s = 70 - (p - 27) * 69 / 73
    return max(1, min(100, round(s)))


def rating(score: int | None) -> str | None:
    if score is None:
        return None
    if score >= 85:
        return GOOD
    if score >= 70:
        return OK
    return CONCERNING


def nyc_hygiene(points: int | None, action: str | None) -> int | None:
    if points is None:
        return None
    score = points_to_score(points)
    act = (action or "").lower()
    if "closed by dohmh" in act and "re-opened" not in act:
        score = min(score, CLOSED_CAP)
    return score
