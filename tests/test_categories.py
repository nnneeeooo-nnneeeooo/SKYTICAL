"""Offline tests for AVWIRE's editorial category contract."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import common  # noqa: E402
import write  # noqa: E402


def article(title: str, category: str = "ops") -> dict:
    return {
        "id": "a-20260727-1200-category-test",
        "publishedUtc": "2026-07-27T12:00Z",
        "cat": category,
        "primarySource": "中央社 CNA",
        "image": None,
        "zh": {"title": title, "summary": "測試摘要", "body": ["測試內文。"]},
        "en": {"title": "Category test", "summary": "Test summary.",
               "body": ["Test body."]},
        "sources": [{"name": "中央社 CNA",
                     "url": "https://www.cna.com.tw/news/test.aspx"}],
    }


def valid_draft(category: str) -> dict:
    zh_body = ["測" * 125 for _ in range(write.MIN_BODY_PARAGRAPHS)]
    en_body = ["word " * 63 for _ in range(write.MIN_BODY_PARAGRAPHS)]
    return {
        "status": "publish",
        "decisionReason": "",
        "cat": category,
        "zh": {"title": "測試標題", "summary": "測試摘要",
               "body": zh_body},
        "en": {"title": "Test title", "summary": "Test summary.",
               "body": en_body},
        "flash": {"zh": "測試快訊", "en": "Test flash", "hot": False},
        "incident": None,
        "facts": [{"factId": "F1", "claim": "Test claim",
                   "sourceQuote": "Test source quote"}],
        "headlineSupportedBy": ["F1"],
        "summarySupportedBy": ["F1"],
        "entities": {key: [] for key in write.ENTITY_KEYS},
        "eventStatus": "confirmed",
        "riskFlags": [],
        "requiresHumanReview": False,
    }


def main() -> None:
    assert common.CATEGORIES == ("safety", "reg", "biz", "ops", "mil")
    assert write.DRAFT_SCHEMA["properties"]["cat"]["enum"] \
        == list(common.CATEGORIES)
    assert write.validate_draft(valid_draft("mil")) is None

    published = build.prep_article(
        article("國防部公布共機艦動態", category="ops"))
    assert published is not None
    assert published["cat"] == "mil"
    assert build.CATS["mil"] == {"zh": "軍事", "en": "Military"}
    assert build.TAGCLS["mil"] == "tag-accent-2"
    assert build.L["zh"]["cats"][-1] == "軍事"
    assert build.L["en"]["cats"][-1] == "Military"

    group = {
        "id": "g-military-test",
        "primarySource": "中央社 CNA",
        "items": [{
            "sourceKey": "cnataiwan",
            "source": "中央社 CNA",
            "title": "漢光演習驗證軍機聯合作戰能力",
            "summary": "國防部說明軍機演習規劃。",
            "url": "https://www.cna.com.tw/news/test.aspx",
            "publishedUtc": "2026-07-27T11:00Z",
        }],
    }
    drafted_as_ops = valid_draft("ops")
    military_article = write.build_article(
        drafted_as_ops, group, datetime.now(timezone.utc), set())
    assert military_article is not None
    assert military_article["cat"] == "mil"

    civil_counter_drone = {
        "title": "FAA reports counter-drone enforcement at World Cup",
        "summary": "The civil aviation regulator seized unauthorised drones.",
        "sourceKey": "faa",
    }
    assert common.story_category("reg", civil_counter_drone) == "reg"
    assert common.story_category("biz", {
        "title": "PLA builds models of Taiwan facilities",
    }) == "mil"
    assert common.story_category("ops", {
        "sourceKey": "mndnews",
        "title": "Daily activity report",
    }) == "mil"

    mixed_company_results = article(
        "波音第二季營收246億美元 交付171架民航機",
        category="mil",
    )
    mixed_company_results["zh"]["summary"] = (
        "波音公布第二季財報與民航機交付量。")
    mixed_company_results["en"]["title"] = (
        "Boeing Reports Q2 Revenue and Commercial Deliveries")
    mixed_company_results["en"]["summary"] = (
        "The company reported quarterly results and commercial deliveries.")
    mixed_company_results["zh"]["body"] = [
        "正文次要段落提及國防部門與美國海軍計畫。"]
    mixed_company_results["en"]["body"] = [
        "A secondary paragraph mentions the U.S. Navy and defense segment."]
    mixed_company_results["entities"] = {
        "organizations": ["U.S. Navy", "U.S. Space Force"],
        "aircraft_models": ["VC-25B", "MQ-25A"],
    }
    assert not common.is_military_story(mixed_company_results)
    assert common.story_category("mil", mixed_company_results) == "biz"
    assert build.prep_article(mixed_company_results)["cat"] == "biz"

    military_order = {
        "title": "美國海軍向製造商下單採購新型軍機",
        "summary": "採購案直接涉及海軍航空兵力。",
    }
    assert common.story_category("biz", military_order) == "mil"

    prompt_words = " ".join(write.SYSTEM_PROMPT.split())
    assert "secondary part of the report" in prompt_words
    assert "body paragraphs do not by themselves make the story mil" \
        in prompt_words

    print("test_categories: OK")


if __name__ == "__main__":
    main()
