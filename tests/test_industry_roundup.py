"""Routine industry routing and verified daily compilation regressions."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import build  # noqa: E402
import industry_roundup  # noqa: E402
from editorial_policy import publication_route  # noqa: E402


def group(title: str, summary: str = "", number: int = 1) -> dict:
    return {"id": f"g-{number}", "items": [{
        "title": title, "summary": summary,
        "url": f"https://example.com/{number}",
    }]}


def article(number: int) -> dict:
    url = f"https://example.com/{number}"
    return {
        "id": f"a-example-{number}",
        "sourcePublishedUtc": "2026-10-27T12:00Z",
        "zh": {"title": f"事件{number}", "summary": f"事件{number}摘要",
               "body": [f"第{number}起事件的經查證內容。"]},
        "en": {"title": f"Event {number}", "summary": f"Event {number} summary",
               "body": [f"Verified account of event {number}."]},
        "sources": [{"name": "Example", "url": url}],
        "facts": [{"factId": "F1", "claim": f"Event {number}",
                   "sourceQuote": f"Event {number}", "sourceUrl": url,
                   "evidenceScope": "source", "archiveEventId": None,
                   "archiveContext": False}],
    }


def test_owner_examples_and_urgent_overrides() -> None:
    routine = [
        group("Electra EL2 makes fixed-wing landing at Manhattan heliport",
              "The prototype aircraft completed a demonstration"),
        group("Life Flight Network orders five Airbus H135 helicopters",
              "Five helicopters were ordered"),
        group("SITA to acquire CAE airline operations software business"),
        group("Boeing subsidiary Spirit Defense joins production of General Atomics FQ-42"),
        group("Hynaero and Leonardo sign MOU to develop amphibious firefighting aircraft"),
        group("EASA provides complete Easy Access Rules publication history in XML"),
        group("Gulfstream deliveries rise as General Dynamics aerospace profit climbs 19%"),
        group("Maxwell unveils hybrid amphibious aircraft concept for cargo flights"),
    ]
    assert all(publication_route(item).route == "industry_roundup"
               for item in routine)
    for title in (
            "Airliner crash at airport",
            "FAA grounds all Boeing 737 aircraft",
            "FAA issues safety alert after software partnership incident",
            "EVA Air orders five H135 helicopters for Taiwan operations",
            "Airline announces new route to Paris"):
        assert publication_route(group(title)).route == "standalone", title
    assert publication_route(group("Airbus receives order for 80 helicopters")).route == "standalone"


def test_queue_deduplication_and_daily_compilation() -> None:
    now = datetime(2026, 10, 27, 15, 45, tzinfo=timezone.utc)
    state = {"lastEdition": "", "items": []}
    assert industry_roundup.add(state, article(1), now,
                                reason="routine_demo", event_key="event-one")
    assert not industry_roundup.add(state, article(1), now)
    assert not industry_roundup.add(state, article(9), now,
                                    event_key="event-one")
    assert state["items"][0]["routeReason"] == "routine_demo"
    assert industry_roundup.has_group(state, group("same source", number=1))
    assert industry_roundup.has_group(
        state, {"eventKey": "event-one", "items": []})
    assert industry_roundup.compile_due(state, now, []) is None
    assert state["items"], "one routine item is held, not published alone"
    assert industry_roundup.add(state, article(2), now)
    tomorrow = now  # The second item arriving in the same slot can publish.
    compiled = industry_roundup.compile_due(state, tomorrow, [])
    assert compiled is not None
    assert compiled["articleFormat"] == "roundup"
    assert len(compiled["zh"]["body"]) == 3
    assert len(compiled["en"]["body"]) == 3
    assert len(compiled["sources"]) == 2
    assert [f["factId"] for f in compiled["facts"]] == ["F1", "F2"]
    assert build.prep_article(compiled) is not None
    assert not state["items"]
    assert industry_roundup.compile_due(state, tomorrow, []) is None


def test_short_news_protects_taiwan_safety_and_regulatory():
    brief = {"articleFormat": "brief"}
    assert publication_route(group("Airline adds new lounge seating"), brief).route == "industry_roundup"
    assert publication_route(group("Airline cuts seasonal routes" )).route == "industry_roundup"
    for title in ("EVA Air adds lounge seating", "Airliner emergency landing",
                  "FAA issues airworthiness directive",
                  "Bomb threats hit 25 European flights, trigger fighter escorts"):
        assert publication_route(group(title), brief).route == "standalone", title


def test_six_hour_editions_and_one_visible_carousel_slot():
    now = datetime(2026, 11, 6, 2, tzinfo=timezone.utc)
    state = {"lastEdition": "", "items": []}
    for n in range(1, 5):
        industry_roundup.add(state, article(n), now)
    first = industry_roundup.compile_due(state, now, [])
    assert first and len(first["roundupItems"]) == 4
    for n in (5, 6):
        industry_roundup.add(state, article(n), now)
    assert industry_roundup.compile_due(state, now + timedelta(hours=1), [first]) is None
    second = industry_roundup.compile_due(state, now + timedelta(hours=6), [first])
    assert second and second["id"] != first["id"]
    prepared = [build.prep_article(a) for a in (first, second)]
    recent = [dict(prepared[0], id=f"a-global-{n}", roundup_kind=None,
                   published_dt=now + timedelta(hours=6)) for n in range(10)]
    chosen = build.headline_carousel_articles(recent + prepared, now + timedelta(hours=6), pinned_ids=[])
    assert prepared[1] in chosen and prepared[0] not in chosen
    assert len(chosen) == 8
    expired = build.headline_carousel_articles(prepared, now + timedelta(hours=55), pinned_ids=[])
    assert not expired
    assert not build.headline_carousel_articles(prepared, now - timedelta(hours=1), pinned_ids=[])


def test_event_dedup_and_eight_item_cap():
    now = datetime(2026, 11, 6, 2, tzinfo=timezone.utc)
    state = {"lastEdition": "", "items": []}
    for n in range(1, 12):
        industry_roundup.add(state, article(n), now, event_key=f"event-{n}")
    compiled = industry_roundup.compile_due(state, now, [
        {"roundupItems": [{"eventKey": "event-1"}], "sources": []}])
    assert len(compiled["roundupItems"]) == 8
    assert all(row["eventKey"] != "event-1" for row in compiled["roundupItems"])
    assert len(state["items"]) == 2
    assert state["history"][0]["reason"] == "already_published"


def test_roundup_does_not_displace_pin_or_taiwan_focus():
    now = datetime(2026, 11, 6, 2, tzinfo=timezone.utc)
    state = {"lastEdition": "", "items": []}
    for n in (1, 2):
        industry_roundup.add(state, article(n), now)
    roundup = build.prep_article(industry_roundup.compile_due(state, now, []))
    pin = dict(roundup, id="a-editor-pin", roundup_kind=None)
    taiwan = dict(roundup, id="a-taiwan", roundup_kind=None,
                  zh={"title": "長榮航空新增臺北航線", "summary": "桃園機場出發"})
    chosen = build.headline_carousel_articles([roundup, taiwan, pin], now,
                                             pinned_ids=[pin["id"]], limit=3)
    assert [a["id"] for a in chosen] == [pin["id"], taiwan["id"], roundup["id"]]


def test_published_source_wins_and_expired_item_is_dropped() -> None:
    now = datetime(2026, 10, 27, 15, 45, tzinfo=timezone.utc)
    state = {"lastEdition": "", "items": []}
    for number in (1, 2, 3):
        assert industry_roundup.add(state, article(number), now)
    compiled = industry_roundup.compile_due(
        state, now, [{"sources": article(1)["sources"]}])
    assert compiled is not None and len(compiled["sources"]) == 2
    assert not state["items"]
    late = now + timedelta(hours=49)
    state = {"lastEdition": "", "items": []}
    assert industry_roundup.add(state, article(4), now)
    assert industry_roundup.compile_due(state, late, []) is None
    assert not state["items"]
    assert {row["reason"] for row in state["history"]} == {"expired"}


if __name__ == "__main__":
    test_owner_examples_and_urgent_overrides()
    test_queue_deduplication_and_daily_compilation()
    test_published_source_wins_and_expired_item_is_dropped()
    test_short_news_protects_taiwan_safety_and_regulatory()
    test_six_hour_editions_and_one_visible_carousel_slot()
    test_event_dedup_and_eight_item_cap()
    test_roundup_does_not_displace_pin_or_taiwan_focus()
    print("PASS industry routing, deduplication and daily compilation")
