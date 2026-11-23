"""Checks for bilingual source selection and the production notice contract."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from update_notice import build_notices, notice_data


def row(sha, zh, en, day="2026-11-16", kind="feature", **extra):
    return {"commit": sha * 40, "date": day, "kind": kind, "zh": zh, "en": en, **extra}


def main():
    major = {"importance": "major"}
    rows = [
        row("a", "撰稿流程更新。查證門檻維持。",
            "Drafting has been updated. Source checks still apply.",
            kind="system", notice=major),
        row("b", "重大停飛消息優先處理。", "Major disruptions get priority.",
            day="2026-11-15", notice=major),
        row("c", "團隊介紹更新。", "Team introduction updated.",
            notice={"importance": "minor"}),
        row("2", "修正頁首標誌跑位。", "Fixed the header logo layout.",
            notice={"importance": "minor", "standalone": True}),
        row("d", "新聞配圖持續補齊。", "More news photos."),
        row("e", "未來功能。", "A future feature.",
            day="2026-12-01", notice=major),
        row("f", "舊功能。", "An old feature.",
            day="2026-10-01", notice=major),
        row("1", "缺少英文。", "", notice=major),
    ]
    station = {"enabled": True, "contactEmail": "editor@example.com",
               "messages": {"zh": "先行來信", "en": "email me."}}
    data = build_notices({"entries": rows}, station, today=date(2026, 11, 16))
    assert [item["date"] for item in data["zh"]["items"]] == ["2026-11-16", "2026-11-16", "2026-11-15"]
    assert [item["date"] for item in data["en"]["items"]] == ["2026-11-16", "2026-11-16", "2026-11-15"]
    assert data["en"]["items"][0]["title"] == "Drafting has been updated"
    assert "Source checks still apply." in data["en"]["items"][0]["copy"]
    assert data["zh"]["items"][1]["title"] == "修正頁首標誌跑位"
    assert data["en"]["items"][1]["title"] == "Fixed the header logo layout"
    assert data["en"]["station"]["email"] == "editor@example.com"
    assert "Team introduction" not in json.dumps(data)
    assert "More news photos" not in json.dumps(data)
    actual = notice_data()
    for phrase in ("\u5718\u968a\u4ecb\u7d39\u66f4\u65b0", "\u8fd1\u671f\u65b0\u805e\u7167\u7247\u6301\u7e8c\u88dc\u9f4a", "team introduction", "more photos for recent news"):
        assert phrase.casefold() not in json.dumps(actual, ensure_ascii=False).casefold()
    for lang in ("zh", "en"):
        assert actual[lang]["items"] and actual[lang]["station"]
        assert actual[lang]["ui"]["emailLabel"] in actual[lang]["station"]["message"]
    import build
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True, undefined=StrictUndefined)
    for lang in ("zh", "en"):
        ctx = build.base_ctx(lang, "home", "", title="SKYTICAL", description="News", ticker=[], build={"date": "2026-11-16", "utc_hm": "12:00", "tpe_hm": "20:00", "stamp": "2026-11-16 12:00"})
        html = env.get_template("_update_notice.html").render(**ctx)
        assert html.count('id="site-update-notice"') == 1
        assert 'data-compact-copy' in html
        assert actual[lang]["ui"]["continue"] in html
        assert 'neo-life-expanded.jpg' in html
        assert 'iframe' not in html and '?preview' not in html
    print("test_update_notice: OK (bilingual content, source gates, render)")


if __name__ == "__main__":
    main()
