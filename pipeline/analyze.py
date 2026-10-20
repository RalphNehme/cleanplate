import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import anthropic
from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
from anthropic.types.messages.batch_create_params import Request
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.food import MenuReport, menu_score, refresh_food
from app.models import MenuAnalysis

MODEL = "claude-haiku-5-5"
# Bump when the prompt or schema changes so existing analyses are redone.
ANALYZER = f"{MODEL}/v2"
MAX_TOKENS = 8000
# The SDK waits as long as a 429 response asks; enough retries ride out a busy minute.
MAX_RETRIES = 8
# USD per million tokens for claude-haiku-5-5 (prompts under 100K tokens); batches cost half.
PRICE_IN, PRICE_OUT = 0.10, 0.50

SYSTEM = """You assess how healthy and high-quality a restaurant's food is, using only the menu \
text provided. The text was scraped from the restaurant's website and may include navigation \
or other noise; ignore anything that isn't food or drink.

Rules:
- Judge only from what the menu says. Do not assume ingredients or cooking methods the menu \
doesn't mention, except that items described as fried, crispy, tempura, battered or breaded \
count as deep-fried.
- Cooking oil: set oil.stated only when the menu names the oil or fat used (e.g. "fried in \
beef tallow", "extra virgin olive oil", "seed-oil free", "canola"). Otherwise use "not_stated". \
"Seed-oil free" without naming the fat counts as "mixed".
- Shares are fractions from 0 to 1 of the menu's items. Sweetened drinks, smoothies, shakes, \
frappes and juices with added sugar count toward sweets_share.
- Quality markers and highlight quotes must be copied verbatim from the menu text.
- If the text is not a food menu (e.g. a homepage with no dishes), set is_restaurant_menu to \
false and keep other fields minimal."""

PENDING = text("""
SELECT m.restaurant_id, m.text, m.text_hash, r.name
FROM menus m
JOIN restaurants r ON r.id = m.restaurant_id
LEFT JOIN menu_analyses a ON a.restaurant_id = m.restaurant_id
WHERE r.city_id = :cid AND m.status = 'ok'
  AND (a.id IS NULL OR a.text_hash <> m.text_hash OR a.model <> :model)
ORDER BY md5(m.restaurant_id::text)
LIMIT :limit
""")

log = logging.getLogger("pipeline.analyze")


def make_client() -> anthropic.Anthropic:
    if settings.anthropic_api_key:
        return anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=MAX_RETRIES)
    # An empty ANTHROPIC_API_KEY would outrank `ant auth login` and workload identity federation.
    if os.environ.get("ANTHROPIC_API_KEY") == "":
        del os.environ["ANTHROPIC_API_KEY"]
    return anthropic.Anthropic(max_retries=MAX_RETRIES)


def user_prompt(name: str, menu: str) -> str:
    return f"Restaurant: {name}\n\n<menu>\n{menu}\n</menu>"


def json_schema() -> dict:
    def strict(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                node["additionalProperties"] = False
                node["required"] = list(node.get("properties", {}))
            for value in node.values():
                strict(value)
        elif isinstance(node, list):
            for value in node:
                strict(value)
        return node

    return strict(MenuReport.model_json_schema())


def params(name: str, menu: str) -> dict:
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM,
        "output_config": {
            "effort": "low",
            "format": {"type": "json_schema", "schema": json_schema()},
        },
        "messages": [{"role": "user", "content": user_prompt(name, menu)}],
    }


def parse_message(message) -> MenuReport | None:
    if message.stop_reason in ("refusal", "max_tokens"):
        return None
    body = next((b.text for b in message.content if b.type == "text"), None)
    if body is None:
        return None
    try:
        return MenuReport.model_validate_json(body)
    except ValidationError:
        return None


def save(session: Session, rid: int, text_hash: str, report: MenuReport) -> None:
    values = {
        "restaurant_id": rid,
        "model": ANALYZER,
        "text_hash": text_hash,
        "score": menu_score(report),
        "cuisine": report.cuisine[:100] if report.is_restaurant_menu else None,
        "summary": report.summary,
        "data": report.model_dump(),
    }
    stmt = insert(MenuAnalysis).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["restaurant_id"],
        set_={
            **{k: stmt.excluded[k] for k in values if k != "restaurant_id"},
            "analyzed_at": text("now()"),
        },
    )
    session.execute(stmt)


def cost(input_tokens: int, output_tokens: int, batch: bool) -> float:
    total = (input_tokens * PRICE_IN + output_tokens * PRICE_OUT) / 1_000_000
    return total / 2 if batch else total


def analyze_city(session: Session, city_id: int, limit: int, batch: bool, workers: int = 4):
    rows = session.execute(PENDING, {"cid": city_id, "limit": limit, "model": ANALYZER}).all()
    if not rows:
        return {"analyzed": 0, "failed": 0, "cost": 0.0}

    # Chain locations often share identical menu text: analyze each unique menu once.
    known = {
        h: MenuReport.model_validate(data)
        for h, data in session.execute(
            text(
                "SELECT DISTINCT ON (text_hash) text_hash, data FROM menu_analyses "
                "WHERE model = :model AND text_hash = ANY(:hashes)"
            ),
            {"model": ANALYZER, "hashes": list({r.text_hash for r in rows})},
        )
    }
    unique = {}
    for row in rows:
        if row.text_hash not in known:
            unique.setdefault(row.text_hash, row)

    tokens_in = tokens_out = 0
    if unique:
        client = make_client()
        todo = list(unique.values())
        results = run_batch(client, todo) if batch else run_sync(client, todo, workers)
        for row, message in results:
            if message is None:
                continue
            tokens_in += message.usage.input_tokens
            tokens_out += message.usage.output_tokens
            report = parse_message(message)
            if report is not None:
                known[row.text_hash] = report

    analyzed = failed = 0
    for row in rows:
        report = known.get(row.text_hash)
        if report is None:
            failed += 1
            continue
        save(session, row.restaurant_id, row.text_hash, report)
        analyzed += 1
    refresh_food(session, city_id=city_id)
    session.commit()
    return {
        "analyzed": analyzed,
        "api_calls": len(unique),
        "failed": failed,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost": round(cost(tokens_in, tokens_out, batch), 4),
    }


def run_sync(client: anthropic.Anthropic, rows, workers: int):
    def work(row):
        try:
            return row, client.messages.create(**params(row.name, row.text))
        except anthropic.BadRequestError as exc:
            log.warning("Restaurant %s rejected: %s", row.restaurant_id, exc)
        except anthropic.APIStatusError as exc:
            log.warning("Restaurant %s failed (%s)", row.restaurant_id, exc.status_code)
        except anthropic.APIConnectionError as exc:
            log.warning("Restaurant %s connection error: %s", row.restaurant_id, exc)
        return row, None

    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(work, rows))


def run_batch(client: anthropic.Anthropic, rows, poll_seconds: int = 30):
    by_id = {str(row.restaurant_id): row for row in rows}
    batch = client.messages.batches.create(
        requests=[
            Request(
                custom_id=rid,
                params=MessageCreateParamsNonStreaming(**params(row.name, row.text)),
            )
            for rid, row in by_id.items()
        ]
    )
    log.info("Submitted batch %s with %d menus", batch.id, len(rows))
    while batch.processing_status != "ended":
        time.sleep(poll_seconds)
        batch = client.messages.batches.retrieve(batch.id)
        log.info("Batch %s: %d processing", batch.id, batch.request_counts.processing)
    results = []
    for result in client.messages.batches.results(batch.id):
        row = by_id[result.custom_id]
        if result.result.type == "succeeded":
            results.append((row, result.result.message))
        else:
            log.warning("Restaurant %s: batch result %s", row.restaurant_id, result.result.type)
            results.append((row, None))
    return results
