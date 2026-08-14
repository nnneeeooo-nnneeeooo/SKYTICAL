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

    print("PASS test_airport_codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
