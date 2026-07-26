"""companion.py — same-topic retrieval for thin story groups.

Owner direction (2026-07-27): keep Simple Flying (and similar excerpt-only
feeds) as a DISCOVERY INDEX - when their item flags a story but carries
almost no text, the PIPELINE (never the model) searches Google News for
the same topic and merges matching coverage from an allowlist of reliable
outlets (config/companion_sources.json) into the story group before
drafting. The model then writes from several real summaries - and, where
a companion comes from a fulltext-allowlisted official host, from the
full page - instead of inventing detail around one sentence.

Guard rails:
- Only allowlisted domains join a group; the outlet is identified from
  Google News' own <source> element, and links are resolved off
  news.google.com when possible.
- A candidate must share enough significant title tokens with the seed
  headline to count as the same topic.
- Caps: MAX_ITEMS_PER_GROUP companions, MAX_SEARCHES_PER_RUN searches per
  run; a group is searched once (the companion flag persists with it).
- Companions become ordinary group items: shown in <SOURCE>, quotable and
  machine-verified like everything else, credited in the article footer.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import feedparser
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    USER_AGENT,
    iso_minute,
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

TIMEOUT = (10, 30)
HEADERS = {"User-Agent": USER_AGENT}

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
    """Single-perspective group with barely any text and no full page."""
    items = group.get("items") or []
    if not items or len(items) > 2:
        return False
    if any(str(item.get("fulltext") or "").strip() for item in items):
        return False
    if any(item.get("companion") for item in items):
        return False  # already enriched in an earlier run
    material = squash_text(" ".join(
        f"{item.get('title') or ''} {item.get('summary') or ''}"
        for item in items))
    return len(material) < THIN_MATERIAL_CHARS


def build_query(group: dict) -> tuple[str, list[str]]:
    """(google-news query, seed tokens) from the group's headline."""
    title = str((group.get("items") or [{}])[0].get("title") or "")
    tokens = significant_tokens(title)[:10]
    return " ".join(tokens), tokens


def _domain_ok(host: str) -> bool:
    host = str(host or "").casefold().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in DOMAINS)


def _resolve(link: str) -> str:
    """One redirect hop off news.google.com; the Google link otherwise."""
    try:
        resp = requests.get(link, headers=HEADERS, timeout=TIMEOUT,
                            allow_redirects=False)
    except requests.RequestException:
        return link
    location = resp.headers.get("Location") if hasattr(resp, "headers") else None
    if getattr(resp, "status_code", 0) in (301, 302, 303, 307, 308) \
            and location:
        location = urljoin(link, location)
        host = urlsplit(location).netloc.lower()
        if host and "google.com" not in host:
            return location
    return link


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
            "url": _resolve(urljoin(url, str(entry.get("link") or ""))),
            "source": source_title or urlsplit(source_href).netloc,
            "publishedUtc": iso_minute(published) if published else None,
            "score": len(overlap),
        })
    out.sort(key=lambda c: c["score"], reverse=True)
    return out


def enrich_thin_groups(groups: list) -> int:
    """Merge same-topic reliable coverage into thin groups. Returns the
    number of companion items added."""
    searches = added_total = 0
    for group in groups or []:
        if searches >= MAX_SEARCHES_PER_RUN:
            break
        if not is_thin(group):
            continue
        query, seed_tokens = build_query(group)
        if len(seed_tokens) < 3:
            continue
        searches += 1
        lang_zh = bool(re.search(r"[一-鿿]", query))
        try:
            candidates = search_candidates(query, seed_tokens, lang_zh)
        except Exception as exc:
            print(f"companion: search failed for group "
                  f"{group.get('id')}: {type(exc).__name__}: {exc}")
            continue
        existing = {norm_url(str(item.get("url") or ""))
                    for item in group.get("items") or []}
        added = 0
        for cand in candidates:
            if added >= MAX_ITEMS_PER_GROUP:
                break
            key = norm_url(cand["url"])
            if key in existing:
                continue
            existing.add(key)
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
