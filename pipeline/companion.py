"""companion.py — same-topic retrieval for every under-sourced story group.

Owner direction (2026-07-27): keep Simple Flying (and similar excerpt-only
feeds) as a DISCOVERY INDEX - when their item flags a story but carries
almost no text, the PIPELINE (never the model) searches Google News for
the same topic.  The same retrieval now also runs for otherwise substantial
single-source groups, because a long article from one publisher is not
cross-source reporting. Matching coverage from an allowlist of reliable
outlets (config/companion_sources.json) joins the group before drafting.
The model then writes from several real summaries - and, where
a companion comes from a fulltext-allowlisted official host, from the
full page - instead of inventing detail around one sentence.

Guard rails:
- Only allowlisted domains join a group; the outlet is identified from
  Google News' own <source> element, and links are resolved off
  news.google.com when possible; an unresolved aggregator URL is discarded.
- A candidate must share enough significant title tokens with the seed
  headline to count as the same topic.
- Caps: MAX_ITEMS_PER_GROUP companions and MAX_SEARCHES_PER_RUN searches per
  run. Search priority follows the ranked pending groups that can be drafted.
- Companions become ordinary group items: shown in <SOURCE>, quotable and
  machine-verified like everything else, credited in the article footer.
"""
from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    USER_AGENT,
    iso_minute,
    is_google_news_url,
    load_json,
    norm_url,
    squash_text,
)

ROOT = Path(__file__).resolve().parent.parent
_CFG = load_json(ROOT / "config" / "companion_sources.json", {})
DOMAINS = tuple(str(d).casefold() for d in _CFG.get("domains") or [])
MAX_ITEMS_PER_GROUP = int(_CFG.get("max_items_per_group") or 3)
MAX_SEARCHES_PER_RUN = int(_CFG.get("max_searches_per_run") or 2)
MAX_BACKGROUND_SEARCHES_PER_RUN = max(
    0, int(_CFG.get("max_background_searches_per_run", 2)))
MAX_BACKGROUND_ITEMS_PER_GROUP = 1
THIN_MATERIAL_CHARS = int(_CFG.get("thin_material_chars") or 400)
TARGET_MATERIAL_CHARS = int(_CFG.get("target_material_chars") or 1600)
TARGET_SOURCE_COUNT = int(_CFG.get("target_source_count") or 4)

TIMEOUT = (5, 12)
HEADERS = {"User-Agent": USER_AGENT}
SEARCH_WORKERS = 5
RESOLVE_WORKERS = 4
MAX_RESOLVE_CANDIDATES = max(MAX_ITEMS_PER_GROUP * 2, 4)

_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is",
    "are", "was", "were", "its", "his", "her", "their", "this", "that",
    "with", "as", "at", "by", "from", "about", "into", "after", "before",
    "how", "much", "many", "what", "why", "when", "where", "who", "will",
    "would", "could", "should", "has", "have", "had", "be", "been",
    "actually", "during", "revealed", "reveals", "publishes", "published",
    "report", "reports", "article", "analysis", "map", "video", "photos",
    "ever", "long", "awaited", "your", "you", "our", "new", "just",
}
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-']*|[一-鿿]{2,}")
_BACKGROUND_EVENT_WORDS = {
    "first", "first-ever", "rare", "rarely", "unusual", "arrival",
    "arrive", "arrives", "arrived", "landing", "lands", "landed",
    "flight", "flights", "ferry", "ferried", "sighting", "seen",
    "returns", "return", "returned", "visits", "visit", "visited",
    "today", "yesterday", "桃園", "抵達", "飛抵", "罕見", "少見",
    "首度", "首次", "再度", "重返", "今日", "昨天",
}
_BACKGROUND_TERMS = (
    "(fleet OR route OR routes OR maintenance OR history OR operations "
    "OR airport OR aircraft OR 機隊 OR 航線 OR 維修 OR 維護 OR 歷史 OR "
    "營運 OR 機場 OR 機型 OR 過往)"
)


def significant_tokens(title: str) -> list[str]:
    tokens = []
    for tok in _TOKEN_RE.findall(str(title or "")):
        low = tok.casefold()
        if low in _STOPWORDS or (len(low) < 3 and not low.isdigit()):
            continue
        tokens.append(low)
    return tokens


def is_thin(group: dict) -> bool:
    """Whether a group still needs current-event source enrichment.

    Kept under its original public name so existing callers and offline tests
    remain compatible; the decision now measures both evidence volume and
    source diversity.
    """
    items = group.get("items") or []
    if not items:
        return False
    sources = {
        str(item.get("source") or item.get("sourceKey") or "").casefold()
        for item in items
        if str(item.get("source") or item.get("sourceKey") or "").strip()
    }
    material = squash_text(" ".join(
        f"{item.get('title') or ''} {item.get('summary') or ''} "
        f"{item.get('fulltext') or ''}"
        for item in items))
    return (
        len(sources) < TARGET_SOURCE_COUNT
        or len(material) < TARGET_MATERIAL_CHARS
    )


def build_query(group: dict) -> tuple[str, list[str]]:
    """(google-news query, seed tokens) from the group's headline."""
    items = group.get("items") or [{}]
    title = str(items[0].get("title") or "")
    tokens = significant_tokens(title)
    # Add anchors from alternate headlines when deterministic dedupe already
    # joined more than one current source.
    for item in items[1:]:
        for token in significant_tokens(str(item.get("title") or "")):
            if token not in tokens:
                tokens.append(token)
    tokens = tokens[:12]
    return " ".join(tokens), tokens


def build_background_query(group: dict) -> tuple[str, list[str], bool]:
    """Build one broader, unbounded query anchored to the story's entities."""
    query, tokens = build_query(group)
    lang_zh = bool(re.search(r"[一-鿿]", query))
    anchors = list(dict.fromkeys(
        token for token in tokens if token not in _BACKGROUND_EVENT_WORDS))
    identifiers = [token for token in anchors if re.search(r"\d", token)]
    names = [token for token in anchors if token not in identifiers]
    if identifiers:
        anchors = list(dict.fromkeys(names[:2] + identifiers[:1]))
    else:
        anchors = names[:4]
    if len(anchors) < 2:
        return "", anchors, lang_zh
    return f"{' '.join(anchors)} {_BACKGROUND_TERMS}", anchors, lang_zh


def _domain_ok(host: str) -> bool:
    host = str(host or "").casefold().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in DOMAINS)


def _resolve(link: str) -> str | None:
    """Resolve one hop to a direct outlet URL, or fail closed."""
    try:
        resp = requests.get(link, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=False)
    except requests.RequestException:
        return None
    location = resp.headers.get("Location") if hasattr(resp, "headers") else None
    if getattr(resp, "status_code", 0) in (301, 302, 303, 307, 308) \
            and location:
        location = urljoin(link, location)
        host = (urlsplit(location).hostname or "").casefold()
        if host and not (
            is_google_news_url(location)
            or host == "google.com"
            or host.endswith(".google.com")
        ):
            return location
    return None


def _entry_source(entry) -> tuple[str, str]:
    src = entry.get("source") or {}
    return (str(src.get("title") or "").strip(),
            str(src.get("href") or "").strip())


def _clean_title(title: str, source_title: str) -> str:
    title = str(title or "").strip()
    if source_title and title.endswith(" - " + source_title):
        title = title[: -len(" - " + source_title)].rstrip()
    return title


def search_candidates(query: str, seed_tokens: list[str],
                      lang_zh: bool, *, when: str | None = "2d",
                      min_shared_tokens: int | None = None) -> list[dict]:
    """Same-topic items from allowlisted outlets, best-first."""
    if not query:
        return []
    locale = ("&hl=zh-TW&gl=TW&ceid=TW:zh-Hant" if lang_zh
              else "&hl=en-US&gl=US&ceid=US:en")
    time_filter = f" when:{when}" if when else ""
    url = ("https://news.google.com/rss/search?q="
           + quote(f"{query}{time_filter}") + locale)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if getattr(resp, "status_code", 0) != 200:
        return []
    feed = feedparser.parse(resp.content)
    seed = set(seed_tokens)
    out = []
    for entry in feed.entries[:25]:
        source_title, source_href = _entry_source(entry)
        if not _domain_ok(urlsplit(source_href).netloc):
            continue
        title = _clean_title(entry.get("title"), source_title)
        overlap = seed & set(significant_tokens(title))
        # same-topic bar: at least 3 shared significant tokens, or all of
        # a short seed
        threshold = (min(3, max(1, len(seed)))
                     if min_shared_tokens is None
                     else max(1, min_shared_tokens))
        if len(overlap) < threshold:
            continue
        summary = re.sub(r"<[^>]+>", " ", str(entry.get("summary") or ""))
        summary = re.sub(r"\s+", " ", summary).strip()[:500]
        published = None
        for key in ("published_parsed", "updated_parsed"):
            if entry.get(key):
                import calendar
                from datetime import datetime, timezone

                published = datetime.fromtimestamp(
                    calendar.timegm(entry[key]), tz=timezone.utc)
                break
        out.append({
            "title": title,
            "summary": summary,
            "_googleUrl": urljoin(url, str(entry.get("link") or "")),
            "source": source_title or urlsplit(source_href).netloc,
            "publishedUtc": iso_minute(published) if published else None,
            "score": len(overlap),
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    # Resolve only the strongest candidates, in parallel. The previous
    # implementation resolved every accepted result serially and could spend
    # nearly an hour waiting on Google redirect links that would never be used.
    out = out[:MAX_RESOLVE_CANDIDATES]
    with ThreadPoolExecutor(max_workers=RESOLVE_WORKERS) as executor:
        futures = {
            executor.submit(_resolve, candidate["_googleUrl"]): candidate
            for candidate in out
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                resolved = future.result()
                if (resolved and not is_google_news_url(resolved)
                        and _domain_ok(urlsplit(resolved).netloc)):
                    candidate["url"] = resolved
            except Exception:
                pass
    resolved_candidates = []
    for candidate in out:
        candidate.pop("_googleUrl", None)
        if candidate.get("url") and not is_google_news_url(candidate["url"]):
            resolved_candidates.append(candidate)
    return resolved_candidates


def _merge_candidates(group: dict, candidates: list[dict], *, limit: int,
                      background: bool = False) -> int:
    existing = {norm_url(str(item.get("url") or ""))
                for item in group.get("items") or []}
    existing_sources = {
        str(item.get("source") or "").strip().casefold()
        for item in group.get("items") or []
        if str(item.get("source") or "").strip()
    }
    added = 0
    for candidate in candidates:
        if added >= limit:
            break
        key = norm_url(candidate["url"])
        source_key = str(candidate.get("source") or "").strip().casefold()
        if key in existing or source_key in existing_sources:
            continue
        existing.add(key)
        existing_sources.add(source_key)
        item = {
            "title": candidate["title"],
            "summary": candidate["summary"],
            "url": candidate["url"],
            "source": str(candidate["source"]),
            "companion": True,
        }
        if background:
            item["backgroundCompanion"] = True
        if candidate.get("publishedUtc"):
            item["publishedUtc"] = candidate["publishedUtc"]
        else:
            item["dateInferred"] = True
        group.setdefault("items", []).append(item)
        added += 1
    return added


def enrich_thin_groups(groups: list) -> int:
    """Merge same-topic reliable coverage into thin groups. Returns the
    number of companion items added."""
    targets = []
    for group in groups or []:
        if len(targets) >= MAX_SEARCHES_PER_RUN:
            break
        if not is_thin(group):
            continue
        query, seed_tokens = build_query(group)
        if len(seed_tokens) < 3:
            continue
        lang_zh = bool(re.search(r"[一-鿿]", query))
        targets.append((group, query, seed_tokens, lang_zh))

    # Search independent event groups concurrently but merge results back in
    # ranked order. This keeps the 10-group coverage target without turning
    # network latency into a serial 10x multiplier.
    results = {}
    with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
        futures = {
            executor.submit(search_candidates, query, seed_tokens, lang_zh):
                index
            for index, (_group, query, seed_tokens, lang_zh)
            in enumerate(targets)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                group = targets[index][0]
                print(f"companion: search failed for group "
                      f"{group.get('id')}: {type(exc).__name__}: {exc}")
                results[index] = []

    added_total = 0
    for index, (group, query, _seed_tokens, _lang_zh) in enumerate(targets):
        candidates = results.get(index, [])
        added = _merge_candidates(
            group, candidates, limit=MAX_ITEMS_PER_GROUP)
        added_total += added
        if added:
            print(f"companion: group {group.get('id')} +{added} same-topic "
                  f"item(s) from reliable outlets (query: {query[:60]})")

    # A small second pass looks for older background reporting only when the
    # current-event pass still leaves a group thin. It is separately capped,
    # uses the same outlet allowlist, and adds at most one context item/group.
    background_targets = []
    if MAX_BACKGROUND_SEARCHES_PER_RUN > 0:
        for group, _event_query, _seed_tokens, _lang_zh in targets:
            if (group.get("groupKind") == "safety_roundup"
                    or not is_thin(group) or any(
                    item.get("backgroundCompanion")
                    for item in group.get("items") or [])):
                continue
            query, anchors, lang_zh = build_background_query(group)
            if not query or len(anchors) < 2:
                continue
            background_targets.append((group, query, anchors, lang_zh))
            if len(background_targets) >= MAX_BACKGROUND_SEARCHES_PER_RUN:
                break

    background_results = {}
    if background_targets:
        with ThreadPoolExecutor(max_workers=SEARCH_WORKERS) as executor:
            futures = {
                executor.submit(
                    search_candidates, query, anchors, lang_zh,
                    when=None, min_shared_tokens=2): index
                for index, (_group, query, anchors, lang_zh)
                in enumerate(background_targets)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    background_results[index] = future.result()
                except Exception as exc:
                    group = background_targets[index][0]
                    print(f"companion: background search failed for group "
                          f"{group.get('id')}: {type(exc).__name__}: {exc}")
                    background_results[index] = []

    for index, (group, query, _anchors, _lang_zh) in enumerate(
            background_targets):
        added = _merge_candidates(
            group, background_results.get(index, []),
            limit=MAX_BACKGROUND_ITEMS_PER_GROUP, background=True)
        added_total += added
        if added:
            print(f"companion: group {group.get('id')} +{added} verified "
                  f"background source(s) (query: {query[:60]})")
    return added_total
