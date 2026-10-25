"""Offline selection and rendered-link checks for the homepage right rail."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import build


def test_taiwan_sidebar_selection():
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)

    def article(title, hours, body=""):
        return {
            "id": title, "published_dt": now - timedelta(hours=hours),
            "source": "Test source",
            "zh": {"title": title, "summary": "", "body": [body]},
            "en": {"title": title, "summary": "", "body": [body]},
        }

    local = [article(f"星宇航空新增航線 {index}", index) for index in range(7)]
    excluded = [
        article("Taiwan airport old announcement", 169),
        article("華航未來消息", -1),
        article("Cathay Pacific announces new London flights", 1),
        article("US TSA announces security policy", 1),
        article("Boeing quarterly earnings", 1, body="臺灣、Taiwan"),
    ]
    selected = build.taiwan_sidebar_articles(list(reversed(local)) + excluded, now)
    assert selected == local[:5]
    assert build.taiwan_sidebar_articles(excluded, now) == []
    assert build.taiwan_sidebar_articles([], now) == []
    boundary = article("EVA Air fleet update", 168)
    assert build.taiwan_sidebar_articles([boundary], now) == [boundary]


def test_rendered_sidebar():
    assert build.main() == 0
    for lang, prefix in (("zh", ""), ("en", "en/")):
        path = build.SITE_DIR / prefix / "index.html"
        soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")
        rail = soup.select_one(".rail-right")
        assert rail.select_one("#taiwan-focus-heading").text == build.L[lang]["taiwanFocusTitle"]
        assert rail.select_one("#explore-topics-heading").text == build.L[lang]["exploreTopics"]
        assert len(rail.select(".rail-story")) <= 5
        assert rail.select(".rail-story") or rail.select_one(".rail-empty")
        topics = rail.select(".rail-topics a")
        assert len(topics) == len(build.TOPICS)
        for link in rail.select(".rail-story, .rail-more, .rail-topics a"):
            url = link["href"]
            assert url.startswith(f"/{prefix}")
            assert (build.SITE_DIR / url.lstrip("/") / "index.html").is_file()
        for timestamp in rail.select(".rail-story time"):
            assert build.parse_iso(timestamp["datetime"])


def test_compact_attribution_preserves_article_references():
    import json
    raw = json.loads((ROOT / "data" / "articles" /
                     "manual-cal-b18306-lease-return-20261021.json").read_text())
    article = raw["articles"][0]
    assert article["primarySource"] == "Flightradar24"
    assert len(article["sources"]) == 3
    assert article["sources"][0]["url"].endswith("/b-18306")
    for prefix in ("", "en/"):
        home = BeautifulSoup((build.SITE_DIR / prefix / "index.html").read_text(
            encoding="utf-8"), "html.parser")
        public_id = build.public_article_id(article["id"])
        row = home.select_one(f'.feed-row[href="/{prefix}news/{public_id}/"]')
        if row:  # This report eventually ages out of the homepage feed.
            assert row.select_one(".feed-source").text.strip() == "Flightradar24"
        page = build.SITE_DIR / prefix / "news" / public_id / "index.html"
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        for source in article["sources"]:
            assert soup.find("a", href=source["url"])


if __name__ == "__main__":
    test_taiwan_sidebar_selection()
    test_rendered_sidebar()
    test_compact_attribution_preserves_article_references()
    print("test_home_sidebar: 3 passed")
