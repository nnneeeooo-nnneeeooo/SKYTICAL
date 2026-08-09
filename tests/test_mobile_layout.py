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
    airadvisor = (ROOT / "site" / "news" /
                  "a-20260809-0948-london-heathrow-tops-airadvisor-2026-glo" /
                  "index.html").read_text(encoding="utf-8")
    jetstar = (ROOT / "site" / "news" /
               "a-20260809-0948-jetstar-to-introduce-overhead-locker-fee" /
               "index.html").read_text(encoding="utf-8")

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
    assert "<span>重點摘要</span>" not in home
    assert 'class="article-page"' in article
    assert 'class="summary-preview summary-preview--article"' in article
    assert 'class="summary-preview__icon"' in article
    assert 'class="article-source-row"' in article
    assert "AirAdvisor；2026機場排名；倫敦希斯洛16.94分居首" in airadvisor
    assert "捷星航空；2027年2月2日起；頭頂置物箱收費；單程25澳幣起" in jetstar

    zh_long = "中華航空8月10日宣布調整桃園至福岡航班，受機場作業限制影響，兩班延後三小時，旅客須留意報到時間。" * 2
    zh_short = build.notification_summary(
        zh_long, "zh", "中華航空調整桃園至福岡航班 兩班延後三小時")
    assert zh_short == "中華航空調整桃園至福岡航班；兩班延後三小時"
    assert len(zh_short) <= 38 and "；" in zh_short and "…" not in zh_short
    en_short = build.notification_summary(
        "word " * 60, "en",
        "China Airlines Adjusts Two Taoyuan-Fukuoka Flights After Airport Restrictions")
    assert len(en_short.split()) <= 14 and "…" not in en_short

    assert "@media (max-width: 720px)" in css
    assert ".js .site-nav.is-open { display: grid; }" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in css
    assert ".center-col { order: 1;" in css
    assert ".feed-copy { grid-column: 1 / -1; }" in css
    assert ".summary-preview__text" in css
    assert "grid-template-columns: auto minmax(0, 1fr);" in css
    assert "-webkit-line-clamp: 2" in css
    assert "line-clamp: 2" in css
    assert "max-height: 3.16em" in css
    assert "max-height: 3.1em" in css
    assert "max-height: 3.3em" in css
    assert "width: 100%; padding: 0;" in css
    assert "border: 0; border-radius: 0; background: transparent; box-shadow: none;" in css
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
