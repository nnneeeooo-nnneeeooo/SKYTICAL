"""Source-registry regression tests."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import common  # noqa: E402
import fetch  # noqa: E402


def test_aerotime_is_a_primary_rss_source() -> None:
    source = common.SOURCES["aerotime"]

    assert source["name"] == "AeroTime"
    assert source["kind"] == "media"
    assert source["fmt"] == "RSS"
    assert source["type"] == "rss"
    assert source["url"] == "https://www.aerotime.aero"
    assert source["endpoint"] == "https://www.aerotime.aero/feed"
    assert source.get("public", True) is True


def test_taiwan_airline_sources_cover_business_and_official_releases() -> None:
    finance = common.SOURCES["cnataiwanfinance"]
    evaair = common.SOURCES["evaair"]

    assert finance["endpoint"] == "https://feeds.feedburner.com/rsscna/finance"
    assert finance["keywords"] == common.SOURCES["cnataiwan"]["keywords"]
    assert evaair["kind"] == "official"
    assert evaair["type"] == "rss"
    assert "news.google.com/rss/search" in evaair["endpoint"]
    assert "site:evaair.com" in evaair["endpoint"]
    assert fetch._matches_keywords({
        "title": "長榮航空12月開航台北直飛德里",
        "summary": "每週五班使用A330-300客機飛航。",
    }, finance["keywords"])


def test_taiwan_airline_priority_signal_covers_all_national_carriers() -> None:
    for title in (
        "華航新增台北鳳凰城航線",
        "長榮航空直飛德里",
        "星宇航空增購新機",
        "台灣虎航開闢新航點",
        "立榮航空調整國內線",
        "華信航空接收新客機",
        "EVA Air launches a new nonstop route",
    ):
        assert common.is_taiwan_airline_story({"title": title}), title
    assert not common.is_taiwan_airline_story(
        {"title": "Boeing resumes 777-9 certification testing"})
