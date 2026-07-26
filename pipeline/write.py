"""AVWIRE write stage: data/pending.json -> bilingual articles via the Anthropic API.

For each pending story group (capped at MAX_GROUPS_PER_RUN per run) one
structured-output Messages API call drafts the article, flash and optional
incident row. Outputs are appended/prepended to data/articles/<hour>.json,
data/flashes.json and data/incidents.json; data/seen.json is updated only for
groups that were actually published, so failed groups stay "unseen" and are
re-emitted by dedupe.py next run. data/stats.json is always rewritten.

Without ANTHROPIC_API_KEY the stage prints a notice, leaves pending.json
untouched and still refreshes stats.json. Exit code 0 in all data-driven
failure modes; non-zero exits are reserved for programming errors.
"""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta

from common import (
    ARTICLES_DIR,
    DATA_DIR,
    MAX_FLASHES,
    RAW_DIR,
    iso_minute,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
    slugify,
)

try:
    import anthropic
except ImportError:  # pragma: no cover - anthropic is in requirements.txt
    anthropic = None

MODEL = os.environ.get("AVWIRE_MODEL", "claude-opus-5")
MAX_GROUPS_PER_RUN = 10
MAX_INCIDENTS = 60
SEEN_MAX_AGE_DAYS = 21
SERIOUS_WINDOW_DAYS = 7
SOURCE_TITLE_MAX = 60

PENDING_PATH = DATA_DIR / "pending.json"
SEEN_PATH = DATA_DIR / "seen.json"
FLASHES_PATH = DATA_DIR / "flashes.json"
INCIDENTS_PATH = DATA_DIR / "incidents.json"
STATS_PATH = DATA_DIR / "stats.json"
FLIGHTAWARE_RAW_PATH = RAW_DIR / "flightaware.json"

_BILINGUAL_SCHEMA = {
    "type": "object",
    "properties": {"zh": {"type": "string"}, "en": {"type": "string"}},
    "required": ["zh", "en"],
    "additionalProperties": False,
}

_LANG_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "body": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "summary", "body"],
    "additionalProperties": False,
}

_INCIDENT_SCHEMA = {
    "type": "object",
    "properties": {
        "date": {"type": "string"},
        "sev": {"type": "string", "enum": ["acc", "ser", "inc"]},
        "aircraft": {"type": "string"},
        "operator": {"type": "string"},
        "phase": _BILINGUAL_SCHEMA,
        "location": _BILINGUAL_SCHEMA,
        "desc": _BILINGUAL_SCHEMA,
        "status": {"type": "string", "enum": ["open", "closed", "prelim"]},
    },
    "required": [
        "date",
        "sev",
        "aircraft",
        "operator",
        "phase",
        "location",
        "desc",
        "status",
    ],
    "additionalProperties": False,
}

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "cat": {"type": "string", "enum": ["safety", "reg", "biz", "ops"]},
        "zh": _LANG_SCHEMA,
        "en": _LANG_SCHEMA,
        "flash": {
            "type": "object",
            "properties": {
                "zh": {"type": "string"},
                "en": {"type": "string"},
                "hot": {"type": "boolean"},
            },
            "required": ["zh", "en", "hot"],
            "additionalProperties": False,
        },
        "incident": {"anyOf": [_INCIDENT_SCHEMA, {"type": "null"}]},
    },
    "required": ["cat", "zh", "en", "flash", "incident"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """\
You are the automated news desk writer for AVWIRE, an aviation news wire.
You receive one story group (one event, possibly covered by several sources)
and produce a bilingual wire story as JSON.

STRICT RULES:
- Use ONLY facts present in the provided source items. Never invent numbers,
  names, aircraft types, registrations, casualty figures or causes. If the
  sources do not state something, omit it.
- Write two versions: Traditional Chinese with Taiwan usage (zh) and
  English (en).
- summary: at most 80 characters for zh, at most 200 characters for en.
- body: 2 to 4 paragraphs in wire-service register. Plain text only,
  no markdown, no headlines inside the body.
- cat: classify the story as exactly one of:
  safety (事故/飛安), reg (法規/監理), biz (商業/財務), ops (營運/航網).
- flash: a one-line news flash in both languages; the zh flash is at most
  40 characters. Set hot=true ONLY for breaking safety events.
- incident: fill this object if and only if the story describes an actual
  aviation occurrence (accident, serious incident or incident in the sense of
  ICAO Annex 13). Otherwise incident must be null.
  - date: occurrence date as YYYY-MM-DD, best supported by the sources
  - sev: acc (accident), ser (serious incident) or inc (incident),
    per ICAO Annex 13 definitions
  - aircraft: aircraft type as stated in the sources
  - operator: operator name as stated in the sources
  - phase, location, desc: bilingual objects with zh and en strings
  - status: open, closed or prelim (preliminary report published)
"""


def _norm_title(title: str) -> str:
    """Normalize a title for dedupe memory: lowercase alphanumeric words."""
    text = re.sub(r"[^0-9a-zA-Z一-鿿]+", " ", title.lower())
    return " ".join(text.split())


def group_prompt(group: dict) -> str:
    """Render a pending group as the compact user message for the model."""
    lines = [
        f"Story group {group.get('id', '?')} | primary source: "
        f"{group.get('primarySource', '?')}",
        "Source items:",
    ]
    for idx, item in enumerate(group.get("items", []), 1):
        lines.append(f"{idx}. [{item.get('source', '?')}] {item.get('title', '')}")
        lines.append(f"   published: {item.get('publishedUtc', '?')}")
        summary = str(item.get("summary") or "").strip()
        if summary:
            lines.append(f"   summary: {summary}")
        lines.append(f"   url: {item.get('url', '')}")
    lines.append("")
    lines.append("Write the bilingual wire story now, following the rules strictly.")
    return "\n".join(lines)


def draft_group(client, group: dict):
    """One Messages API call for one group.

    Returns the parsed draft dict, or None when the model refused or the
    response was truncated. API/network errors propagate to the caller.
    """
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": group_prompt(group)}],
        output_config={"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
    )
    if response.stop_reason == "refusal":
        print(f"write: model refused group {group.get('id')}; skipping")
        return None
    if response.stop_reason == "max_tokens":
        print(f"write: response truncated for group {group.get('id')}; skipping")
        return None
    text = next(
        (block.text for block in response.content
         if getattr(block, "type", None) == "text"),
        None,
    )
    if text is None:
        print(f"write: no text block for group {group.get('id')}; skipping")
        return None
    return json.loads(text)


def build_sources(items: list) -> list:
    """Build the article's sources array in code (never from the LLM)."""
    sources, seen_urls = [], set()
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        key = norm_url(url)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        title = str(item.get("title") or "").strip()
        if len(title) > SOURCE_TITLE_MAX:
            title = title[: SOURCE_TITLE_MAX - 1].rstrip() + "…"
        name = str(item.get("source") or "?")
        if title:
            name = f"{name} — {title}"
        sources.append({"name": name, "url": url})
    return sources


def build_article(draft: dict, group: dict, now, used_ids: set):
    """Assemble one article dict, or None when it cannot credit any source."""
    items = group.get("items", [])
    sources = build_sources(items)
    if not sources:
        print(f"write: group {group.get('id')} has no usable sources; skipping")
        return None
    slug = slugify(str(draft.get("en", {}).get("title") or ""))
    base_id = f"a-{now.strftime('%Y%m%d-%H%M')}-{slug}"
    article_id, n = base_id, 2
    while article_id in used_ids:
        article_id = f"{base_id}-{n}"
        n += 1
    used_ids.add(article_id)
    image = next((item.get("image") for item in items if item.get("image")), None)
    return {
        "id": article_id,
        "publishedUtc": iso_minute(now),
        "cat": draft.get("cat", "ops"),
        "primarySource": group.get("primarySource", ""),
        "image": image,
        "zh": draft.get("zh", {}),
        "en": draft.get("en", {}),
        "sources": sources,
    }


def build_flash(draft: dict, article_id: str, now) -> dict:
    flash = draft.get("flash") or {}
    return {
        "timeUtc": iso_minute(now),
        "hot": bool(flash.get("hot")),
        "zh": str(flash.get("zh") or ""),
        "en": str(flash.get("en") or ""),
        "articleId": article_id,
    }


def build_incident(draft: dict, group: dict, article_id: str):
    incident = draft.get("incident")
    if not isinstance(incident, dict):
        return None
    names = []
    for item in group.get("items", []):
        name = item.get("source")
        if name and name not in names:
            names.append(name)
    row = dict(incident)
    row["sources"] = names
    row["articleId"] = article_id
    return row


def _is_fresh(stamp, cutoff) -> bool:
    try:
        return parse_iso(str(stamp)) >= cutoff
    except (ValueError, TypeError):
        return False


def update_seen(published_groups: list, now) -> None:
    """Record urls + normalized titles of published groups; prune old entries."""
    seen = load_json(SEEN_PATH, {})
    if not isinstance(seen, dict):
        seen = {}
    urls = seen.get("urls") if isinstance(seen.get("urls"), dict) else {}
    titles = seen.get("titles") if isinstance(seen.get("titles"), list) else []
    stamp = iso_minute(now)
    known_titles = {row[0] for row in titles if isinstance(row, list) and row}
    for group in published_groups:
        for item in group.get("items", []):
            url = str(item.get("url") or "").strip()
            if url:
                urls.setdefault(norm_url(url), stamp)
            title = _norm_title(str(item.get("title") or ""))
            if title and title not in known_titles:
                known_titles.add(title)
                titles.append([title, stamp])
    cutoff = now - timedelta(days=SEEN_MAX_AGE_DAYS)
    urls = {u: d for u, d in urls.items() if _is_fresh(d, cutoff)}
    titles = [
        row for row in titles
        if isinstance(row, list) and len(row) == 2 and _is_fresh(row[1], cutoff)
    ]
    save_json(SEEN_PATH, {"urls": urls, "titles": titles})


def refresh_stats(now) -> None:
    """Rewrite stats.json: updatedUtc, seriousThisWeek, optional FlightAware."""
    stats = {"updatedUtc": iso_minute(now)}
    incidents = load_json(INCIDENTS_PATH, [])
    if not isinstance(incidents, list):
        incidents = []
    cutoff = now - timedelta(days=SERIOUS_WINDOW_DAYS)
    serious = 0
    for row in incidents:
        if isinstance(row, dict) and row.get("sev") in ("acc", "ser") \
                and _is_fresh(row.get("date"), cutoff):
            serious += 1
    stats["seriousThisWeek"] = serious
    raw = load_json(FLIGHTAWARE_RAW_PATH, {})
    fa_stats = raw.get("stats") if isinstance(raw, dict) else None
    if isinstance(fa_stats, dict):
        for key in ("flightsTracked", "delayRate", "notams"):
            value = fa_stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                stats[key] = value
    save_json(STATS_PATH, stats)


def _write_articles_batch(articles: list, now) -> None:
    path = ARTICLES_DIR / (now.strftime("%Y-%m-%dT%H") + ".json")
    existing = load_json(path, {})
    merged = existing.get("articles") if isinstance(existing, dict) else None
    if not isinstance(merged, list):
        merged = []
    save_json(path, {"articles": merged + articles})


def _prepend_capped(path, new_rows: list, cap: int) -> None:
    old = load_json(path, [])
    if not isinstance(old, list):
        old = []
    save_json(path, (new_rows + old)[:cap])


def main() -> None:
    now = now_utc()
    pending = load_json(PENDING_PATH, {})
    if not isinstance(pending, dict):
        pending = {}
    groups = pending.get("groups")
    if not isinstance(groups, list):
        groups = []

    if not os.environ.get("ANTHROPIC_API_KEY") or anthropic is None:
        print("write: ANTHROPIC_API_KEY not set; skipping article generation")
        refresh_stats(now)
        return

    if not groups:
        print("write: no pending groups")
        refresh_stats(now)
        return

    client = anthropic.Anthropic()
    used_ids: set = set()
    new_articles, new_flashes, new_incidents = [], [], []
    published_groups, published_ids = [], set()
    skipped = 0

    for group in groups[:MAX_GROUPS_PER_RUN]:
        try:
            draft = draft_group(client, group)
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            print(f"write: API error on group {group.get('id')}: "
                  f"{type(exc).__name__}; skipping")
            skipped += 1
            continue
        except Exception as exc:  # never let one bad group kill the run
            print(f"write: unexpected error on group {group.get('id')}: "
                  f"{type(exc).__name__}: {exc}; skipping")
            skipped += 1
            continue
        if not isinstance(draft, dict):
            skipped += 1
            continue
        article = build_article(draft, group, now, used_ids)
        if article is None:
            skipped += 1
            continue
        new_articles.append(article)
        new_flashes.append(build_flash(draft, article["id"], now))
        incident = build_incident(draft, group, article["id"])
        if incident is not None:
            new_incidents.append(incident)
        published_groups.append(group)
        published_ids.add(group.get("id"))

    if new_articles:
        _write_articles_batch(new_articles, now)
        _prepend_capped(FLASHES_PATH, new_flashes, MAX_FLASHES)
        _prepend_capped(INCIDENTS_PATH, new_incidents, MAX_INCIDENTS)
        update_seen(published_groups, now)
        remaining = [g for g in groups if g.get("id") not in published_ids]
        save_json(PENDING_PATH, {**pending, "groups": remaining})

    refresh_stats(now)
    print(f"write: published {len(new_articles)} article(s), "
          f"skipped {skipped}, pending {max(len(groups) - len(new_articles), 0)}")


if __name__ == "__main__":
    main()
