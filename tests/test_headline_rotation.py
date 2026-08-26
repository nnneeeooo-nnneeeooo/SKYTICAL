"""Regression tests for weather-driven national-airline hero pinning."""
from datetime import timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import build


def _article(now, title, summary, *, source="中央社 CNA 國籍航空",
             age_hours=1):
    return {
        "published_dt": now - timedelta(hours=age_hours),
        "source": source,
        "zh": {"title": title, "summary": summary},
        "en": {"title": title, "summary": summary},
    }


def test_weather_national_airline_flight_change_is_priority_story():
    now = build.now_utc()
    article = _article(
        now,
        "颱風沙德爾逼近 國籍航空調整25與26日沖繩航班",
        "受到颱風影響，國籍航空調整航班並協助旅客疏運。",
    )
    assert build.is_weather_airline_flight_story(article, now)


def test_priority_story_requires_all_three_signals():
    now = build.now_utc()
    weather_only = _article(
        now,
        "颱風影響東部地區",
        "氣象單位提醒民眾注意強風豪雨。",
        source="中央氣象署",
    )
    airline_only = _article(
        now,
        "華航宣布新增台北巴黎航線",
        "中華航空公布新航線與航班時刻。",
    )
    no_weather = _article(
        now,
        "華航籌集180萬元公益款項捐贈團體",
        "中華航空捐贈公益團體，會員哩程突破百萬哩。",
    )
    assert not build.is_weather_airline_flight_story(weather_only, now)
    assert not build.is_weather_airline_flight_story(airline_only, now)
    assert not build.is_weather_airline_flight_story(no_weather, now)


def test_priority_story_at_sixteen_hours_is_still_pinned():
    now = build.now_utc()
    article = _article(
        now,
        "豪雨造成國籍航空航班異動",
        "國籍航空因天候調整航班。",
        age_hours=16,
    )
    assert build.is_weather_airline_flight_story(article, now)


def test_stale_priority_story_is_not_pinned():
    now = build.now_utc()
    article = _article(
        now,
        "豪雨造成國籍航空航班異動",
        "國籍航空因天候調整航班。",
        age_hours=17,
    )
    assert not build.is_weather_airline_flight_story(article, now)


def test_rotation_payload_contains_localized_hero_fields():
    view = {
        "id": "a-weather-flight",
        "url": "/news/a-weather-flight/",
        "external": False,
        "title": "颱風影響航班",
        "display_summary": "國籍航空調整航班。",
        "cat_label": "營運",
        "article_format": "brief",
        "time": "6:00 PM",
        "source": "中央社 CNA 國籍航空",
        "image": {
            "url": "https://example.com/aircraft.jpg",
            "subject": "China Airlines Boeing 777-300ER",
            "kind": "file_photo",
            "credit": "Photographer",
            "license": "CC BY 4.0",
            "provider": "Wikimedia Commons",
        },
    }
    payload = build.hero_rotation_view(view, "zh")
    assert payload["kicker"] == "營運 · 短訊 — 頭條"
    assert payload["summary"] == "國籍航空調整航班。"
    assert "China Airlines Boeing 777-300ER" in payload["image_caption"]
    assert build.HERO_ROTATION_SECONDS == 300


def main() -> int:
    tests = (
        test_weather_national_airline_flight_change_is_priority_story,
        test_priority_story_requires_all_three_signals,
        test_priority_story_at_sixteen_hours_is_still_pinned,
        test_stale_priority_story_is_not_pinned,
        test_rotation_payload_contains_localized_hero_fields,
    )
    for test in tests:
        test()
    print(f"test_headline_rotation: {len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
