from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_REPORTS = 3

OIL_POINTS = {"seed": 20, "olive": 95, "avocado": 95, "animal": 85}
INGREDIENT_POINTS = {"fresh": 95, "mixed": 65, "processed": 30}
HEALTHY_POINTS = {"many": 95, "some": 65, "few": 30}
WEIGHTS = {"oil": 0.5, "ingredients": 0.3, "healthy": 0.2}

OIL_LABELS = {
    "seed": "Seed oils (canola, soybean, vegetable…)",
    "olive": "Olive oil",
    "avocado": "Avocado oil",
    "animal": "Butter, ghee or tallow",
    "mixed": "A mix of oils",
}


class OilInfo(BaseModel):
    stated: Literal["seed", "olive", "avocado", "animal", "mixed", "not_stated"]
    evidence: str = Field(description="Verbatim menu quote naming the oil or fat, or empty.")


class Highlight(BaseModel):
    quote: str = Field(description="Verbatim text copied from the menu, under 120 characters.")
    effect: Literal["positive", "negative"]
    reason: str = Field(description="Under 12 words: why this helps or hurts the food score.")


class MenuReport(BaseModel):
    is_restaurant_menu: bool
    cuisine: str = Field(description="Main cuisine in 1-3 words, e.g. 'Thai', 'Burgers'.")
    item_count: int
    fried_share: float = Field(description="0-1: share of savory items deep-fried or battered.")
    whole_food_share: float = Field(
        description="0-1: share of items built mainly from minimally processed ingredients."
    )
    ultra_processed_share: float = Field(
        description="0-1: share of items centered on processed meats, pre-made, frozen or "
        "refined-flour-heavy foods, or sugary drinks."
    )
    vegetable_forward_share: float = Field(
        description="0-1: share of items where vegetables or legumes are a main component."
    )
    sweets_share: float = Field(description="0-1: share of items that are desserts or sweets.")
    quality_markers: list[str] = Field(
        description="Explicit menu claims such as organic, grass-fed, wild-caught, "
        "pasture-raised, house-made, scratch-made, local, seed-oil free. Empty if none."
    )
    oil: OilInfo
    highlights: list[Highlight] = Field(description="Up to 6 quotes that drive the score.")
    summary: str = Field(description="One or two plain sentences about the food's quality.")


def _share(value: float) -> float:
    return max(0.0, min(1.0, value))


def menu_score(r: MenuReport) -> int | None:
    if not r.is_restaurant_menu or r.item_count < 3:
        return None
    s = 50.0
    s += 30 * _share(r.whole_food_share)
    s += 10 * _share(r.vegetable_forward_share)
    s -= 25 * _share(r.fried_share)
    s -= 20 * _share(r.ultra_processed_share)
    s -= 10 * _share(r.sweets_share)
    s += min(10.0, 2.5 * len(r.quality_markers))
    if r.oil.stated in ("olive", "avocado", "animal"):
        s += 10
    elif r.oil.stated == "seed":
        s -= 15
    elif r.oil.stated == "not_stated" and r.fried_share > 0.2:
        s -= 5
    return max(1, min(100, round(s)))


def likely_seed_oil(r: dict) -> bool:
    return r["oil"]["stated"] == "not_stated" and r["fried_share"] > 0.2


def report_score(oil: str | None, ingredients: str | None, healthy: str | None) -> int | None:
    parts = [
        (OIL_POINTS.get(oil or ""), WEIGHTS["oil"]),
        (INGREDIENT_POINTS.get(ingredients or ""), WEIGHTS["ingredients"]),
        (HEALTHY_POINTS.get(healthy or ""), WEIGHTS["healthy"]),
    ]
    parts = [(p, w) for p, w in parts if p is not None]
    if not parts:
        return None
    return round(sum(p * w for p, w in parts) / sum(w for _, w in parts))


REFRESH_FOOD = """
WITH agg AS (
    SELECT restaurant_id, count(*) AS n, round(avg(score))::int AS score,
           mode() WITHIN GROUP (ORDER BY oil) FILTER (WHERE oil IS NOT NULL) AS oil
    FROM food_reports GROUP BY restaurant_id
)
UPDATE restaurants r
SET food_reports_count = coalesce(agg.n, 0),
    reported_oil = agg.oil,
    cuisine = coalesce(r.cuisine, r.osm_cuisine, ma.cuisine),
    food_score = CASE WHEN ma.score IS NULL THEN NULL
                      WHEN agg.n >= :min THEN round((ma.score + agg.score) / 2.0)
                      ELSE ma.score END,
    food_source = CASE WHEN ma.score IS NULL THEN NULL
                       WHEN agg.n >= :min THEN 'menu+reports'
                       ELSE 'menu' END
FROM restaurants r2
LEFT JOIN agg ON agg.restaurant_id = r2.id
LEFT JOIN menu_analyses ma ON ma.restaurant_id = r2.id
WHERE r.id = r2.id AND {where}
"""


def refresh_food(session: Session, city_id: int | None = None, restaurant_id: int | None = None):
    if restaurant_id is not None:
        sql, params = REFRESH_FOOD.format(where="r.id = :rid"), {"rid": restaurant_id}
    else:
        sql, params = REFRESH_FOOD.format(where="r.city_id = :cid"), {"cid": city_id}
    session.execute(text(sql), {**params, "min": MIN_REPORTS})
