"""Offline regression checks for pipeline/image_fallbacks.py."""
from __future__ import annotations

import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import image_fallbacks  # noqa: E402


class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def article(title: str, body: str = "", airport: str | None = None) -> dict:
    entities = {"airports": [airport]} if airport else {}
    return {
        "zh": {"title": title, "summary": body, "body": [body]},
        "en": {"title": "", "summary": "", "body": []},
        "entities": entities,
    }


def main() -> int:
    # Existing deterministic topic fallback must remain unchanged.
    drone = image_fallbacks.topic_image(
        article("美國對無人機開徵232條款關稅", "一般商業無人機適用新稅率")
    )
    assert drone is not None
    assert drone["matched"] == "topic:drone"
    assert drone["kind"] == "file_photo"
    assert drone["provider"] == "Wikimedia Commons"
    assert drone["license"] == "CC BY-SA 4.0"
    assert "Quadcopter_Drone_in_flight.jpg" in drone["url"]

    english = image_fallbacks.topic_image(
        article("Section 232 drone tariff update", "New tariffs apply to imported UAS components")
    )
    assert english is not None
    assert english["matched"] == "topic:drone"

    # A body-only mention must not turn an unrelated fleet story into a
    # quadcopter card.
    assert image_fallbacks.topic_image(
        article("UK military fleet inventory update", "The report also counts drone systems")
    ) is None

    # Regression: the Etna story already exposes Catania airport as a verified
    # entity, so a non-Taiwan airport must now become a Commons lookup target.
    catania = article(
        "埃特納火山噴發影響 義大利卡塔尼亞機場關閉延長至週六",
        "埃特納火山噴發持續影響機場營運。",
        airport="Catania airport",
    )
    assert image_fallbacks._airport_entity(catania) == "Catania airport"
    assert image_fallbacks._airport_title_tokens("Catania airport") == ["Catania"]

    good = FakeResp(200, {"query": {"pages": {
        "1": {
            "index": 0,
            "title": "File:Catania airport.jpg",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/catania-airport.jpg",
                "descriptionshorturl": "https://commons.wikimedia.org/wiki/File:Catania_airport.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "DornaXenia"},
                },
            }],
        },
    }}})
    fake = FakeHttp(good)
    original_requests = image_fallbacks.requests
    image_fallbacks.requests = types.SimpleNamespace(get=fake.get)
    try:
        matched = image_fallbacks.topic_image(catania)
    finally:
        image_fallbacks.requests = original_requests
    assert matched is not None
    assert matched["url"] == "https://upload.wikimedia.org/catania-airport.jpg"
    assert matched["matched"] == "airport:Catania airport"
    assert matched["license"] == "CC BY-SA 4.0"
    assert matched["kind"] == "file_photo"
    assert fake.calls[0][1]["params"]["gsrsearch"] == "filetype:bitmap Catania airport"

    # Safety regression: reject branding, unrelated airports and non-free files.
    bad = FakeResp(200, {"query": {"pages": {
        "1": {
            "index": 0,
            "title": "File:Catania Airport logo.png",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/logo.png",
                "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}},
            }],
        },
        "2": {
            "index": 1,
            "title": "File:Catania airport terminal.jpg",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/nonfree.jpg",
                "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}},
            }],
        },
        "4": {
            "index": 3,
            "title": "File:Catania airport ceiling interior.jpg",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/ceiling.jpg",
                "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}},
            }],
        },
        "3": {
            "index": 2,
            "title": "File:Palermo airport.jpg",
            "imageinfo": [{
                "thumburl": "https://upload.wikimedia.org/wrong-airport.jpg",
                "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}},
            }],
        },
    }}})
    fake = FakeHttp(bad)
    image_fallbacks.requests = types.SimpleNamespace(get=fake.get)
    try:
        assert image_fallbacks.lookup_commons_airport("Catania airport") is None
    finally:
        image_fallbacks.requests = original_requests

    unrelated = image_fallbacks.topic_image(
        article("航空公司公布季度財報", "營收與載客率同步成長")
    )
    assert unrelated is None

    # Airport names in a route, finance or compliance story are background
    # context; without an airport-operation headline they must not create a
    # generic airport card.
    background_airport = article(
        "航空公司完成機師藥檢",
        "結果均為陰性。",
        airport="Kuala Lumpur International Airport",
    )
    assert image_fallbacks.topic_image(background_airport) is None

    # Independent-event roundups must keep the neutral site image even when
    # one item exposes an airport that would normally trigger a fallback.
    roundup = article(
        "航空安全快訊：6起獨立事件彙整",
        "各事件互不相關。",
        airport="Atlanta",
    )
    roundup["articleFormat"] = "roundup"
    assert image_fallbacks.topic_image(roundup) is None

    # Returned deterministic mappings must be copies so callers cannot mutate
    # the registry for later articles.
    drone["subject"] = "changed"
    fresh = image_fallbacks.topic_image(article("無人機政策更新"))
    assert fresh is not None
    assert fresh["subject"] == "四軸無人機資料照片"

    print("PASS test_image_fallbacks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
