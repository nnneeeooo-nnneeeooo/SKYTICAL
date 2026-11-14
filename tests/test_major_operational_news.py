"""System-wide disruption priority, scheduling and published visibility."""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
import common
import news_retry
from editorial_policy import news_policy, publication_route
from text_spacing import compact_text


def group(title, key="event"):
    return {"id": key, "items": [{"title": title, "url": f"https://example.com/{key}"}]}


@pytest.mark.parametrize("title", [
    "FAA Statement on Nationwide Ground Stop",
    "FAA halts all US departures, warns airborne flights to expect holding nationwide",
    "FAA issues nationwide ground stop after air traffic control outage",
    "FAA lifts nationwide ground stop after more than four hours",
    "FAA issues nationwide ground stop, warns recovery may take days",
    "All U.S. airports halt departures after communications failure",
    "Fleet-wide grounding halts airline operations",
    "FAA grounds all Boeing 737 aircraft",
    "全美航班暫停起飛令逾4小時後解除",
    "航管通訊中斷：美國聯邦航空總署下令全美航班地面停飛",
    "全國空域關閉 所有航班取消",
])
def test_disruptions_get_discovery_drafting_and_standalone_priority(title):
    event = group(title)
    assert common.is_major_operational_event(event)
    assert common.is_major_event_story(event)
    assert news_policy(event).priority == "urgent"
    assert news_policy(event).paid_allowed
    assert publication_route(event, {"articleFormat": "brief"}).route == "standalone"


@pytest.mark.parametrize("title", [
    "FAA expands AI traffic planning tool nationwide",
    "Nationwide Microsoft outage affects office software",
    "Could FAA issue a nationwide ground stop?",
    "FAA warns of possible nationwide ground stop",
    "FAA warns nationwide ground stop could occur",
    "Weather threatens all US flights with a ground stop",
    "Why the FAA issued a nationwide ground stop",
    "FAA says no nationwide ground stop is planned",
    "FAA prepares for nationwide ground stop drill",
    "Watch: rock bands play concert that narrowly beat FAA nationwide ground stop",
    "機場可能因颱風造成全國航班停飛",
    "全美停飛事件回顧",
    "美國航空冬季取消三條航線",
    "FAA每日天氣展望 雷雨可能影響航班",
    "全美航空新增航線",
])
def test_background_forecasts_explainers_and_routine_news_do_not_pin(title):
    assert not common.is_major_operational_event(group(title))


def test_scope_cannot_come_from_flags_background_or_unrelated_items():
    event = group("FAA updates air traffic equipment")
    event.update(mustReport=True, editorialPriority="major")
    event["items"][0]["summary"] = "A nationwide ground stop happened in the past."
    event["items"].append({"title": "FAA nationwide ground stop", "backgroundCompanion": True})
    assert not common.is_major_operational_event(event)
    assert not common.is_major_operational_event({"items": [
        {"title": "FAA expands nationwide training"}, {"title": "Local airport halts flights"}]})


@pytest.mark.parametrize("limit", [1, 3, 5])
def test_fresh_urgent_news_precedes_retry_and_niche_reservations(tmp_path, monkeypatch, limit):
    monkeypatch.setattr(news_retry, "DATA_DIR", tmp_path)
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    ledger = news_retry.RetryLedger(now)
    retries = [group("Airport opens new terminal", f"old-{n}") for n in range(5)]
    for event in retries:
        ledger.failure(event, content=False)
    ledger.now += timedelta(hours=2)
    urgent = [group("FAA nationwide ground stop", f"urgent-{n}") for n in range(3)]
    niche = group("Airbus completes H140 flight tests", "niche")
    selected, _ = ledger.plan(retries + [niche] + urgent, limit)
    assert selected[:min(limit, 3)] == urgent[:limit]
    assert len(selected) <= limit
    assert sum(event in retries for event in selected) <= news_retry.MAX_RETRIES_PER_RUN
    # A failed urgent attempt still observes evidence/service backoff.
    ledger.failure(urgent[0], content=True)
    selected, deferred = ledger.plan(urgent, limit)
    assert urgent[0] not in selected and urgent[0] in deferred


def article(now, title="FAA lifts nationwide ground stop", hours=1, key="major"):
    return {"id": key, "published_dt": now - timedelta(hours=hours),
            "time": "11/14", "available_languages": ["zh", "en"],
            "source": "FAA", "zh": {"title": title, "summary": "停飛令已解除。"},
            "en": {"title": title, "summary": "The ground stop has been lifted."}}


def test_major_news_precedes_manual_pins_and_taiwan_focus():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    major = article(now)
    taiwan = article(now, "長榮航空新增桃園航線", key="taiwan")
    manual = article(now, "Boeing aircraft certification", key="manual")
    rows = [taiwan, manual, major]
    snapshot = copy.deepcopy(rows)
    assert build.headline_carousel_articles(rows, now, limit=1, pinned_ids=["manual"]) == [major]
    assert build.headline_carousel_articles(rows, now, pinned_ids=["manual"]) == [major, manual, taiwan]
    assert rows == snapshot


def test_pins_expire_without_edit_time_extending_them():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    valid = article(now, hours=48)
    expired = article(now, hours=48.01, key="old")
    expired["modified_dt"] = now
    future = article(now, hours=-1, key="future")
    assert build.major_operational_articles([valid, expired, future], now) == [valid]
    assert build.major_operational_articles([valid], now + timedelta(seconds=1)) == []


def test_recovery_article_gets_live_entry_before_full_cap_without_duplicates():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    major = article(now)
    flashes = [{"time": "11/14", "hot": False, "pinned": False,
                "articleId": str(n), "zh": "一般消息", "en": "Routine news",
                "available_languages": ["zh", "en"]} for n in range(build.MAX_FLASHES)]
    flashes.append({**flashes[0], "articleId": "major", "zh": "舊版停飛文字"})
    snapshot = copy.deepcopy(flashes)
    result = build.major_operational_flashes(flashes, [major], now)
    assert len(result) == build.MAX_FLASHES
    assert result[0]["articleId"] == "major"
    assert result[0]["hot"] and result[0]["pinned"]
    assert sum(f["articleId"] == "major" for f in result) == 1
    for lang in ("zh", "en"):
        view = build.flash_view(result, lang, {"major"})
        assert view[0]["priority"] and view[0]["text"] == major[lang]["title"]
        assert view[0]["url"].endswith("/news/major/")
    assert flashes == snapshot
    assert build.major_operational_flashes([], [], now) == []
    assert build.major_operational_flashes([], [major], now + timedelta(days=3)) == []


def test_live_respects_published_language_availability():
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    major = article(now)
    major["available_languages"] = ["zh"]
    flashes = build.major_operational_flashes([], [major], now)
    assert len(build.flash_view(flashes, "zh")) == 1
    assert build.flash_view(flashes, "en") == []


def test_nationwide_ground_stop_survives_busy_discovery_cap():
    sys.path.insert(0, str(ROOT / "tests"))
    from test_dedupe import _mk_item, _write_snapshot, _run_dedupe, _load_pending
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        data = Path(tmp)
        ordinary = [_mk_item(f"FAA terminal project {n}", f"https://www.faa.gov/{n}",
                             1, "A detailed summary about the airport construction project.")
                    for n in range(16)]
        urgent = _mk_item("FAA Statement on Nationwide Ground Stop",
                          "https://www.faa.gov/nationwide-stop", 20, "")
        _write_snapshot(data, "faa", ordinary + [urgent])
        _run_dedupe(data)
        groups = _load_pending(data)["groups"]
        assert groups[0]["items"][0]["url"] == urgent["url"]
        assert groups[0]["mustReport"] is True
        assert groups[0]["editorialPriority"] == "major"


def test_production_article_renders_as_pinned_headline_and_live_in_both_languages(tmp_path, monkeypatch):
    raw = json.loads((ROOT / "data/articles/scheduled-faa-nationwide-ground-stop-20261113.json").read_text(encoding="utf-8"))["articles"][0]
    now = common.parse_iso(raw["publishedUtc"]) + timedelta(hours=12)
    monkeypatch.setattr(build, "now_utc", lambda: now)
    monkeypatch.setattr(build, "SITE_DIR", tmp_path / "site")
    monkeypatch.setattr(build, "collect_articles", lambda: [build.prep_article(raw)])
    assert build.main() == 0
    for lang, prefix in (("zh", ""), ("en", "en/")):
        title = compact_text(raw[lang]["title"])
        soup = BeautifulSoup((build.SITE_DIR / prefix / "index.html").read_text(encoding="utf-8"), "html.parser")
        assert soup.select_one("#hero-carousel")["data-major-pinned"] == "true"
        assert soup.select_one("#hero-story-link")["href"].endswith(f"/news/{raw['id']}/")
        assert soup.select_one("#hero-story-title").get_text() == title
        assert title in soup.select_one(".flash-row").get_text()
        assert soup.select_one(".flash-row .flash-pin")
        assert title in soup.select_one(".ticker-item").get_text()
