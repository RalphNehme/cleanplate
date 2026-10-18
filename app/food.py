import re

from sqlalchemy import text
from sqlalchemy.orm import Session

MIN_REPORTS = 3
DEFAULT_ESTIMATE = 52

# (pattern, estimated food score, cuisine label). First match wins; chains come first.
RULES = [
    (r"sweetgreen|just salad|chopt|\bdig\b|salad", 86, "Salads"),
    (r"juice|smoothie|acai|açaí", 84, "Juice, Smoothies"),
    (r"\bpoke\b", 82, "Hawaiian"),
    (r"vegan|vegetarian|plant.based", 84, "Vegetarian"),
    (r"\bcava\b", 80, "Mediterranean"),
    (
        r"mcdonald|burger king|wendy'?s|white castle|jack in the box|checkers|sonic drive|"
        r"five guys|shake shack|smashburger",
        30,
        "Hamburgers",
    ),
    (
        r"popeyes|\bkfc\b|kentucky fried|church'?s chicken|raising cane|wingstop|chick.fil.a",
        28,
        "Chicken",
    ),
    (r"taco bell", 32, "Tex-Mex"),
    (r"domino'?s|papa john|little caesar|pizza hut", 33, "Pizza"),
    (r"dunkin|krispy kreme|donut|doughnut", 28, "Donuts"),
    (r"subway|jimmy john|jersey mike|potbelly|panera", 50, "Sandwiches"),
    (r"chipotle", 58, "Mexican"),
    (
        r"mediterranean|greek|lebanese|middle eastern|turkish|falafel|israeli|moroccan|persian|"
        r"afghan|gyro",
        76,
        "Mediterranean",
    ),
    (r"sushi|omakase", 76, "Japanese"),
    (r"ramen", 52, "Japanese"),
    (r"japanese", 72, "Japanese"),
    (r"vietnamese|\bpho\b|banh mi", 72, "Vietnamese"),
    (r"ethiopian", 72, "Ethiopian"),
    (r"korean", 66, "Korean"),
    (r"spanish|tapas", 68, "Spanish"),
    (r"seafood|fish|oyster", 68, "Seafood"),
    (r"peruvian", 62, "Peruvian"),
    (r"steak", 60, "Steakhouse"),
    (r"italian|trattoria|osteria|pasta", 60, "Italian"),
    (r"french|bistro|brasserie", 58, "French"),
    (r"\bthai\b", 58, "Thai"),
    (r"indian|tandoor|curry|masala", 56, "Indian"),
    (r"coffee|cafe|café|\btea\b|espresso", 62, "Coffee/Tea"),
    (r"taco|taqueria|burrito|mexican|tex.mex", 52, "Mexican"),
    (r"latin|cuban|colombian|salvadoran|dominican|puerto ric", 52, "Latin American"),
    (r"caribbean|jamaican|haitian|trinidad", 50, "Caribbean"),
    (r"filipino", 50, "Filipino"),
    (r"chinese|wok|dumpling|szechuan|sichuan|hunan|cantonese", 48, "Chinese"),
    (r"deli\b|delicatessen|sandwich|sub shop|hero", 52, "Sandwiches"),
    (r"bagel", 48, "Bagels"),
    (r"bbq|barbecue|barbeque|smokehouse", 46, "Barbecue"),
    (r"soul food", 40, "Soul Food"),
    (r"pizza|pizzeria", 42, "Pizza"),
    (r"burger|hamburger", 36, "Hamburgers"),
    (r"chicken|wings|fried", 32, "Chicken"),
    (r"hot ?dog|hotdog", 32, "Hotdogs"),
    (
        r"bakery|pastr|dessert|cake|cookie|ice cream|gelato|frozen|creamery|sweets",
        36,
        "Bakery/Desserts",
    ),
    (r"\bbar\b|tavern|\bpub\b|lounge|saloon|brewery", 44, "Bar"),
    (r"american|diner|grill", 50, "American"),
]
COMPILED = [(re.compile(p, re.I), s, c) for p, s, c in RULES]

OIL_POINTS = {"seed": 20, "olive": 95, "avocado": 95, "animal": 85}
INGREDIENT_POINTS = {"fresh": 95, "mixed": 65, "processed": 30}
HEALTHY_POINTS = {"many": 95, "some": 65, "few": 30}
WEIGHTS = {"oil": 0.5, "ingredients": 0.3, "healthy": 0.2}

OIL_LABELS = {
    "seed": "Seed oils (canola, soybean, vegetable…)",
    "olive": "Olive oil",
    "avocado": "Avocado oil",
    "animal": "Butter, ghee or tallow",
}


CHAINS = COMPILED[:12]


def _match(cuisine: str | None, name: str):
    for rules, text_ in ((CHAINS, name), (COMPILED, cuisine), (COMPILED, name)):
        if text_:
            for pattern, score, label in rules:
                if pattern.search(text_):
                    return score, label
    return None


def infer_cuisine(name: str) -> str | None:
    m = _match(None, name)
    return m[1] if m else None


def estimate(cuisine: str | None, name: str) -> int:
    m = _match(cuisine, name)
    return m[0] if m else DEFAULT_ESTIMATE


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
    food_score = CASE WHEN agg.n >= :min THEN agg.score ELSE r.food_estimate END,
    food_source = CASE WHEN agg.n >= :min THEN 'reports'
                       WHEN r.food_estimate IS NOT NULL THEN 'estimate' END
FROM restaurants r2
LEFT JOIN agg ON agg.restaurant_id = r2.id
WHERE r.id = r2.id AND {where}
"""


def refresh_food(session: Session, city_id: int | None = None, restaurant_id: int | None = None):
    if restaurant_id is not None:
        sql, params = REFRESH_FOOD.format(where="r.id = :rid"), {"rid": restaurant_id}
    else:
        sql, params = REFRESH_FOOD.format(where="r.city_id = :cid"), {"cid": city_id}
    session.execute(text(sql), {**params, "min": MIN_REPORTS})
