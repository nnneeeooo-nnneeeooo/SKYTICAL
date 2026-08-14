"""Deterministic topic-photo fallbacks for stories the strict matcher cannot cover.

This stage runs after images.py. It only fills articles whose ``image`` is
still empty, and only for explicitly mapped aviation topics with a vetted,
freely licensed Wikimedia Commons photograph. This preserves images.py's
strict event/airframe matching while preventing visually relevant policy or
regulatory stories from being left without a real illustration.

The site templates still provide the final SKYTICAL brand-image fallback, so
published pages never render an empty image slot even when no topic rule
matches.
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTICLES_DIR, load_json, now_utc, parse_iso, save_json

MAX_ARTICLE_AGE_DAYS = 14

# Every entry must be manually vetted for relevance and reusable licensing.
# Keep these generic: they are file photos, never represented as event photos.
_TOPIC_IMAGES = (
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


def topic_image(article: dict) -> dict | None:
    """Return a vetted generic file photo for a clearly matched topic."""
    text = _article_text(article)
    for rule in _TOPIC_IMAGES:
        if any(pattern.search(text) for pattern in rule["patterns"]):
            return dict(rule["image"])
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
            if not isinstance(article, dict) or article.get("image"):
                continue
            try:
                if parse_iso(str(article.get("publishedUtc"))) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            image = topic_image(article)
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

    print(f"image_fallbacks: {attached} article(s) got a topic photo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
