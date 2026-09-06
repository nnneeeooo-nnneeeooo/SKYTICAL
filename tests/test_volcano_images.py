"""A named volcano must get its own dated file photo, never another mountain."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
import image_fallbacks as fallbacks
import images


def article(title):
    return {"id": "volcano", "publishedUtc": images.now_utc().isoformat(),
            "zh": {"title": title}, "en": {}, "image": None,
            "entities": {"airlines": ["Garuda Indonesia"]}}


class VolcanoImagesTests(unittest.TestCase):
    def test_named_volcano_and_caption(self):
        for title in ("印尼喀拉喀托之子火山噴發 8座機場暫停營運",
                      "Mount Anak Krakatau eruption closes airports",
                      "Anak Krakatoa ash disrupts flights"):
            row = article(title)
            image = fallbacks.topic_image(row)
            self.assertIsNotNone(image)
            self.assertEqual(image["kind"], "file_photo")
            self.assertTrue(images.existing_image_matches(row, image))
            caption = build._hero_image_caption(build.normalize_image(image), "zh")
            self.assertEqual(image["subject"], "印尼喀拉喀托之子火山（Anak Krakatau）冒煙景象")
            self.assertEqual(image["photoDate"], "2012-09-09")
            self.assertNotIn("2012-09-09", caption)
            for value in ("Anak Krakatau", "非事件現場照片", "Uprising", "CC BY-SA 3.0"):
                self.assertIn(value, caption)

    def test_other_volcano_and_body_only_do_not_match(self):
        original = fallbacks.topic_image(article("Anak Krakatau eruption"))
        for title in ("Etna eruption closes airport", "Lewotobi eruption",
                      "印尼火山噴發影響航班", "航空公司財報"):
            row = article(title)
            row["zh"]["body"] = ["背景曾提及喀拉喀托之子火山。"]
            self.assertIsNone(fallbacks.topic_image(row))
            self.assertFalse(images.existing_image_matches(row, original))
        row = article("Anak Krakatau eruption")
        row["articleFormat"] = "roundup"
        self.assertIsNone(fallbacks.topic_image(row))
        bad = dict(original, url="https://example.org/Anak_Krakatau_map.jpg")
        self.assertFalse(images.existing_image_matches(article("Anak Krakatau eruption"), bad))

    def test_batch_attaches_without_network_and_survives_next_run(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "batch.json"
            path.write_text(json.dumps({"articles": [article("Anak Krakatau eruption")]}), encoding="utf-8")
            with patch.object(fallbacks, "ARTICLES_DIR", Path(temp)), \
                 patch.object(fallbacks.requests, "get", side_effect=AssertionError("network not needed")):
                self.assertEqual(fallbacks.main(), 0)
                first = path.read_text(encoding="utf-8")
                self.assertEqual(fallbacks.main(), 0)
                self.assertEqual(first, path.read_text(encoding="utf-8"))
            row = json.loads(first)["articles"][0]
            self.assertTrue(images.existing_image_matches(row, row["image"]))


if __name__ == "__main__":
    unittest.main()
