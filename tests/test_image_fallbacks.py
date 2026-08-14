"""Offline checks for pipeline/image_fallbacks.py."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "pipeline"))

import image_fallbacks  # noqa: E402


def article(title: str, body: str = "") -> dict:
    return {
        "zh": {"title": title, "summary": body, "body": [body]},
        "en": {"title": "", "summary": "", "body": []},
    }


def main() -> int:
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
        article("Section 232 tariff update", "New tariffs apply to imported UAS components")
    )
    assert english is not None
    assert english["matched"] == "topic:drone"

    unrelated = image_fallbacks.topic_image(
        article("航空公司公布季度財報", "營收與載客率同步成長")
    )
    assert unrelated is None

    # Returned mappings must be copies so callers cannot mutate the registry.
    drone["subject"] = "changed"
    fresh = image_fallbacks.topic_image(article("無人機政策更新"))
    assert fresh is not None
    assert fresh["subject"] == "四軸無人機資料照片"

    print("PASS test_image_fallbacks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
