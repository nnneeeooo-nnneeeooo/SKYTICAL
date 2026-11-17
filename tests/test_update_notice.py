"""Checks for bilingual source selection and the production notice contract."""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from update_notice import build_notices, notice_data, compact


def row(sha, zh, en, day="2026-11-16", kind="feature", **extra):
    return {"commit": sha * 40, "date": day, "kind": kind, "zh": zh, "en": en, **extra}


def main():
    rows = [
        row("a", "原使用 Luna 的撰稿、審核與快報改用 GPT 6.1 Terra。", "Luna drafting, review and briefings now use GPT 6.1 Terra.", kind="system"),
        row("b", "來源不足的新聞由 GPT 6.1 Terra 補查。", "GPT 6.1 Terra searches for additional sources.", kind="system"),
        row("c", "航空短訊彙整每期最多三則，每則各有配圖並共用輪播。", "Roundups now have three image slides."),
        row("d", "航空短訊彙整每期最多八則。", "Roundups contain eight stories.", day="2026-11-06"),
        row("e", "手機排版調整。", "Mobile layout refined.", kind="design"),
        row("f", "未來功能。", "A future feature.", day="2026-12-01"),
        row("1", "舊功能。", "An old feature.", day="2026-10-01"),
        row("2", "通知調整。", "Notice refined.", notice={"importance": "minor"}),
    ]
    data = build_notices({"entries": rows}, {"enabled": True, "contactEmail": "editor@example.com", "messages": {"zh": "站長neo，歡迎先行來信。", "en": "neo says: email me."}}, today=date(2026, 11, 16), model="gpt-6.1-terra")
    assert len(data["zh"]["items"]) == len(data["en"]["items"]) == 3
    assert [item["date"] for item in data["zh"]["items"]] == [item["date"] for item in data["en"]["items"]]
    assert data["zh"]["items"][0]["copy"] == "加入新AI模型ChatGPT 6.1 Terra，撰稿、查證、快報一併換新。新聞資料不夠，還會繼續找來源。"
    assert "joins the crew" in data["en"]["items"][0]["copy"]
    assert "evidence" in data["en"]["items"][0]["copy"]
    assert "三則" in data["zh"]["items"][1]["copy"]
    assert "eight" not in json.dumps(data["en"])
    assert data["en"]["station"]["email"] == "editor@example.com"
    assert not any("kind" in item for item in data["zh"]["items"])
    unchanged = build_notices({"entries": rows}, {}, today=date(2026, 11, 16), model="different-model")
    assert not any("AI大升級" in item["title"] for item in unchanged["zh"]["items"])
    broken = build_notices({"entries": [row("bad", "錯誤", "Bad"), row("3", "沒有英文", "")]}, {}, today=date(2026, 11, 16))
    assert broken["zh"]["items"] == broken["en"]["items"] == []
    assert compact("AI 大升級，GPT 6.1 Terra 接棒！", "zh") == "AI大升級，GPT 6.1 Terra接棒！"
    actual = notice_data()
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
