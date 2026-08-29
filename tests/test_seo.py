"""Offline regression checks for SKYTICAL search and Google News metadata."""
from __future__ import annotations

import html as html_lib
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def _json_ld(html: str) -> list[dict]:
    return [json.loads(value) for value in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html,
        flags=re.DOTALL)]


def _schema_entities(html: str) -> list[dict]:
    entities = []
    for document in _json_ld(html):
        if not isinstance(document, dict):
            continue
        if document.get("@type"):
            entities.append(document)
        entities.extend(
            entity for entity in document.get("@graph", [])
            if isinstance(entity, dict)
        )
    return entities


def main() -> None:
    assert build.SITE_ORIGIN == "https://skytical.tech"
    assert build.BASE_PATH == ""
    assert build.main() == 0

    verification = ROOT / "site" / "google83f7fe8f9aeba973.html"
    assert verification.read_text(encoding="utf-8").strip() == (
        "google-site-verification: google83f7fe8f9aeba973.html")

    sitemap = ET.parse(ROOT / "site" / "sitemap.xml").getroot()
    ns = {"sm": build.SITEMAP_NS, "news": build.NEWS_NS}
    locations = [node.text for node in sitemap.findall("sm:url/sm:loc", ns)]
    sitemap_rows = {
        row.findtext("sm:loc", namespaces=ns): row
        for row in sitemap.findall("sm:url", ns)
    }
    assert len(locations) == len(set(locations))
    assert f"{build.SITE_ORIGIN}{build.BASE_PATH}/" in locations
    assert f"{build.SITE_ORIGIN}{build.BASE_PATH}/en/" in locations
    assert (f"{build.SITE_ORIGIN}{build.BASE_PATH}/editorial-policy/"
            in locations)
    for slug in build.TOPICS:
        assert (f"{build.SITE_ORIGIN}{build.BASE_PATH}/topics/{slug}/"
                in locations)
    localized_zh_count = sum(
        "zh" in article["available_languages"]
        for article in build.collect_articles()
    )
    expected_zh_pages = max(
        1, math.ceil(localized_zh_count / build.NEWS_PAGE_SIZE))
    if expected_zh_pages > 1:
        assert (f"{build.SITE_ORIGIN}{build.BASE_PATH}/news/page/2/"
                in locations)
    localized_en_count = sum(
        "en" in article["available_languages"]
        for article in build.collect_articles()
    )
    expected_en_pages = max(
        1, math.ceil(localized_en_count / build.NEWS_PAGE_SIZE))
    if expected_en_pages > 1:
        assert (f"{build.SITE_ORIGIN}{build.BASE_PATH}/en/news/page/2/"
                in locations)
    for slug in build.TOPICS:
        assert (f"{build.SITE_ORIGIN}{build.BASE_PATH}/en/topics/{slug}/"
                in locations)
    for path in ("/", "/news/", "/topics/taiwan-aviation/",
                 "/en/", "/en/news/", "/en/topics/taiwan-aviation/"):
        lastmod = sitemap_rows[f"{build.SITE_ORIGIN}{path}"].findtext(
            "sm:lastmod", namespaces=ns)
        assert lastmod and lastmod.endswith("Z")

    news_index = ROOT / "site" / "news" / "index.html"
    en_news_index = ROOT / "site" / "en" / "news" / "index.html"
    assert news_index.is_file() and en_news_index.is_file()
    news_html = news_index.read_text(encoding="utf-8")
    assert "https://skytical.tech/news/" in news_html
    assert "塑膠包材循環示範聯盟" not in news_html

    feed = ET.parse(ROOT / "site" / "feed.xml").getroot()
    en_feed = ET.parse(ROOT / "site" / "en" / "feed.xml").getroot()
    assert feed.tag == "rss" and en_feed.tag == "rss"
    assert feed.findtext("channel/link").endswith("/news/")
    assert en_feed.findtext("channel/link").endswith("/en/news/")
    assert feed.findall("channel/item")
    for feed_item in feed.findall("channel/item") + en_feed.findall("channel/item"):
        source = feed_item.find("source")
        assert source is not None and source.attrib.get("url")
        assert "news.google.com" not in source.attrib["url"]

    news_sitemap = ET.parse(ROOT / "site" / "news-sitemap.xml").getroot()
    news_rows = news_sitemap.findall("sm:url", ns)
    assert news_rows and len(news_rows) <= 1000
    cutoff = build.now_utc() - timedelta(days=2, minutes=1)
    for row in news_rows:
        assert row.findtext("sm:loc", namespaces=ns).startswith(
            f"{build.SITE_ORIGIN}{build.BASE_PATH}/")
        assert row.findtext("news:news/news:publication/news:name",
                            namespaces=ns) == "SKYTICAL"
        assert row.findtext("news:news/news:publication/news:language",
                            namespaces=ns) in {"zh-tw", "en"}
        published = build.parse_iso(row.findtext(
            "news:news/news:publication_date", namespaces=ns))
        assert published >= cutoff
        assert row.findtext("news:news/news:title", namespaces=ns)

    robots = (ROOT / "site" / "robots.txt").read_text(encoding="utf-8")
    assert "User-agent: *\nAllow: /" in robots
    assert f"Sitemap: {build.SITE_ORIGIN}{build.BASE_PATH}/sitemap.xml" in robots
    assert (f"Sitemap: {build.SITE_ORIGIN}{build.BASE_PATH}/news-sitemap.xml"
            in robots)

    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    home_schema = _json_ld(home)
    assert home_schema and home_schema[0]["@context"] == "https://schema.org"
    assert {node["@type"] for node in home_schema[0]["@graph"]} == {
        "Organization", "WebSite"}
    assert '<html lang="zh-Hant-TW">' in home
    assert '<meta name="robots" content="index,follow,max-image-preview:large">' in home
    assert '<meta name="author" content="SKYTICAL">' in home
    assert '<meta property="og:image:width" content="1200">' in home
    assert '<meta property="og:image:height" content="630">' in home
    assert '<meta property="og:image:type" content="image/png">' in home
    assert '<link rel="alternate" hreflang="zh-Hant-TW"' in home
    assert "SKYTICAL 航空新聞｜臺灣與全球即時航空快訊" in home
    assert "可追溯來源" in home
    assert "設計原型" not in home and "示意樣本" not in home
    assert "即時航班雷達" in home
    assert "今日全球延誤" in home and "今日全球取消" in home
    assert "來源未設定" in home
    assert "FlightAware AeroAPI 尚未設定" in home
    assert "全球延誤率" not in home and "生效中 NOTAM" not in home
    assert 'type="application/rss+xml"' in home

    if expected_zh_pages > 1:
        page_two = (ROOT / "site" / "news" / "page" / "2" /
                    "index.html").read_text(encoding="utf-8")
        assert 'rel="prev" href="https://skytical.tech/news/"' in page_two
        assert 'rel="next" href="https://skytical.tech/news/page/3/"' in page_two
        assert "第 2 / " in page_two
        assert page_two.count('class="feed-row"') <= build.NEWS_PAGE_SIZE
    if expected_en_pages > 1:
        en_page_two = (ROOT / "site" / "en" / "news" / "page" / "2" /
                       "index.html").read_text(encoding="utf-8")
        assert 'rel="prev" href="https://skytical.tech/en/news/"' in en_page_two
        assert "Page 2 of " in en_page_two
        assert en_page_two.count('class="feed-row"') <= build.NEWS_PAGE_SIZE

    article_paths = list((ROOT / "site" / "news").glob("*/index.html"))
    article = article_paths[0].read_text(encoding="utf-8")
    article_entities = _schema_entities(article)
    article_schema = next(
        entity for entity in article_entities
        if entity.get("@type") == "NewsArticle")
    article_breadcrumb = next(
        entity for entity in article_entities
        if entity.get("@type") == "BreadcrumbList")
    assert article_schema["@type"] == "NewsArticle"
    assert article_schema["headline"]
    assert article_schema["datePublished"].endswith("Z")
    assert article_schema["dateModified"].endswith("Z")
    assert article_schema["inLanguage"] == "zh-Hant-TW"
    assert article_schema["author"]["name"] == "SKYTICAL"
    assert article_schema["publisher"]["name"] == "SKYTICAL"
    assert [item["position"] for item in
            article_breadcrumb["itemListElement"]] == [1, 2, 3]
    assert article_breadcrumb["itemListElement"][1]["item"].endswith(
        "/news/")
    assert '<meta property="og:type" content="article">' in article
    assert '<meta property="article:published_time"' in article
    assert '<meta property="article:section"' in article
    assert '<meta property="article:author" content="SKYTICAL">' in article
    assert f'<time datetime="{article_schema["datePublished"]}"' in article
    assert "發布：" in article and "來源時間：" in article
    assert "SKYTICAL 編輯系統" in article
    pictured_article = next(
        path.read_text(encoding="utf-8") for path in article_paths
        if "<figure" in path.read_text(encoding="utf-8")
        and "data-image-fallback" not in path.read_text(encoding="utf-8"))
    pictured_schema = next(
        entity for entity in _schema_entities(pictured_article)
        if entity.get("@type") == "NewsArticle")
    assert 'fetchpriority="high" decoding="async"' in pictured_article
    assert 'loading="lazy"' not in re.search(
        r'<figure.*?</figure>', pictured_article, flags=re.DOTALL).group(0)
    assert (
        f'<meta property="og:image" content="'
        f'{html_lib.escape(pictured_schema["image"][0], quote=True)}">'
        in pictured_article
    )

    search = (ROOT / "site" / "search" / "index.html").read_text(
        encoding="utf-8")
    not_found = (ROOT / "site" / "404.html").read_text(encoding="utf-8")
    assert '<meta name="robots" content="noindex,follow">' in search
    assert '<meta name="robots" content="noindex,follow">' in not_found

    taiwan_hub = (ROOT / "site" / "topics" / "taiwan-aviation" /
                  "index.html").read_text(encoding="utf-8")
    assert "<h1>臺灣航空新聞</h1>" in taiwan_hub
    assert 'href="/news/' in taiwan_hub
    assert any(entity.get("@type") == "BreadcrumbList"
               for entity in _schema_entities(taiwan_hub))
    for slug in build.TOPICS:
        assert f'href="/topics/{slug}/"' in article

    policy = (ROOT / "site" / "editorial-policy" / "index.html").read_text(
        encoding="utf-8")
    assert "編輯、更正與聯絡政策" in policy
    assert "avwire/issues/new" in policy
    assert 'href="/editorial-policy/"' in article

    print("test_seo: OK")


if __name__ == "__main__":
    main()
