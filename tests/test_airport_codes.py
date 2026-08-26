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

    assert airport_codes.resolve_airport("London Heathrow")["code"] == "LHR"
    assert airport_codes.resolve_airport("倫敦希斯洛機場")["code"] == "LHR"
    assert airport_codes.resolve_airport("Dubai International Airport")["code"] == "DXB"
    assert airport_codes.resolve_airport("杜拜國際機場")["code"] == "DXB"
    assert airport_codes.resolve_airport("Al Maktoum International")["code"] == "DWC"
    assert airport_codes.resolve_airport("阿勒馬克圖姆國際機場")["code"] == "DWC"

    # The textual airport identity outranks a stale/wrong embedded code.
    resolved_phl = airport_codes.resolve_airport(
        "Philadelphia International Airport (PNE)")
    assert resolved_phl is not None
    assert resolved_phl["code"] == "PHL", resolved_phl

    # The first visible article mention is title/body; an invisible summary
    # must not consume the code before the reader reaches the body.
    visible_body = catania_article()
    visible_body["zh"]["title"] = "埃特納火山活動持續"
    visible_body["en"]["title"] = "Etna volcanic activity continues"
    visible_body["zh"]["summary"] = "卡塔尼亞機場（CTA）摘要"
    visible_body["en"]["summary"] = "Catania airport (CTA) summary"
    airport_codes.enforce_article(visible_body)
    assert "卡塔尼亞機場（CTA）" in visible_body["zh"]["body"][0]
    assert "Catania airport (CTA)" in visible_body["en"]["body"][0]

    # Two similarly named London airports must retain their own codes; the
    # old city-generic matcher could append both codes to one mention.
    london = {
        "entities": {"airports": [
            "London-Gatwick Airport", "London-Heathrow Airport"]},
        "zh": {"title": "英國機場航班調整", "summary": "",
                "body": ["航班往返 London Gatwick Airport 與 London Heathrow Airport。"]},
        "en": {"title": "UK airport schedule update", "summary": "",
                "body": ["Flights link London Gatwick Airport with London Heathrow Airport."]},
    }
    changed, unresolved = airport_codes.enforce_article(london)
    assert changed is True and unresolved == []
    assert "London Gatwick Airport (LGW)" in london["en"]["body"][0]
    assert "London Heathrow Airport (LHR)" in london["en"]["body"][0]
    assert "(LHR)" not in london["en"]["body"][0].split("London Heathrow")[0]
    assert airport_codes.validate_article(london) == []

    # City-only and military-installation entities remain review noise rather
    # than being reported as missing civilian airport codes.
    noise = {
        "entities": {"airports": [
            "Atlanta", "Springfield Air National Guard Base"]},
        "zh": {"title": "航空安全更新", "summary": "", "body": []},
        "en": {"title": "Aviation safety update", "summary": "", "body": []},
    }
    _changed, unresolved = airport_codes.enforce_article(noise)
    assert unresolved == [], unresolved

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

    assert airport_codes.resolve_airport(
        "Atlantic City Bader Field (AIY)")["code"] == "AIY"

    # A Chinese title can lead an English body paragraph, and a bilingual
    # parenthetical should remain readable while receiving only one code.
    qantas = {
        "entities": {"airports": ["London Heathrow", "Melbourne Airport"]},
        "zh": {
            "title": "澳洲航空航線調整",
            "summary": "",
            "body": [
                "旅客將繼續前往倫敦希斯洛機場並經由新加坡停靠。",
                "澳洲航空集團已與墨爾本機場就基礎設施達成協議。",
            ],
        },
        "en": {
            "title": "Qantas network update",
            "summary": "",
            "body": [
                "Passengers will continue to London Heathrow via Singapore.",
                "Qantas and Melbourne Airport agreed infrastructure terms.",
            ],
        },
    }
    changed, unresolved = airport_codes.enforce_article(qantas)
    assert changed is True and unresolved == []
    assert "倫敦希斯洛機場（LHR）" in qantas["zh"]["body"][0]
    assert "墨爾本機場（MEL）" in qantas["zh"]["body"][1]
    assert "London Heathrow (LHR)" in qantas["en"]["body"][0]
    assert "Melbourne Airport (MEL)" in qantas["en"]["body"][1]
    assert airport_codes.validate_article(qantas) == []

    bilingual = {
        "entities": {"airports": ["Midland International Air & Space Port"]},
        "zh": {"title": "德州米德蘭國際空天港（Midland International Air & Space Port）",
                "summary": "", "body": []},
        "en": {"title": "Midland International Air & Space Port",
                "summary": "", "body": []},
    }
    airport_codes.enforce_article(bilingual)
    assert bilingual["zh"]["title"] == (
        "德州米德蘭國際空天港（MAF；Midland International Air & Space Port）")
    assert bilingual["zh"]["title"].count("MAF") == 1
    assert airport_codes.validate_article(bilingual) == []

    # A code-only entity does not provide a name anchor. Preserve its
    # already-correct first-mention annotations instead of deleting them.
    code_only = {
        "entities": {"airports": ["ATL"]},
        "zh": {"title": "航線公告", "summary": "", "body": [
            "航班由亞特蘭大（ATL）飛往達拉斯-沃斯堡。",
        ]},
        "en": {"title": "Route update", "summary": "", "body": [
            "The flight operated from Atlanta (ATL) to Dallas-Fort Worth; the airport remained open.",
        ]},
    }
    airport_codes.enforce_article(code_only)
    assert "亞特蘭大（ATL）" in code_only["zh"]["body"][0]
    assert code_only["en"]["body"][0].count("(ATL)") == 1
    assert "airport (ATL)" not in code_only["en"]["body"][0]

    # Existing bilingual formatting is stable on the second publishing pass.
    bilingual_snapshot = copy.deepcopy(bilingual)
    changed_again, unresolved_again = airport_codes.enforce_article(bilingual)
    assert changed_again is False
    assert unresolved_again == []
    assert bilingual == bilingual_snapshot

    print("PASS test_airport_codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
