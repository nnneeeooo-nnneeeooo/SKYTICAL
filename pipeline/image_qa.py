"""Maintain a seven-day queue for manual image visual checks.

The automatic image policy can reject obvious metadata mismatches, but it
cannot know whether a thumbnail actually depicts the promised subject.  This
queue records every current article image with enough context for a human to
inspect it.  It is deliberately kept under ``data/`` and is not copied into
the public site.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (ARTICLES_DIR, DATA_DIR, load_json, now_utc, parse_iso,
                    save_json)

QA_PATH = DATA_DIR / "image-qa.json"
MAX_ARTICLE_AGE_DAYS = 7
MAX_QUEUE_ITEMS = 200
VALID_STATUSES = {"pending", "approved", "rejected"}


def _image_snapshot(image: dict) -> dict:
    """Keep provenance fields useful to a reviewer, not arbitrary payload."""
    return {
        key: image.get(key)
        for key in ("url", "link", "provider", "kind", "matched",
                    "subject", "credit", "license", "photoYear")
        if image.get(key) not in (None, "")
    }


def _article_rows(articles_dir: Path, now):
    cutoff = now - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    for path in sorted(articles_dir.glob("*.json"), reverse=True):
        batch = load_json(path, None)
        if not isinstance(batch, dict):
            continue
        for article in batch.get("articles") or []:
            if not isinstance(article, dict) or not article.get("id"):
                continue
            try:
                published = parse_iso(str(article.get("publishedUtc")))
            except (TypeError, ValueError):
                continue
            if published < cutoff or not isinstance(article.get("image"), dict):
                continue
            image = article["image"]
            if not str(image.get("url") or "").strip():
                continue
            yield article, published, image


def _queue_key(article: dict, image: dict) -> str:
    return f"{article.get('id')}|{image.get('url')}"


def build_queue(now, *, articles_dir: Path = ARTICLES_DIR,
                existing: dict | None = None) -> dict:
    """Return the current seven-day visual-review queue."""
    old_items = (existing or {}).get("items") if isinstance(existing, dict) else []
    old_by_key = {
        str(row.get("key")): row for row in old_items
        if isinstance(row, dict) and row.get("key")
    }
    rows = []
    for article, published, image in _article_rows(articles_dir, now):
        key = _queue_key(article, image)
        old = old_by_key.get(key) or {}
        status = (old.get("status") if old.get("status") in VALID_STATUSES
                  else "pending")
        zh = article.get("zh") if isinstance(article.get("zh"), dict) else {}
        en = article.get("en") if isinstance(article.get("en"), dict) else {}
        row = {
            "key": key,
            "articleId": str(article["id"]),
            "publishedUtc": published.isoformat(),
            "title": {
                "zh": str(zh.get("title") or en.get("title") or ""),
                "en": str(en.get("title") or zh.get("title") or ""),
            },
            "image": _image_snapshot(image),
            "status": status,
            "createdUtc": str(old.get("createdUtc") or now.isoformat()),
            "lastSeenUtc": now.isoformat(),
        }
        if isinstance(old.get("note"), str) and old["note"].strip():
            row["note"] = old["note"][:500]
        rows.append(row)

    rows.sort(key=lambda row: row["publishedUtc"], reverse=True)
    return {
        "updatedUtc": now.isoformat(),
        "windowDays": MAX_ARTICLE_AGE_DAYS,
        "items": rows[:MAX_QUEUE_ITEMS],
    }


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("image_qa: no articles yet")
        return 0
    existing = load_json(QA_PATH, {})
    payload = build_queue(now_utc(), existing=existing)
    if payload != existing:
        save_json(QA_PATH, payload)
    pending = sum(row.get("status") == "pending" for row in payload["items"])
    print(f"image_qa: {len(payload['items'])} current image(s), "
          f"{pending} pending visual review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
