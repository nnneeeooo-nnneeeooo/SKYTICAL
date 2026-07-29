"""Source-registry regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import common  # noqa: E402


def test_aerotime_is_a_primary_rss_source() -> None:
    source = common.SOURCES["aerotime"]

    assert source["name"] == "AeroTime"
    assert source["kind"] == "media"
    assert source["fmt"] == "RSS"
    assert source["type"] == "rss"
    assert source["url"] == "https://www.aerotime.aero"
    assert source["endpoint"] == "https://www.aerotime.aero/feed"
    assert source.get("public", True) is True
