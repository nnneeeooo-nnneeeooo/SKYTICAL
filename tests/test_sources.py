"""Source-registry regression tests."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import common  # noqa: E402
import dedupe  # noqa: E402
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
    airline_index = common.SOURCES["cnataiwanairlines"]
    evaair = common.SOURCES["evaair"]

    assert finance["endpoint"] == "https://feeds.feedburner.com/rsscna/finance"
    assert finance["keywords"] == common.SOURCES["cnataiwan"]["keywords"]
    assert evaair["kind"] == "official"
    assert evaair["type"] == "rss"
    assert "news.google.com/rss/search" in evaair["endpoint"]
    assert "site:evaair.com" in evaair["endpoint"]
    assert airline_index["endpoint"].endswith(
        "/GoogleNewsSitemap_fromRemote_cfp.xml")
    assert airline_index["type"] == "html"
    assert airline_index["parser"] == "xml"
    for brand in ("中華航空", "長榮航空", "星宇航空", "台灣虎航",
                  "臺灣虎航", "立榮航空", "華信航空"):
        assert brand in airline_index["keywords"]
    assert airline_index["scope_filter"] is True
    assert fetch._matches_keywords({
        "title": "長榮航空12月開航台北直飛德里",
        "summary": "每週五班使用A330-300客機飛航。",
    }, finance["keywords"])


def test_cna_news_sitemap_parser_returns_direct_dated_article_urls() -> None:
    fixture = """<?xml version="1.0" encoding="utf-8"?>
    <urlset xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
            xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url>
        <loc>https://www.cna.com.tw/news/afe/202608050172.aspx</loc>
        <news:news>
          <news:publication_date>2026-08-05T15:01:39+08:00</news:publication_date>
          <news:title>長榮航12/1直飛印度德里</news:title>
          <news:keywords>長榮航空,印度德里,空中巴士A330</news:keywords>
        </news:news>
      </url>
    </urlset>"""

    items = fetch._parse_cna_news_sitemap(
        BeautifulSoup(fixture, "xml"), "https://www.cna.com.tw")

    assert len(items) == 1
    assert items[0]["url"] == (
        "https://www.cna.com.tw/news/afe/202608050172.aspx")
    assert items[0]["published"].isoformat() == "2026-08-05T15:01:39+08:00"
    assert "長榮航空" in items[0]["summary"]


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


def test_asia_fleet_discovery_and_hainan_official_sources_are_registered() -> None:
    official = common.SOURCES["hainanair"]
    discovery = common.SOURCES["asiaairlinefleet"]

    assert official["kind"] == "official"
    assert "news.google.com/rss/search" in official["endpoint"]
    official_query = parse_qs(urlsplit(official["endpoint"]).query)["q"][0]
    assert "site:hnair.com" in official_query
    assert "site:sse.com.cn" in official_query

    assert discovery["publisher_passthrough"] is True
    assert discovery["scope_filter"] is True
    query = parse_qs(urlsplit(discovery["endpoint"]).query)["q"][0]
    for anchor in ("海南航空", "Hainan Airlines", "T'way Air", "停飛",
                   "停場", "退役", "交付", "rename", "when:7d"):
        assert anchor in query
    assert dedupe._source_label(
        discovery, {"publisher": "Example Aviation"}) == "Example Aviation"
    assert dedupe._source_label(
        official, {"publisher": "Google News"}) == "海南航空官方資訊"
