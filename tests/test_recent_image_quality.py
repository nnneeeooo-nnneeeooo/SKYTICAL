"""Fail closed when the current seven-day data contains an unsafe image."""
from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import images  # noqa: E402
from image_policy import (  # noqa: E402
    article_is_airport_operations,
    article_is_drone_story,
)


def main() -> int:
    cutoff = images.now_utc() - timedelta(days=images.MAX_ARTICLE_AGE_DAYS)
    total = with_image = structured = 0
    failures: list[str] = []
    for path in sorted(images.ARTICLES_DIR.glob("*.json")):
        batch = json.loads(path.read_text(encoding="utf-8"))
        for article in batch.get("articles") or []:
            try:
                published = images.parse_iso(str(article.get("publishedUtc")))
            except (TypeError, ValueError):
                continue
            if published < cutoff:
                continue
            total += 1
            image = article.get("image")
            if not image:
                continue
            with_image += 1
            if not isinstance(image, dict):
                continue
            structured += 1
            matched = str(image.get("matched") or "")
            valid = images.existing_image_matches(article, image)
            if matched.casefold().startswith("airport:"):
                valid = valid and article_is_airport_operations(article)
            if matched.casefold().startswith("topic:drone"):
                valid = valid and article_is_drone_story(article)
            if not valid:
                failures.append(str(article.get("id") or path.name))

    print(
        f"recent image audit: {total} article(s), {with_image} with image, "
        f"{structured} structured, {len(failures)} unsafe"
    )
    if failures:
        print("unsafe: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
