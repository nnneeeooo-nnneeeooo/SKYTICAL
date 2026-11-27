"""Luna-assisted, licence-verified Commons image search for recent news.

The model proposes search terms and reviews candidate thumbnails. Wikimedia's
own metadata supplies the licence, author and file URL; model claims never do.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import images
from common import DATA_DIR, USER_AGENT, load_json, now_utc, parse_iso, save_json
from image_selection import MAX_STOCK_REUSE, image_key, rejection_reason, stock_usage, manual_image
from model_config import model_route_allowed

MODEL = "gpt-6-luna"
CACHE_PATH = DATA_DIR / "terra-images.json"
API_URL = "https://api.openai.com/v1/responses"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MAX_AGE = timedelta(hours=24)
RETRY = timedelta(hours=6)
MAX_CANDIDATES = 6
FREE_LICENSE = re.compile(
    r"^(?:CC0(?: 1\.0)?|CC BY(?:-SA)?(?: [1-4]\.0)?|Public domain|PD-[A-Za-z0-9.-]+)$", re.I)


def _text(response):
    data = response.json()
    if response.status_code != 200 or data.get("status") != "completed":
        raise ValueError("Luna response incomplete")
    parts = [part.get("text", "") for row in data.get("output", [])
             if row.get("type") == "message" for part in row.get("content", [])
             if part.get("type") == "output_text"]
    return json.loads("".join(parts))


def _ask(content, *, max_output_tokens=2048):
    if not model_route_allowed("openai", MODEL):
        raise RuntimeError("Luna model route is disabled")
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY unavailable")
    payload = {
        "model": MODEL, "store": False,
        "reasoning": {"effort": "max"},
        "max_output_tokens": max_output_tokens,
        "input": [{"role": "user", "content": content}],
        "text": {"format": {"type": "json_object"}},
    }
    response = requests.post(
        API_URL, headers={"Authorization": f"Bearer {key}",
                          "Content-Type": "application/json"},
        json=payload, timeout=(10, 120))
    return _text(response)


def _article_brief(article):
    zh, en = article.get("zh") or {}, article.get("en") or {}
    return json.dumps({
        "zh_title": zh.get("title"), "zh_summary": zh.get("summary"),
        "en_title": en.get("title"), "en_summary": en.get("summary"),
        "published": article.get("publishedUtc"),
        "entities": article.get("entities"),
    }, ensure_ascii=False)[:3500]


def _queries(article):
    result = _ask([{"type": "input_text", "text":
        "為這則新聞尋找可在 Wikimedia Commons 核實授權的直接相關照片。"
        "優先搜尋活動名稱、參與者、地點與日期；不要用航空公司客機代替旅遊活動。"
        "只回傳 JSON，格式為 {\"queries\":[\"...\",\"...\"]}，最多四個精確的中英文搜尋詞；"
        "不確定時回傳空陣列。新聞：" + _article_brief(article)}])
    queries = result.get("queries")
    if not isinstance(queries, list):
        return []
    return [q.strip() for q in queries[:4] if isinstance(q, str)
            and 3 <= len(q.strip()) <= 120 and not re.search(r"[\r\n]", q)]


def _clean(value):
    return re.sub(r"<[^>]+>", " ", unescape(str(value or ""))).strip()


def _candidates(article, queries, usage):
    seen, found = set(), []
    for query in queries:
        response = requests.get(COMMONS_API, headers={"User-Agent": USER_AGENT},
            params={"action": "query", "format": "json", "generator": "search",
                    "gsrnamespace": 6, "gsrlimit": 12,
                    "gsrsearch": f"filetype:bitmap {query}", "prop": "imageinfo",
                    "iiprop": "url|size|extmetadata", "iiurlwidth": 640}, timeout=(10, 30))
        response.raise_for_status()
        pages = ((response.json().get("query") or {}).get("pages") or {}).values()
        for page in sorted(pages, key=lambda row: row.get("index", 99)):
            title = str(page.get("title") or "")
            if images._BAD_TITLE_RE.search(title):
                continue
            for info in page.get("imageinfo") or []:
                meta = info.get("extmetadata") or {}
                license_name = _clean((meta.get("LicenseShortName") or {}).get("value"))
                if not FREE_LICENSE.match(license_name):
                    continue
                artist = _clean((meta.get("Artist") or {}).get("value"))[:120]
                if license_name.upper().startswith("CC BY") and not artist:
                    continue
                thumb = str(info.get("thumburl") or "")
                link = str(info.get("descriptionshorturl") or info.get("descriptionurl") or "")
                if (urlsplit(thumb).hostname not in {"upload.wikimedia.org", "thumb.wikimedia.org"}
                        or urlsplit(link).hostname != "commons.wikimedia.org"
                        or thumb in seen):
                    continue
                seen.add(thumb)
                candidate = {
                    "url": thumb, "link": link,
                    "credit": artist or None,
                    "license": license_name, "provider": "Wikimedia Commons",
                    "kind": "file_photo", "matched": query,
                    "subject": title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " "),
                    "description": title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " "),
                    "photoYear": images._commons_photo_year(meta),
                    "selectionModel": MODEL,
                }
                if (not rejection_reason(article, candidate)
                        and usage.get(image_key(candidate), 0) < MAX_STOCK_REUSE):
                    found.append(candidate)
                    if len(found) == MAX_CANDIDATES:
                        return found
    return found


def find_images(article, usage):
    queries = _queries(article)
    if not queries:
        return []
    candidates = _candidates(article, queries, usage)
    if not candidates:
        return []
    content = [{"type": "input_text", "text":
        "你是新聞照片審核員。請看每張照片與 Wikimedia 檔名，選出最多五張直接相關且合適的圖片，依關聯程度排序。"
        "照片若只是同航空公司的客機，但新聞主題是旅遊業者、活動、觀光或合作，必須拒絕。"
        "不可把舊照片稱為本次現場。若不能確認照片確實呈現新聞的主要人物、地點或活動，"
        "回傳 {\"indices\":[]}；否則回傳 {\"indices\":[整數,...]}，最有關聯者在前，不要為了數量放入不相關圖片。"
        "只輸出 JSON。新聞：" + _article_brief(article) + " 候選：" +
        json.dumps([{"index": i, "title": c["description"],
                     "year": c["photoYear"]} for i, c in enumerate(candidates)],
                   ensure_ascii=False)}]
    found = []
    # Keep the existing per-request visual budget; the gallery retains at most five.
    for offset in range(0, len(candidates), MAX_CANDIDATES):
        chunk = candidates[offset:offset + MAX_CANDIDATES]
        prompt = [{"type": "input_text", "text": content[0]["text"].split(" 候選：")[0] + " 候選：" +
                   json.dumps([{"index": i, "title": c["description"], "year": c["photoYear"]}
                               for i, c in enumerate(chunk)], ensure_ascii=False)}]
        prompt.extend({"type": "input_image", "image_url": c["url"], "detail": "low"} for c in chunk)
        selection = _ask(prompt, max_output_tokens=2048)
        indices = selection.get("indices", [selection.get("index")])
        if not isinstance(indices, list):
            continue
        for index in indices:
            if type(index) is int and 0 <= index < len(chunk):
                photo = chunk[index]
                if photo not in found and not rejection_reason(article, photo):
                    found.append(photo)
    from image_galleries import verified
    return verified(article, found)


def find_image(article, usage):
    """Compatibility for callers that only need a cover."""
    photos = find_images(article, usage)
    return photos[0] if photos else None


def main():
    if not os.environ.get("OPENAI_API_KEY"):
        print("terra images: no API key; skipped")
        return 0
    now = now_utc()
    cache = load_json(CACHE_PATH, {})
    if not isinstance(cache, dict):
        cache = {}
    from roundup_images import expand_batches
    batches = expand_batches(list(images._recent_batches()))
    usage = stock_usage([a for _, _, adapter in batches for a in adapter.articles])
    attempted = attached = 0
    for path, batch, adapter in batches:
        articles = adapter.articles
        changed = False
        for article in articles:
            art_id = str(article.get("id") or "")
            if (not art_id or article.get("editorialImageLocked") is True
                    or manual_image(article, article.get("image"))
                    or article.get("articleFormat") == "roundup"):
                continue
            try:
                age = now - parse_iso(str(article.get("publishedUtc")))
            except (ValueError, TypeError):
                continue
            if not timedelta(0) <= age <= MAX_AGE:
                continue
            current = article.get("image")
            if current and (not isinstance(current, dict)
                            or current.get("kind") != "file_photo"
                            or current.get("selectionModel") == MODEL):
                continue
            previous = cache.get(art_id) or {}
            try:
                if parse_iso(previous["next_retry_utc"]) > now:
                    continue
            except (KeyError, ValueError, TypeError):
                pass
            attempted += 1
            try:
                photos = find_images(article, usage)
                candidate = photos[0] if photos else None
            except (requests.RequestException, RuntimeError, ValueError, KeyError, TypeError) as exc:
                print(f"terra images: {art_id}: {type(exc).__name__}")
                candidate = None
            cache[art_id] = {"checked_utc": now.isoformat(),
                             "next_retry_utc": (now + RETRY).isoformat(),
                             "status": "matched" if candidate else "none"}
            if candidate and (image_key(candidate) != image_key(current)
                              or any(image_key(p) not in {image_key(i) for i in article.get("images") or []}
                                     for p in photos)):
                previous_usage = stock_usage([article])
                from image_galleries import verified
                article["images"] = verified(article, [*photos, *(article.get("images") or []), current])
                article["image"] = article["images"][0]
                article.pop("imageSelection", None)
                usage.subtract(previous_usage)
                usage.update(stock_usage([article]))
                attached += 1
                changed = True
        if adapter.sync() or changed:
            save_json(path, batch)
    if attempted:
        save_json(CACHE_PATH, cache)
    print(f"terra images: reviewed {attempted}; attached {attached}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
