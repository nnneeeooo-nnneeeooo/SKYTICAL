"""Regression coverage for incident database inclusion rules."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import write  # noqa: E402


def test_build_incident_includes_non_safety_military_occurrence() -> None:
    incident = {
        "date": "2026-09-23",
        "sev": "acc",
        "aircraft": "BAE Systems Hawk T2",
        "operator": "Royal Air Force",
        "phase": {"zh": "訓練飛行", "en": "Training flight"},
        "location": {"zh": "安格爾西島附近", "en": "near Anglesey"},
        "desc": {"zh": "飛機墜毀", "en": "aircraft crashed"},
        "status": "open",
    }
    group = {
        "items": [{"source": "AeroTime"}],
    }

    row = write.build_incident(
        {"cat": "mil", "incident": incident}, group, "article-123")

    assert row == {
        **incident,
        "sources": ["AeroTime"],
        "articleId": "article-123",
    }
