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
    assert payload["kicker"] == "臺灣焦點 · 營運 · 短訊 — 頭條"
    assert payload["summary"] == "國籍航空調整航班。"
    assert "China Airlines Boeing 777-300ER" in payload["image_caption"]
    assert build.HERO_ROTATION_SECONDS == 8


def test_taiwan_focus_scores_direct_and_material_cathay_stories():
    now = build.now_utc()
    taiwan = _article(
        now, "星宇航空宣布臺北新航線", "新航線將由桃園機場出發。")
    cathay = _article(
        now, "國泰航空調整台北香港航班", "航班時刻將於冬季更新。",
        source="Cathay Pacific")
    promotion = _article(
        now, "華航公益捐贈活動", "中華航空捐贈公益團體。")
    unrelated = _article(
        now, "歐洲地方機場翻修停機坪", "工程預計年底完成。",
        source="Regional Airport News")
    tsa = _article(
        now, "911事件25週年：航空安檢演變歷程回顧",
        "美國運輸安全管理局TSA成立並導入全身掃描儀。",
        source="Aerospace Global News")
    foreign_caa = _article(
        now, "英國民航局警告雷射攻擊直升機",
        "英國民航局要求機場通報相關事件。",
        source="UK Civil Aviation Authority")
    assert build.taiwan_focus_score(taiwan, now) > \
        build.taiwan_focus_score(cathay, now) >= 60
    assert build.taiwan_focus_score(promotion, now) == 0
    assert build.taiwan_focus_score(unrelated, now) == 0
    assert build.taiwan_focus_score(tsa, now) == 0
    assert build.taiwan_focus_score(foreign_caa, now) == 0


def test_focus_selection_prefers_fresh_and_uses_safe_recent_fallback():
    now = build.now_utc()
    fresh = _article(
        now, "長榮航空新增桃園航線", "新航線預計下月開航。", age_hours=23)
    old_route = _article(
        now, "華航公布臺北巴黎新航線", "中華航空公布新航線規畫。",
        age_hours=30)
    stale_alert = _article(
        now, "颱風造成國籍航空航班取消", "航空公司宣布停飛。",
        age_hours=30)
    assert build.taiwan_focus_articles([old_route, fresh], now) == [fresh, old_route]
    assert build.taiwan_focus_articles([stale_alert, old_route], now) == [old_route]


def test_flash_priority_is_distinct_from_legacy_pinned_flag():
    flashes = [
        {"time": "6:00 PM", "hot": False, "pinned": True,
         "articleId": "a-weather", "zh": "天氣航班異動", "en": "Weather flight change",
         "available_languages": ["zh"]},
        {"time": "5:00 PM", "hot": False, "pinned": True,
         "articleId": "a-normal", "zh": "一般航空新聞", "en": "Regular aviation news",
         "available_languages": ["zh"]},
    ]
    views = build.flash_view(flashes, "zh", {"a-weather"})
    assert views[0]["pinned"] is True and views[0]["priority"] is True
    assert views[1]["pinned"] is True and views[1]["priority"] is False


def main() -> int:
    tests = (
        test_weather_national_airline_flight_change_is_priority_story,
        test_priority_story_requires_all_three_signals,
        test_priority_story_at_sixteen_hours_is_still_pinned,
        test_stale_priority_story_is_not_pinned,
        test_rotation_payload_contains_localized_hero_fields,
        test_taiwan_focus_scores_direct_and_material_cathay_stories,
        test_focus_selection_prefers_fresh_and_uses_safe_recent_fallback,
        test_flash_priority_is_distinct_from_legacy_pinned_flag,
    )
    for test in tests:
        test()
    print(f"test_headline_rotation: {len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
