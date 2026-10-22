import asyncio
import hashlib
import io
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Menu
from pipeline.osm import USER_AGENT

MAX_BYTES = 5_000_000
MAX_CHARS = 30_000
MIN_SIGNAL = 30
RENDER_SECONDS = 45
MENU_LINK = re.compile(r"menu|food|eat|dinner|lunch|brunch|breakfast", re.I)
SKIP_LINK = re.compile(
    r"instagram|facebook|twitter|tiktok|yelp|google|mailto:|tel:|reserv|opentable|resy|"
    r"gift|career|job",
    re.I,
)
# Delivery marketplaces forbid scraping in their terms, so their pages are never fetched.
DELIVERY = re.compile(r"ubereats|doordash|grubhub|seamless|postmates|caviar|instacart", re.I)
PRICE = re.compile(r"\$\s?\d{1,3}(?:\.\d{2})?|\b\d{1,3}\.\d{2}\b")
FOOD = re.compile(
    r"\b(?:chicken|beef|pork|lamb|steak|burger|fries|salad|soup|rice|noodles?|pasta|pizza|"
    r"taco|burrito|sandwich|wrap|fish|salmon|tuna|shrimp|crab|lobster|oyster|tofu|egg|cheese|"
    r"bread|toast|bacon|sausage|ham|turkey|duck|vegetables?|veggie|vegan|mushroom|onion|garlic|"
    r"tomato|avocado|potato|bean|lentil|chickpea|hummus|curry|ramen|sushi|roll|dumpling|"
    r"wings?|fried|grilled|roasted|braised|smoked|sauce|aioli|dressing|cream|butter|olive|"
    r"dessert|cake|pie|cookie|ice cream|gelato|coffee|latte|espresso|tea|juice|smoothie|"
    r"appetizers?|entrees?|mains?|sides?|starters?|brunch|lunch|dinner)\b",
    re.I,
)

log = logging.getLogger("pipeline.menus")


@dataclass
class MenuResult:
    status: str
    url: str | None = None
    text: str | None = None
    detail: str | None = None
    render: list[str] = field(default_factory=list)


def normalize_url(url: str) -> str:
    url = url.strip()
    return url if re.match(r"https?://", url) else f"https://{url}"


def menu_signal(value: str) -> int:
    return len(FOOD.findall(value)) + 2 * len(PRICE.findall(value))


@dataclass
class Page:
    url: str
    headers: httpx.Headers
    content: bytes
    encoding: str | None

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")


class Fetcher:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True
        )
        self.robots: dict[str, RobotFileParser] = {}

    def download(self, url: str, max_bytes: int = MAX_BYTES, seconds: float = 30) -> Page:
        """GET with a total time and size cap; slow or endless responses are cut off."""
        deadline = time.monotonic() + seconds
        with self.client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunks, size = [], 0
            for chunk in resp.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("response too large")
                if time.monotonic() > deadline:
                    raise ValueError("download too slow")
            return Page(str(resp.url), resp.headers, b"".join(chunks), resp.charset_encoding)

    def allowed(self, url: str) -> bool:
        if DELIVERY.search(urlparse(url).netloc):
            return False
        parts = urlparse(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root not in self.robots:
            parser = RobotFileParser()
            try:
                page = self.download(f"{root}/robots.txt", max_bytes=500_000, seconds=10)
                parser.parse(page.text.splitlines())
            except (httpx.HTTPError, ValueError):
                parser.parse([])
            self.robots[root] = parser
        return self.robots[root].can_fetch(USER_AGENT, url)

    def get(self, url: str) -> Page | None:
        if not self.allowed(url):
            return None
        return self.download(url)


def html_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "footer", "form"]):
        tag.decompose()
    lines = (line.strip() for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line)


def page_text(resp: Page) -> tuple[str, BeautifulSoup | None]:
    kind = resp.headers.get("content-type", "")
    if "pdf" in kind or str(resp.url).lower().endswith(".pdf"):
        reader = PdfReader(io.BytesIO(resp.content))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:20]), None
    return html_text(resp.text), BeautifulSoup(resp.text, "html.parser")


def menu_links(soup: BeautifulSoup, base: str) -> list[str]:
    host = urlparse(base).netloc.removeprefix("www.")
    links = []
    for a in soup.find_all("a", href=True):
        href, label = a["href"], a.get_text(" ", strip=True)
        if SKIP_LINK.search(href) or DELIVERY.search(href):
            continue
        if not (MENU_LINK.search(label) or MENU_LINK.search(href)):
            continue
        url = urljoin(base, href).split("#")[0]
        if url.startswith("http") and url not in links and url.rstrip("/") != base.rstrip("/"):
            same_site = urlparse(url).netloc.removeprefix("www.") == host
            links.insert(0, url) if same_site else links.append(url)
    return links[:4]


def choose(pages: list[tuple[str, str]], fallback_url: str, render: list[str]) -> MenuResult:
    pages = sorted(pages, key=lambda p: menu_signal(p[1]), reverse=True)
    if not pages or menu_signal(pages[0][1]) < MIN_SIGNAL:
        return MenuResult(
            "not_found", fallback_url, detail="no page that reads as a menu", render=render
        )
    combined = pages[0][1]
    if len(pages) > 1 and menu_signal(pages[1][1]) >= MIN_SIGNAL:
        combined += "\n\n" + pages[1][1]
    return MenuResult("ok", pages[0][0], combined[:MAX_CHARS])


def fetch_menu(fetcher: Fetcher, website: str) -> MenuResult:
    url = normalize_url(website)
    try:
        home = fetcher.get(url)
        if home is None:
            return MenuResult("blocked", url, detail="robots.txt or delivery site")
        home_text, soup = page_text(home)
        links = menu_links(soup, str(home.url)) if soup else []
        pages = [(str(home.url), home_text)]
        for link in links:
            try:
                resp = fetcher.get(link)
            except (httpx.HTTPError, ValueError):
                continue
            if resp is not None:
                pages.append((str(resp.url), page_text(resp)[0]))
    except (httpx.HTTPError, ValueError) as exc:
        return MenuResult("error", url, detail=str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - malformed pages shouldn't stop the run
        return MenuResult("unreadable", url, detail=f"{type(exc).__name__}: {exc}"[:300])
    render = [u for u in links if not u.lower().endswith(".pdf")][:2] or [str(home.url)]
    return choose(pages, url, render)


def render_menus(fetcher: Fetcher, results: dict[int, MenuResult], tabs: int = 8) -> None:
    todo = {rid: r for rid, r in results.items() if r.status == "not_found" and r.render}
    if todo:
        asyncio.run(_render_all(fetcher, results, todo, tabs))


async def _render_all(fetcher: Fetcher, results, todo, tabs: int) -> None:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    async def visit(page, result: MenuResult, pages: list) -> None:
        for url in result.render:
            if not await asyncio.to_thread(fetcher.allowed, url):
                continue
            try:
                await page.goto(url, wait_until="networkidle", timeout=15_000)
            except PlaywrightError:
                try:
                    await page.wait_for_load_state("load", timeout=3_000)
                except PlaywrightError:
                    continue
            try:
                pages.append((page.url, html_text(await page.content())))
            except PlaywrightError:
                continue

    async def render(context, sem, rid: int, result: MenuResult) -> None:
        async with sem:
            page = await context.new_page()
            pages: list = []
            try:
                await asyncio.wait_for(visit(page, result, pages), RENDER_SECONDS)
            except (TimeoutError, PlaywrightError):
                pass
            finally:
                try:
                    await asyncio.wait_for(page.close(), 5)
                except (TimeoutError, PlaywrightError):
                    pass
            rendered = choose(pages, result.url, [])
            if rendered.status == "ok":
                results[rid] = rendered

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(user_agent=USER_AGENT)
        sem = asyncio.Semaphore(tabs)
        await asyncio.gather(*(render(context, sem, rid, r) for rid, r in todo.items()))
        await browser.close()


CANDIDATES = text("""
SELECT r.id, r.website
FROM restaurants r
LEFT JOIN menus m ON m.restaurant_id = r.id
WHERE r.city_id = :cid AND r.active AND r.website IS NOT NULL
  AND (m.id IS NULL OR m.fetched_at < now() - interval '60 days')
  -- Locations of a chain whose national menu was found share that menu instead.
  AND NOT EXISTS (SELECT 1 FROM chains c WHERE c.id = r.chain_id AND c.status = 'ok')
ORDER BY md5(r.id::text)
LIMIT :limit
""")


def _clean(value: str | None) -> str | None:
    return value.replace("\x00", "") if value else value


def save(session: Session, rid: int, result: MenuResult) -> None:
    menu_text = _clean(result.text)
    values = {
        "restaurant_id": rid,
        "status": result.status,
        "url": _clean(result.url or "")[:1000] or None,
        "text": menu_text,
        "text_hash": hashlib.sha256(menu_text.encode()).hexdigest() if menu_text else None,
        "detail": _clean(result.detail),
    }
    stmt = insert(Menu).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["restaurant_id"],
        set_={
            **{k: stmt.excluded[k] for k in values if k != "restaurant_id"},
            "fetched_at": text("now()"),
        },
    )
    session.execute(stmt)


def fetch_city(
    session: Session, city_id: int, limit: int, workers: int = 16, chunk: int = 50
) -> dict[str, int]:
    rows = session.execute(CANDIDATES, {"cid": city_id, "limit": limit}).all()

    def work(row):
        return row.id, fetch_menu(Fetcher(), row.website)

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(workers) as pool:
        for start in range(0, len(rows), chunk):
            results = dict(pool.map(work, rows[start : start + chunk]))
            render_menus(Fetcher(), results)
            for rid, result in results.items():
                save(session, rid, result)
                counts[result.status] = counts.get(result.status, 0) + 1
            session.commit()
            log.info("%d/%d sites checked: %s", min(start + chunk, len(rows)), len(rows), counts)
    return counts
