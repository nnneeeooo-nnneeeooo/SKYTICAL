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
    david = (ROOT / "site" / "news" /
             "a-20260809-0853-david-cummins-sworn-in-as-eighth-tsa-adm" /
             "index.html").read_text(encoding="utf-8")
    emirates = (ROOT / "site" / "news" /
                "a-20260809-1305-emirates-temporarily-suspends-airbus-a38" /
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
    assert 'class="summary-preview' not in article
    assert 'class="article-source-row"' in article
    summaries = (
        ("AirAdvisor發布2026機場排名；倫敦希斯洛以16.94分居首", airadvisor),
        ("捷星航空2027年2月2日起收取頭頂置物箱費；單程25澳幣起", jetstar),
        ("David Cummins就任TSA第八任局長；監管全美逾430座機場安檢", david),
        ("阿聯酋航空夏季暫停PRG、GLA A380航班；10月恢復每日服務", emirates),
    )
    for summary, article_html in summaries:
        assert summary in home
        assert 'class="summary-preview' not in article_html

    zh_long = "中華航空8月10日宣布調整桃園至福岡航班，受機場作業限制影響，兩班延後三小時，旅客須留意報到時間。" * 2
    zh_short = build.notification_summary(
        zh_long, "zh", "中華航空調整桃園至福岡航班 兩班延後三小時")
    assert zh_short == "中華航空調整桃園至福岡航班 兩班延後三小時"
    assert len(zh_short) <= 38 and "…" not in zh_short
    david_fallback = build.notification_summary(
        "美國參議院通過確認案後，David Cummins已正式宣誓就任TSA第八任局長。",
        "zh", "David Cummins宣誓就任TSA第八任局長")
    assert david_fallback == "David Cummins宣誓就任TSA第八任局長"
    assert "David；Cummins" not in david_fallback
    cessna_fallback = build.notification_summary(
        "Textron Aviation宣布Cessna Citation CJ3 Gen3完成首飛。",
        "zh", "Cessna Citation CJ3 Gen3 於 Wichita 完成首飛")
    assert cessna_fallback == "Cessna Citation CJ3 Gen3於Wichita完成首飛"
    emirates_fallback = build.notification_summary(
        "根據Simple Flying報導，阿聯酋航空已暫停PRG與GLA的A380航班。",
        "zh", "阿聯酋航空暫停PRG與GLA A380航班")
    assert emirates_fallback != "阿聯酋航空" and "A380航班" in emirates_fallback
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
