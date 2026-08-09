"""Offline regression checks for AVWIRE's shared mobile layout."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    assert build.main() == 0

    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "static" / "site.css").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    articles = list((ROOT / "site" / "news").glob("*/index.html"))
    assert articles
    article = articles[0].read_text(encoding="utf-8")

    assert 'class="nav-toggle"' in home
    assert 'aria-controls="site-nav"' in home
    assert 'class="site-nav" id="site-nav"' in home
    assert 'class="utility-row"' in home
    assert 'class="ticker-window"' in home
    assert 'class="ticker-pass"' in home
    assert 'class="feed-copy"' in home
    assert 'class="summary-preview summary-preview--hero"' in home
    assert 'class="summary-preview summary-preview--feed"' in home
    assert 'aria-label="重點摘要"' in home
    assert 'class="article-page"' in article
    assert 'class="summary-preview summary-preview--article"' in article
    assert 'class="summary-preview__icon"' in article
    assert 'class="article-source-row"' in article

    zh_long = "中華航空8月10日宣布調整桃園至福岡航班，受機場作業限制影響，兩班延後三小時，旅客須留意報到時間。" * 2
    zh_short = build.notification_summary(zh_long, "zh")
    assert len(zh_short) <= 93
    assert "中華航空" in zh_short and "福岡" in zh_short
    en_short = build.notification_summary("word " * 60, "en")
    assert len(en_short.split()) <= 42

    assert "@media (max-width: 720px)" in css
    assert ".js .site-nav.is-open { display: grid; }" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert ".center-col { order: 1;" in css
    assert ".feed-copy { grid-column: 1 / -1; }" in css
    assert ".summary-preview__text" in css
    assert "-webkit-line-clamp: 2" in css
    assert "--ticker-duration: 130s" in css
    assert 'font-family: "Noto Sans TC", sans-serif' in css
    assert "font-size: 13px; font-weight: 400" in css
    assert "font-family: inherit; font-size: 11px; font-weight: 600" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".marquee-track .ticker-pass:nth-child(2) { display: none; }" in css
    assert 'setAttribute("aria-expanded"' in script
    assert 'event.key === "Escape"' in script
    assert 'matchMedia("(min-width: 721px)")' in script
    assert 'matches ? 32 : 52' in script
    assert 'style.setProperty("--ticker-duration"' in script

    print("test_mobile_layout: OK")


if __name__ == "__main__":
    main()
