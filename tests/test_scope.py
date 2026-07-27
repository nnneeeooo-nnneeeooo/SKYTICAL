"""Regression tests for AVWIRE subject scope and non-destructive archiving."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import common  # noqa: E402
import fetch  # noqa: E402
import write  # noqa: E402


TARGET_ID = "a-20260727-0838-presidential-office-rejects-show-claim-s"


def story(title: str, summary: str = "", source_key: str = "cnataiwan") -> dict:
    return {
        "id": "g-scope-test",
        "primarySource": "中央社 CNA",
        "items": [{
            "sourceKey": source_key,
            "source": "中央社 CNA",
            "title": title,
            "summary": summary,
            "url": "https://www.cna.com.tw/news/test.aspx",
            "publishedUtc": "2026-07-27T08:00Z",
        }],
    }


def draft() -> dict:
    return {
        "status": "publish",
        "decisionReason": "",
        "cat": "mil",
        "zh": {"title": "測試標題", "summary": "測試摘要",
               "body": ["測" * 125 for _ in range(4)]},
        "en": {"title": "Test title", "summary": "Test summary",
               "body": ["word " * 63 for _ in range(4)]},
        "flash": {"zh": "測試", "en": "Test", "hot": False},
        "incident": None,
        "facts": [{"factId": "F1", "claim": "Test",
                   "sourceQuote": "Test source quote"}],
        "headlineSupportedBy": ["F1"],
        "summarySupportedBy": ["F1"],
        "entities": {key: [] for key in write.ENTITY_KEYS},
        "eventStatus": "confirmed",
        "riskFlags": [],
        "requiresHumanReview": False,
    }


def main() -> None:
    political = story(
        "府：總統視導漢光是責任與義務 作秀之說污名化國軍",
        "總統府說明三軍統帥參與演訓的責任與憲政義務。",
    )
    assert not common.is_transport_story(political)
    assert not fetch._matches_keywords(
        political["items"][0], ["國軍", "漢光"])

    assert common.is_transport_story(story(
        "國防部公布共機艦動態",
        "偵獲共機4架次、共艦7艘於台海周邊活動。"))
    assert common.is_transport_story(story(
        "台鐵列車故障部分區間停駛"))
    assert common.is_transport_story(story(
        "港務公司公告客輪停航"))
    assert common.is_transport_story(story(
        "高速公路客運事故造成回堵"))
    assert not common.is_transport_story(story(
        "國防預算攻防延燒 朝野公布最新主張"))

    cna_keywords = common.SOURCES["cnataiwan"]["keywords"]
    assert "國軍" not in cna_keywords
    assert "國防部" not in cna_keywords
    assert common.SOURCES["mndnews"]["scope_filter"] is True
    assert "OUT-OF-SCOPE" in write.SYSTEM_PROMPT

    assert write.build_article(
        draft(), political, datetime.now(timezone.utc), set()) is None
    on_topic = story("國防部公布共機艦動態",
                     "偵獲共機4架次、共艦7艘於台海周邊活動。")
    assert write.build_article(
        draft(), on_topic, datetime.now(timezone.utc), set()) is not None

    article_data = json.loads(
        (ROOT / "data" / "articles" / "2026-07-27T08.json")
        .read_text(encoding="utf-8"))
    archived = next(row for row in article_data["articles"]
                    if row["id"] == TARGET_ID)
    assert archived["archived"] is True
    assert archived["archiveReason"]
    assert build.prep_article(archived) is None

    flash_data = json.loads(
        (ROOT / "data" / "flashes.json").read_text(encoding="utf-8"))
    archived_flash = next(row for row in flash_data
                          if row.get("articleId") == TARGET_ID)
    assert archived_flash["archived"] is True
    visible_flashes = build.prep_flashes(flash_data, {TARGET_ID})
    assert all(row.get("articleId") != TARGET_ID for row in visible_flashes)

    print("test_scope: OK")


if __name__ == "__main__":
    main()
