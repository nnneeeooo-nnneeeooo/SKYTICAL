"""Regression checks for SKYTICAL news freshness and time semantics."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import common  # noqa: E402


def _article(*, published: str, source_published: str) -> dict:
    return {
        "id": "a-20261001-1200-freshness-test",
        "publishedUtc": published,
        "sourcePublishedUtc": source_published,
        "cat": "biz",
        "primarySource": "Test source",
        "zh": {
            "title": "測試新聞",
            "summary": "測試來源時間與補收錄標示。",
            "body": ["這是一則測試新聞。"],
        },
        "en": {
            "title": "Freshness test",
            "summary": "Tests source-time ordering and backfill semantics.",
            "body": ["This is a test story."],
        },
        "sources": [{"name": "Test source", "url": "https://example.com/news"}],
    }


def main() -> None:
    # Official discovery coverage for previously missed high-value sources.
    for key in ("starluxnews", "americannews", "bfu"):
        assert key in common.SOURCES
        source = common.SOURCES[key]
        assert source["kind"] == "official"
        assert source["type"] == "rss"
        assert "news.google.com/rss/search" in source["endpoint"]

    # First site publication drives reader-facing chronology.
    late = build.prep_article(_article(
        published="2026-10-01T12:00Z",
        source_published="2026-09-29T10:00Z",
    ))
    assert late is not None
    assert late["news_dt"].isoformat().startswith("2026-10-01T12:00")
    assert late["source_meta_ts"].startswith("2026-09-29")
    assert late["published_dt"].isoformat().startswith("2026-10-01T12:00")
    assert late["late_ingest"] is True

    fresh = build.prep_article(_article(
        published="2026-10-01T12:00Z",
        source_published="2026-10-01T08:00Z",
    ))
    assert fresh is not None
    assert fresh["late_ingest"] is False

    article_template = (ROOT / "templates" / "article.html").read_text(encoding="utf-8")
    assert "t.lateIngestLabel" in article_template
    assert '"publishedLabel": "SKYTICAL 發布"' in (
        ROOT / "pipeline" / "build.py").read_text(encoding="utf-8")
    assert '"publishedLabel": "SKYTICAL published"' in (
        ROOT / "pipeline" / "build.py").read_text(encoding="utf-8")

    hourly = (ROOT / ".github" / "workflows" / "hourly.yml").read_text(encoding="utf-8")
    briefing = (ROOT / ".github" / "workflows" / "briefing.yml").read_text(encoding="utf-8")
    assert "group: skytical-news-pipeline" in hourly
    assert "group: skytical-briefing-pipeline" in briefing
    assert hourly.count("group: skytical-pages-publish") == 1
    assert briefing.count("group: skytical-pages-publish") == 1

    print("test_news_freshness: OK")


if __name__ == "__main__":
    main()
