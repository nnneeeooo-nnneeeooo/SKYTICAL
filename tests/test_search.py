"""Offline regression checks for AVWIRE's static full-text news search."""
from __future__ import annotations

import json
import re
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
    alias_payload = json.loads(
        (ROOT / "site" / "search-aliases.json").read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["count"] == len(payload["items"]) == len(build.collect_articles())
    assert payload["items"]
    assert all(row["search"] and row["url"] for row in payload["items"])
    assert any(
        "中華航空" in row["search"] and "華航" in row["search"]
        for row in payload["items"]
    )
    assert alias_payload["version"] == 1
    assert ["中華航空", "華航", "China Airlines"] in alias_payload["groups"]

    zh = (ROOT / "site" / "search" / "index.html").read_text(encoding="utf-8")
    en = (ROOT / "site" / "en" / "search" / "index.html").read_text(
        encoding="utf-8")
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    article = next((ROOT / "site" / "news").glob("*/index.html")).read_text(
        encoding="utf-8")
    script = (ROOT / "static" / "search.js").read_text(encoding="utf-8")
    highlight_script = (ROOT / "static" / "highlight.js").read_text(
        encoding="utf-8")
    app_script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "site.css").read_text(encoding="utf-8")

    assert 'id="news-search-input"' in zh
    assert 'data-search-placeholders=' in zh
    zh_placeholders = json.loads(re.search(
        r"data-search-placeholders='([^']+)'", zh).group(1))
    en_placeholders = json.loads(re.search(
        r"data-search-placeholders='([^']+)'", en).group(1))
    assert zh_placeholders == list(build.header_search_placeholders("zh"))
    assert en_placeholders == list(build.header_search_placeholders("en"))
    assert len(zh_placeholders) == len(en_placeholders) == 6
    assert zh.count('id="news-search-form"') == 1
    assert 'class="header-search-form"' in home
    assert 'class="header-search-form"' in article
    assert 'data-article-body' in article
    assert 'data-search-aliases-url="/avwire/search-aliases.json"' in article
    assert re.search(r'/avwire/assets/highlight\.js\?v=[0-9a-f]{10}', article)
    assert 'action="/avwire/search/"' in home
    assert 'action="/avwire/en/search/"' in en
    assert re.search(r'/avwire/assets/site\.css\?v=[0-9a-f]{10}', zh)
    assert re.search(r'/avwire/assets/app\.js\?v=[0-9a-f]{10}', zh)
    assert re.search(r'/avwire/assets/search\.js\?v=[0-9a-f]{10}', zh)
    assert home.index('class="header-search-row"') < home.index('id="clock-utc"')
    assert home.index('class="header-search-row"') < home.index('class="brand-row"')
    main_markup = re.search(r'<main class="search-page">(.*?)</main>', zh,
                            re.DOTALL).group(1)
    assert "<form" not in main_markup
    assert 'data-index-url="/avwire/search-index.json"' in zh
    assert 'data-index-url="/avwire/search-index.json"' in en
    assert 'href="/avwire/en/search/"' in en
    assert "border-radius: 999px" in css
    assert ".header-search-form:focus-within" in css
    assert ".header-search-input:not(:placeholder-shown) + .header-search-clear" in css
    assert ".header-search-submit" in css
    assert "航空公司正式名稱與常用簡稱可互相查找" in zh
    assert "Official airline names and common short names are interchangeable" in en
    assert "terms.every" in script
    assert "textContent" in script
    assert "replaceChildren" in script
    assert "innerHTML" not in script
    assert "URLSearchParams" not in script  # URL.searchParams is used directly
    assert 'url.searchParams.set("highlight", highlightQuery)' in script
    assert "resultCard(row.record, query)" in script
    assert 'searchParams.get("highlight")' in highlight_script
    assert "payload.groups" in highlight_script
    assert 'mark.className = "search-hit"' in highlight_script
    assert 'mark.classList.add("search-hit-pulse")' in highlight_script
    assert 'mark.classList.remove("search-hit-pulse")' in highlight_script
    assert ", 3000);" in highlight_script
    assert "prefers-reduced-motion: reduce" in css
    assert "@keyframes search-hit-pulse" in css
    assert 'headerSearchClear.addEventListener("click"' in app_script
    assert 'getAttribute("data-search-placeholders")' in app_script
    assert "JSON.parse" in app_script
    assert "Math.floor(Math.random() * searchPlaceholders.length)" in app_script
    assert 'headerSearchForm.addEventListener("submit"' in app_script
    assert "queryFromSearchPlaceholder" in app_script
    assert "搜尋|查詢|尋找|看看|想看|探索|了解" in app_script
    assert "Search|Explore|Find|Look\\s+up|Show\\s+me" in app_script
    assert "if (headerSearchInput.value.trim()) return" in app_script
    assert "headerSearchInput.value = suggestedQuery" in app_script
    assert 'headerSearchInput.value = ""' in app_script
    assert 'new Event("input", { bubbles: true })' in app_script

    print("test_search: OK")


if __name__ == "__main__":
    main()
