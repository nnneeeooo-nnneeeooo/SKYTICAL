"""Fetch stage: download every source in common.SOURCES into data/raw/.

For each registry entry this script performs a polite conditional HTTP
request (ETag / Last-Modified persisted in data/raw/_http_cache.json),
parses the response into normalized items and writes one snapshot per
source plus data/sources.json — see pipeline/CONTRACTS.md.

A failing source never aborts the run: it is recorded as ok=false with an
error string and the loop continues. The script always exits 0.
"""
from __future__ import annotations

import calendar
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import feedparser
import requests
from bs4 import BeautifulSoup

from common import (
    DATA_DIR,
    MAX_ITEMS_PER_SOURCE,
    RAW_DIR,
    SOURCES,
    USER_AGENT,
    is_transport_story,
    iso_minute,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    save_json,
)

TIMEOUT = 20  # seconds per request


def _matches_keywords(item: dict, keywords) -> bool:
    """True when a broad-feed item matches both keyword and site scope."""
    blob = (f"{item.get('title') or ''} "
            f"{item.get('summary') or ''}").casefold()
    return (any(str(k).casefold() in blob for k in keywords)
            and is_transport_story(item))
RETRY_DELAY = 2  # seconds between the two attempts
RESOLVE_TIMEOUT = 6  # seconds for google-news link resolution
MAX_RESOLVE_FAILURES = 3  # stop resolving after this many misses in a row
SUMMARY_MAX = 500
GOOGLE_NEWS_HOST = "news.google.com"
CACHE_PATH = RAW_DIR / "_http_cache.json"

_MONTHS = {
    name: num
    for num, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"),
        start=1,
    )
}

# "July 23, 2026" (FAA) or "16 December 2025" (Eurocontrol <time> text).
_DATE_MDY = re.compile(r"^([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})$")
_DATE_DMY = re.compile(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$")
# CAA Taiwan RSS titles end with " - (2026-07-23)".
_CAA_TITLE_DATE = re.compile(r"\s*-\s*\((\d{4}-\d{2}-\d{2})\)\s*$")


class FetchError(Exception):
    """Per-source fetch/parse failure — recorded in the raw file, never fatal."""


# --------------------------------------------------------------------------
# small text/date helpers

def _collapse(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _collapse(BeautifulSoup(value, "lxml").get_text(" ", strip=True))


def _clip(text: str, limit: int = SUMMARY_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _date_from_text(text: str) -> datetime | None:
    text = _collapse(text)
    match = _DATE_MDY.match(text)
    if match:
        month_name, day, year = match.group(1), match.group(2), match.group(3)
    else:
        match = _DATE_DMY.match(text)
        if not match:
            return None
        day, month_name, year = match.group(1), match.group(2), match.group(3)
    month = _MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        return datetime(int(year), month, int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def _time_tag_datetime(tag) -> datetime | None:
    value = tag.get("datetime") or tag.get_text(strip=True)
    if not value:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        return _date_from_text(value)


def _entry_datetime(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc)
    for key in ("published", "updated"):
        value = entry.get(key)
        if not value:
            continue
        try:
            parsed = parsedate_to_datetime(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (TypeError, ValueError):
            pass
        try:
            return parse_iso(value)
        except ValueError:
            pass
    return None


def _entry_image(entry) -> str | None:
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return link.get("href")
    for key in ("media_thumbnail", "media_content"):
        media = entry.get(key)
        if media and media[0].get("url"):
            return media[0]["url"]
    return None


# --------------------------------------------------------------------------
# HTTP

def _request(session: requests.Session, url: str, headers: dict | None = None,
             timeout: int = TIMEOUT) -> requests.Response:
    """GET with a 20s timeout and one retry. Raises FetchError on failure."""
    last_error: FetchError | None = None
    for attempt in range(2):
        try:
            resp = session.get(url, headers=headers or {}, timeout=timeout)
            if resp.status_code == 304 or resp.ok:
                return resp
            last_error = FetchError(f"HTTP {resp.status_code} for {url}")
        except requests.RequestException as exc:
            last_error = FetchError(f"{type(exc).__name__}: {exc}")
        if attempt == 0:
            time.sleep(RETRY_DELAY)
    raise last_error  # type: ignore[misc]  # always set after both attempts


def _conditional_get(session: requests.Session, key: str, url: str,
                     cache: dict) -> requests.Response:
    """GET with If-None-Match / If-Modified-Since from the validator cache."""
    entry = cache.get(key) or {}
    headers = {}
    if entry.get("url") == url:  # ignore validators from an older endpoint
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            headers["If-Modified-Since"] = entry["last_modified"]
    resp = _request(session, url, headers)
    if resp.status_code == 304 and not (RAW_DIR / f"{key}.json").exists():
        # Validator cache survived but the snapshot did not: fetch fresh.
        resp = _request(session, url)
    if resp.status_code != 304:
        validators = {"url": url}
        if resp.headers.get("ETag"):
            validators["etag"] = resp.headers["ETag"]
        if resp.headers.get("Last-Modified"):
            validators["last_modified"] = resp.headers["Last-Modified"]
        if len(validators) > 1:
            cache[key] = validators
        else:
            cache.pop(key, None)
    return resp


_ROBOTS: dict[str, robotparser.RobotFileParser] = {}


def _robots_ok(session: requests.Session, url: str) -> bool:
    """Check robots.txt for HTML sources; fail open when it is unreachable."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    parser = _ROBOTS.get(origin)
    if parser is None:
        parser = robotparser.RobotFileParser()
        try:
            resp = session.get(origin + "/robots.txt", timeout=10)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                parser.allow_all = True
        except requests.RequestException:
            parser.allow_all = True
        _ROBOTS[origin] = parser
    return parser.can_fetch(USER_AGENT, url)


# --------------------------------------------------------------------------
# RSS sources

def _clean_gnews_title(title: str, entry) -> str:
    """Strip Google News' ' - <publisher>' title suffix; '' for junk entries."""
    source_title = str((entry.get("source") or {}).get("title") or "")
    for suffix in (f" - {source_title}", " - Reuters"):
        if len(suffix) > 3 and title.endswith(suffix):
            title = title[: -len(suffix)].rstrip()
            break
    if title == source_title or title.lower().endswith(".aspx"):
        return ""  # publisher homepage or bare docket/file link, no headline
    return title


def _resolve_gnews_link(session: requests.Session, link: str) -> str | None:
    """Follow one redirect off news.google.com; None when it stays on Google."""
    try:
        resp = session.get(link, timeout=RESOLVE_TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        return None
    location = resp.headers.get("Location")
    if resp.status_code in (301, 302, 303, 307, 308) and location:
        location = urljoin(link, location)
        host = urlsplit(location).netloc.lower()
        if host and not (host == "google.com" or host.endswith(".google.com")):
            return location
    return None


def _rss_items(session: requests.Session, key: str, entries: list,
               endpoint: str) -> list[dict]:
    """Normalize feed entries to raw items (published as datetime or None)."""
    is_google = GOOGLE_NEWS_HOST in urlsplit(endpoint).netloc
    items: list[dict] = []
    resolve_failures = 0
    for entry in entries:
        title = _strip_html(entry.get("title", ""))
        link = urljoin(endpoint, (entry.get("link") or "").strip())
        if not title or not link:
            continue
        published = _entry_datetime(entry)
        if key == "caataiwan":
            match = _CAA_TITLE_DATE.search(title)
            if match:
                title = title[: match.start()].rstrip()
                if published is None:
                    try:
                        published = parse_iso(match.group(1) + "T00:00Z")
                    except ValueError:
                        pass
        if is_google:
            title = _clean_gnews_title(title, entry)
            if not title:
                continue
            if (GOOGLE_NEWS_HOST in urlsplit(link).netloc
                    and resolve_failures < MAX_RESOLVE_FAILURES):
                resolved = _resolve_gnews_link(session, link)
                if resolved:
                    link = resolved
                    resolve_failures = 0
                else:
                    resolve_failures += 1
        summary = _strip_html(entry.get("summary") or entry.get("description"))
        if is_google and len(summary) <= len(title) + 40:
            summary = ""  # google news descriptions just repeat the headline
        items.append({
            "title": title,
            "url": link,
            "published": published,
            "summary": summary,
            "image": _entry_image(entry),
        })
        if len(items) >= MAX_ITEMS_PER_SOURCE:
            break
    return items


# --------------------------------------------------------------------------
# HTML sources — one small parser per site

def _parse_faa(soup: BeautifulSoup, base: str) -> list[dict]:
    """FAA newsroom press releases: Drupal views rows with date + teaser."""
    items = []
    for row in soup.select("div.views-row"):
        anchor = row.select_one(".views-field-title a[href]") or row.find("a", href=True)
        if anchor is None:
            continue
        title = _collapse(anchor.get_text(" ", strip=True))
        if not title:
            continue
        date_el = row.select_one(".views-field-field-effective-date .field-content")
        body_el = row.select_one(".views-field-body .field-content")
        items.append({
            "title": title,
            "url": urljoin(base, anchor["href"]),
            "published": _date_from_text(date_el.get_text(strip=True)) if date_el else None,
            "summary": body_el.get_text(" ", strip=True) if body_el else "",
            "image": None,
        })
    return items


def _parse_icao(soup: BeautifulSoup, base: str) -> list[dict]:
    """ICAO /news listing: teaser links /news/<slug>; date/image when nearby."""
    items, seen = [], set()
    for anchor in soup.find_all("a", href=re.compile(r"^/news/[a-z0-9-]{8,}$")):
        url = urljoin(base, anchor["href"])
        title = _collapse(anchor.get_text(" ", strip=True))
        if url in seen or len(title) < 12:
            continue
        seen.add(url)
        published, image = _card_context(anchor, base)
        items.append({"title": title, "url": url, "published": published,
                      "summary": "", "image": image})
    return items


def _card_context(anchor, base: str):
    """Walk up from a teaser link looking for the card's <time> and image."""
    node = anchor
    for _ in range(4):
        node = node.parent
        if node is None or node.name == "body":
            break
        time_tag = node.find("time")
        if time_tag is not None:
            image = node.find("img", src=True)
            return (_time_tag_datetime(time_tag),
                    urljoin(base, image["src"]) if image else None)
    return None, None


def _parse_eurocontrol(soup: BeautifulSoup, base: str) -> list[dict]:
    """Eurocontrol /newsroom: node--news / node--publication teaser cards."""
    items, seen = [], set()
    generic = {"learn more", "read more", "more", "find out more"}
    for card in soup.find_all("div", class_=re.compile(r"\bnode--(news|publication|press)")):
        anchor = card.find("a", href=re.compile(r"^/(news|publication|press-release)/"))
        if anchor is None:
            continue
        url = urljoin(base, anchor["href"])
        heading = card.find(["h2", "h3", "h4"])
        title = _collapse(heading.get_text(" ", strip=True)) if heading else ""
        if not title:
            title = _collapse(anchor.get_text(" ", strip=True))
        if url in seen or len(title) < 8 or title.lower() in generic:
            continue
        seen.add(url)
        time_tag = card.find("time")
        image = card.find("img", src=True)
        items.append({
            "title": title,
            "url": url,
            "published": _time_tag_datetime(time_tag) if time_tag else None,
            "summary": "",
            "image": urljoin(base, image["src"]) if image else None,
        })
    return items


HTML_PARSERS = {
    "faa": _parse_faa,
    "icao": _parse_icao,
    "eurocontrol": _parse_eurocontrol,
}


# --------------------------------------------------------------------------
# FlightAware AeroAPI (optional)

def _fetch_flightaware(session: requests.Session, spec: dict) -> dict:
    """One cheap AeroAPI call -> best-effort stats object; items stay empty."""
    api_key = os.environ.get("AEROAPI_KEY")
    if not api_key:
        raise FetchError("AEROAPI_KEY not set")
    url = spec["endpoint"].rstrip("/") + "/disruption_counts/origin"
    resp = _request(session, url, {"x-apikey": api_key})
    data = resp.json()
    stats: dict = {}
    for src_key, dest_key in (
        ("total_flights", "flightsTracked"),
        ("total_delays_worldwide", "delaysWorldwide"),
        ("total_cancellations_worldwide", "cancellationsWorldwide"),
    ):
        value = data.get(src_key)
        if isinstance(value, (int, float)):
            stats[dest_key] = value
    delays = stats.get("delaysWorldwide")
    tracked = stats.get("flightsTracked")
    if delays is not None and tracked:
        stats["delayRate"] = round(100.0 * delays / tracked, 1)
    return stats


# --------------------------------------------------------------------------
# main loop

TITLE_MAX = 300


def _finalize(raw_items: list[dict], fetched_iso: str,
              previous: dict | None) -> list[dict]:
    # For items whose page/feed carries no date, keep the publishedUtc we
    # stamped when we FIRST saw the URL (from the previous snapshot) instead
    # of re-stamping every fetch — otherwise long-lived undated listings look
    # perpetually fresh and get republished once seen.json prunes them.
    prev_published: dict[str, str] = {}
    if isinstance(previous, dict):
        for prev_item in previous.get("items") or []:
            if isinstance(prev_item, dict) and prev_item.get("url"):
                stamp = prev_item.get("publishedUtc")
                if stamp:
                    prev_published[norm_url(str(prev_item["url"]))] = str(stamp)

    items = []
    for item in raw_items[:MAX_ITEMS_PER_SOURCE]:
        published = item.get("published")
        inferred = False
        if published:
            published_iso = iso_minute(published)
        else:
            # No source-provided date: stamp first-seen time, stable across
            # fetches, and FLAG it so downstream never presents the stamp
            # as a real publication time.
            published_iso = prev_published.get(norm_url(item["url"]), fetched_iso)
            inferred = True
        row = {
            "title": _clip(item["title"], TITLE_MAX),
            "url": item["url"],
            "publishedUtc": published_iso,
            "summary": _clip(_collapse(item.get("summary"))),
            "image": item.get("image"),
        }
        if inferred:
            row["dateInferred"] = True
        items.append(row)
    return items


def _fetch_source(session: requests.Session, key: str, spec: dict,
                  cache: dict, raw_path, fetched_iso: str) -> bool:
    """Fetch one source and write its raw snapshot. Returns success."""
    source_type = spec.get("type")
    if source_type == "api":
        stats = _fetch_flightaware(session, spec)
        save_json(raw_path, {"source": key, "fetchedUtc": fetched_iso,
                             "ok": True, "error": None, "items": [],
                             "stats": stats})
        print(f"[fetch] {key}: ok, stats keys={sorted(stats)}")
        return True
    if source_type not in ("rss", "html"):
        raise FetchError(f"unknown source type: {source_type!r}")

    endpoint = spec["endpoint"]
    if source_type == "html" and not _robots_ok(session, endpoint):
        raise FetchError("blocked by robots.txt")

    resp = _conditional_get(session, key, endpoint, cache)
    if resp.status_code == 304:
        previous = load_json(raw_path, None)
        if not isinstance(previous, dict):
            raise FetchError("304 without a previous snapshot")
        previous["fetchedUtc"] = fetched_iso
        save_json(raw_path, previous)
        print(f"[fetch] {key}: not modified (304), kept "
              f"{len(previous.get('items') or [])} items")
        return bool(previous.get("ok"))

    if source_type == "rss":
        feed = feedparser.parse(resp.content)
        if not feed.entries and feed.bozo:
            raise FetchError(f"feed parse failed: {getattr(feed, 'bozo_exception', 'bozo')}")
        raw_items = _rss_items(session, key, feed.entries, endpoint)
    else:
        parser = HTML_PARSERS.get(key)
        if parser is None:
            raise FetchError("no HTML parser registered for this source")
        raw_items = parser(BeautifulSoup(resp.content, "lxml"), resp.url or endpoint)
        if not raw_items:
            raise FetchError("page parsed to 0 items (layout changed?)")

    keywords = spec.get("keywords")
    if keywords:
        # Broad feeds (e.g. the CNA politics wire) keep only on-topic items,
        # so unrelated stories never reach the paid editorial stage.
        before = len(raw_items)
        raw_items = [it for it in raw_items if _matches_keywords(it, keywords)]
        if before != len(raw_items):
            print(f"[fetch] {key}: keyword filter kept "
                  f"{len(raw_items)}/{before} items")
    elif spec.get("scope_filter"):
        # Broad feeds without a keyword list (currently MND/軍聞社) still need
        # the same aviation/transport gate.  General defence politics and
        # land-exercise stories never enter the editorial queue.
        before = len(raw_items)
        raw_items = [it for it in raw_items if is_transport_story(it)]
        if before != len(raw_items):
            print(f"[fetch] {key}: scope filter kept "
                  f"{len(raw_items)}/{before} items")

    items = _finalize(raw_items, fetched_iso, load_json(raw_path, None))
    save_json(raw_path, {"source": key, "fetchedUtc": fetched_iso,
                         "ok": True, "error": None, "items": items})
    print(f"[fetch] {key}: ok, {len(items)} items")
    return True


def _write_sources(last_success: dict[str, str | None]) -> None:
    """data/sources.json: registry order, lastFetchUtc persisted across runs."""
    sources_path = DATA_DIR / "sources.json"
    previous = {
        entry["key"]: entry
        for entry in (load_json(sources_path, []) or [])
        if isinstance(entry, dict) and entry.get("key")
    }
    output = []
    for key, spec in SOURCES.items():
        fetched = last_success.get(key)
        carried = (previous.get(key) or {}).get("lastFetchUtc")
        output.append({
            "key": key,
            "name": spec["name"],
            "kind": spec["kind"],
            "fmt": spec["fmt"],
            "url": spec["url"],
            "cover": spec["cover"],
            "lastFetchUtc": fetched or carried,
            "ok": bool(fetched),
        })
    save_json(sources_path, output)
    ok_count = sum(1 for entry in output if entry["ok"])
    print(f"[fetch] sources.json written: {ok_count}/{len(output)} sources ok")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT

    last_success: dict[str, str | None] = {}
    for key, spec in SOURCES.items():
        fetched_iso = iso_minute(now_utc())
        raw_path = RAW_DIR / f"{key}.json"
        try:
            success = _fetch_source(session, key, spec, cache, raw_path, fetched_iso)
        except Exception as exc:  # noqa: BLE001 — one source must never kill the run
            error = _collapse(str(exc))[:300] or type(exc).__name__
            # Carry the previous snapshot's items (and stats) forward so a
            # flapping source cannot destroy the only copy of stories that
            # write.py has not published yet (see CONTRACTS.md retry path).
            previous = load_json(raw_path, None)
            payload = {"source": key, "fetchedUtc": fetched_iso,
                       "ok": False, "error": error, "items": []}
            if isinstance(previous, dict):
                prev_items = previous.get("items")
                if isinstance(prev_items, list) and prev_items:
                    payload["items"] = prev_items
                if isinstance(previous.get("stats"), dict):
                    payload["stats"] = previous["stats"]
            save_json(raw_path, payload)
            cache.pop(key, None)  # do not 304 our way past a failure next run
            print(f"[fetch] {key}: FAILED - {error}")
            success = False
        last_success[key] = fetched_iso if success else None

    save_json(CACHE_PATH, cache)
    _write_sources(last_success)


if __name__ == "__main__":
    main()
