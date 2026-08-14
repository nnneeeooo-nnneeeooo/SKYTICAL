"""Companion-source allowlist regression tests."""
from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


def test_airway_magazine_related_domains_are_allowlisted() -> None:
    config = json.loads(
        (REPO / "config" / "companion_sources.json").read_text(encoding="utf-8")
    )
    domains = set(config["domains"])

    assert "airway.com.tw" in domains
    assert "airshop.com.tw" in domains
