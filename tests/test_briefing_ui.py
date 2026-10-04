"""Offline contract checks for the public aviation briefing views.

Run from the repository root with::

    python tests/test_briefing_ui.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-brief-ui-")
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader  # noqa: E402

# Keep calendar assertions independent of the machine clock and timezone.
build.now_utc = lambda: datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def row(date: str, edition: str, *, cutoff: str | None = None,
        url: str | None = None) -> dict:
    hour = {"morning": "07", "afternoon": "15", "evening": "23"}[edition]
    return {
        "date_iso": date,
        "edition": edition,
        "url": url or f"/briefings/{date}-{edition}/",
        "cutoff_iso": cutoff or f"{date}T{hour}:00:00+08:00",
    }


def period(nav: dict, edition: str) -> dict:
    return next(p for p in nav["periods"] if p["edition"] == edition)


def test_calendar_gaps_disable_neighbor_links() -> None:
    current = row("2026-10-05", "afternoon")
    briefs = [current, row("2026-10-03", "evening"),
              row("2026-10-07", "morning")]
    nav = build.briefing_navigation(current, briefs, "zh")

    assert nav["date"] == "2026-10-05"
    assert nav["previous_url"] is None  # 10-04 has no issue
    assert nav["next_url"] is None  # 10-06 has no issue
    assert period(nav, "afternoon")["selected"] is True
    assert [p["label"] for p in nav["periods"]] == ["早晨", "中午", "傍晚"]


def test_unpublished_evening_and_future_data_are_not_links() -> None:
    current = row("2026-10-05", "afternoon")
    evening = row("2026-10-05", "evening")
    tomorrow = row("2026-10-06", "morning")
    # These future records exercise the view's fail-safe even if a caller
    # accidentally passes a row that should already have been filtered.
    evening["cutoff_iso"] = "2026-10-05T23:00:00+08:00"
    nav = build.briefing_navigation(current, [current, evening, tomorrow], "zh")

    evening_period = period(nav, "evening")
    assert evening_period["available"] is False
    assert evening_period["url"] is None
    assert nav["next_url"] is None


def test_neighbor_day_falls_back_to_its_latest_available_edition() -> None:
    current = row("2026-10-05", "afternoon")
    previous_morning = row("2026-10-04", "morning")
    nav = build.briefing_navigation(
        current, [current, previous_morning], "en")

    assert nav["previous_url"] == previous_morning["url"]
    assert period(nav, "morning")["label"]
    assert period(nav, "morning")["available"] is False
    assert period(nav, "morning")["url"] is None
    assert [p["label"] for p in nav["periods"]] == [
        "Morning", "Afternoon", "Evening"]


def test_item_keyword_language_photo_refresh_and_dangling_article() -> None:
    item = {
        "headline": "Airbus A350 N123AB 航班調整",
        "headline_en": "Airbus A350 N123AB flight schedule change",
        "summary": "快報摘要",
        "summary_en": "Brief summary",
        "keyword_zh": "已保存的中文關鍵字",
        "keyword_en": "Saved English keyword",
        "article_id": "published-story",
        "image": {"url": "https://images.example.com/old-snapshot.jpg"},
        "source_published_at": "2026-10-05T01:00:00Z",
        "sources": [{"name": "Example", "url": "https://example.com/story"}],
    }
    published_ids = {"published-story"}
    fallback_zh = build.brief_item_view(item, "zh", published_ids)
    fallback_en = build.brief_item_view(item, "en", published_ids)
    fallback_photo = f"{build.BASE_PATH}/assets/skytical-social.png?v="
    assert fallback_zh["keyword"] == item["keyword_zh"]
    assert fallback_en["keyword"] == item["keyword_en"]
    assert fallback_zh["url"]
    assert fallback_zh["image_url"].startswith(fallback_photo)
    no_saved_keyword = deepcopy(item)
    no_saved_keyword.pop("keyword_zh")
    no_saved_keyword.pop("keyword_en")
    title_fallback = build.brief_item_view(
        no_saved_keyword, "zh", published_ids)
    assert "A350" in title_fallback["keyword"]
    assert "N123AB" in title_fallback["keyword"]

    article = {
        "image": {
            "url": "https://images.example.com/current.jpg",
            "credit": "Example photographer",
            "link": "https://images.example.com/credit",
            "license": "CC BY 4.0",
            "kind": "event_photo",
            "subject": "Aircraft at airport",
        },
    }
    current_photo = build.brief_item_view(
        item, "zh", published_ids, {"published-story": article})
    assert current_photo["image_url"] == article["image"]["url"]
    assert current_photo["image_alt"]
    assert current_photo["image_credit"] == "Example photographer"
    assert current_photo["image_credit_url"] == "https://images.example.com/credit"
    assert current_photo["image_license"] == "CC BY 4.0"
    assert current_photo["photo_kind"] == "event_photo"
    assert current_photo["keyword"] == fallback_zh["keyword"]

    # An ID that is absent from the published set cannot be made into an
    # internal story link, even if a matching lookup row happens to exist.
    dangling = build.brief_item_view(item, "zh", set(), {
        "published-story": article,
    })
    assert dangling["url"] is None


def test_brief_view_keeps_only_aviation_and_merges_taiwan_subsections() -> None:
    brief = {
        "briefing_id": "2026-10-05-afternoon",
        "edition": "afternoon",
        "date": "2026-10-05",
        "status": "published",
        "cutoff_time": "2026-10-05T15:00:00+08:00",
        "sections": {
            "aviation_incidents": [{"headline": "航空事故", "summary": "事故摘要",
                                    "origin": "grounded",
                                    "article_id": "published-incident"}],
            "taiwan_aviation": [
                {"headline": "臺灣民航", "summary": "民航摘要",
                 "origin": "grounded", "article_id": "published-civil"},
                {"headline": "臺灣軍機", "summary": "軍機摘要",
                 "origin": "grounded", "article_id": "published-mil",
                 "military": True},
                {"headline": "無原文的搜尋快報", "summary": "不可刊出",
                 "origin": "grounded", "article_id": "unpublished"},
            ],
            "international_aviation": [{"headline": "國際航空", "summary": "國際摘要",
                                        "origin": "grounded",
                                        "article_id": "published-international"}],
            "ground_and_maritime": [{"headline": "地面與海事", "summary": "不可刊出"}],
        },
    }
    view = build.brief_view(
        brief, "zh", build.L["zh"], {
            "published-incident", "published-civil", "published-mil",
            "published-international",
        })
    assert len(view["sections"]) == 3
    taiwan = view["sections"][1]
    assert taiwan["subsections"] == []
    assert [it["headline"] for it in taiwan["items"]] == ["臺灣民航", "臺灣軍機"]
    assert "地面與海事" not in repr(view)
    assert "不可刊出" not in repr(view)
    assert "無原文的搜尋快報" not in repr(view)


def test_jinja_index_and_detail_show_one_report_with_photo_citation() -> None:
    brief = {
        "briefing_id": "2026-10-05-morning",
        "edition": "morning",
        "date": "2026-10-05",
        "status": "published",
        "cutoff_time": "2026-10-05T07:00:00+08:00",
        "window_start": "2026-10-04T07:00:00+08:00",
        "window_end": "2026-10-05T07:00:00+08:00",
        "sections": {
            "aviation_incidents": [{
        "headline": "Airbus A350 N123AB 航班調整",
                "summary": "航班異動摘要",
        "keyword_zh": "Airbus A350 航班調整",
                "article_id": "published-story",
                "sources": [{"name": "Private test source",
                             "url": "https://private.example.test/source"}],
            }],
        },
    }
    published = {"published-story"}
    article_lookup = {"published-story": {
        "image": {
            "url": "https://images.example.test/current.jpg",
        "subject": "Airbus A350 at airport",
            "credit": "Test photographer",
            "link": "https://images.example.test/credit",
            "license": "CC BY 4.0",
            "kind": "event_photo",
        },
    }}
    view = build.brief_view(
        brief, "zh", build.L["zh"], published, article_lookup)
    nav = build.briefing_navigation(view, [view], "zh")
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block content %}{% endblock %}"
                                "{% block body_scripts %}{% endblock %}"}),
        FileSystemLoader(str(ROOT / "templates")),
    ]), autoescape=True)
    context = {
        "b": view,
        "briefing_navigation": nav,
        "t": build.L["zh"],
        "lang": "zh",
        "base": build.BASE_PATH,
        "fallback_image_url": f"{build.BASE_PATH}/assets/skytical-social.png?v={build.ASSET_VERSION}",
        "asset_version": build.ASSET_VERSION,
    }
    detail = env.get_template("briefing.html").render(**context)
    index = env.get_template("briefings.html").render(**context)

    for rendered in (detail, index):
        assert rendered.count('class="briefing-report"') == 1
        assert rendered.count('class="briefing-story"') == 1
        assert rendered.count('class="briefing-thumbnail"') == 1
        assert rendered.count('<img src="https://images.example.test/current.jpg"') == 1
        assert rendered.count('class="briefing-citation"') == 1
        assert 'title="Airbus A350 N123AB 航班調整"' in rendered
        assert "Airbus A350 航班調整" in rendered
        assert "Private test source" not in rendered
        assert "private.example.test/source" not in rendered
        assert "Test photographer" in rendered
        assert "CC BY 4.0" in rendered
    css = (ROOT / "static" / "briefing.css").read_text(encoding="utf-8")
    assert ".briefing-citation" in css and "color-mix" in css


def main() -> int:
    tests = [
        test_calendar_gaps_disable_neighbor_links,
        test_unpublished_evening_and_future_data_are_not_links,
        test_neighbor_day_falls_back_to_its_latest_available_edition,
        test_item_keyword_language_photo_refresh_and_dangling_article,
        test_brief_view_keeps_only_aviation_and_merges_taiwan_subsections,
        test_jinja_index_and_detail_show_one_report_with_photo_citation,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
