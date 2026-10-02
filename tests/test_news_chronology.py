"""Chronological feeds and search must agree with the displayed news time."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build


def test_news_chronology():
    def article(id, published, source=None, sort=None):
        row = {
            "id": id, "publishedUtc": published, "cat": "ops",
            "zh": {"title": "台灣虎航接收A320neo客機", "body": ["交機新聞。"]},
            "sources": [{"name": "Test", "url": "https://example.com/news"}],
        }
        if source is not None:
            row["sourcePublishedUtc"] = source
        if sort is not None:
            row["sortUtc"] = sort
        return row

    rows = [
        article("older-late-generated", "2026-10-01T02:00:00Z",
                "2026-09-28T08:00:00Z"),
        article("newer-manual", "2026-09-30T08:50:00Z",
                "2026-09-30T08:50:00Z", "2026-09-20T00:00:00Z"),
        article("no-source-time", "2026-09-29T08:00:00Z"),
        article("invalid-source-time", "2026-09-27T08:00:00Z", "invalid"),
        article("date-only-source", "2026-10-01T03:00:00Z",
                "2026-09-26T00:00:00Z"),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        (folder / "fixture.json").write_text(json.dumps({"articles": rows}))
        with patch.object(build, "ARTICLES_DIR", folder):
            collected = build.collect_articles()
    assert [a["id"] for a in collected] == [
        "date-only-source", "older-late-generated", "newer-manual",
        "no-source-time", "invalid-source-time",
    ]
    assert collected[0]["meta_ts"] == "2026-10-01 11:00 AM UTC+8"
    assert collected[0]["source_meta_ts"] == "2026-09-26"
    assert collected[-1]["source_meta_ts"] is None
    for prepared in collected:
        indexed = build.search_index_item(prepared, [])
        assert build.parse_iso(indexed["published"]) == prepared["news_dt"]
    assert collected[2]["published_iso"] == "2026-09-30T08:50:00Z"
    revised = rows[0] | {"updatedUtc": "2026-10-02T08:00:00Z"}
    assert build.prep_article(revised)["news_dt"] == collected[1]["news_dt"]


if __name__ == "__main__":
    test_news_chronology()
    print("PASS news chronology, source-time fallback and search timestamps")
