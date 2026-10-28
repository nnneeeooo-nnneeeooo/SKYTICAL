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
    tomorrow = now + timedelta(days=1)
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
    print("PASS industry routing, deduplication and daily compilation")
