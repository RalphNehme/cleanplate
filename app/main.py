import hashlib
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BeforeValidator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import food, queries
from app.config import settings
from app.db import get_session
from app.models import City, FoodReport

BASE = Path(__file__).parent
app = FastAPI(title="CleanPlate")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

DB = Annotated[Session, Depends(get_session)]
Coord = Annotated[float | None, BeforeValidator(lambda v: v or None)]


def band(score: int | None) -> dict:
    if score is None:
        return {"key": "none", "label": "No score yet"}
    if score >= 90:
        return {"key": "excellent", "label": "Excellent"}
    if score >= 85:
        return {"key": "good", "label": "Good"}
    if score >= 70:
        return {"key": "fair", "label": "Fair"}
    return {"key": "poor", "label": "Poor"}


templates.env.globals.update(
    band=band,
    oil_labels=food.OIL_LABELS,
    min_reports=food.MIN_REPORTS,
    breakdown=food.breakdown,
    factor_labels=food.FACTOR_LABELS,
)


def get_city(slug: str, db: DB) -> City:
    c = queries.city(db, slug)
    if not c:
        raise HTTPException(404)
    return c


CityDep = Annotated[City, Depends(get_city)]


class Filters:
    def __init__(
        self,
        area: str | None = None,
        cuisine: str | None = None,
        hygiene: str | None = None,
        food: str | None = None,
        oil: str | None = None,
    ):
        self.values = {
            "area": area or None,
            "cuisine": cuisine or None,
            "hygiene": hygiene or None,
            "food": food or None,
            "oil": oil or None,
        }


FiltersDep = Annotated[Filters, Depends()]


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: DB):
    return templates.TemplateResponse(request, "home.html", {"cards": queries.city_cards(db)})


@app.get("/scores", response_class=HTMLResponse)
def scores_page(request: Request, db: DB):
    return templates.TemplateResponse(
        request,
        "scores.html",
        {
            "weights": food.MEAL_WEIGHTS,
            "factor_labels": food.FACTOR_LABELS,
            "sodium_weight": food.SODIUM_WEIGHT,
            "center": food.CALIBRATION_CENTER,
            "stretch": food.CALIBRATION_STRETCH,
            "prior_meals": food.PRIOR_MEALS,
        },
    )


@app.get("/r/{rid}", response_class=HTMLResponse)
def restaurant_page(request: Request, rid: int, db: DB):
    r = queries.restaurant(db, rid)
    if not r:
        raise HTTPException(404)
    history = [
        {"date": i.inspected_at.isoformat(), "score": i.hygiene_score}
        for i in reversed(r.inspections)
        if i.hygiene_score is not None
    ]
    return templates.TemplateResponse(
        request,
        "restaurant.html",
        {"r": r, "city": r.city, "history": history, "coords": queries.coords(db, rid)},
    )


@app.post("/r/{rid}/report", response_class=HTMLResponse)
def submit_report(
    request: Request,
    rid: int,
    db: DB,
    oil: Annotated[str, Form()] = "",
    ingredients: Annotated[str, Form()] = "",
    healthy: Annotated[str, Form()] = "",
):
    r = queries.restaurant(db, rid)
    if not r:
        raise HTTPException(404)
    oil = oil if oil in food.OIL_CHOICES else None
    ingredients = ingredients if ingredients in food.INGREDIENT_POINTS else None
    healthy = healthy if healthy in food.HEALTHY_POINTS else None
    score = food.report_score(ingredients, healthy)
    message = "Thanks! Your report was added."
    if score is None and oil is None:
        message = "Pick at least one answer before submitting."
    else:
        ip = request.client.host if request.client else ""
        digest = hashlib.sha256(
            f"{settings.report_salt}|{ip}|{rid}|{date.today()}".encode()
        ).hexdigest()
        duplicate = db.scalar(
            select(FoodReport.id).where(
                FoodReport.restaurant_id == rid, FoodReport.reporter_hash == digest
            )
        )
        if duplicate:
            message = "You already reported on this restaurant today."
        else:
            db.add(
                FoodReport(
                    restaurant_id=rid,
                    oil=oil,
                    ingredients=ingredients,
                    healthy_options=healthy,
                    score=score,
                    reporter_hash=digest,
                )
            )
            db.flush()
            food.refresh_food(db, restaurant_id=rid)
            db.commit()
            db.refresh(r)
    return templates.TemplateResponse(request, "partials/food.html", {"r": r, "message": message})


@app.get("/api/cities")
def api_cities(db: DB):
    return [
        {
            "slug": c["city"].slug,
            "name": c["city"].name,
            "restaurants": c.get("restaurants"),
            "avg_food": c.get("avg_food"),
        }
        for c in queries.city_cards(db)
    ]


@app.get("/api/restaurants/{rid}")
def api_restaurant(rid: int, db: DB):
    r = queries.restaurant(db, rid)
    if not r:
        raise HTTPException(404)
    return {
        "id": r.id,
        "city": r.city.slug,
        "name": r.name,
        "address": r.address,
        "area": r.borough or r.zip,
        "cuisine": r.cuisine,
        "phone": r.phone,
        "hygiene_score": r.hygiene_score,
        "food_score": r.food_score,
        "food_source": r.food_source,
        "food_reports": r.food_reports_count,
        "reported_oil": r.reported_oil,
        "menu": (
            {
                "url": r.menu.url,
                "analyzed_at": r.analysis.analyzed_at,
                "model": r.analysis.model,
                "menu_score": r.analysis.score,
                "report": r.analysis.data,
            }
            if r.analysis and r.menu
            else None
        ),
        "official": r.latest_grade,
        "inspections": [
            {
                "date": i.inspected_at,
                "type": i.type,
                "hygiene_score": i.hygiene_score,
                "official": i.raw_grade,
                "official_points": i.raw_score,
                "result": i.action,
                "violations": [
                    {"code": v.code, "description": v.description, "critical": v.critical}
                    for v in i.violations
                ],
            }
            for i in r.inspections
        ],
    }


@app.get("/api/{slug}/points")
def api_points(city: CityDep, db: DB, f: FiltersDep):
    return JSONResponse(
        queries.points(db, city.id, **f.values),
        headers={"Cache-Control": "public, max-age=600"},
    )


@app.get("/api/{slug}/search")
def api_search(
    city: CityDep, db: DB, f: FiltersDep, q: str = "", lat: Coord = None, lon: Coord = None
):
    return queries.search(db, city.id, q.strip(), lat, lon, **f.values)


@app.get("/api/{slug}/stats")
def api_stats(city: CityDep, db: DB):
    return queries.stats(db, city.id)


@app.get("/{slug}", response_class=HTMLResponse)
def city_page(request: Request, city: CityDep, db: DB):
    return templates.TemplateResponse(
        request,
        "city.html",
        {
            "city": city,
            "options": queries.options(db, city.id),
            "results": queries.search(db, city.id),
        },
    )


@app.get("/{slug}/search", response_class=HTMLResponse)
def city_search(
    request: Request,
    city: CityDep,
    db: DB,
    f: FiltersDep,
    q: str = "",
    lat: Coord = None,
    lon: Coord = None,
):
    results = queries.search(db, city.id, q.strip(), lat, lon, **f.values)
    return templates.TemplateResponse(request, "partials/results.html", {"results": results})


@app.get("/{slug}/stats", response_class=HTMLResponse)
def city_stats(request: Request, city: CityDep, db: DB):
    return templates.TemplateResponse(
        request, "stats.html", {"city": city, "s": queries.stats(db, city.id)}
    )
