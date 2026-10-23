from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_REPORTS = 3
MIN_MEALS = 5

INGREDIENT_POINTS = {"fresh": 95, "mixed": 65, "processed": 30}
HEALTHY_POINTS = {"many": 95, "some": 65, "few": 30}
OIL_CHOICES = ("seed", "olive", "avocado", "animal")

OIL_LABELS = {
    "seed": "Seed oils (canola, soybean, vegetable…)",
    "olive": "Olive oil",
    "avocado": "Avocado oil",
    "animal": "Butter, ghee or tallow",
    "mixed": "A mix of oils",
}

# Points for a factor at full strength (level 1); level 0.5 earns half. Proportions follow the
# USDA Healthy Eating Index (HEI-2020) components each factor stands for.
MEAL_WEIGHTS = {
    "vegetables": 17.5,  # total vegetables 5 + greens 2.5 + total fruits 5 + whole fruits 5
    "whole_grains_legumes": 12.5,  # whole grains 10 + beans 2.5
    "healthy_protein": 10,  # total protein foods 5 + seafood and plant proteins 5
    "unsaturated_fats": 10,  # fatty acids 10
    "deep_fried": -15,  # refined grains 10 (batter, breading) + part of unprinted sodium
    "processed_meat": -7.5,  # part of sodium, which menus rarely print
    "added_sugar": -10,  # added sugars 10
    "saturated_fat": -10,  # saturated fats 10
}
SODIUM_WEIGHT = -10  # sodium 10, when the menu prints it
# Short or partial menus (e.g. a chain page listing only promo items) are pulled toward the
# average restaurant, as if PRIOR_MEALS average meals were added. PRIOR_RAW is that average.
PRIOR_MEALS = 6
PRIOR_RAW = 54.1
# Averaging many meals bunches restaurants between ~40 and ~70, so the average is stretched
# around a center (order unchanged). Tuned on all ~1,600 scored restaurants: average ~71,
# about a quarter scoring 80+.
CALIBRATION_CENTER = 46
CALIBRATION_STRETCH = 2.6
FACTOR_LABELS = {
    "vegetables": "Vegetables & fruit",
    "whole_grains_legumes": "Whole grains & legumes",
    "healthy_protein": "Healthy protein",
    "unsaturated_fats": "Unsaturated fats",
    "deep_fried": "Deep-fried",
    "processed_meat": "Processed meat",
    "added_sugar": "Added sugar",
    "saturated_fat": "Saturated fat",
}

LEVEL = "0 = absent or negligible, 0.5 = moderate part of the meal, 1 = substantial or main part"


class OilInfo(BaseModel):
    stated: Literal["seed", "olive", "avocado", "animal", "mixed", "not_stated"]
    evidence: str = Field(description="Verbatim menu quote naming the oil or fat, or empty.")


class Meal(BaseModel):
    name: str = Field(description="The dish name copied verbatim from the menu.")
    described: bool = Field(
        description="True if the menu lists its ingredients or preparation, not just a name."
    )
    vegetables: float = Field(description=f"Vegetables and fruit. {LEVEL}.")
    whole_grains_legumes: float = Field(
        description=f"Whole grains, beans, lentils, chickpeas. {LEVEL}."
    )
    healthy_protein: float = Field(
        description=f"Beans, lentils, tofu, fish, or lean unprocessed poultry or meat. {LEVEL}."
    )
    unsaturated_fats: float = Field(
        description=f"Nuts, seeds, avocado, olive oil or other stated unsaturated oils. {LEVEL}."
    )
    deep_fried: float = Field(description=f"Deep-fried main components or fried sides. {LEVEL}.")
    processed_meat: float = Field(
        description=f"Bacon, sausage, hot dogs, salami, deli meats. {LEVEL}."
    )
    added_sugar: float = Field(description=f"Sugary sauces, glazes, syrups. {LEVEL}.")
    saturated_fat: float = Field(
        description=f"Butter, ghee, tallow, cream, cheese, fatty red meat. {LEVEL}."
    )
    sodium_mg: int | None = Field(
        description="Sodium per serving in mg, only if the menu publishes it; otherwise null."
    )
    note: str = Field(description="Under 12 words: what makes this meal healthy or not.")


class MenuReport(BaseModel):
    is_restaurant_menu: bool
    cuisine: str = Field(description="Main cuisine in 1-3 words, e.g. 'Thai', 'Burgers'.")
    summary: str = Field(description="One or two plain sentences about how healthy the food is.")
    meals: list[Meal] = Field(
        description="Up to 25 representative main meals (entrees, mains, bowls, sandwiches, "
        "plates), including their default sides and sauces. Not desserts or drinks."
    )
    dessert_count: int = Field(description="Number of desserts and sweets on the menu.")
    sugary_drink_count: int = Field(description="Number of sweetened drinks, shakes, sodas.")
    oil: OilInfo
    quality_markers: list[str] = Field(
        description="Explicit menu claims such as organic, grass-fed, wild-caught, house-made, "
        "seed-oil free. Empty if none."
    )


def _level(value: float) -> float:
    return min((0.0, 0.5, 1.0), key=lambda option: abs(option - value))


def sodium_level(mg: int | None) -> float | None:
    if mg is None:
        return None
    if mg <= 600:
        return 0.0
    return 0.5 if mg <= 1000 else 1.0


def raw_meal_score(meal: Meal) -> float:
    s = 50.0 + sum(w * _level(getattr(meal, k)) for k, w in MEAL_WEIGHTS.items())
    sodium = sodium_level(meal.sodium_mg)
    if sodium is not None:
        s += SODIUM_WEIGHT * sodium
    return max(0.0, min(100.0, s))


def calibrate(raw: float) -> float:
    return 50 + (raw - CALIBRATION_CENTER) * CALIBRATION_STRETCH


def meal_score(meal: Meal) -> int:
    return max(1, min(100, round(calibrate(raw_meal_score(meal)))))


def menu_score(r: MenuReport) -> int | None:
    if not r.is_restaurant_menu or len(r.meals) < MIN_MEALS:
        return None
    total = sum(raw_meal_score(m) for m in r.meals) + PRIOR_MEALS * PRIOR_RAW
    mean = total / (len(r.meals) + PRIOR_MEALS)
    return max(5, min(100, 5 * round(calibrate(mean) / 5)))


def confidence(r: MenuReport) -> str:
    described = sum(m.described for m in r.meals) / max(len(r.meals), 1)
    if described >= 0.7 and len(r.meals) >= 8:
        return "high"
    return "medium" if described >= 0.4 else "low"


def breakdown(data: dict) -> dict | None:
    """Per-meal scores and summary figures for display; None for older analyses."""
    if "meals" not in data:
        return None
    report = MenuReport.model_validate(data)
    meals = sorted(
        ({"meal": m, "score": meal_score(m)} for m in report.meals),
        key=lambda x: x["score"],
        reverse=True,
    )
    good = sum(1 for m in meals if m["score"] >= 70)
    return {
        "meals": meals,
        "best": meals[:3],
        "worst": [m for m in meals[-3:][::-1] if m not in meals[:3]],
        "share_good": round(100 * good / len(meals)) if meals else 0,
        "confidence": confidence(report),
        "sodium_known": any(m.sodium_mg is not None for m in report.meals),
        "report": report,
    }


def report_score(ingredients: str | None, healthy: str | None) -> int | None:
    """Visitor report score. Cooking oil is recorded for information but not scored."""
    parts = [
        p
        for p in (INGREDIENT_POINTS.get(ingredients or ""), HEALTHY_POINTS.get(healthy or ""))
        if p is not None
    ]
    return round(sum(parts) / len(parts)) if parts else None


REFRESH_FOOD = """
WITH agg AS (
    SELECT restaurant_id, count(score) AS n, round(avg(score))::int AS score,
           mode() WITHIN GROUP (ORDER BY oil) FILTER (WHERE oil IS NOT NULL) AS oil,
           count(*) AS reports
    FROM food_reports GROUP BY restaurant_id
)
UPDATE restaurants r
SET food_reports_count = coalesce(agg.reports, 0),
    reported_oil = agg.oil,
    cuisine = coalesce(r.cuisine, r.osm_cuisine, ma.cuisine),
    food_score = CASE WHEN ma.score IS NULL OR ch.status = 'featured_only' THEN NULL
                      WHEN agg.n >= :min THEN round((ma.score + agg.score) / 2.0)
                      ELSE ma.score END,
    food_source = CASE WHEN ma.score IS NULL OR ch.status = 'featured_only' THEN NULL
                       WHEN agg.n >= :min THEN 'menu+reports'
                       ELSE 'menu' END
FROM restaurants r2
LEFT JOIN agg ON agg.restaurant_id = r2.id
LEFT JOIN menu_analyses ma ON ma.restaurant_id = r2.id
LEFT JOIN chains ch ON ch.id = r2.chain_id
WHERE r.id = r2.id AND {where}
"""


def refresh_food(session: Session, city_id: int | None = None, restaurant_id: int | None = None):
    if restaurant_id is not None:
        sql, params = REFRESH_FOOD.format(where="r.id = :rid"), {"rid": restaurant_id}
    else:
        sql, params = REFRESH_FOOD.format(where="r.city_id = :cid"), {"cid": city_id}
    session.execute(text(sql), {**params, "min": MIN_REPORTS})
