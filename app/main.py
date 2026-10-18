from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BeforeValidator
from sqlalchemy.orm import Session

from app import queries
from app.db import get_session

BASE = Path(__file__).parent
app = FastAPI(title="CleanPlate")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

DB = Annotated[Session, Depends(get_session)]
Coord = Annotated[float | None, BeforeValidator(lambda v: v or None)]


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: DB):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "options": queries.options(db),
            "results": queries.search(db),
        },
    )


@app.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    db: DB,
    q: str = "",
    borough: str | None = None,
    cuisine: str | None = None,
    grade: str | None = None,
    lat: Coord = None,
    lon: Coord = None,
):
    results = queries.search(db, q.strip(), borough, cuisine, grade, lat, lon)
    return templates.TemplateResponse(request, "partials/results.html", {"results": results})


@app.get("/r/{rid}", response_class=HTMLResponse)
def restaurant_page(request: Request, rid: int, db: DB):
    r = queries.restaurant(db, rid)
    if not r:
        raise HTTPException(404)
    history = [
        {"date": i.inspected_at.isoformat(), "score": i.raw_score}
        for i in reversed(r.inspections)
        if i.raw_score is not None
    ]
    return templates.TemplateResponse(
        request,
        "restaurant.html",
        {
            "r": r,
            "history": history,
            "coords": queries.coords(db, rid),
            "city": queries.city(db),
        },
    )


@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, db: DB):
    return templates.TemplateResponse(request, "stats.html", {"s": queries.stats(db)})


@app.get("/api/points")
def api_points(
    db: DB, borough: str | None = None, cuisine: str | None = None, grade: str | None = None
):
    return JSONResponse(
        queries.points(db, borough, cuisine, grade),
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/api/search")
def api_search(
    db: DB,
    q: str = "",
    borough: str | None = None,
    cuisine: str | None = None,
    grade: str | None = None,
    lat: Coord = None,
    lon: Coord = None,
):
    return queries.search(db, q.strip(), borough, cuisine, grade, lat, lon)


@app.get("/api/restaurants/{rid}")
def api_restaurant(rid: int, db: DB):
    r = queries.restaurant(db, rid)
    if not r:
        raise HTTPException(404)
    return {
        "id": r.id,
        "name": r.name,
        "address": r.address,
        "borough": r.borough,
        "zip": r.zip,
        "cuisine": r.cuisine,
        "phone": r.phone,
        "grade": r.latest_grade,
        "score": r.latest_score,
        "rating": r.latest_rating,
        "inspections": [
            {
                "date": i.inspected_at,
                "type": i.type,
                "score": i.raw_score,
                "grade": i.raw_grade,
                "rating": i.rating,
                "action": i.action,
                "violations": [
                    {"code": v.code, "description": v.description, "critical": v.critical}
                    for v in i.violations
                ],
            }
            for i in r.inspections
        ],
    }


@app.get("/api/stats")
def api_stats(db: DB):
    return queries.stats(db)
