"""Fallback photos for stories the strict matcher cannot cover.

This stage runs after images.py and only fills articles whose ``image`` is
still empty. It has two responsibilities:

1. deterministic, manually vetted topic photos for a small set of clearly
   identifiable aviation topics;
2. a conservative global-airport fallback driven by the article's verified
   ``entities.airports`` values only when the headline describes airport
   operations or facilities. The Commons result must be freely licensed,
   bitmap-based, visually usable, and contain a meaningful airport-name token
   in the file title.

The site templates remain the final brand-image fallback, so a transient
network failure can never leave a published article page with an empty visual
slot.
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from html import unescape
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from airport_codes import resolve_airport  # noqa: E402
from common import (
    ARTICLES_DIR,
    USER_AGENT,
    load_json,
    now_utc,
    parse_iso,
    save_json,
)
from image_policy import (  # noqa: E402
    ANAK_KRAKATAU_RE,
    BAD_AIRPORT_TITLE_RE,
    article_headline_text,
    article_is_airport_operations,
)

MAX_ARTICLE_AGE_DAYS = 7
TIMEOUT = (10, 30)
HEADERS = {"User-Agent": USER_AGENT}
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

_FREE_LICENSE_RE = re.compile(r"\b(cc[ -]|cc0|public domain|pd-)", re.I)
_BAD_TITLE_RE = re.compile(
    r"map|logo|diagram|schematic|seal|icon|flag|emblem|coat of arms|"
    r"chart|plan\b|mairie|municipal|town hall|city hall|residential|"
    r"\bhouse\b|\bmemorial\b|statue",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_GENERIC_AIRPORT_WORDS = {
    "airport", "international", "intl", "aeroporto", "aeropuerto",
    "aéroport", "flughafen", "terminal", "airfield",
}

# Every deterministic entry must be manually vetted for relevance and reuse.
# They are file photos, never represented as photos from the current event.
_TOPIC_IMAGES = (
    {
        "name": "anak-krakatau",
        "patterns": (ANAK_KRAKATAU_RE,),
        "image": {
            "url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/79/Uprising-mt_anak_krakatau.jpg/1280px-Uprising-mt_anak_krakatau.jpg",
            "link": "https://commons.wikimedia.org/wiki/File:Uprising-mt_anak_krakatau.jpg",
            "credit": "Uprising",
            "license": "CC BY-SA 3.0",
            "provider": "Wikimedia Commons",
            "kind": "file_photo",
            "matched": "topic:volcano:anak-krakatau",
            "subject": "印尼喀拉喀托之子火山（Anak Krakatau）冒煙景象；2012-09-09 拍攝的歷史資料照",
            "photoYear": 2012,
        },
    },
    {
        "name": "china-airlines",
        "patterns": (
            re.compile(r"^(?:華航|中華航空)"),
            re.compile(r"^China Airlines\b", re.I),
        ),
        "image": {
            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/df/China_Airlines_Boeing_737-800_B-18651_on_final_approach_to_Taoyuan_February_2026.jpg/1280px-China_Airlines_Boeing_737-800_B-18651_on_final_approach_to_Taoyuan_February_2026.jpg?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content=thumbnail",
            "link": "https://commons.wikimedia.org/wiki/File:China_Airlines_Boeing_737-800_B-18651_on_final_approach_to_Taoyuan_February_2026.jpg",
            "credit": "4300streetcar",
            "license": "CC BY 4.0",
            "provider": "Wikimedia Commons",
            "kind": "file_photo",
            "matched": "topic:china-airlines",
            "subject": "China Airlines Boeing 737-800",
            "photoYear": 2026,
        },
    },
    {
        "name": "f16",
        "patterns": (
            re.compile(r"(?<![A-Za-z0-9])F-?16(?:[A-Z0-9-]*)(?![A-Za-z0-9])", re.I),
        ),
        "image": {
            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/be/A_USAF_F-16_pilot_breaking_right_on_final_approach_over_northern_Las_Vegas.jpg/1280px-A_USAF_F-16_pilot_breaking_right_on_final_approach_over_northern_Las_Vegas.jpg",
            "link": "https://commons.wikimedia.org/wiki/File:A_USAF_F-16_pilot_breaking_right_on_final_approach_over_northern_Las_Vegas.jpg",
            "credit": "Master Sgt. Benjamin Bloker",
            "license": "Public domain",
            "provider": "Wikimedia Commons",
            "kind": "file_photo",
            "matched": "topic:f16",
            "subject": "USAF F-16 資料照片",
            "photoYear": 2017,
        },
    },
    {
        "name": "drone",
        "patterns": (
            re.compile(r"無人機"),
            re.compile(r"\b(?:drone|drones|UAS|UAV|unmanned aerial)\b", re.I),
        ),
        "image": {
            "url": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/96/Quadcopter_Drone_in_flight.jpg/1280px-Quadcopter_Drone_in_flight.jpg",
            "link": "https://commons.wikimedia.org/wiki/File:Quadcopter_Drone_in_flight.jpg",
            "credit": "Project Kei",
            "license": "CC BY-SA 4.0",
            "provider": "Wikimedia Commons",
            "kind": "file_photo",
            "matched": "topic:drone",
            "subject": "四軸無人機資料照片",
            "photoYear": 2020,
        },
    },
)


def _article_text(article: dict) -> str:
    parts: list[str] = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.append(str(block.get("title") or ""))
        parts.append(str(block.get("summary") or ""))
        parts.extend(str(p) for p in block.get("body") or [])
    return " ".join(parts)


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", unescape(value))).strip()


def _airport_entity(article: dict) -> str | None:
    entities = article.get("entities") or {}
    if not isinstance(entities, dict):
        return None
    airports = entities.get("airports") or []
    if not isinstance(airports, list):
        return None
    for value in airports:
        name = str(value or "").strip()
        if len(name) >= 3 and resolve_airport(name):
            return name
    return None


def _airport_title_tokens(name: str) -> list[str]:
    """Meaningful tokens that must identify the airport in a Commons title."""
    tokens = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", name)
    meaningful = [
        token for token in tokens
        if len(token) >= 4 and token.casefold() not in _GENERIC_AIRPORT_WORDS
    ]
    if meaningful:
        return meaningful[:3]
    # CJK or an unusual short airport name: use the literal name as a strict
    # token rather than silently accepting an unrelated result.
    return [name]


def lookup_commons_airport(airport: str) -> dict | None:
    """Find a freely licensed file photo that visibly identifies ``airport``."""
    tokens = _airport_title_tokens(airport)
    resp = requests.get(
        COMMONS_API,
        headers=HEADERS,
        timeout=TIMEOUT,
        params={
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 6,
            "gsrlimit": 20,
            "gsrsearch": f"filetype:bitmap {airport}",
            "prop": "imageinfo",
            "iiprop": "url|extmetadata",
            "iiurlwidth": 1280,
        },
    )
    if resp.status_code != 200:
        return None

    pages = ((resp.json() or {}).get("query") or {}).get("pages") or {}
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        title = str(page.get("title") or "")
        title_low = title.casefold()
        if (_BAD_TITLE_RE.search(title)
                or BAD_AIRPORT_TITLE_RE.search(title)):
            continue
        if not any(token.casefold() in title_low for token in tokens):
            continue
        for info in page.get("imageinfo") or []:
            meta = info.get("extmetadata") or {}
            license_name = _strip_html(
                str((meta.get("LicenseShortName") or {}).get("value") or "")
            )
            if not _FREE_LICENSE_RE.search(license_name):
                continue
            thumb = info.get("thumburl") or info.get("url")
            if not thumb:
                continue
            artist = _strip_html(
                str((meta.get("Artist") or {}).get("value") or "")
            )[:80]
            return {
                "url": str(thumb),
                "link": str(
                    info.get("descriptionshorturl")
                    or info.get("descriptionurl")
                    or thumb
                ),
                "credit": artist or None,
                "license": license_name or None,
                "provider": "Wikimedia Commons",
                "kind": "file_photo",
                "matched": f"airport:{airport}",
                "subject": f"{airport} 資料照片",
                "description": title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " "),
            }
    return None


def topic_image(article: dict) -> dict | None:
    """Return a vetted topic image, then a strict verified-airport image."""
    if article.get("articleFormat") == "roundup":
        # A photo selected from one item would visually misrepresent a
        # collection of unrelated events. Keep the neutral site fallback.
        return None
    text = article_headline_text(article)
    for rule in _TOPIC_IMAGES:
        if any(pattern.search(text) for pattern in rule["patterns"]):
            return dict(rule["image"])

    airport = _airport_entity(article)
    if airport and article_is_airport_operations(article):
        return lookup_commons_airport(airport)
    return None


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("image_fallbacks: no articles yet")
        return 0

    cutoff = now_utc() - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    attached = 0
    for path in sorted(ARTICLES_DIR.glob("*.json"), reverse=True):
        batch = load_json(path, None)
        if not isinstance(batch, dict):
            continue
        changed = False
        for article in batch.get("articles") or []:
            if not isinstance(article, dict):
                continue
            try:
                if parse_iso(str(article.get("publishedUtc"))) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            if article.get("articleFormat") == "roundup":
                if article.pop("image", None) is not None:
                    changed = True
                continue
            existing_image = article.get("image")
            if (isinstance(existing_image, dict)
                    and str(existing_image.get("matched") or "")
                    .startswith("airport:")
                    and not article_is_airport_operations(article)):
                # A verified airport entity may be background context for an
                # airline, finance or safety story.  Do not turn that into a
                # generic airport card unless the headline is actually about
                # airport operations or facilities.
                article.pop("image", None)
                changed = True
                existing_image = None
            if article.get("image"):
                continue
            try:
                image = topic_image(article)
            except Exception as exc:
                # Enhancement only: article publishing and the final brand
                # fallback must continue even when Commons is unavailable.
                print(
                    "image_fallbacks: lookup failed for "
                    f"{article.get('id') or path.name}: "
                    f"{type(exc).__name__}: {exc}"
                )
                continue
            if not image:
                continue
            article["image"] = image
            changed = True
            attached += 1
            print(
                "image_fallbacks: attached "
                f"{image['matched']} to {article.get('id') or path.name}"
            )
        if changed:
            save_json(path, batch)

    print(f"image_fallbacks: {attached} article(s) got a fallback photo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
