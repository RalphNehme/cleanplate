# CleanPlate

How clean is that restaurant? CleanPlate gives every restaurant in New York City and Chicago two scores from 1 to 100, where higher is better: a **hygiene score** built from official health inspections and a **food score** for how healthy the food is.

**Stack:** Python · FastAPI · PostgreSQL + PostGIS · SQLAlchemy · Alembic · HTMX · MapLibre GL · Chart.js · Docker · GitHub Actions

## Features
- City picker homepage, then a map, search and stats page for each city (~31,000 NYC and ~9,400 open Chicago restaurants)
- Vector map (MapLibre + OpenFreeMap) with clusters colored by their average hygiene score
- **Hygiene score:** NYC violation points and Chicago violation severity converted to one 1–100 scale, with the official grade (A/B/C or Pass/Fail) shown alongside
- **Food score:** estimated from cuisine and name until 3 visitors report on cooking oil, ingredients and healthy options. Seed oils lower the score.
- Fuzzy name search (Postgres trigram index), filters for area, cuisine, hygiene and food bands, and "no seed oils"
- "Near me" via PostGIS distance queries
- Restaurant pages with hygiene history, every violation cited and a visitor report form
- JSON API: `/api/cities`, `/api/{city}/search`, `/api/{city}/points`, `/api/{city}/stats`, `/api/restaurants/{id}`

See [How scores work](app/templates/scores.html) (served at `/scores`) for the exact formulas.

## How it works
```
NYC Open Data ──► pipeline/adapters/nyc.py ─┐
                                             ├─► pipeline/load.py ──► Postgres + PostGIS
Chicago Data  ──► pipeline/adapters/chicago.py┘   upserts, scores,          │
                                                   food estimates            ▼
                                                              FastAPI (app/) ──► pages + JSON API
```
Each city is a small adapter that outputs the same normalized records with a 1–100 hygiene score, so adding a city doesn't touch the database or the website.

## Run locally
Requires Docker and Python 3.12.

```bash
docker compose up -d db
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env
alembic upgrade head
python -m pipeline.run --city nyc --full       # ~3 min
python -m pipeline.run --city chicago --full   # ~2 min
docker compose up -d --build web               # http://localhost:8000
```

Nightly refresh (re-reads the last 120 days, since results change after re-inspections):
```bash
python -m pipeline.run --city nyc
python -m pipeline.run --city chicago
```

Tests and lint:
```bash
pytest
ruff check . && ruff format --check .
```

## Roadmap
- [ ] "Ask the Inspector": plain-English questions answered from the database
- [ ] AWS deployment: Terraform, ECS Fargate, RDS, scheduled pipeline task, CD on push
- [ ] Email alerts when a followed restaurant's score drops
- [ ] More cities

## Data
- New York City: NYC Department of Health and Mental Hygiene, [Restaurant Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
- Chicago: Chicago Department of Public Health, [Food Inspections](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5) (July 2018 onward)
- Map: © OpenStreetMap contributors, tiles by OpenFreeMap

Hygiene and food scores are CleanPlate's own, not official ratings. CleanPlate is independent and not affiliated with any city government.
