"""Regression checks for mandatory first-mention airport IATA codes."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import airport_codes  # noqa: E402


def catania_article() -> dict:
    return {
        "entities": {"airports": ["Catania airport"]},
        "zh": {
            "title": "埃特納火山噴發影響 義大利卡塔尼亞機場關閉延長至週六",
            "summary": "埃特納火山噴發持續；義大利西西里卡塔尼亞機場關閉時間延長至星期六",
            "body": [
                "位於義大利西西里島的卡塔尼亞機場因埃特納火山噴發影響持續關閉。",
                "卡塔尼亞機場的夏季旅遊航空交通持續受到影響。",
            ],
        },
        "en": {
            "title": "Etna eruption extends Catania airport closure until Saturday",
            "summary": "Catania airport remains closed following continued volcanic activity.",
            "body": [
                "The eruption has kept Catania airport closed until Saturday.",
                "Traffic at Catania airport remains disrupted.",
            ],
        },
    }



def ohare_article() -> dict:
    return {
        "entities": {"airports": ["Chicago O'Hare", "O'Hare"]},
        "zh": {
            "title": "美國航空波音737-800於芝加哥奧黑爾降落後爆胎",
            "summary": "美國航空737-800於芝加哥奧黑爾滑行時爆胎；該機場一週發生三起輪胎故障",
            "body": [
                "美國航空一架波音737-800客機於芝加哥奧黑爾降落後發生爆胎事件。",
                "本次事件是芝加哥奧黑爾在同一週內發生的第三起輪胎故障。這幾起異常狀況已引發對該繁忙機場（ORD）地面作業的關注。"
            ],
        },
        "en": {
            "title": "American Airlines Boeing 737-800 Suffers Tire Burst At Chicago O'Hare",
            "summary": "The Boeing 737-800 suffered a tire burst while taxiing at Chicago O'Hare after landing.",
            "body": [
                "The aircraft experienced a tire burst after landing at Chicago O'Hare.",
                "The incident was one of three tire failures recorded at Chicago O'Hare during the week."
            ],
        },
    }


def main() -> int:
    resolved = airport_codes.resolve_airport("Catania airport")
    assert resolved is not None, "Catania airport must resolve"
    assert resolved["code"] == "CTA", resolved

    article = catania_article()
    changed, unresolved = airport_codes.enforce_article(article)
    assert changed is True
    assert unresolved == []

    zh_all = "\n".join([
        article["zh"]["title"], article["zh"]["summary"], *article["zh"]["body"]
    ])
    en_all = "\n".join([
        article["en"]["title"], article["en"]["summary"], *article["en"]["body"]
    ])
    assert "卡塔尼亞機場（CTA）" in article["zh"]["title"]
    assert "Catania airport (CTA)" in article["en"]["title"]
    assert zh_all.count("（CTA）") == 1, zh_all
    assert en_all.count("(CTA)") == 1, en_all

    # Idempotence: running the publishing guard repeatedly must not duplicate
    # or move the already-inserted code.
    snapshot = copy.deepcopy(article)
    changed_again, unresolved_again = airport_codes.enforce_article(article)
    assert unresolved_again == []
    assert changed_again is False
    assert article == snapshot

    # Existing correct code remains exactly once.
    pretagged = catania_article()
    pretagged["zh"]["title"] = pretagged["zh"]["title"].replace(
        "卡塔尼亞機場", "卡塔尼亞機場（CTA）"
    )
    pretagged["en"]["title"] = pretagged["en"]["title"].replace(
        "Catania airport", "Catania airport (CTA)"
    )
    airport_codes.enforce_article(pretagged)
    assert "\n".join([
        pretagged["zh"]["title"], pretagged["zh"]["summary"], *pretagged["zh"]["body"]
    ]).count("（CTA）") == 1
    assert "\n".join([
        pretagged["en"]["title"], pretagged["en"]["summary"], *pretagged["en"]["body"]
    ]).count("(CTA)") == 1

    resolved_ohare = airport_codes.resolve_airport("Chicago O'Hare")
    assert resolved_ohare is not None
    assert resolved_ohare["code"] == "ORD", resolved_ohare
    resolved_ohare_zh = airport_codes.resolve_airport("芝加哥奧黑爾")
    assert resolved_ohare_zh is not None
    assert resolved_ohare_zh["code"] == "ORD", resolved_ohare_zh

    # Each article owns its first-mention counter. The second fixture must
    # independently receive ORD even though the first fixture was processed.
    for article in (ohare_article(), ohare_article()):
        changed, unresolved = airport_codes.enforce_article(article)
        assert changed is True
        assert unresolved == []
        zh_all = "\n".join([
            article["zh"]["title"], article["zh"]["summary"], *article["zh"]["body"]
        ])
        en_all = "\n".join([
            article["en"]["title"], article["en"]["summary"], *article["en"]["body"]
        ])
        assert "芝加哥奧黑爾（ORD）" in article["zh"]["title"]
        assert "（ORD）" not in article["zh"]["body"][1]
        assert "Chicago O'Hare (ORD)" in article["en"]["title"]
        assert zh_all.count("（ORD）") == 1, zh_all
        assert en_all.count("(ORD)") == 1, en_all

    print("PASS test_airport_codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
