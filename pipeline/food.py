import argparse
import logging
import time

from app.db import SessionLocal
from pipeline.load import city_id

STEPS = ("chains", "osm", "menus", "analyze", "rescore")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build menu-based food scores.")
    parser.add_argument("step", choices=STEPS)
    parser.add_argument("--city", help="required for every step except chains")
    parser.add_argument("--refetch", action="store_true", help="chains: fetch all menus again")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--batch", action="store_true", help="use the Batches API (half price)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    log = logging.getLogger("pipeline.food")

    start = time.monotonic()
    with SessionLocal() as session:
        if args.step == "chains":
            from pipeline.chains import detect, fetch_menus

            log.info("Detected %d chains", detect(session))
            log.info("Chain menus: %s", dict(fetch_menus(session, args.refetch, args.limit)))
            return
        if not args.city:
            parser.error("--city is required for this step")
        cid = city_id(session, args.city)
        if args.step == "osm":
            from pipeline.osm import match_city

            log.info("Matched %d restaurants to OpenStreetMap", match_city(session, cid))
        elif args.step == "menus":
            from pipeline.menus import fetch_city

            log.info("Menu fetch results: %s", fetch_city(session, cid, args.limit))
        elif args.step == "analyze":
            from pipeline.analyze import analyze_city

            log.info("Analysis: %s", analyze_city(session, cid, args.limit, args.batch))
        else:
            from pipeline.analyze import rescore_city

            log.info("Rescored %d analyses from saved data", rescore_city(session, cid))
    log.info("Done in %.0fs", time.monotonic() - start)


if __name__ == "__main__":
    main()
