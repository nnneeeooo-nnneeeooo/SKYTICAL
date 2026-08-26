"""Regression checks for direct public source links."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import common  # noqa: E402
import write  # noqa: E402


def main() -> int:
    google = "https://news.google.com/rss/articles/example?oc=5"
    direct = "https://www.reuters.com/world/example"
    assert common.is_google_news_url(google)
    assert not common.is_google_news_url(direct)
    assert not common.is_google_news_url("https://www.google.com/search?q=aviation")

    sources = write.build_sources([
        {"title": "Google discovery", "source": "Reuters", "url": google},
        {"title": "Original report", "source": "Reuters", "url": direct},
    ])
    assert [source["url"] for source in sources] == [direct]

    raw = {
        "id": "a-source-filter",
        "publishedUtc": "2026-08-26T00:00Z",
        "cat": "ops",
        "primarySource": "Reuters",
        "zh": {"title": "航空新聞", "summary": "", "body": ["航空公司更新航線。"]},
        "en": {"title": "Airline news", "summary": "", "body": ["The airline updated its route."]},
        "sources": [
            {"name": "Reuters discovery", "url": google},
            {"name": "Reuters original", "url": direct},
        ],
    }
    prepared = build.prep_article(raw)
    assert prepared is not None
    assert [source["url"] for source in prepared["sources"]] == [direct]

    briefing_item = build.brief_item_view({
        "headline": "快報來源測試",
        "summary": "測試摘要",
        "sources": [
            {"name": "Google discovery", "url": google},
            {"name": "Original report", "url": direct},
        ],
    }, "zh", set())
    assert [source["url"] for source in briefing_item["sources"]] == [direct]

    public_sources = build.merged_sources(
        build.load_json(build.DATA_DIR / "sources.json", []))
    assert all(not common.is_google_news_url(source["url"])
               for source in public_sources)

    print("PASS test_source_links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
