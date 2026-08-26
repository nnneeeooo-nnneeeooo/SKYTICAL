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
                      lang_zh: bool) -> list[dict]:
    """Same-topic items from allowlisted outlets, best-first."""
    if not query:
        return []
    locale = ("&hl=zh-TW&gl=TW&ceid=TW:zh-Hant" if lang_zh
              else "&hl=en-US&gl=US&ceid=US:en")
    url = ("https://news.google.com/rss/search?q="
           + quote(f"{query} when:2d") + locale)
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
        if len(overlap) < min(3, max(1, len(seed))):
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
                if resolved and not is_google_news_url(resolved):
                    candidate["url"] = resolved
            except Exception:
                pass
    resolved_candidates = []
    for candidate in out:
        candidate.pop("_googleUrl", None)
        if candidate.get("url") and not is_google_news_url(candidate["url"]):
            resolved_candidates.append(candidate)
    return resolved_candidates


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
        existing = {norm_url(str(item.get("url") or ""))
                    for item in group.get("items") or []}
        existing_sources = {
            str(item.get("source") or "").strip().casefold()
            for item in group.get("items") or []
            if str(item.get("source") or "").strip()
        }
        added = 0
        for cand in candidates:
            if added >= MAX_ITEMS_PER_GROUP:
                break
            key = norm_url(cand["url"])
            source_key = str(cand.get("source") or "").strip().casefold()
            if key in existing or source_key in existing_sources:
                continue
            existing.add(key)
            existing_sources.add(source_key)
            item = {
                "title": cand["title"],
                "summary": cand["summary"],
                "url": cand["url"],
                "source": f'{cand["source"]}',
                "companion": True,
            }
            if cand.get("publishedUtc"):
                item["publishedUtc"] = cand["publishedUtc"]
            else:
                item["dateInferred"] = True
            group.setdefault("items", []).append(item)
            added += 1
        added_total += added
        if added:
            print(f"companion: group {group.get('id')} +{added} same-topic "
                  f"item(s) from reliable outlets (query: {query[:60]})")
    return added_total
