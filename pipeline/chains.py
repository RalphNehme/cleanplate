import asyncio
import hashlib
import logging
import re
from collections import Counter
from urllib.parse import urljoin, urlparse

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Chain
from pipeline.menus import (
    MAX_CHARS,
    SKIP_LINK,
    Fetcher,
    MenuResult,
    _clean,
    html_text,
    menu_signal,
)
from pipeline.osm import USER_AGENT

MIN_LOCATIONS = 3
NAME_MATCH_SHARE = 0.6
MAX_PAGES = 12
# A national menu replaces every location's own menu, so it must read as a full menu, not a
# promo or landing page (a "featured menu" page scores ~40; full menus score in the hundreds).
CHAIN_MIN_SIGNAL = 150
# Hosting, social and listing sites many unrelated restaurants share.
NOT_CHAINS = {
    "business.site",
    "instagram.com",
    "facebook.com",
    "square.site",
    "wixsite.com",
    "squarespace.com",
    "toasttab.com",
    "linktr.ee",
    "google.com",
    "yelp.com",
    "weebly.com",
    "godaddysites.com",
    "wordpress.com",
    "blogspot.com",
    "menufy.com",
    "chownow.com",
    "clover.com",
    "order.online",
    "popmenu.com",
    "bentobox.com",
    "spothopperapp.com",
}
DROP_WORDS = {"the", "restaurant", "restaurants", "inc", "llc", "corp", "store"}
# One-word brands too generic to match other restaurants by name alone.
GENERIC = {
    "coffee",
    "cafe",
    "pizza",
    "pizzeria",
    "sushi",
    "deli",
    "grill",
    "bakery",
    "bar",
    "kitchen",
    "fresh",
    "burger",
    "burgers",
    "chicken",
    "taco",
    "tacos",
    "bagels",
    "juice",
    "wonder",
    "empanadas",
    "halal",
    "diner",
    "bistro",
    "noodles",
    "ramen",
    "poke",
    "salad",
    "market",
}

log = logging.getLogger("pipeline.chains")


def domain_of(url: str) -> str | None:
    host = urlparse(url if "://" in url else f"https://{url}").netloc.lower().split(":")[0]
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else None


def normalize(name: str) -> str:
    """Lowercase brand words, dropping store numbers ("#123", or a number ending the name)."""
    name = re.sub(r"#\s*\d+|\s\d+\s*$", " ", name.lower())
    words = [w for w in re.sub(r"[^a-z0-9]+", " ", name).split() if w not in DROP_WORDS]
    return " ".join(words)


def belongs(name: str, brand: str, anywhere: bool = True) -> bool:
    n = normalize(name)
    if n == brand or n.startswith(brand + " "):
        return True
    return anywhere and f" {brand} " in f" {n} "


def detect(session: Session) -> int:
    rows = session.execute(
        text("SELECT id, name, website FROM restaurants WHERE active AND website IS NOT NULL")
    ).all()
    groups: dict[str, list] = {}
    for rid, name, website in rows:
        dom = domain_of(website)
        if dom and dom not in NOT_CHAINS:
            groups.setdefault(dom, []).append((rid, name))

    found = 0
    for dom, members in groups.items():
        if len(members) < MIN_LOCATIONS:
            continue
        brand, _ = Counter(normalize(n) for _, n in members).most_common(1)[0]
        if len(brand) < 3:
            continue
        if sum(belongs(n, brand) for _, n in members) / len(members) < NAME_MATCH_SHARE:
            continue
        display = Counter(n for _, n in members if normalize(n) == brand).most_common(1)[0][0]
        taken = session.scalar(text("SELECT domain FROM chains WHERE brand = :b"), {"b": brand})
        if taken and taken != dom:
            continue
        stmt = insert(Chain).values(brand=brand, name=display, domain=dom)
        stmt = stmt.on_conflict_do_update(index_elements=["domain"], set_={"name": display})
        chain_id = session.execute(stmt.returning(Chain.id)).scalar_one()
        session.execute(
            text("UPDATE restaurants SET chain_id = :c WHERE id = ANY(:ids)"),
            {"c": chain_id, "ids": [rid for rid, _ in members]},
        )
        found += 1

    # Locations without a website join the chain whose name they start with.
    for chain_id, brand in session.execute(text("SELECT id, brand FROM chains")).all():
        if brand in GENERIC or len(brand) < 4:
            continue
        unlinked = session.execute(
            text(
                "SELECT id, name FROM restaurants WHERE active AND chain_id IS NULL "
                "AND lower(name) LIKE :p"
            ),
            {"p": f"%{brand.split()[0]}%"},
        ).all()
        ids = [rid for rid, name in unlinked if belongs(name, brand, anywhere=False)]
        if ids:
            session.execute(
                text("UPDATE restaurants SET chain_id = :c WHERE id = ANY(:ids)"),
                {"c": chain_id, "ids": ids},
            )
    session.commit()
    return found


async def _fetch_chain(fetcher: Fetcher, context, domain: str) -> MenuResult:
    from playwright.async_api import Error as PlaywrightError

    page = await context.new_page()

    async def render(url: str) -> tuple[str, str] | None:
        if not await asyncio.to_thread(fetcher.allowed, url):
            return None
        try:
            await page.goto(url, wait_until="networkidle", timeout=20_000)
        except PlaywrightError:
            try:
                await page.wait_for_load_state("load", timeout=3_000)
            except PlaywrightError:
                return None
        try:
            return page.url, await page.content()
        except PlaywrightError:
            return None

    def same_site_links(html: str, base: str, under: str | None = None) -> list[str]:
        from bs4 import BeautifulSoup

        links = []
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            url = urljoin(base, a["href"]).split("#")[0].split("?")[0]
            if domain_of(url) != domain or SKIP_LINK.search(url) or url in links:
                continue
            path = urlparse(url).path.lower()
            if under is not None and not (path.startswith(under) and path != under):
                continue
            if under is None and "menu" not in path and "food" not in path:
                continue
            links.append(url)
        return links

    try:
        start = None
        for url in (f"https://www.{domain}/menu", f"https://www.{domain}/"):
            start = await render(url)
            if start:
                break
        if not start:
            return MenuResult("blocked", f"https://www.{domain}/", detail="not reachable or robots")
        pages = [(start[0], html_text(start[1]))]
        menu_pages = [start] + [
            r for r in [await render(u) for u in same_site_links(start[1], start[0])[:3]] if r
        ]
        menu_pages.sort(key=lambda p: menu_signal(html_text(p[1])), reverse=True)
        best_url, best_html = menu_pages[0]
        pages = [(best_url, html_text(best_html))]
        under = urlparse(best_url).path.lower().rstrip("/") or "/"
        for url in same_site_links(best_html, best_url, under=under + "/")[:MAX_PAGES]:
            got = await render(url)
            if got:
                pages.append((got[0], html_text(got[1])))
    finally:
        await page.close()

    combined = "\n\n".join(t for _, t in pages)
    if menu_signal(combined) < CHAIN_MIN_SIGNAL:
        return MenuResult("not_found", best_url, detail="no national menu found")
    return MenuResult("ok", best_url, combined[: MAX_CHARS * 2])


async def _fetch_all(chains: list[tuple[int, str]]) -> dict[int, MenuResult]:
    from playwright.async_api import async_playwright

    fetcher = Fetcher()
    results: dict[int, MenuResult] = {}
    sem = asyncio.Semaphore(4)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(user_agent=USER_AGENT)

        async def one(chain_id: int, domain: str):
            async with sem:
                try:
                    results[chain_id] = await asyncio.wait_for(
                        _fetch_chain(fetcher, context, domain), 180
                    )
                except Exception as exc:  # noqa: BLE001 - one bad site shouldn't stop the run
                    results[chain_id] = MenuResult("error", None, detail=str(exc)[:300])
                log.info("%s: %s", domain, results[chain_id].status)

        await asyncio.gather(*(one(cid, dom) for cid, dom in chains))
        await browser.close()
    return results


def fetch_menus(session: Session, refetch: bool = False, limit: int = 1000) -> Counter:
    """Fetch national menus, largest chains first."""
    where = "" if refetch else "WHERE c.status = 'pending'"
    chains = session.execute(
        text(
            f"SELECT c.id, c.domain FROM chains c LEFT JOIN restaurants r ON r.chain_id = c.id "
            f"{where} GROUP BY c.id ORDER BY count(r.id) DESC LIMIT :limit"
        ),
        {"limit": limit},
    ).all()
    results = asyncio.run(_fetch_all([(c.id, c.domain) for c in chains]))
    for chain_id, result in results.items():
        menu = _clean(result.text) if result.status == "ok" else None
        session.execute(
            text(
                "UPDATE chains SET status = :s, menu_url = :u, detail = :d, fetched_at = now(), "
                "menu_text = :t, menu_hash = :h, source_pages = NULL WHERE id = :id"
            ),
            {
                "s": result.status,
                "u": result.url,
                "d": result.detail,
                "t": menu,
                "h": _hash(menu),
                "id": chain_id,
            },
        )
    session.commit()
    return Counter(r.status for r in results.values())


def _hash(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def merge_texts(texts: list[str], min_share: int = 2) -> str:
    """Combine a chain's location pages: keep lines that appear on at least `min_share` pages
    (menu items repeat; addresses and opening hours don't), in first-seen order."""
    pages_with: Counter = Counter()
    order: dict[str, None] = {}
    for page in texts:
        lines = [line.strip() for line in page.splitlines() if len(line.strip()) >= 3]
        for line in lines:
            order.setdefault(line)
        pages_with.update(set(lines))
    needed = min_share if len(texts) >= 4 else 1
    kept = [line for line in order if pages_with[line] >= needed]
    return "\n".join(kept)[: MAX_CHARS * 2]


def merge_menus(session: Session, min_pages: int = 2) -> Counter:
    """Give chains without a national menu one merged from their locations' own pages."""
    chains = (
        session.execute(text("SELECT id FROM chains WHERE status <> 'ok' ORDER BY id"))
        .scalars()
        .all()
    )
    counts: Counter = Counter()
    for chain_id in chains:
        pages = session.execute(
            text(
                "SELECT DISTINCT ON (m.text_hash) m.text, m.url FROM menus m "
                "JOIN restaurants r ON r.id = m.restaurant_id "
                "WHERE r.chain_id = :c AND m.status = 'ok' ORDER BY m.text_hash"
            ),
            {"c": chain_id},
        ).all()
        if len(pages) < min_pages:
            counts["too_few_pages"] += 1
            continue
        merged = merge_texts([p.text for p in pages])
        if menu_signal(merged) < CHAIN_MIN_SIGNAL:
            counts["too_thin"] += 1
            continue
        session.execute(
            text(
                "UPDATE chains SET status = 'merged', menu_text = :t, menu_hash = :h, "
                "menu_url = :u, source_pages = :n, "
                "detail = 'merged from location pages' WHERE id = :id"
            ),
            {"t": merged, "h": _hash(merged), "u": pages[0].url, "n": len(pages), "id": chain_id},
        )
        counts["merged"] += 1
    session.commit()
    return counts
