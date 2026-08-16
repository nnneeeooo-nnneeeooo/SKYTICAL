"""Regression checks for Taiwan aircraft-age terminology enforcement."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-aircraft-term-")
sys.path.insert(0, str(REPO / "pipeline"))

import write  # noqa: E402


def _draft(zh_summary: str, zh_body: str) -> dict:
    return {
        "zh": {
            "title": "阿聯酋航空最老空中巴士A380持續執飛英國航線",
            "summary": zh_summary,
            "body": [zh_body],
        },
        "en": {
            "title": "Emirates' Oldest Airbus A380 Continues Operations to UK Airports",
            "summary": "Emirates operates its nearly 21-year-old Airbus A380 aircraft to UK airports.",
            "body": ["The aircraft is nearly 21 years old and remains in service."],
        },
        "flash": {
            "zh": "阿聯酋航空A380持續執飛英國航線",
            "en": "Emirates A380 continues UK operations",
            "hot": False,
        },
    }


GROUP = {
    "id": "aircraft-age",
    "items": [{
        "title": "Emirates' Oldest Airbus A380 Is Nearly 21",
        "summary": "The aircraft remains active and flew to three UK airports.",
        "source": "Simple Flying",
        "url": "https://example.com/emirates-a380",
    }],
}


def test_aircraft_age_rejects_vehicle_age_term():
    candidate = _draft(
        "阿聯酋航空車齡近21年的空中巴士A380持續執飛英國航線。",
        "這架空中巴士A380目前車齡接近21年。",
    )
    problem = write.glossary_problem(candidate, GROUP)
    assert problem is not None
    assert "車齡" in problem
    assert "aircraft" in problem


def test_aircraft_age_accepts_aircraft_age_term():
    candidate = _draft(
        "阿聯酋航空機齡近21年的空中巴士A380持續執飛英國航線。",
        "這架空中巴士A380目前機齡接近21年。",
    )
    assert write.glossary_problem(candidate, GROUP) is None
