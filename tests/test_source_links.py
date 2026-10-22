"""Regression checks for direct public source links."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
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

    # Persisted corporate rows remain fetchable, but cannot leak into either
    # language's selected directory even when their public flag is true.
    corporate_keys = {"starluxnews", "americannews", "evaair", "hainanair",
                      "airbus", "boeing", "iata"}
    corporate_names = {common.SOURCES[key]["name"] for key in corporate_keys}
    stale_rows = [{"key": key, "public": True} for key in corporate_keys]
    merged = build.merged_sources(stale_rows)
    assert corporate_keys.issubset({row["key"] for row in merged})
    for lang in ("zh", "en"):
        rows = build.sources_rows_view(merged, lang, datetime.now(timezone.utc))
        names = {row["name"] for row in rows}
        status = build.source_status_view(merged, datetime.now(timezone.utc), lang)
        assert {row["name"] for row in status} == names
        assert not names & corporate_names
        assert {"FAA", "NTSB", "ICAO", "EASA", "Reuters", "AeroTime",
                "CAA Taiwan", "FlightAware"}.issubset(names)
    assert all(common.SOURCES[key].get("endpoint") for key in corporate_keys)

    # Every non-archived historical article must retain at least one direct
    # publisher/source URL. Google News may be discovery input, but it is not
    # a public attribution target and build.py intentionally filters it out.
    google_only = []
    for path in sorted(build.ARTICLES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for article in payload.get("articles", []):
            if not isinstance(article, dict) or article.get("archived") is True:
                continue
            urls = [
                str(source.get("url") or "")
                for source in article.get("sources", [])
                if isinstance(source, dict) and source.get("url")
            ]
            direct_urls = [
                url for url in urls
                if url.startswith(("http://", "https://"))
                and not common.is_google_news_url(url)
            ]
            if not direct_urls:
                google_only.append((path.name, article.get("id")))
    assert not google_only, f"published articles without direct sources: {google_only}"

    print("PASS test_source_links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
