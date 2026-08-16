"""Readability and rendering contracts for independent-event roundups."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import build  # noqa: E402
import images  # noqa: E402
import write  # noqa: E402


def sample_group() -> dict:
    return {
        "id": "g-roundup-test",
        "primarySource": "The Aviation Herald",
        "groupKind": "safety_roundup",
        "independentEvents": True,
        "items": [
            {
                "title": "Incident: Alaska B39M near Chicago on Aug 16th 2026, engine shut down in flight",
                "url": "https://example.com/alaska",
                "publishedUtc": "2026-08-16T19:05Z",
                "summary": "",
                "source": "The Aviation Herald",
                "sourceKey": "avherald",
            },
            {
                "title": "Incident: Hainan A333 near Krasnoyarsk on Aug 15th 2026, mechanical fault",
                "url": "https://example.com/hainan",
                "publishedUtc": "2026-08-15T12:27Z",
                "summary": "",
                "source": "The Aviation Herald",
                "sourceKey": "avherald",
            },
        ],
    }


def sample_facts() -> list[dict]:
    return [
        {
            "factId": "F1", "claim": "Alaska event",
            "sourceQuote": "Incident: Alaska B39M near Chicago on Aug 16th 2026, engine shut down in flight",
            "sourceUrl": "https://example.com/alaska",
            "evidenceScope": "source", "archiveEventId": None,
            "archiveContext": False,
        },
        {
            "factId": "F2", "claim": "Hainan event",
            "sourceQuote": "Incident: Hainan A333 near Krasnoyarsk on Aug 15th 2026, mechanical fault",
            "sourceUrl": "https://example.com/hainan",
            "evidenceScope": "source", "archiveEventId": None,
            "archiveContext": False,
        },
    ]


def sample_draft() -> dict:
    return {
        "status": "publish_brief",
        "decisionReason": "",
        "cat": "safety",
        "zh": {
            "title": "航空安全快訊：2起獨立事件彙整",
            "summary": "阿拉斯加與海南航空分別通報獨立事件",
            "body": [
                "以下為2起彼此獨立、沒有已知直接關聯的事件。",
                "1. 阿拉斯加航空波音737 MAX 9（ICAO機型代碼B39M）在芝加哥附近關閉一具引擎。",
                "2. 海南航空空中巴士A330-300（A333）在俄羅斯克拉斯諾亞爾斯克附近發生機械故障。",
            ],
        },
        "en": {
            "title": "Aviation Safety Roundup: Two Independent Events",
            "summary": "Alaska and Hainan reported separate independent occurrences",
            "body": [
                "The following two events are independent and have no stated relationship.",
                "1. An Alaska Airlines Boeing 737 MAX 9 (ICAO type code B39M) had an engine shut down near Chicago.",
                "2. A Hainan Airlines Airbus A330-300 (A333) had a mechanical fault near Krasnoyarsk, Russia.",
            ],
        },
        "flash": {"zh": "2起獨立安全事件彙整", "en": "Two-event safety roundup", "hot": True},
        "incident": {
            "date": "2026-08-16", "sev": "inc", "aircraft": "B39M",
            "operator": "Alaska", "phase": {"zh": "飛行中", "en": "in flight"},
            "location": {"zh": "芝加哥附近", "en": "near Chicago"},
            "desc": {"zh": "引擎關閉", "en": "engine shutdown"}, "status": "open",
        },
        "facts": sample_facts(),
        "headlineSupportedBy": ["F1", "F2"],
        "summarySupportedBy": ["F1", "F2"],
        "entities": {"organizations": [], "airlines": ["Alaska", "Hainan"],
                     "aircraft_models": ["B39M", "A333"], "airports": [],
                     "locations": ["Chicago", "Krasnoyarsk"],
                     "flight_numbers": [], "registration_numbers": [],
                     "event_dates": ["2026-08-16", "2026-08-15"]},
        "eventStatus": "preliminary",
        "riskFlags": ["unconfirmed_or_developing"],
        "requiresHumanReview": False,
    }


def test_roundup_prompt_and_machine_gate() -> None:
    group = sample_group()
    prompt = write.group_prompt(group)
    assert "format: safety_roundup" in prompt
    assert "independent event count: 2" in prompt
    assert "B39M: en=\"Boeing 737 MAX 9\"" in prompt
    assert "A333: en=\"Airbus A330-300\"" in prompt
    assert "Krasnoyarsk: en=\"Krasnoyarsk, Russia\"" in prompt
    draft = sample_draft()
    assert write.has_material(group)
    assert write.roundup_readability_problem(
        draft, group, sample_facts()) is None

    broken = json.loads(json.dumps(draft))
    broken["zh"]["body"][1] = "1. 阿拉斯加航空B39M在芝加哥附近關閉一具引擎。"
    assert "B39M" in (write.roundup_readability_problem(
        broken, group, sample_facts()) or "")


def test_roundup_storage_rendering_and_image_policy() -> None:
    group = sample_group()
    draft = sample_draft()
    article = write.build_article(
        draft, group, datetime(2026, 8, 16, 23, 25, tzinfo=timezone.utc), set(),
        writer="test:model", facts=sample_facts())
    assert article is not None
    assert article["articleFormat"] == "roundup"
    assert write.build_incident(draft, group, article["id"]) is None
    assert images.resolve_image(article) is None
    prepared = build.prep_article(article)
    assert prepared is not None
    assert prepared["article_format"] == "roundup"


def test_published_roundup_is_reader_facing() -> None:
    payload = json.loads(
        (REPO / "data" / "articles" / "2026-08-16T23.json")
        .read_text(encoding="utf-8"))
    article = next(
        row for row in payload["articles"]
        if row["id"] == "a-20260816-2304-alaska-airlines-b39m-engine-shutdown-in")
    zh_text = " ".join([article["zh"]["title"], article["zh"]["summary"],
                        *article["zh"]["body"]])
    assert article["articleFormat"] == "roundup"
    assert "獨立" in zh_text and "波音737 MAX 9" in zh_text
    assert "空中巴士A330-300" in zh_text and "空中巴士A321neo" in zh_text
    assert "俄羅斯克拉斯諾亞爾斯克" in zh_text
    assert "犬隻逃脫" not in zh_text
    assert "image" not in article
    assert "leads six" not in article["en"]["title"].casefold()

    flash = json.loads((REPO / "data" / "flashes.json").read_text(encoding="utf-8"))
    current = next(row for row in flash if row["articleId"] == article["id"])
    assert "737 MAX 9" in current["zh"] and "B39M" not in current["zh"]

    article_template = (REPO / "templates" / "article.html").read_text(encoding="utf-8")
    assert 'a.article_format == "roundup"' in article_template
