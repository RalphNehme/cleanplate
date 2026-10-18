import re

GOOD, OK, CONCERNING = "good", "ok", "concerning"


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


def nyc_rating(score: int | None, grade: str | None, action: str | None) -> str | None:
    if action and "closed by dohmh" in action.lower() and "re-opened" not in action.lower():
        return CONCERNING
    if grade in ("A", "B", "C"):
        return {"A": GOOD, "B": OK, "C": CONCERNING}[grade]
    if score is None:
        return None
    if score <= 13:
        return GOOD
    if score <= 27:
        return OK
    return CONCERNING
