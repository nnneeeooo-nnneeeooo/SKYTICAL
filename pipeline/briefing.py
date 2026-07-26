"""briefing.py — thrice-daily air & transport briefing assembler.

Selects already-verified articles (data/articles/) whose source time falls
inside a fixed 8-hour Asia/Taipei window, deduplicates events across
editions via a persistent event index, and writes one briefing JSON per
edition to data/briefings/. Assembly is deterministic by default: verified
headlines and summaries are reused as-is and no model is called. At most
one optional batch LLM call per edition (BRIEFING_LLM_INTRO=true) may add
an intro paragraph; any failure falls back to the deterministic output.

Never fetches the network for content and never bypasses the editorial
gate: rejected groups never reach data/articles/, and manual_review items
stay in data/review.json until a human approves them, so reading only the
published article store enforces both exclusions structurally.

Editions (config/briefing_editions.json is the single source of truth):
  morning    23:00 (previous day) <= source_time < 07:00, runs 07:15 TPE
  afternoon  07:00               <= source_time < 15:00, runs 15:15 TPE
  evening    15:00               <= source_time < 23:00, runs 23:15 TPE
Windows are half-open and fixed: a delayed run never widens or shifts them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ARTICLES_DIR,
    DATA_DIR,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
    squash_text,
)

# Asia/Taipei has had a fixed +08:00 offset with no DST since 1980, so the
# static fallback (Windows without tzdata) is exact.
try:
    from zoneinfo import ZoneInfo

    TPE = ZoneInfo("Asia/Taipei")
except Exception:  # pragma: no cover
    TPE = timezone(timedelta(hours=8), "UTC+8")

ROOT = Path(__file__).resolve().parent.parent
EDITIONS_PATH = ROOT / "config" / "briefing_editions.json"
BRIEFINGS_DIR = DATA_DIR / "briefings"
INDEX_PATH = BRIEFINGS_DIR / "index.json"
EVENT_INDEX_PATH = BRIEFINGS_DIR / "event_index.json"

# GitHub Actions cron (UTC) -> edition. briefing.yml must use the same
# mapping; test_briefing.py cross-checks both against the edition config.
CRON_TO_EDITION = {
    "15 23 * * *": "morning",
    "15 7 * * *": "afternoon",
    "15 15 * * *": "evening",
}

SECTIONS = ("aviation_incidents", "taiwan_aviation",
            "international_aviation", "ground_and_maritime")

# Event-index retention: incidents/investigations/policy keep 30 days for
# update matching; everything else 72 hours (spec minimum).
RETAIN_HOURS_DEFAULT = 72
RETAIN_HOURS_LONG = 30 * 24

_SEVERITY_RANK = {"fatal": 3, "serious": 2, "significant": 1, "routine": 0}


def _int_setting(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        print(f"config: {name}={raw!r} is not an integer; using {default}")
        return default
    if not low <= value <= high:
        print(f"config: {name}={value} outside [{low}, {high}]; "
              f"using {default}")
        return default
    return value


MAX_ITEMS = _int_setting("BRIEFING_MAX_ITEMS", 15, 1, 50)
MAX_ITEMS_PER_SECTION = _int_setting("BRIEFING_MAX_ITEMS_PER_SECTION",
                                     6, 1, 20)
EXTRA_LLM_CALLS_MAX = _int_setting("BRIEFING_EXTRA_LLM_CALLS_MAX", 1, 0, 3)


def _llm_intro_enabled() -> bool:
    return (os.environ.get("BRIEFING_LLM_INTRO", "").strip().lower()
            in ("1", "true", "yes"))


def load_editions() -> dict:
    editions = load_json(EDITIONS_PATH, None)
    if not isinstance(editions, dict) or set(editions) != {
            "morning", "afternoon", "evening"}:
        raise SystemExit(f"briefing: bad or missing {EDITIONS_PATH}")
    return editions


# ── fixed window ─────────────────────────────────────────────────────────────

@dataclass
class BriefingWindow:
    edition: str
    date: date  # Taipei calendar date the edition belongs to
    window_start: datetime  # aware, Asia/Taipei
    window_end: datetime
    cutoff_time: datetime
    scheduled_time: datetime
    timezone: str = "Asia/Taipei"

    @property
    def briefing_id(self) -> str:
        return f"{self.date.isoformat()}-{self.edition}"

    def contains(self, dt: datetime) -> bool:
        """Half-open [window_start, window_end) — compared in UTC."""
        if dt.tzinfo is None:
            raise ValueError("briefing window comparisons need aware datetimes")
        t = dt.astimezone(timezone.utc)
        return (self.window_start.astimezone(timezone.utc) <= t
                < self.window_end.astimezone(timezone.utc))


def get_briefing_window(edition: str, taipei_date: date) -> BriefingWindow:
    """Fixed 8-hour window for one edition on one Taipei date.

    Derived only from the edition config and the date — never from the
    clock — so a delayed Actions run keeps the exact same window.
    """
    cfg = load_editions().get(edition)
    if cfg is None:
        raise ValueError(f"unknown edition {edition!r}")
    start_day = taipei_date + timedelta(days=int(cfg["window_start_day_offset"]))
    return BriefingWindow(
        edition=edition,
        date=taipei_date,
        window_start=datetime.combine(
            start_day, time(int(cfg["window_start_hour"])), tzinfo=TPE),
        window_end=datetime.combine(
            taipei_date, time(int(cfg["window_end_hour"])), tzinfo=TPE),
        cutoff_time=datetime.combine(
            taipei_date, time(int(cfg["cutoff_hour"])), tzinfo=TPE),
        scheduled_time=datetime.combine(
            taipei_date,
            time(int(cfg["scheduled_hour"]), int(cfg["scheduled_minute"])),
            tzinfo=TPE),
    )


# ── article classification (deterministic, from existing metadata) ──────────

_TAIWAN_MARKERS = (
    "民航局", "臺灣", "台灣", "桃園機場", "桃園國際機場", "松山機場", "小港機場",
    "澎湖", "金門", "馬祖", "中華航空", "華航", "長榮航空", "星宇航空",
    "台灣虎航", "臺灣虎航", "立榮航空", "華信航空", "taiwan", "taoyuan",
    "caa taiwan", "china airlines", "eva air", "starlux", "tigerair taiwan",
    "uni air", "mandarin airlines",
)
_GROUND_MARKERS = (
    "台鐵", "臺鐵", "高鐵", "捷運", "輕軌", "鐵路", "國道客運", "公路重大",
    "railway", "high-speed rail", "metro line", "light rail", "train derail",
)
_MARITIME_MARKERS = (
    "港務", "航港", "海運", "商港", "貨輪", "客輪", "渡輪", "船舶",
    "maritime", "ferry", "cargo ship", "container ship", "port authority",
    "vessel",
)
_MILITARY_MARKERS = (
    "軍機", "國軍", "空軍", "軍用機", "military aircraft", "air force",
    "fighter jet",
)
_FATAL_MARKERS = (
    "罹難", "死亡", "喪生", "身亡", "fatal", "killed", "fatalities", "died",
)
_SERIOUS_MARKERS = (
    "墜毀", "墜機", "失事", "失聯", "劫機", "迫降", "crash", "crashed",
    "hull loss", "mayday", "hijack", "emergency landing",
)

_IDENT_RE = re.compile(
    r"\b(?:[A-Z]{2}\d{2,4}|B-[A-Z0-9]{4,5}|N\d{2,5}[A-Z]{0,2}"
    r"|9M-[A-Z]{3}|JA\d{3,4}[A-Z]?)\b")


def _entity_values(article: dict) -> list[str]:
    ents = article.get("entities") or {}
    values: list[str] = []
    if isinstance(ents, dict):
        for group in ents.values():
            if isinstance(group, list):
                values.extend(str(v) for v in group if v)
    return values


def _text_blob(article: dict) -> str:
    parts = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.append(str(block.get("title") or ""))
        parts.append(str(block.get("summary") or ""))
    for fact in article.get("facts") or []:
        if isinstance(fact, dict):
            parts.append(str(fact.get("claim") or ""))
    parts.extend(_entity_values(article))
    return squash_text(" ".join(parts))


def _has_marker(blob: str, markers: tuple[str, ...]) -> bool:
    return any(m.casefold() in blob for m in markers)


def classify_section(article: dict) -> str:
    blob = _text_blob(article)
    if _has_marker(blob, _GROUND_MARKERS) or _has_marker(blob, _MARITIME_MARKERS):
        return "ground_and_maritime"
    if article.get("cat") == "safety":
        return "aviation_incidents"
    if _has_marker(blob, _TAIWAN_MARKERS):
        return "taiwan_aviation"
    return "international_aviation"


def item_category(article: dict, section: str) -> str:
    if section == "aviation_incidents":
        return "aviation_incident"
    if section == "taiwan_aviation":
        return "taiwan_aviation"
    if section == "ground_and_maritime":
        blob = _text_blob(article)
        return ("maritime" if _has_marker(blob, _MARITIME_MARKERS)
                else "ground_transport")
    return "aviation_industry"


def classify_severity(article: dict) -> str:
    blob = _text_blob(article)
    if _has_marker(blob, _FATAL_MARKERS):
        return "fatal"
    if _has_marker(blob, _SERIOUS_MARKERS):
        return "serious"
    if article.get("cat") == "safety":
        return "significant"
    return "routine"


# ── event identity & dedup index ─────────────────────────────────────────────

def article_source_time(article: dict) -> datetime | None:
    """Source-verified time when present, else our verified-publish time.

    Half-open windows partition all time, so every article lands in exactly
    one edition either way; the fallback is our own honest timestamp, never
    an invented source time.
    """
    for key in ("sourcePublishedUtc", "publishedUtc"):
        raw = article.get(key)
        if raw:
            try:
                return parse_iso(str(raw))
            except ValueError:
                continue
    return None


def _canonical_urls(article: dict) -> list[str]:
    urls = []
    for src in article.get("sources") or []:
        url = (src or {}).get("url")
        if url:
            urls.append(norm_url(str(url)))
    return sorted(set(urls))


def _fact_keys(article: dict) -> list[str]:
    keys = set()
    for fact in article.get("facts") or []:
        if isinstance(fact, dict) and fact.get("claim"):
            keys.add(squash_text(fact["claim"]))
    return sorted(keys)


def event_fingerprint(article: dict, section: str) -> str:
    """Stable identity for one real-world event.

    Built from category, core entities, locations, vehicle identifiers and
    the event date — never from edition, AI headline, generated_at or list
    position, so the id survives retitles and later editions. Canonical
    source URLs are deliberately NOT hashed (a reprint has a new URL but is
    the same event); they are kept in the index as alternate match keys.
    """
    ents = article.get("entities") or {}

    def _vals(key):
        vals = ents.get(key) if isinstance(ents, dict) else None
        return sorted({squash_text(v) for v in vals or [] if v})[:6]

    src_time = article_source_time(article)
    idents = sorted(set(_IDENT_RE.findall(
        " ".join([str((article.get("en") or {}).get("title") or "")]
                 + [str(f.get("claim") or "") for f in article.get("facts") or []
                    if isinstance(f, dict)]))))
    core = {
        "section": section,
        "organizations": _vals("organizations"),
        "locations": _vals("locations"),
        "idents": idents,
        "event_date": (src_time.astimezone(TPE).date().isoformat()
                       if src_time else None),
        "event_type": article.get("cat"),
    }
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_event_index() -> dict:
    data = load_json(EVENT_INDEX_PATH, {})
    events = data.get("events")
    return {"events": events if isinstance(events, dict) else {}}


def prune_event_index(index: dict, now: datetime) -> None:
    events = index["events"]
    for event_id in list(events):
        raw = events[event_id].get("retain_until")
        try:
            if raw and parse_iso(raw) < now:
                del events[event_id]
        except ValueError:
            del events[event_id]


def _find_event(index: dict, event_id: str, urls: list[str]):
    events = index["events"]
    if event_id in events:
        return event_id, events[event_id]
    url_set = set(urls)
    for eid, event in events.items():
        if url_set & set(event.get("urls") or []):
            return eid, event
    return None, None


def _retain_until(section: str, cat, now: datetime) -> str:
    hours = (RETAIN_HOURS_LONG
             if section == "aviation_incidents" or cat == "reg"
             else RETAIN_HOURS_DEFAULT)
    return (now + timedelta(hours=hours)).isoformat()


# ── selection & assembly ─────────────────────────────────────────────────────

def load_published_articles() -> tuple[list[dict], list[str]]:
    """All published articles + warnings for unreadable batch files."""
    articles, warnings = [], []
    if not ARTICLES_DIR.is_dir():
        return articles, warnings
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                batch = json.load(fh)
        except (OSError, json.JSONDecodeError):
            warnings.append(f"article batch unreadable: {path.name}")
            continue
        for article in batch.get("articles") or []:
            if isinstance(article, dict):
                articles.append(article)
    return articles, warnings


def _eligible(article: dict) -> bool:
    zh = article.get("zh") or {}
    return bool(str(zh.get("title") or "").strip()
                and str(zh.get("summary") or "").strip()
                and _canonical_urls(article))


def _build_item(article: dict, section: str, event_id: str,
                item_type: str, previous_event_id, new_information):
    zh = article.get("zh") or {}
    en = article.get("en") or {}
    src_time = article_source_time(article)
    ents = article.get("entities") or {}
    locations = [str(v) for v in (ents.get("locations") or [])
                 if v] if isinstance(ents, dict) else []
    blob = _text_blob(article)
    item = {
        "event_id": event_id,
        "item_type": item_type,
        "previous_event_id": previous_event_id,
        "category": item_category(article, section),
        "headline": str(zh.get("title") or "").strip(),
        "summary": str(zh.get("summary") or "").strip(),
        "headline_en": str(en.get("title") or "").strip(),
        "summary_en": str(en.get("summary") or "").strip(),
        "event_time": None,
        "source_published_at": src_time.isoformat() if src_time else None,
        "source_updated_at": None,
        "location": locations[0] if locations else None,
        "entities": _entity_values(article)[:10],
        "severity": classify_severity(article),
        "taiwan_priority": _has_marker(blob, _TAIWAN_MARKERS),
        "military": _has_marker(blob, _MILITARY_MARKERS),
        "sources": [{"name": str((s or {}).get("name") or ""),
                     "url": str((s or {}).get("url") or "")}
                    for s in article.get("sources") or []
                    if (s or {}).get("url")],
        "risk_flags": list(article.get("riskFlags") or []),
        "article_id": article.get("id"),
    }
    if item_type == "update":
        item["new_information"] = list(new_information or [])
    return item


def select_items(articles: list[dict], window: BriefingWindow,
                 event_index: dict, now: datetime,
                 warnings: list[str]) -> list[tuple[str, dict]]:
    """(section, item) pairs for this window; mutates event_index."""
    events = event_index["events"]
    briefing_id = window.briefing_id
    in_window = []
    for article in articles:
        src_time = article_source_time(article)
        if src_time is None or not window.contains(src_time):
            continue
        if not _eligible(article):
            warnings.append(
                f"article {article.get('id')} skipped: missing verified "
                f"headline/summary or source URL")
            continue
        in_window.append((src_time, article))
    in_window.sort(key=lambda pair: pair[0], reverse=True)

    picked: list[tuple[str, dict]] = []
    emitted: set[str] = set()
    for src_time, article in in_window:
        section = classify_section(article)
        fingerprint = event_fingerprint(article, section)
        event_id = "ev-" + fingerprint[:16]
        urls = _canonical_urls(article)
        facts = _fact_keys(article)
        matched_id, event = _find_event(event_index, event_id, urls)
        if matched_id:
            event_id = matched_id

        if event_id in emitted:
            continue  # one item per event per edition

        if event is None:
            events[event_id] = {
                "fingerprint": fingerprint,
                "urls": urls,
                "section": section,
                "cat": article.get("cat"),
                "first_seen": now.isoformat(),
                "last_seen": now.isoformat(),
                "first_briefing_id": briefing_id,
                "article_ids": [article.get("id")],
                "fact_keys": facts,
                "updates": {},
                "retain_until": _retain_until(section, article.get("cat"), now),
            }
            picked.append((section, _build_item(
                article, section, event_id, "new", None, None)))
            emitted.add(event_id)
            continue

        if event.get("first_briefing_id") == briefing_id:
            # Re-run of the same edition: rebuild the same item.
            picked.append((section, _build_item(
                article, section, event_id, "new", None, None)))
            emitted.add(event_id)
            continue

        prior_updates = event.get("updates") or {}
        if briefing_id in prior_updates:
            # Re-run: the update was already accepted for this edition.
            picked.append((section, _build_item(
                article, section, event_id, "update", event_id,
                prior_updates[briefing_id].get("new_information"))))
            emitted.add(event_id)
            continue

        new_facts = [f for f in facts if f not in set(event.get("fact_keys") or [])]
        if not new_facts:
            # Same event, nothing substantive: retitles/reprints are not
            # updates. Remember the extra URLs so later reprints match too.
            event["urls"] = sorted(set(event.get("urls") or []) | set(urls))
            event["last_seen"] = now.isoformat()
            continue

        original_claims = [
            str(f.get("claim")) for f in article.get("facts") or []
            if isinstance(f, dict) and f.get("claim")
            and squash_text(f["claim"]) in set(new_facts)]
        event["fact_keys"] = sorted(set(event.get("fact_keys") or [])
                                    | set(facts))
        event["urls"] = sorted(set(event.get("urls") or []) | set(urls))
        event["last_seen"] = now.isoformat()
        event.setdefault("article_ids", []).append(article.get("id"))
        event.setdefault("updates", {})[briefing_id] = {
            "article_id": article.get("id"),
            "new_information": original_claims,
        }
        picked.append((section, _build_item(
            article, section, event_id, "update", event_id, original_claims)))
        emitted.add(event_id)
    return picked


def arrange_sections(picked: list[tuple[str, dict]],
                     warnings: list[str]) -> dict:
    sections = {name: [] for name in SECTIONS}
    for section, item in picked:
        sections[section].append(item)

    def sort_key(item):
        return (-_SEVERITY_RANK.get(item.get("severity"), 0),
                not item.get("taiwan_priority"),
                item.get("source_published_at") or "")

    dropped = 0
    for name in SECTIONS:
        rows = sorted(sections[name], key=sort_key)
        if len(rows) > MAX_ITEMS_PER_SECTION:
            dropped += len(rows) - MAX_ITEMS_PER_SECTION
            rows = rows[:MAX_ITEMS_PER_SECTION]
        sections[name] = rows

    total = sum(len(v) for v in sections.values())
    if total > MAX_ITEMS:
        overflow = total - MAX_ITEMS
        dropped += overflow
        # Trim from the least critical end of the section priority order.
        for name in reversed(SECTIONS):
            while overflow and sections[name]:
                sections[name].pop()
                overflow -= 1
    if dropped:
        warnings.append(f"{dropped} item(s) dropped by "
                        f"BRIEFING_MAX_ITEMS/_PER_SECTION caps")
    return sections


# ── optional single batch LLM intro ──────────────────────────────────────────

INTRO_SCHEMA = {
    "type": "object",
    "properties": {
        "introZh": {"type": "string"},
        "introEn": {"type": "string"},
    },
    "required": ["introZh", "introEn"],
    "additionalProperties": False,
}

INTRO_SYSTEM_PROMPT = (
    "You write a 1-2 sentence neutral intro for a transport-news briefing. "
    "Use ONLY the items given; add no outside facts, numbers, names or "
    "speculation. Return JSON {\"introZh\": \"...\", \"introEn\": \"...\"} — "
    "Traditional Chinese (Taiwan usage) and English. Each 30-160 characters."
)


def _intro_digest(sections: dict) -> str:
    lines = []
    for name in SECTIONS:
        for item in sections[name]:
            lines.append(f"- [{name}] {item['headline']} — {item['summary']}")
    return "\n".join(lines)


def maybe_llm_intro(briefing: dict, sections: dict,
                    warnings: list[str]) -> None:
    """At most EXTRA_LLM_CALLS_MAX (default 1) batch calls per edition.

    Zero items or the flag off → zero calls. Any failure leaves the
    deterministic briefing untouched.
    """
    total = sum(len(v) for v in sections.values())
    if not _llm_intro_enabled() or total == 0 or EXTRA_LLM_CALLS_MAX <= 0:
        return
    try:
        from providers import build_providers

        providers = [p for p in build_providers() if p.available()]
    except Exception as exc:  # provider layer unusable → deterministic
        warnings.append(f"intro skipped: providers unavailable ({exc})")
        return
    calls = 0
    for provider in providers:
        if calls >= EXTRA_LLM_CALLS_MAX:
            break
        calls += 1
        try:
            draft = provider.draft(INTRO_SYSTEM_PROMPT,
                                   _intro_digest(sections), INTRO_SCHEMA)
        except Exception as exc:
            warnings.append(f"intro call failed on {provider.name}: "
                            f"{type(exc).__name__}")
            continue
        if not isinstance(draft, dict):
            warnings.append(f"intro refused/empty on {provider.name}")
            continue
        intro_zh = str(draft.get("introZh") or "").strip()
        intro_en = str(draft.get("introEn") or "").strip()
        if not (10 <= len(intro_zh) <= 300 and 10 <= len(intro_en) <= 400):
            warnings.append("intro discarded: length outside bounds")
            continue
        briefing["intro_zh"] = intro_zh
        briefing["intro_en"] = intro_en
        briefing["generation_mode"] = "llm_assisted"
        briefing["generation_model"] = {"provider": provider.name,
                                        "model": provider.model}
        return
    # all attempts failed → deterministic output stands


# ── assembly, persistence ────────────────────────────────────────────────────

def checked_sources_snapshot() -> tuple[list[dict], list[str]]:
    rows, warnings = [], []
    for src in load_json(DATA_DIR / "sources.json", []) or []:
        if not isinstance(src, dict):
            continue
        if src.get("kind") == "data":
            # Data platforms (e.g. the optional FlightAware stats API)
            # never feed news candidates; their status is not briefing
            # coverage.
            continue
        row = {"name": src.get("name"), "ok": bool(src.get("ok")),
               "last_fetch_utc": src.get("lastFetchUtc")}
        rows.append(row)
        if not row["ok"]:
            warnings.append(f"source fetch failing: {row['name']} — a fetch "
                            f"failure is a coverage gap, not an absence of "
                            f"events")
    return rows, warnings


def assemble_briefing(window: BriefingWindow, sections: dict,
                      checked_sources: list[dict], warnings: list[str],
                      generated_at: datetime, partial: bool) -> dict:
    cfg = load_editions()[window.edition]
    total = sum(len(v) for v in sections.values())
    return {
        "content_type": "daily_transport_briefing",
        "briefing_id": window.briefing_id,
        "date": window.date.isoformat(),
        "edition": window.edition,
        "edition_label": cfg["label_zh_tw"],
        "timezone": window.timezone,
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "cutoff_time": window.cutoff_time.isoformat(),
        "scheduled_time": window.scheduled_time.isoformat(),
        "generated_at": generated_at.astimezone(TPE).isoformat(),
        "status": "partial" if partial else "published",
        "item_count": total,
        "sections": sections,
        "checked_sources": checked_sources,
        "warnings": warnings,
        "generation_mode": "deterministic",
        "generation_model": None,
    }


def _briefing_changed(old, new) -> bool:
    if not isinstance(old, dict):
        return True
    ignore = ("generated_at",)
    a = {k: v for k, v in old.items() if k not in ignore}
    b = {k: v for k, v in new.items() if k not in ignore}
    return a != b


def upsert_index_row(row: dict) -> None:
    index = load_json(INDEX_PATH, {"briefings": []})
    rows = [r for r in index.get("briefings") or []
            if isinstance(r, dict)
            and r.get("briefing_id") != row["briefing_id"]]
    rows.append(row)
    rows.sort(key=lambda r: (str(r.get("date") or ""),
                             str(r.get("cutoff_time") or "")), reverse=True)
    new = {"briefings": rows}
    if new != index:
        save_json(INDEX_PATH, new)


def run_edition(edition: str, taipei_date: date) -> int:
    now = now_utc()
    window = get_briefing_window(edition, taipei_date)
    warnings: list[str] = []

    articles, load_warnings = load_published_articles()
    warnings.extend(load_warnings)
    checked_sources, source_warnings = checked_sources_snapshot()
    warnings.extend(source_warnings)

    event_index = load_event_index()
    prune_event_index(event_index, now)
    picked = select_items(articles, window, event_index, now, warnings)
    sections = arrange_sections(picked, warnings)

    # partial = our own inputs were degraded, never "no events".
    partial = bool(load_warnings or source_warnings)
    briefing = assemble_briefing(window, sections, checked_sources,
                                 warnings, now, partial)
    maybe_llm_intro(briefing, sections, warnings)

    path = BRIEFINGS_DIR / f"{window.briefing_id}.json"
    old = load_json(path, None)
    if _briefing_changed(old, briefing):
        save_json(path, briefing)
        save_json(EVENT_INDEX_PATH, event_index)
        changed = "written"
    else:
        changed = "unchanged"

    upsert_index_row({
        "briefing_id": window.briefing_id,
        "date": window.date.isoformat(),
        "edition": edition,
        "status": briefing["status"],
        "cutoff_time": briefing["cutoff_time"],
        "generated_at": briefing["generated_at"],
        "item_count": briefing["item_count"],
    })
    print(f"briefing: {window.briefing_id} status={briefing['status']} "
          f"items={briefing['item_count']} mode={briefing['generation_mode']} "
          f"warnings={len(warnings)} ({changed})")
    return 0


def record_failure(edition: str, taipei_date: date, error: str) -> None:
    """A failed run never touches briefing files, and never downgrades an
    edition that already succeeded (a crashing re-run must not hide the
    previously published briefing)."""
    briefing_id = f"{taipei_date.isoformat()}-{edition}"
    for row in load_json(INDEX_PATH, {}).get("briefings") or []:
        if (isinstance(row, dict) and row.get("briefing_id") == briefing_id
                and row.get("status") in ("published", "partial")):
            print(f"briefing: {briefing_id} already succeeded earlier; "
                  f"failure not recorded over it")
            return
    upsert_index_row({
        "briefing_id": briefing_id,
        "date": taipei_date.isoformat(),
        "edition": edition,
        "status": "failed",
        "cutoff_time": None,
        "generated_at": now_utc().astimezone(TPE).isoformat(),
        "item_count": 0,
        "error": error[:300],
    })


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edition", choices=sorted(CRON_TO_EDITION.values()))
    parser.add_argument("--cron", help="GitHub Actions schedule string; "
                                       "mapped via CRON_TO_EDITION")
    parser.add_argument("--date", help="Taipei date YYYY-MM-DD "
                                       "(default: today in Asia/Taipei)")
    args = parser.parse_args(argv)

    edition = args.edition
    if not edition and args.cron:
        edition = CRON_TO_EDITION.get(args.cron.strip())
        if not edition:
            print(f"briefing: unknown cron {args.cron!r}")
            return 1
    if not edition:
        print("briefing: --edition or --cron required")
        return 1

    if args.date:
        try:
            taipei_date = date.fromisoformat(args.date.strip())
        except ValueError:
            print(f"briefing: bad --date {args.date!r} (want YYYY-MM-DD)")
            return 1
    else:
        taipei_date = now_utc().astimezone(TPE).date()

    try:
        return run_edition(edition, taipei_date)
    except Exception as exc:  # never nuke previous briefings on a crash
        traceback.print_exc()
        record_failure(edition, taipei_date, f"{type(exc).__name__}: {exc}")
        print(f"briefing: FAILED {taipei_date}-{edition}; previous "
              f"briefings left untouched")
        return 0


if __name__ == "__main__":
    sys.exit(main())
