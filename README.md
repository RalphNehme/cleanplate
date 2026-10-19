# CleanPlate

How good is the food, really? CleanPlate reads each restaurant's actual menu and gives it a **food score** from 1 to 100: fresh whole ingredients score high, while deep-fried, ultra-processed and seed-oil cooking score low. A smaller **hygiene score** from official health inspections sits alongside. Cities: New York City and Chicago.

**Stack:** Python · FastAPI · PostgreSQL + PostGIS · SQLAlchemy · Alembic · Claude API (Haiku 5.5) · Playwright · HTMX · MapLibre GL · Chart.js · Docker · GitHub Actions

## Features
- **Menu-based food score:** Claude reads each restaurant's menu and reports the share of fried, ultra-processed, sweet, whole-food and vegetable-forward dishes, quality claims ("organic", "grass-fed", "house-made") and any cooking oil named. A fixed formula turns that report into the score. Every score shows the quoted menu lines behind it.
- **No guesses:** restaurants without a readable menu aren't scored or listed
- **Visitor reports:** with 3 or more reports on oil, ingredients and healthy options, visitors count for half of the score
- **Hygiene score:** NYC violation points and Chicago violation severity converted to 1–100, next to the official grade
- City picker homepage, then a map, search and stats for each city
- Vector map (MapLibre + OpenFreeMap) with clusters colored by average food score
- Filters for area, cuisine, food and hygiene bands, and "no seed oils"
- JSON API: `/api/cities`, `/api/{city}/search`, `/api/{city}/points`, `/api/{city}/stats`, `/api/restaurants/{id}`

See `/scores` on the site for the exact formulas.

## How it works
```
NYC / Chicago open data ──► pipeline.run      inspections, hygiene scores ─┐
OpenStreetMap (Overpass) ─► pipeline.food osm  real cuisine, diet tags, websites
Restaurant websites ──────► pipeline.food menus  HTML/PDF menus, Playwright for JS sites
Claude Haiku 5.5 ─────────► pipeline.food analyze  structured menu report ──► food score
                                                                            ▼
                                                     Postgres + PostGIS ──► FastAPI pages + JSON API
```
The menu fetcher respects robots.txt and never fetches delivery marketplaces. Identical chain menus are analyzed once, and large runs can use the Message Batches API at half price.

## Run locally
Requires Docker and Python 3.12.

```bash
docker compose up -d db
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # macOS/Linux: .venv/bin/pip
.venv/Scripts/python -m playwright install chromium
cp .env.example .env                       # add ANTHROPIC_API_KEY, or run `ant auth login`
alembic upgrade head
python -m pipeline.run --city nyc --full
python -m pipeline.run --city chicago --full
python -m pipeline.food osm --city chicago
python -m pipeline.food menus --city chicago --limit 500
python -m pipeline.food analyze --city chicago --limit 200        # add --batch for big runs
docker compose up -d --build web           # http://localhost:8000
```

Tests and lint:
```bash
pytest
ruff check . && ruff format --check .
```

## Roadmap
- [ ] Full menu run for both cities, then a monthly refresh of changed menus
- [ ] AWS deployment: Terraform, ECS Fargate, RDS, scheduled pipeline tasks, CD on push
- [ ] Email alerts when a followed restaurant's score changes
- [ ] More cities

## Data
- New York City: NYC Department of Health and Mental Hygiene, [Restaurant Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
- Chicago: Chicago Department of Public Health, [Food Inspections](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5) (July 2018 onward)
- Restaurant cuisines and websites: © OpenStreetMap contributors (ODbL)
- Map: © OpenStreetMap contributors, tiles by OpenFreeMap

Food scores are AI readings of published menus and can be wrong; hygiene scores are CleanPlate's conversion of official inspections. Neither is an official rating. CleanPlate is independent and not affiliated with any city government.
