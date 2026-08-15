"""Regression tests for sentence-safe manual summary fallbacks."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import summary_guard  # noqa: E402


def main() -> int:
    zh_first = (
        "星宇航空與日本當代藝術家空山基（Hajime Sorayama）合作打造的「STARLUX AIRSORAYAMA GOLD 空山金」完成交機。"
        "這架註冊編號 B-58554 的 Airbus A350-1000，在法國當地時間 8 月 14 日完成交機程序後，"
        "於 8 月 15 日中午 12 時 27 分自土魯斯布拉尼亞克機場（TLS）啟程飛往臺灣，"
        "預計於臺北時間 8 月 16 日上午 9 時 28 分抵達桃園國際機場（TPE）。"
    )
    en_first = (
        "STARLUX Airlines has completed the delivery of STARLUX AIRSORAYAMA GOLD in collaboration with Hajime Sorayama. "
        "Registered B-58554, the Airbus A350-1000 departed Toulouse-Blagnac Airport (TLS) for Taiwan on August 15 and "
        "is scheduled to arrive at Taoyuan International Airport (TPE) at 9:28 AM Taipei time on August 16."
    )
    article = {
        "zh": {"summary": zh_first[:180], "body": [zh_first]},
        "en": {"summary": en_first[:180], "body": [en_first]},
    }

    assert article["zh"]["summary"].endswith("臺北")
    assert summary_guard.repair_article(article) is True
    assert article["zh"]["summary"].endswith("。")
    assert article["en"]["summary"].endswith(".")
    assert "桃園國際機場（TPE）" in article["zh"]["summary"]
    assert "Taoyuan International Airport (TPE)" in article["en"]["summary"]

    # A deliberate editor-written summary is never rewritten.
    custom = {
        "zh": {
            "summary": "編輯自訂摘要，不應由發布防呆改寫。",
            "body": [zh_first],
        },
        "en": {
            "summary": "Editor-written summary must remain untouched.",
            "body": [en_first],
        },
    }
    snapshot = {lang: custom[lang]["summary"] for lang in ("zh", "en")}
    assert summary_guard.repair_article(custom) is False
    assert {lang: custom[lang]["summary"] for lang in ("zh", "en")} == snapshot

    # If no sentence boundary exists near the limit, use an explicit ellipsis
    # instead of silently exposing an unfinished hard cut.
    no_boundary = "A" * 400
    fallback = summary_guard.sentence_safe_fallback(no_boundary)
    assert fallback.endswith("…")
    assert len(fallback) <= 181

    print("PASS test_summary_guard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
