"""Dedupe stage: data/raw/*.json -> data/pending.json.

Reads every raw source snapshot, drops stale/untitled items, merges
cross-source coverage into event groups, then suppresses only groups that
contain no new source URL or headline.  Previously published items stay in
an active group as evidence when a later source covers the same event, so
write.py can revise the existing article instead of losing the new material.

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
    is_taiwan_airline_story,
    iso_minute,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
)

MAX_GROUPS = 12          # emitted per run; bounds LLM cost in write.py
MAX_ITEMS_PER_GROUP = 6
# Freshness window: single source of truth in common.NEWS_MAX_AGE_HOURS
# (env NEWS_MAX_AGE_HOURS, validated, default 120).
MAX_ITEM_AGE_HOURS = NEWS_MAX_AGE_HOURS
SEEN_TITLE_DAYS = 21     # only seen.json titles this recent are compared
SEEN_TITLE_SIM = 0.75    # vs seen.json titles -> drop as already covered
GROUP_TITLE_SIM = 0.60   # between fresh items -> same story group
GROUP_TOKEN_COVERAGE = 0.55
GROUP_TOKEN_JACCARD = 0.38

_PUNCT_RE = re.compile(r"[^\w\s]|_")
_WS_RE = re.compile(r"\s+")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_SOURCE_ORDER = {key: i for i, key in enumerate(SOURCES)}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9+'-]*|[\u3400-\u9fff]{2,}")
_EVENT_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
    "are", "was", "were", "its", "with", "as", "at", "by", "from", "after",
    "before", "new", "latest", "report", "reports", "says", "said", "set",
    "about", "more", "will", "could", "would", "into", "over", "amid",
    "航空", "飛機", "客機", "宣布", "表示", "報導", "最新",
    # Boilerplate in occurrence-feed headlines.  These tokens describe the
    # template, not the identity of an event.
    "incident", "accident", "near", "aug", "sep", "oct", "nov", "dec",
    "jan", "feb", "mar", "apr", "may", "jun", "jul",
}
_EVENT_ACTIONS = {
    "order", "orders", "ordered", "purchase", "buys", "delivery",
    "deliveries", "delivers", "delivered", "certification", "certified",
    "approval", "approved", "launch", "launches", "launched", "flight",
    "flights", "route", "routes", "service", "base", "profit", "loss",
    "revenue", "results", "crash", "incident", "emergency", "diversion",
    "investigation", "inspection", "contract", "agreement", "lease",
    "upgrade", "expands", "expansion", "adds", "additional", "test",
    "testing", "first", "maiden", "訂單", "增購", "交付", "認證", "核准",
    "航線", "首航", "事故", "調查", "合約", "協議", "測試", "財報",
}
_DATE_TOKEN_RE = re.compile(
    r"(?:19|20)\d{2}|\d{1,2}(?:st|nd|rd|th)", re.I)
_AVHERALD_INCIDENT_RE = re.compile(r"^\s*incident\s*:", re.I)


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


def _event_tokens(item: dict) -> set[str]:
    """Significant headline tokens plus a short excerpt.

    The excerpt helps when two publishers lead with different actors, while
    the stopword/action gates below keep generic same-company stories apart.
    """
    text = (
        f"{item.get('title') or ''} "
        f"{str(item.get('summary') or '')[:280]}"
    )
    return {
        token.casefold()
        for token in _TOKEN_RE.findall(text)
        if token.casefold() not in _EVENT_STOPWORDS
        and not _DATE_TOKEN_RE.fullmatch(token)
        and (len(token) >= 3 or any(ch.isdigit() for ch in token))
    }


def _identifier_tokens(tokens: set[str]) -> set[str]:
    """Model, flight, registration and other digit-bearing event anchors."""
    return {token for token in tokens if any(ch.isdigit() for ch in token)}


def same_event(a: dict, b: dict) -> bool:
    """Conservative deterministic event match beyond headline edit distance."""
    title_a = norm_title(str(a.get("title") or ""))
    title_b = norm_title(str(b.get("title") or ""))
    tokens_a, tokens_b = _event_tokens(a), _event_tokens(b)
    overlap = tokens_a & tokens_b
    title_similarity = (
        _similar(title_a, title_b) if title_a and title_b else 0.0
    )
    if title_similarity >= 0.75:
        return True
    if len(overlap) < 3:
        return False
    smaller = min(len(tokens_a), len(tokens_b))
    union = len(tokens_a | tokens_b)
    if not smaller or not union:
        return False
    coverage = len(overlap) / smaller
    jaccard = len(overlap) / union
    shared_identifier = bool(
        _identifier_tokens(tokens_a) & _identifier_tokens(tokens_b)
    )
    shared_action = bool(overlap & _EVENT_ACTIONS)
    return (
        (
            title_similarity >= GROUP_TITLE_SIM
            and (shared_identifier or shared_action)
        )
        or
        (shared_identifier and len(overlap) >= 3 and coverage >= 0.45)
        or (
            shared_action
            and len(overlap) >= 4
            and (
                coverage >= GROUP_TOKEN_COVERAGE
                or jaccard >= GROUP_TOKEN_JACCARD
            )
        )
    )


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


def _is_fresh(item: dict, now: datetime, stats: dict) -> bool:
    title = str(item.get("title") or "").strip()
    if not title:
        stats["skipped_untitled"] += 1
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
    return True


def _is_unseen(
    item: dict, seen_urls: set[str], seen_titles: list[str],
) -> tuple[bool, bool]:
    """Return (is_new_evidence, title_matches_seen).

    A new URL remains useful even when its headline resembles an existing
    article: that is exactly how later cross-source coverage is discovered.
    """
    url = str(item.get("url") or "").strip()
    if url and norm_url(url) not in seen_urls:
        normalized = norm_title(str(item.get("title") or ""))
        return True, bool(
            normalized and any(
                _similar(normalized, title) >= SEEN_TITLE_SIM
                for title in seen_titles
            )
        )
    if url:
        return False, False
    normalized = norm_title(str(item.get("title") or ""))
    if not normalized:
        return False, False
    matched = any(
        _similar(normalized, title) >= SEEN_TITLE_SIM
        for title in seen_titles
    )
    return not matched, matched


def _group(items: list[dict]) -> list[list[dict]]:
    """Union-find: same normalized URL or deterministic event match."""
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
            if titles[j] and same_event(items[i], items[j]):
                union(i, j)

    grouped: dict[int, list[dict]] = {}
    for i, item in enumerate(items):
        grouped.setdefault(find(i), []).append(item)
    return list(grouped.values())


def _is_avherald_incident(item: dict) -> bool:
    """Whether one item is an independent Aviation Herald incident notice."""
    return (
        item.get("sourceKey") == "avherald"
        and bool(_AVHERALD_INCIDENT_RE.match(str(item.get("title") or "")))
    )


def _group_with_kind(items: list[dict]) -> list[tuple[list[dict], str]]:
    """Build event groups, then intentionally collect thin safety notices.

    Aviation Herald headlines use a repeated ``Incident: ... on Aug ...``
    template.  Generic dates and boilerplate must not make them the same
    event.  We may still publish them together, but only as an explicitly
    labelled roundup of independent events.
    """
    ordinary: list[tuple[list[dict], str]] = []
    roundup_items: list[dict] = []
    for members in _group(items):
        if len(members) == 1 and _is_avherald_incident(members[0]):
            roundup_items.extend(members)
        else:
            ordinary.append((members, "event"))

    roundup_items.sort(key=lambda item: _published(item) or _EPOCH,
                       reverse=True)
    if len(roundup_items) < 2:
        ordinary.extend(([item], "event") for item in roundup_items)
        return ordinary
    for start in range(0, len(roundup_items), MAX_ITEMS_PER_GROUP):
        chunk = roundup_items[start:start + MAX_ITEMS_PER_GROUP]
        ordinary.append((chunk, "safety_roundup"
                         if len(chunk) > 1 else "event"))
    return ordinary


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
    eligible = [
        item
        for item in raw_items
        if _is_fresh(item, now, stats)
    ]

    # Rank Taiwan national-carrier coverage first so it cannot be crowded out
    # of the MAX_GROUPS cap. Within each priority tier, groups that actually
    # carry summary material come before title-only groups (which cannot
    # survive the evidence rules), then cross-source coverage and recency.
    ranked: list[
        tuple[bool, bool, bool, datetime, list[dict], bool, str]
    ] = []
    active_items = 0
    for members, group_kind in _group_with_kind(eligible):
        novelty = [_is_unseen(item, seen_urls, seen_titles) for item in members]
        if not any(is_new for is_new, _matched in novelty):
            stats["skipped_seen_url"] += sum(
                1 for item in members
                if str(item.get("url") or "").strip()
            )
            stats["skipped_seen_title"] += sum(
                1 for item, (_is_new, matched) in zip(members, novelty)
                if not str(item.get("url") or "").strip() and matched
            )
            continue
        update_candidate = any(
            norm_url(str(item.get("url") or "")) in seen_urls
            for item in members
            if str(item.get("url") or "").strip()
        ) or any(matched for _is_new, matched in novelty)
        members = _best_first(members)[:MAX_ITEMS_PER_GROUP]
        active_items += len(members)
        newest = max((_published(m) or _EPOCH for m in members), default=_EPOCH)
        multi = len({m["sourceKey"] for m in members}) > 1
        material = (
            group_kind == "safety_roundup"
            or group_has_material({"items": members})
        )
        must_report = is_taiwan_airline_story({"items": members})
        ranked.append((must_report, material, multi, newest, members,
                       update_candidate, group_kind))
    ranked.sort(
        key=lambda entry: (entry[0], entry[1], entry[2], entry[3]),
        reverse=True,
    )
    material_groups = sum(1 for entry in ranked if entry[1])

    stamp = now.strftime("%Y%m%d-%H%M")
    payload = {
        "generatedUtc": iso_minute(now),
        "groups": [
            {
                "id": f"g-{stamp}-{n}",
                "primarySource": members[0]["source"],
                "items": members,
                "updateCandidate": update_candidate,
                "mustReport": must_report,
                "groupKind": group_kind,
                "independentEvents": group_kind == "safety_roundup",
            }
            for n, (
                must_report, _material, _multi, _newest, members,
                update_candidate, group_kind
            ) in enumerate(
                ranked[:MAX_GROUPS], start=1
            )
        ],
    }
    save_json(DATA_DIR / "pending.json", payload)
    print(
        f"dedupe: {len(raw_items)} raw items -> {active_items} fresh "
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
