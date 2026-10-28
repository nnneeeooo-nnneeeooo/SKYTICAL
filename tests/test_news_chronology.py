"""Chronological feeds and search must agree with the displayed news time."""
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined

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



def test_wsi_opening_article_public_and_searchable():
    # Regression: a source file existing is not enough; users must be able to
    # find the opening by the airport's name and IATA code.
    repository = Path(__file__).resolve().parents[1]
    canonical_path = repository / "data" / "articles" / "scheduled-western-sydney-airport-opens-20261025.json"
    duplicate_path = repository / "data" / "articles" / "2026-10-25T10.json"
    canonical = json.loads(canonical_path.read_text(encoding="utf-8"))["articles"][0]
    duplicate = json.loads(duplicate_path.read_text(encoding="utf-8"))["articles"][0]
    assert canonical["id"] == "a-western-sydney-airport-opens-20261025"
    assert canonical.get("archived") is not True
    assert duplicate.get("archived") is True
    assert "西雪梨國際機場" in canonical["zh"]["title"]
    assert "WSI" in canonical["zh"]["title"]
    assert "10月25日" in canonical["zh"]["title"]
    assert "1,000萬" in canonical["zh"]["summary"]
    assert "8,000萬" in canonical["zh"]["summary"]
    assert "7月下旬" in " ".join(canonical["zh"]["body"])
    prepared = build.prep_article(canonical)
    assert prepared is not None
    assert build.prep_article(duplicate) is None
    record = build.search_index_item(prepared, [])
    assert record["id"] == canonical["id"]
    assert "WSI" in record["title"]["zh"]
    assert "西雪梨國際機場" in record["title"]["zh"]
    assert record["url"]["zh"].endswith("/news/a-western-sydney-airport-opens-20261025/")
    assert build.parse_iso(record["published"]).date().isoformat() == "2026-10-25"


def test_flash_dates_and_marquee_accessibility():
    # Taipei has crossed midnight while UTC is still on the previous day.
    now = datetime(2026, 10, 24, 16, 30, tzinfo=timezone.utc)
    rows = [
        {"timeUtc": "2026-10-24T16:15Z", "articleId": "today",
         "zh": "今日快訊", "en": "Today's flash", "hot": True},
        {"timeUtc": "2026-10-24T15:59Z", "articleId": "yesterday",
         "zh": "昨日快訊", "en": "Yesterday's flash"},
        {"timeUtc": "2026-10-22T10:54Z", "articleId": "older",
         "zh": "舊快訊", "en": "Older flash"},
    ]
    with patch.object(build, "now_utc", return_value=now):
        flashes = build.prep_flashes(rows, {"today", "yesterday", "older"})
    assert [f["time"] for f in flashes] == ["12:15 AM", "10/24", "10/22"]
    env = Environment(loader=FileSystemLoader(build.TEMPLATES_DIR),
                      undefined=StrictUndefined, autoescape=True)
    for lang in ("zh", "en"):
        ticker = build.flash_view(flashes, lang, {"today"})
        assert ticker[0]["hot"] and ticker[0]["priority"]
        assert ticker[1]["url"] == build.page_url(lang, "news/yesterday/")
        context = build.base_ctx(
            lang, "home", "", title="Test", description="Test", ticker=ticker,
            build={"date": "2026-10-25", "utc_hm": "4:30 PM",
                   "tpe_hm": "12:30 AM", "stamp": "2026-10-24 4:30 PM"})
        soup = BeautifulSoup(env.get_template("base.html").render(**context),
                             "html.parser")
        original, duplicate = soup.select(".ticker-pass")
        assert not original.has_attr("aria-hidden")
        assert duplicate["aria-hidden"] == "true"
        assert len(original.select("a")) == len(duplicate.select("a")) == 3
        assert all(a.get("tabindex") is None for a in original.select("a"))
        assert all(a.get("tabindex") == "-1" for a in duplicate.select("a"))
        assert [a["href"] for a in original.select("a")] == [
            a["href"] for a in duplicate.select("a")]
        assert [t.text for t in original.select(".ticker-time")] == [
            "12:15 AM", "10/24", "10/22"]


if __name__ == "__main__":
    test_news_chronology()
    test_wsi_opening_article_public_and_searchable()
    test_flash_dates_and_marquee_accessibility()
    print("PASS news chronology, flash dates and marquee accessibility")
