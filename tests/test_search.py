"""Offline regression checks for AVWIRE's static full-text news search."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def sample_article(title: str):
    return build.prep_article({
        "id": "a-search-alias-test",
        "publishedUtc": "2026-08-10T00:00:00Z",
        "cat": "ops",
        "primarySource": "Test source",
        "zh": {
            "title": title,
            "summary": "測試航空公司別名搜尋。",
            "body": ["航機抵達臺灣桃園國際機場。"],
        },
        "en": {
            "title": "Airline search alias test",
            "summary": "Testing airline aliases in search.",
            "body": ["The aircraft arrived at Taoyuan Airport."],
        },
        "sources": [{"name": "Test source", "url": "https://example.com/news"}],
    })


def main() -> None:
    aliases = build.load_search_alias_groups()
    assert len(aliases) >= 25

    formal = build.search_index_item(sample_article("中華航空新增航班"), aliases)
    formal_search = formal["search"]
    assert "中華航空" in formal_search
    assert "華航" in formal_search
    assert "china airlines" in formal_search
    assert "桃園機場" in formal_search
    assert "taoyuan airport" in formal_search
    assert "rctp" in formal_search
    assert "tpe" in formal_search

    short = build.search_index_item(sample_article("華航新增航班"), aliases)
    assert "中華航空" in short["search"]
    assert "china airlines" in short["search"]

    # Short Latin aliases require token boundaries: ordinary words must not
    # accidentally activate an airline group.
    assert "中華航空" not in build.expand_search_aliases(
        "The local calendar was updated.", aliases)

    assert build.main() == 0
    payload = json.loads(
        (ROOT / "site" / "search-index.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["count"] == len(payload["items"]) == len(build.collect_articles())
    assert payload["items"]
    assert all(row["search"] and row["url"] for row in payload["items"])
    assert any(
        "中華航空" in row["search"] and "華航" in row["search"]
        for row in payload["items"]
    )

    zh = (ROOT / "site" / "search" / "index.html").read_text(encoding="utf-8")
    en = (ROOT / "site" / "en" / "search" / "index.html").read_text(
        encoding="utf-8")
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "search.js").read_text(encoding="utf-8")

    assert 'id="news-search-input"' in zh
    assert 'data-index-url="/avwire/search-index.json"' in zh
    assert 'data-index-url="/avwire/search-index.json"' in en
    assert 'href="/avwire/search/"' in home
    assert 'href="/avwire/en/search/"' in en
    assert "航空公司正式名稱與常用簡稱可互相查找" in zh
    assert "Official airline names and common short names are interchangeable" in en
    assert "terms.every" in script
    assert "textContent" in script
    assert "replaceChildren" in script
    assert "innerHTML" not in script
    assert "URLSearchParams" not in script  # URL.searchParams is used directly

    print("test_search: OK")


if __name__ == "__main__":
    main()
