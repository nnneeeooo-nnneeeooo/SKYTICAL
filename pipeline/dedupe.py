"""Dedupe stage: data/raw/*.json -> data/pending.json.

Reads every raw source snapshot, drops items that are already known
(URL match or fuzzy title match against data/seen.json), stale (older
than the freshness window, 48 h by default) or untitled, then merges
cross-source coverage of the same story into ranked groups for write.py.

data/seen.json is READ-ONLY here — write.py owns it (see CONTRACTS.md).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from common import (
    DATA_DIR,
    FUTURE_SKEW_HOURS,
    NEWS_MAX_AGE_HOURS,
    RAW_DIR,
    SOURCES,
    group_has_material,
    iso_minute,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
)

MAX_GROUPS = 12          # emitted per run; bounds LLM cost in write.py
MAX_ITEMS_PER_GROUP = 5
# Freshness window: single source of truth in common.NEWS_MAX_AGE_HOURS
# (env NEWS_MAX_AGE_HOURS, validated, default 120).
MAX_ITEM_AGE_HOURS = NEWS_MAX_AGE_HOURS
SEEN_TITLE_DAYS = 21     # only seen.json titles this recent are compared
SEEN_TITLE_SIM = 0.75    # vs seen.json titles -> drop as already covered
GROUP_TITLE_SIM = 0.60   # between fresh items -> same story group

_PUNCT_RE = re.compile(r"[^\w\s]|_")
_WS_RE = re.compile(r"\s+")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SOURCE_ORDER = {key: i for i, key in enumerate(SOURCES)}


def norm_title(title: str) -> str:
    """Normalize a headline for fuzzy matching: lowercase, punctuation
    stripped, whitespace collapsed, trailing " - <source>" dropped."""
    text = title.strip()
    head, sep, tail = text.rpartition(" - ")
    if sep and head.strip() and 0 < len(tail.strip()) <= 40:
        text = head
    text = _PUNCT_RE.sub(" ", text.lower())
    return _WS_RE.sub(" ", text).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _published(item: dict) -> datetime | None:
    try:
        return parse_iso(str(item["publishedUtc"]))
    except (KeyError, TypeError, ValueError):
        return None


def _load_raw_items() -> list[dict]:
    """All items from data/raw/<key>.json snapshots, each annotated with the
    source display name and key. ok=false snapshots are NOT skipped: fetch.py
    carries the previous items forward on failure so unpublished stories
    survive a flapping source (staleness is bounded by the 48h age filter)."""
    items: list[dict] = []
    for key, source in SOURCES.items():
        snapshot = load_json(RAW_DIR / f"{key}.json", None)
        if not isinstance(snapshot, dict):
            continue
        raw_items = snapshot.get("items")
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            item = dict(raw)
            item["source"] = source["name"]
            item["sourceKey"] = key
            items.append(item)
    return items


def _load_seen(now: datetime) -> tuple[set[str], list[str]]:
    """Normalized URLs plus normalized titles (last SEEN_TITLE_DAYS only)
    from data/seen.json. Malformed entries are skipped."""
    seen = load_json(DATA_DIR / "seen.json", {})
    if not isinstance(seen, dict):
        seen = {}
    urls = {norm_url(str(url)) for url in (seen.get("urls") or {})}
    cutoff = now - timedelta(days=SEEN_TITLE_DAYS)
    titles: list[str] = []
    for entry in seen.get("titles") or []:
        try:
            title, first_seen = str(entry[0]), parse_iso(str(entry[1]))
        except (LookupError, TypeError, ValueError):
            continue
        normalized = norm_title(title)
        if normalized and first_seen >= cutoff:
            titles.append(normalized)
    return urls, titles


def _is_fresh(
    item: dict, now: datetime, seen_urls: set[str], seen_titles: list[str],
    stats: dict,
) -> bool:
    title = str(item.get("title") or "").strip()
    if not title:
        stats["skipped_untitled"] += 1
        return False
    url = str(item.get("url") or "").strip()
    if url and norm_url(url) in seen_urls:
        stats["skipped_seen_url"] += 1
        return False
    published = _published(item)
    if published is not None:
        if now - published > timedelta(hours=MAX_ITEM_AGE_HOURS):
            stats["skipped_too_old"] += 1
            return False
        if published - now > timedelta(hours=FUTURE_SKEW_HOURS):
            # Beyond timezone/parse skew: a source clock error, not news.
            stats["skipped_future_date"] += 1
            return False
    normalized = norm_title(title)
    if normalized:
        for seen_title in seen_titles:
            if _similar(normalized, seen_title) >= SEEN_TITLE_SIM:
                stats["skipped_seen_title"] += 1
                return False
    return True


def _group(items: list[dict]) -> list[list[dict]]:
    """Union-find: same normalized URL or title similarity >= GROUP_TITLE_SIM
    puts two items in the same group."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    urls = [norm_url(str(item.get("url") or "")) for item in items]
    titles = [norm_title(str(item.get("title") or "")) for item in items]

    first_by_url: dict[str, int] = {}
    for i, url in enumerate(urls):
        if not url:
            continue
        if url in first_by_url:
            union(first_by_url[url], i)
        else:
            first_by_url[url] = i

    for i in range(len(items)):
        if not titles[i]:
            continue
        for j in range(i + 1, len(items)):
            if titles[j] and _similar(titles[i], titles[j]) >= GROUP_TITLE_SIM:
                union(i, j)

    grouped: dict[int, list[dict]] = {}
    for i, item in enumerate(items):
        grouped.setdefault(find(i), []).append(item)
    return list(grouped.values())


def _best_first(members: list[dict]) -> list[dict]:
    """Longest summary first; ties broken by SOURCES registry order."""
    return sorted(
        members,
        key=lambda item: (
            -len(str(item.get("summary") or "")),
            _SOURCE_ORDER.get(item.get("sourceKey"), len(_SOURCE_ORDER)),
        ),
    )


def main() -> None:
    now = now_utc()
    raw_items = _load_raw_items()
    seen_urls, seen_titles = _load_seen(now)
    stats = {key: 0 for key in (
        "skipped_untitled", "skipped_seen_url", "skipped_too_old",
        "skipped_future_date", "skipped_seen_title")}
    fresh = [
        item
        for item in raw_items
        if _is_fresh(item, now, seen_urls, seen_titles, stats)
    ]

    # Rank: groups that actually carry summary material FIRST (title-only
    # groups cannot survive the evidence rules, so they must never crowd
    # real stories out of the MAX_GROUPS cap - and the Google-News-fed
    # sources produce title-only MULTI-source groups all the time), then
    # cross-source coverage, then recency.
    ranked: list[tuple[bool, bool, datetime, list[dict]]] = []
    for members in _group(fresh):
        members = _best_first(members)[:MAX_ITEMS_PER_GROUP]
        newest = max((_published(m) or _EPOCH for m in members), default=_EPOCH)
        multi = len({m["sourceKey"] for m in members}) > 1
        material = group_has_material({"items": members})
        ranked.append((material, multi, newest, members))
    ranked.sort(key=lambda entry: (entry[0], entry[1], entry[2]), reverse=True)
    material_groups = sum(1 for entry in ranked if entry[0])

    stamp = now.strftime("%Y%m%d-%H%M")
    payload = {
        "generatedUtc": iso_minute(now),
        "groups": [
            {
                "id": f"g-{stamp}-{n}",
                "primarySource": members[0]["source"],
                "items": members,
            }
            for n, (_material, _multi, _newest, members) in enumerate(
                ranked[:MAX_GROUPS], start=1
            )
        ],
    }
    save_json(DATA_DIR / "pending.json", payload)
    print(
        f"dedupe: {len(raw_items)} raw items -> {len(fresh)} fresh "
        f"-> {len(payload['groups'])} groups"
    )
    print(
        "dedupe stats: window={}h sources={} {} "
        "groups_with_material={}/{}".format(
            MAX_ITEM_AGE_HOURS, len(SOURCES),
            " ".join(f"{k}={v}" for k, v in stats.items()),
            min(material_groups, MAX_GROUPS), len(payload["groups"]),
        )
    )


if __name__ == "__main__":
    main()
