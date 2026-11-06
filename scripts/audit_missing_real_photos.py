"""Temporary audit of all publicly published SKYTICAL articles lacking images."""
from __future__ import annotations
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from common import ARTICLES_DIR, DATA_DIR, load_json
import build

def main():
    published = {a["id"] for a in build.collect_articles()}
    raw_rows, gaps = 0, []
    by_category = Counter()
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        data = load_json(path, {})
        if not isinstance(data, dict):
            continue
        for article in data.get("articles", []):
            if not isinstance(article, dict):
                continue
            raw_rows += 1
            id_ = article.get("id")
            if id_ not in published or article.get("archived") is True:
                continue
            if isinstance(article.get("image"), dict) and article["image"].get("url"):
                continue
            # A few older articles store a bare image URL. Only flag empty fields.
            if isinstance(article.get("image"), str) and article["image"].strip():
                continue
            entities = article.get("entities") or {}
            sources = [s.get("url") if isinstance(s,dict) else str(s)
                       for s in (article.get("sources") or [])][:3]
            title = (article.get("zh") or {}).get("title") or ""
            en_title = (article.get("en") or {}).get("title") or ""
            gap = {
              "id": id_, "path": str(path.relative_to(ARTICLES_DIR.parent.parent)),
              "date": article.get("publishedUtc"), "cat": article.get("cat"),
              "title": title, "enTitle": en_title,
              "summary": str((article.get("en") or {}).get("summary") or "")[:280],
              "entities": entities, "sources": sources,
              "format": article.get("articleFormat"),
              "writer": article.get("writer"),
            }
            gaps.append(gap)
            by_category[str(article.get("cat"))] += 1
    report = {
      "generatedUtc": datetime.now(timezone.utc).isoformat(),
      "rawRows": raw_rows, "publicCount": len(published),
      "imageGapCount": len(gaps),
      "byCategory": dict(by_category), "gaps": gaps
    }
    path = DATA_DIR / "photo-gap-audit.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("PHOTO_AUDIT_SUMMARY " + json.dumps(
      {k:v for k,v in report.items() if k != "gaps"},ensure_ascii=False))
if __name__ == "__main__":
    main()
