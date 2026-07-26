"""fulltext.py — fetch the full text of OFFICIAL source pages for write.py.

The RSS/listing fetch stage only yields headlines and short summaries, so
articles written from them are necessarily thin. This stage lets the
PIPELINE (never the model) fetch the complete text of the underlying page
for a small allowlist of official publishers we already crawl, and attach
it to the pending group item as `fulltext`. write.py shows it inside
<SOURCE> and verifies fact quotes against the exact same capped text, so
every extra sentence stays machine-traceable to the original page.

Guard rails:
- Allowlisted official hosts only (regulators/organizations whose listing
  pages fetch.py already requests). News aggregator/redirect hosts
  (news.google.com) and robots-restricted media (avherald) are never
  fetched here.
- robots.txt is honored per host (unreachable robots -> skip, fail closed;
  HTTP 404 robots -> allowed, per convention).
- Results (including misses) are cached in data/fulltext.json with a TTL,
  and each run performs at most MAX_FETCHES_PER_RUN requests.
- Any failure leaves the item exactly as before - thin material then
  simply produces the same short-but-honest article as today.
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA_DIR,
    USER_AGENT,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
)

CACHE_PATH = DATA_DIR / "fulltext.json"
TIMEOUT = (10, 30)
HEADERS = {"User-Agent": USER_AGENT}

# Official publishers only - the same organizations fetch.py already
# crawls for listings. Never add aggregators, social platforms or sites
# whose robots policy we would be working around.
ALLOWED_HOSTS = {
    "www.faa.gov", "faa.gov",
    "www.ntsb.gov", "ntsb.gov",
    "www.caa.gov.tw", "caa.gov.tw",
    "www.easa.europa.eu", "easa.europa.eu",
    "www.icao.int", "icao.int",
    "www.iata.org", "iata.org",
    "www.eurocontrol.int", "eurocontrol.int",
    # official Taiwan defense releases (共機動態 etc.)
    "www.mnd.gov.tw", "mnd.gov.tw", "mna.mnd.gov.tw",
    # CNA articles arrive via CNA's own official feed with direct links;
    # robots.txt is still honored per fetch
    "www.cna.com.tw", "cna.com.tw",
}

# Text shown to the model AND used for quote verification is capped at
# exactly this many characters - write.py imports it so the two sides can
# never drift apart.
FULLTEXT_PROMPT_CHARS = 4000
MAX_STORED_CHARS = 6000
MAX_FETCHES_PER_RUN = 8
MAX_ITEMS_PER_GROUP = 2
CACHE_TTL_HOURS = 21 * 24
MISS_TTL_HOURS = 24

_robots_cache: dict[str, RobotFileParser | None] = {}


def _host(url: str) -> str:
    try:
        return urlsplit(url).netloc.lower()
    except ValueError:
        return ""


def robots_allows(url: str) -> bool:
    """Honor robots.txt; unreachable robots fails closed (skip the fetch)."""
    host = _host(url)
    if not host:
        return False
    if host not in _robots_cache:
        parser = RobotFileParser()
        try:
            resp = requests.get(f"https://{host}/robots.txt",
                                headers=HEADERS, timeout=TIMEOUT)
            if resp.status_code == 404:
                parser.parse([])  # no robots file -> allowed by convention
            elif resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                parser = None
        except requests.RequestException:
            parser = None
        _robots_cache[host] = parser
    parser = _robots_cache[host]
    return bool(parser and parser.can_fetch(USER_AGENT, url))


def extract_text(html: str) -> str:
    """Main-content text of an official press page, whitespace-normalized."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "template", "iframe",
                     "nav", "header", "footer", "aside", "form", "button"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    chunks = []
    for node in root.find_all(["h1", "h2", "h3", "p", "li"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        # keep substantive lines only; menus/labels are short
        if len(text) >= 30 or re.search(r"[一-鿿]{8,}", text):
            chunks.append(text)
    seen, lines = set(), []
    for text in chunks:
        if text in seen:
            continue
        seen.add(text)
        lines.append(text)
    return "\n".join(lines)[:MAX_STORED_CHARS].strip()


def fetch_fulltext(url: str) -> str | None:
    """Fetch + extract one allowlisted page; None on any failure."""
    if _host(url) not in ALLOWED_HOSTS or not robots_allows(url):
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    # requests follows redirects: re-validate the FINAL url, or an
    # allowlisted host could redirect us onto an arbitrary page that we
    # would then present as "this official page".
    final_url = str(getattr(resp, "url", "") or url)
    if _host(final_url) not in ALLOWED_HOSTS or not robots_allows(final_url):
        return None
    # bytes in: let lxml/bs4 sniff the meta charset (header-less CJK pages
    # must not be cached as mojibake for 21 days)
    payload = getattr(resp, "content", None) or resp.text
    text = extract_text(payload)
    # A page whose extraction is barely longer than a feed summary adds
    # nothing worth the tokens.
    return text if len(text) >= 200 else None


def _cache_fresh(entry: dict, now) -> bool:
    try:
        fetched = parse_iso(str(entry.get("fetchedUtc")))
    except (ValueError, TypeError):
        return False
    ttl = CACHE_TTL_HOURS if entry.get("text") else MISS_TTL_HOURS
    return now - fetched < timedelta(hours=ttl)


def enrich_pending(groups: list) -> int:
    """Attach item['fulltext'] where an official full page is available.

    Mutates the in-memory groups only; write.py builds the prompt and
    verifies quotes from the same dicts, so no re-persistence is needed.
    Returns the number of items enriched.
    """
    cache = load_json(CACHE_PATH, {})
    pages = cache.get("pages")
    if not isinstance(pages, dict):
        pages = {}
    now = now_utc()
    # drop stale entries so the cache file cannot grow forever
    pages = {k: v for k, v in pages.items()
             if isinstance(v, dict) and _cache_fresh(v, now)}
    fetches = enriched = 0
    for group in groups or []:
        per_group = 0
        for item in group.get("items") or []:
            if per_group >= MAX_ITEMS_PER_GROUP:
                break
            url = str(item.get("url") or "").strip()
            if not url or item.get("fulltext"):
                continue
            if _host(url) not in ALLOWED_HOSTS:
                continue
            key = norm_url(url)
            entry = pages.get(key)
            if entry is None or not _cache_fresh(entry, now):
                if fetches >= MAX_FETCHES_PER_RUN:
                    continue
                fetches += 1
                entry = {"text": fetch_fulltext(url),
                         "fetchedUtc": now.isoformat()}
                pages[key] = entry
            if entry.get("text"):
                item["fulltext"] = str(entry["text"])
                per_group += 1
                enriched += 1
    new_cache = {"pages": pages}
    if new_cache != cache:
        save_json(CACHE_PATH, new_cache)
    if fetches or enriched:
        print(f"fulltext: {fetches} fetch(es), {enriched} item(s) enriched")
    return enriched
