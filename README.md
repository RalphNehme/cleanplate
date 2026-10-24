# CleanPlate

How good is the food, really? CleanPlate reads each restaurant's actual menu and gives it a **food score** from 1 to 100: meals built on vegetables, whole grains, legumes and lean protein score high, while deep-fried, processed-meat, sugary and saturated-fat-heavy meals score low. A smaller **hygiene score** from official health inspections sits alongside. Live cities: New York City and Chicago, with Washington DC, Boston, Miami and Philadelphia coming soon.

**Stack:** Python · FastAPI · PostgreSQL + PostGIS · SQLAlchemy · Alembic · Claude API (Haiku 5.5) · Playwright · HTMX · MapLibre GL · Chart.js · Docker · GitHub Actions

## Features
- **Per-meal food score:** Claude reads each menu and rates up to 25 main meals on nine factors (vegetables & fruit, whole grains & legumes, healthy protein, unsaturated fats, deep-fried, processed meat, added sugar, saturated fat, and sodium when printed). Weights follow the proportions of the USDA Healthy Eating Index (HEI-2020), with frying and processed meat standing in for sodium, which menus rarely print. Each restaurant page shows every meal's score, the best and worst dishes, and a confidence level.
- **Fair to short menus:** a restaurant's score is its average meal, pulled toward the average restaurant so a few dishes can't produce an extreme score. At least 5 meals are needed; desserts and drinks are counted separately.
- **No guesses:** restaurants without a readable menu aren't scored or listed. Unclear dishes lower the confidence level, not the score.
- **Seed oils, as information:** any cooking oil named on the menu is shown, and there's a "No seed oils" filter, but oils aren't penalized because mainstream evidence doesn't support it. `/scores` explains why.
- **Chains:** restaurants sharing a website are grouped into one entry ("Sweetgreen · 41 locations") with a page listing every location. Their location pages are merged into one chain menu; chains whose pages only show a few featured items stay hidden until a full menu is available.
- **Visitor reports:** with 3 or more reports on ingredients and healthy options, visitors count for half of the score. Reported cooking oil is shown but not scored.
- **Hygiene score:** NYC violation points and Chicago violation severity converted to 1–100, next to the official grade
- City picker homepage, then a map, search and stats for each city
- Vector map (MapLibre + OpenFreeMap) with clusters colored by average food score, in light and dark mode
- Filters for area, cuisine, food and hygiene bands, and "no seed oils"
- JSON API: `/api/cities`, `/api/{city}/search`, `/api/{city}/points`, `/api/{city}/stats`, `/api/restaurants/{id}`

See `/scores` on the site for the exact formulas.

## How it works
```
NYC / Chicago open data ──► pipeline.run      inspections, hygiene scores ─┐
OpenStreetMap (Overpass) ─► pipeline.food osm  real cuisine, diet tags, websites
Restaurant websites ──────► pipeline.food menus  HTML/PDF menus, Playwright for JS sites
Shared website domains ───► pipeline.food chains  group chains, merge location pages
Claude Haiku 5.5 ─────────► pipeline.food analyze  per-meal factor ratings ──► food score
                                                                            ▼
                                                     Postgres + PostGIS ──► FastAPI pages + JSON API
```
The menu fetcher respects robots.txt and bot protection and never fetches delivery marketplaces. Identical menus are analyzed once, and large runs can use the Message Batches API at half price. Saved analyses can be rescored for free after a formula change (`pipeline.food rescore`).

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
python -m pipeline.food chains                                    # after menus, for all cities
python -m pipeline.food analyze --city chicago --limit 200        # add --batch for big runs
docker compose up -d --build web           # http://localhost:8000
```

Tests and lint:
```bash
pytest
ruff check . && ruff format --check .
```

## Roadmap
- [x] Full menu run for Chicago
- [ ] Full menu run for New York City, then a monthly refresh of changed menus
- [ ] AWS deployment: Terraform, ECS Fargate, RDS, scheduled pipeline tasks, CD on push
- [ ] Full menus for chains whose location pages only show featured items
- [ ] Data for Washington DC, Boston, Miami and Philadelphia
- [ ] Email alerts when a followed restaurant's score changes

## Data
- New York City: NYC Department of Health and Mental Hygiene, [Restaurant Inspection Results](https://data.cityofnewyork.us/Health/DOHMH-New-York-City-Restaurant-Inspection-Results/43nn-pn8j)
- Chicago: Chicago Department of Public Health, [Food Inspections](https://data.cityofchicago.org/Health-Human-Services/Food-Inspections/4ijn-s7e5) (July 2018 onward)
- Restaurant cuisines and websites: © OpenStreetMap contributors (ODbL)
- Map: © OpenStreetMap contributors, tiles by OpenFreeMap

Food scores are AI readings of published menus and can be wrong; hygiene scores are CleanPlate's conversion of official inspections. Neither is an official rating. CleanPlate is independent and not affiliated with any city government.
