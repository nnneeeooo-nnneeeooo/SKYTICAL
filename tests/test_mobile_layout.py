"""Offline regression checks for SKYTICAL's shared mobile layout."""
from __future__ import annotations

import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    assert build.main() == 0

    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    en_home = (ROOT / "site" / "en" / "index.html").read_text(encoding="utf-8")
    home_template = (ROOT / "templates" / "home.html").read_text(
        encoding="utf-8")
    css = (ROOT / "static" / "site.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    articles = list((ROOT / "site" / "news").glob("*/index.html"))
    assert articles
    article = articles[0].read_text(encoding="utf-8")
    airadvisor = (ROOT / "site" / "news" /
                  "a-20260809-0948-london-heathrow-tops-airadvisor-2026-glo" /
                  "index.html").read_text(encoding="utf-8")
    jetstar = (ROOT / "site" / "news" /
               "a-20260809-0948-jetstar-to-introduce-overhead-locker-fee" /
               "index.html").read_text(encoding="utf-8")
    emirates = (ROOT / "site" / "news" /
                "a-20260809-1305-emirates-temporarily-suspends-airbus-a38" /
                "index.html").read_text(encoding="utf-8")

    assert 'class="nav-toggle"' in home
    assert 'aria-controls="site-nav"' in home
    assert 'class="site-nav" id="site-nav"' in home
    for html, prefix in ((home, ""), (en_home, "/en")):
        document = BeautifulSoup(html, "html.parser")
        header = document.select_one(".header-search-row")
        assert header is not None
        assert [child.get("class", [""])[0] for child in header.find_all(recursive=False)] == [
            "brand-shell", "header-search-form", "header-social-links"
        ]
        nav = document.select_one("#site-nav")
        assert nav is not None
        visible = [link for link in nav.find_all("a", recursive=False)
                   if "nav-link-mobile-hidden" not in link.get("class", [])]
        assert [link["href"] for link in visible] == [
            f"{prefix}/{section}/" for section in
            ("news", "briefings", "radar", "incidents", "about", "team")
        ]
        assert "BETA" in visible[1].get_text()
    assert 'class="utility-row"' in home
    assert 'class="ticker-window"' in home
    assert 'class="ticker-pass"' in home
    assert 'class="flash-copy"' in home
    assert 'class="flash-text"' in home
    assert 'class="feed-copy"' in home
    assert 'class="summary-preview summary-preview--hero"' in home
    assert 'class="summary-preview summary-preview--feed"' in home
    assert re.search(
        r'<span class="feed-copy">.*?</span>\s*</span>\s*'
        r'<div class="summary-preview summary-preview--feed"',
        home,
        re.DOTALL,
    )
    assert 'aria-label="重點摘要"' in home
    assert "<span>重點摘要</span>" not in home
    assert 'class="article-page"' in article
    assert 'class="summary-preview' not in article
    assert 'class="article-source-row"' in article
    feed_summaries = re.findall(
        r'<div class="summary-preview summary-preview--feed".*?'
        r'<span class="summary-preview__text">(.*?)</span>',
        home,
        re.DOTALL,
    )
    assert feed_summaries and all(summary.strip() for summary in feed_summaries)
    for article_html in (airadvisor, jetstar, emirates):
        assert 'class="summary-preview' not in article_html

    # Cards retain the supplied summary; fitting a small card must never
    # substitute the headline or cut an aircraft name or number in half.
    zh_summary = "空中巴士A350-1000ULR以24小時24分完成墨爾本至土魯斯12,500公里飛行，並取得認證。"
    assert build.notification_summary(zh_summary, "zh", "A350-1000ULR創飛行紀錄") == zh_summary
    en_summary = "The aircraft completed the flight in 24 hours and 24 minutes, retaining the full verified distance of 12,500 kilometres."
    assert build.notification_summary(en_summary, "en", "Aircraft sets flight record") == en_summary
    assert build.notification_summary("航空公司增班。", "zh", "航空公司增班") == ""

    assert "@media (max-width: 1100px)" in css
    assert "@media (max-width: 900px)" not in css
    assert "@media (max-width: 720px)" in css
    assert ".page { width: 100%; overflow-x: clip; }" in css
    assert "aspect-ratio: 50 / 11; position: relative; overflow: visible;" in css
    assert ".brand-flight-crop { position: absolute; inset: 0; overflow: hidden; }" in css
    assert "width: 100%; height: 100%; max-width: 320px" in css
    assert "object-fit: contain; background: transparent;" in css
    assert "position: relative; contain: paint;" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css
    assert ".js .site-nav.is-open { display: grid; }" in css
    assert ".site-nav .nav-link-mobile-hidden { display: none; }" in css
    assert ".header-search-row .nav-toggle { display: none; }" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert "grid-template-columns: 56px minmax(0, 1fr)" in css
    assert ".flash-copy" in css
    assert "max-height: 3.1em" in css
    assert ".center-col { order: 1;" in css
    assert ".radar-layout { grid-template-columns: minmax(0, 1fr); min-height: 0; }" in css
    assert '". . summary"' in css
    assert '". . source"' in css
    assert '"summary summary"' in css
    assert ".summary-preview--feed { grid-area: summary; margin-top: 7px; }" in css
    assert ".summary-preview__text" in css
    assert "grid-template-columns: auto minmax(0, 1fr);" in css
    assert "-webkit-line-clamp: 2" in css
    assert "line-clamp: 2" in css
    assert "max-height: 3.16em" in css
    assert "max-height: 3.1em" in css
    assert "width: 100%; padding: 0;" in css
    assert "border: 0; border-radius: 0; background: transparent; box-shadow: none;" in css
    assert "--ticker-duration: 130s" in css
    assert "font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont" in css
    assert '"PingFang TC", "Microsoft JhengHei", sans-serif' in css
    assert "font-size: 14px; font-weight: 600" in css
    assert "font-synthesis: none; -webkit-font-smoothing: auto" in css
    assert 'font-family: ui-monospace, "SFMono-Regular", Menlo' in css
    assert "font-size: 12px; font-weight: 700" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert 'id="hero-prev"' in home_template
    assert 'id="hero-next"' in home_template
    assert 'id="hero-dots"' in home_template
    assert 'aria-roledescription="carousel"' in home_template
    assert 'aria-label="{% if html_lang.startswith(\'zh\') %}頭條新聞輪播' in home_template
    assert "hero-enter-right" in css
    assert 'data-rotation-ms="2500"' in home
    assert "dataset.rotationMs" in script
    assert 'addEventListener("mouseenter"' in script
    assert 'addEventListener("focusin"' in script
    assert ".marquee-track .ticker-pass:nth-child(2) { display: none; }" in css
    assert 'setAttribute("aria-expanded"' in script
    assert 'event.key === "Escape"' in script
    assert 'matchMedia("(min-width: 1101px)")' in script
    assert 'matches ? 32 : 52' in script
    assert 'style.setProperty("--ticker-duration"' in script

    print("test_mobile_layout: OK")


if __name__ == "__main__":
    main()
