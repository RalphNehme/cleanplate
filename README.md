# CleanPlate

How clean is that restaurant? CleanPlate puts every New York City restaurant's health inspection grade, score history and violations on a searchable map.

**Stack:** Python · FastAPI · PostgreSQL + PostGIS · SQLAlchemy · Alembic · HTMX · Leaflet · Chart.js · Docker · GitHub Actions

## Features
- Map of ~31,000 NYC restaurants, colored by their current A/B/C grade
- Search by name with fuzzy matching (Postgres trigram index), filter by borough, cuisine and grade
- "Near me": nearest restaurants via PostGIS distance queries
- Restaurant pages with score history and every violation cited
- Citywide stats: grades by borough, cleanest/messiest cuisines, most common violations, biggest recent score jumps
- JSON API: `/api/search`, `/api/points`, `/api/restaurants/{id}`, `/api/stats`

## How it works
```
NYC Open Data (Socrata API)
        │  pipeline/adapters/nyc.py  fetch + group violation rows into inspections
        ▼
pipeline/load.py  idempotent upserts ──► Postgres + PostGIS
                                              │
                                              ▼
                                   FastAPI (app/) ──► HTML pages + JSON API
```
Each city is a small adapter that outputs the same normalized records, so adding a city doesn't touch the database or the website. Grading systems differ by city, so each inspection keeps its original score/grade plus a normalized rating (`good` / `ok` / `concerning`).

## Run locally
Requires Docker and Python 3.12.

```bash
docker compose up -d db
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip
cp .env.example .env
alembic upgrade head
python -m pipeline.run --city nyc --full   # ~3 min, ~300k rows
docker compose up -d --build web           # http://localhost:8000
```

Nightly refresh (re-reads the last 120 days, since grades change after re-inspections):
```bash
python -m pipeline.run --city nyc
```

Tests and lint:
```bash
pytest
ruff check . && ruff format --check .
```

## Roadmap
- [ ] "Ask the Inspector": plain-English questions answered from the database
- [ ] AWS deployment: Terraform, ECS Fargate, RDS, scheduled pipeline task, CD on push
- [ ] Email alerts when a followed restaurant's grade drops
- [ ] More cities

## Data
NYC Department of Health and Mental Hygiene, [DOHMH New York City Restaurant Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j), via NYC Open Data. Map tiles © OpenStreetMap contributors. CleanPlate is independent and not affiliated with the City of New York.
