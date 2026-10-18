import argparse
import logging
import time
from datetime import timedelta

from sqlalchemy import func, select

from app.config import settings
from app.db import SessionLocal
from app.models import Inspection, Restaurant
from pipeline.adapters.nyc import NYCAdapter
from pipeline.load import city_id, load

ADAPTERS = {"nyc": NYCAdapter}
# Grades can change after adjudication, so incremental runs re-read recent months.
LOOKBACK = timedelta(days=120)

log = logging.getLogger("pipeline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", required=True, choices=ADAPTERS)
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    adapter = ADAPTERS[args.city](app_token=settings.socrata_app_token)
    with SessionLocal() as session:
        since = None
        if not args.full:
            last = session.scalar(
                select(func.max(Inspection.inspected_at))
                .join(Restaurant)
                .where(Restaurant.city_id == city_id(session, args.city))
            )
            since = last - LOOKBACK if last else None
        log.info("Loading %s (%s)", args.city, f"since {since}" if since else "full")
        start = time.monotonic()
        count = load(session, args.city, adapter.restaurants(since))
        log.info("Loaded %d restaurants in %.0fs", count, time.monotonic() - start)


if __name__ == "__main__":
    main()
