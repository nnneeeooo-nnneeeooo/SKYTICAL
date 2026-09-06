"""Recover descriptions of the exact source image, never from story titles.

The URL-keyed cache also serves legacy URL-only images at build time. Missing
metadata is retried after six hours; the renderer uses the named brand fallback
until a description exists. No model, filename guess, or network call in build.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from html import unescape
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTICLES_DIR, DATA_DIR, USER_AGENT, load_json, now_utc, parse_iso, save_json

CACHE_PATH = DATA_DIR / "image-captions.json"
MAX_LOOKUPS = 80
_GENERIC = re.compile(
    r"^(?:image|photo|picture|thumbnail|featured image|file photo|stock photo|"
    r"untitled|圖片|照片|資料照片|示意圖|示意照片)(?:\s*\d+)?$", re.I)


def clean_description(value) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(BeautifulSoup(unescape(value), "html.parser").stripped_strings)
    text = re.sub(r"\s+", " ", text).strip()
    if (len(text) < 4 or len(text) > 300 or _GENERIC.fullmatch(text)
            or re.search(r"\b(?:untitled design|screenshot|gallery[-_ ]*\d|adobestock[_-]?\d)", text, re.I)
            or re.match(r"^(?:credit|photo credit|copyright|©)\s*[:：]?", text, re.I)
            or re.fullmatch(r"[\W\d_]+", text)
            or re.search(r"\.(?:jpe?g|png|webp|gif)$", text, re.I)):
        return ""
    return text


def image_identity(url: str, base: str = "") -> tuple[str, str]:
    """Ignore CDN resize parameters, but never match by basename alone."""
    try:
        parts = urlsplit(urljoin(base, unescape(url)))
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "", ""
        path = unquote(parts.path)
        path = re.sub(r"-(?:\d{2,4}x\d{2,4}|scaled)(?=\.[^.]+$)", "", path)
        return parts.hostname.lower(), path
    except ValueError:
        return "", ""


def source_description(html: str, image_url: str, source_url: str,
                       titles=()) -> dict | None:
    """Only alt/figcaption tied to this image can describe the photograph."""
    target = image_identity(image_url)
    if not target[0]:
        return None
    soup = BeautifulSoup(html, "html.parser")
    blocked = {str(t).strip().casefold() for t in titles if t}
    blocked.update(node.get_text(" ", strip=True).casefold()
                   for node in soup.select("h1, title"))

    def usable(value):
        text = clean_description(value)
        return text if text.casefold() not in blocked else ""

    for img in soup.find_all("img"):
        urls = [img.get(k, "") for k in
                ("src", "data-src", "data-lazy-src", "data-img-url")]
        for key in ("srcset", "data-srcset"):
            urls.extend(part.strip().split()[0] for part in
                        str(img.get(key, "")).split(",") if part.strip())
        if not any(image_identity(u, source_url) == target for u in urls):
            continue
        subject = usable(img.get("alt", ""))
        figure = img.find_parent("figure")
        caption = figure.find("figcaption") if figure else None
        if not subject and caption:
            # Credit alone is attribution, not a description of the subject.
            text = caption.get_text(" ", strip=True)
            subject = usable(re.split(r"\b(?:Photo )?Credit\s*:", text,
                                      flags=re.I)[0])
        if subject:
            return {"subject": subject, "link": source_url,
                    "captionSource": "source-image-metadata"}
    og_images = soup.find_all("meta", property="og:image")
    if any(image_identity(m.get("content", ""), source_url) == target
           for m in og_images):
        alt = soup.find("meta", property="og:image:alt")
        subject = usable(alt.get("content", "")) if alt else ""
        if subject:
            return {"subject": subject, "link": source_url,
                    "captionSource": "og:image:alt"}
    return None


def resolve_description(image_url: str, sources: list, titles: list) -> dict | None:
    for source in sources[:3]:
        url = str(source.get("url") or "")
        if not image_identity(url)[0]:
            continue
        try:
            response = requests.get(url, timeout=(5, 15),
                                    headers={"User-Agent": USER_AGENT})
            if response.status_code != 200:
                continue
            result = source_description(response.text, image_url, url, titles)
            if result:
                result["provider"] = str(source.get("name") or
                                         urlsplit(url).hostname).split(" — ")[0]
                return result
        except requests.RequestException:
            continue
    return None


def main(*, all_articles=False, max_lookups=MAX_LOOKUPS) -> int:
    now = now_utc()
    cache = load_json(CACHE_PATH, {})
    entries = cache.get("images", {}) if isinstance(cache, dict) else {}
    if not isinstance(entries, dict):
        entries = {}
    candidates = {}
    for path in sorted(ARTICLES_DIR.glob("*.json"), reverse=True):
        for article in (load_json(path, {}) or {}).get("articles", []):
            if not isinstance(article, dict):
                continue
            if not all_articles:
                try:
                    if parse_iso(article.get("publishedUtc", "")) < now - timedelta(days=7):
                        continue
                except (TypeError, ValueError):
                    continue
            raw = article.get("image")
            if isinstance(raw, dict) and clean_description(raw.get("subject")):
                continue
            url = raw.get("url") if isinstance(raw, dict) else raw
            if not isinstance(url, str) or not image_identity(url)[0]:
                continue
            old = entries.get(url) or {}
            if clean_description(old.get("subject")):
                continue
            try:
                if old.get("retryUtc") and parse_iso(old["retryUtc"]) > now:
                    continue
            except (TypeError, ValueError):
                pass
            candidate = candidates.setdefault(url, {"sources": [], "titles": []})
            for source in article.get("sources") or []:
                if isinstance(source, dict) and source not in candidate["sources"]:
                    candidate["sources"].append(source)
            candidate["titles"].extend((article.get(lang) or {}).get("title")
                                       for lang in ("zh", "en"))
    jobs = list(candidates.items())[:max_lookups]

    def lookup(job):
        url, context = job
        return url, resolve_description(url, context["sources"], context["titles"])

    found = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for url, result in pool.map(lookup, jobs):
            entry = {"checkedUtc": now.isoformat()}
            if result:
                entry.update(result)
                found += 1
            else:
                entry["retryUtc"] = (now + timedelta(hours=6)).isoformat()
            entries[url] = entry
    payload = {"images": entries}
    if payload != cache:
        save_json(CACHE_PATH, payload)
    print(f"image captions: {len(jobs)} lookup(s), {found} descriptions, "
          f"{len(jobs) - found} awaiting source metadata", flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--limit", type=int, default=MAX_LOOKUPS)
    args = parser.parse_args()
    raise SystemExit(main(all_articles=args.all, max_lookups=args.limit))
