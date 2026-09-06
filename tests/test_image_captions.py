"""Offline regression checks for evidence-backed, visible image descriptions."""
from datetime import timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import image_captions as captions
import build

IMAGE = "https://images.example/photos/aircraft.jpg"
SOURCE = "https://news.example/story/"


class ImageCaptionTests(unittest.TestCase):
    def test_exact_image_alt_and_resize_variants(self):
        html = '<img src="https://other.example/photos/aircraft.jpg" alt="Wrong plane">' \
               '<img data-src="https://images.example/photos/aircraft-1280x720.jpg?w=900" ' \
               'alt="Virgin Atlantic Airbus A350">'
        result = captions.source_description(html, IMAGE, SOURCE)
        self.assertEqual(result["subject"], "Virgin Atlantic Airbus A350")
        self.assertEqual(result["link"], SOURCE)

    def test_no_story_title_filename_or_unrelated_caption_guess(self):
        for html in (
            '<h1>Airline cuts five routes</h1><img src="' + IMAGE + '" alt="Airline cuts five routes">',
            '<meta property="og:description" content="Airline cuts routes">',
            '<img src="https://images.example/other.jpg" alt="Airbus A350">',
            '<img src="' + IMAGE + '" alt="photo">',
            '<img src="' + IMAGE + '" alt="aircraft.jpg">',
        ):
            self.assertIsNone(captions.source_description(html, IMAGE, SOURCE))

    def test_figcaption_and_credit_only(self):
        html = '<figure><img src="' + IMAGE + '"><figcaption>Airbus A350 at Heathrow. Credit: Jane</figcaption></figure>'
        self.assertEqual(captions.source_description(html, IMAGE, SOURCE)["subject"],
                         "Airbus A350 at Heathrow.")
        self.assertIsNone(captions.source_description(
            html.replace("Airbus A350 at Heathrow. ", ""), IMAGE, SOURCE))

    def test_og_alt_requires_matching_image(self):
        html = '<meta property="og:image" content="' + IMAGE + '">' \
               '<meta property="og:image:alt" content="Boeing 777 freighter">'
        self.assertEqual(captions.source_description(html, IMAGE, SOURCE)["subject"],
                         "Boeing 777 freighter")
        self.assertIsNone(captions.source_description(html, IMAGE + "other", SOURCE))

    def test_generic_or_invalid_descriptions_are_not_publishable(self):
        for value in (None, {}, "資料照片", "123456", "Credit: Someone", "x" * 301):
            self.assertEqual(captions.clean_description(value), "")

    def test_build_legacy_cache_and_no_fake_event_claim(self):
        with patch.object(build, "IMAGE_CAPTIONS", {IMAGE: {
                "subject": "Virgin Atlantic Airbus A350", "link": SOURCE,
                "provider": "Simple Flying"}}):
            image = build.normalize_image(IMAGE)
            self.assertEqual(image["subject"], "Virgin Atlantic Airbus A350")
            self.assertEqual(image["kind"], "file_photo")
            self.assertEqual(image["link"], SOURCE)
            self.assertIn("圖中主體：Virgin Atlantic Airbus A350",
                          build._hero_image_caption(image, "zh"))
            self.assertIn("Pictured: Virgin Atlantic Airbus A350",
                          build._hero_image_caption(image, "en"))
            self.assertIn("非事件現場照片", build._hero_image_caption(image, "zh"))

    def test_uncaptioned_and_headline_copied_images_use_brand_fallback(self):
        with patch.object(build, "IMAGE_CAPTIONS", {}):
            self.assertIsNone(build.normalize_image(IMAGE))
            self.assertIsNone(build.normalize_image({"url": IMAGE, "subject": "資料照片"}))
            self.assertIsNone(build.normalize_image(
                {"url": IMAGE, "subject": "Airline cuts routes"}, ["Airline cuts routes"]))

    def test_explicit_description_preserves_attribution(self):
        raw = {"url": IMAGE, "subject": "Virgin Atlantic",
               "description": "Virgin Atlantic Airbus A350 at Heathrow",
               "credit": "Jane", "license": "CC BY 4.0", "kind": "airframe_photo"}
        normalized = build.normalize_image(raw)
        self.assertEqual(normalized["subject"], raw["description"])
        for key in ("credit", "license", "kind"):
            self.assertEqual(normalized[key], raw[key])

    def test_cache_retry_and_url_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            articles = root / "articles"
            articles.mkdir()
            now = captions.now_utc()
            path = articles / "one.json"
            row = {"id": "a", "publishedUtc": now.isoformat(), "image": IMAGE,
                   "sources": [{"url": SOURCE}], "zh": {"title": "航線調整"}}
            path.write_text(json.dumps({"articles": [row]}), encoding="utf-8")
            with patch.object(captions, "ARTICLES_DIR", articles), \
                 patch.object(captions, "CACHE_PATH", root / "captions.json"), \
                 patch.object(captions, "now_utc", return_value=now), \
                 patch.object(captions, "resolve_description", return_value=None) as resolve:
                captions.main()
                captions.main()
                self.assertEqual(resolve.call_count, 1)
                with patch.object(captions, "now_utc", return_value=now + timedelta(hours=7)):
                    captions.main()
                self.assertEqual(resolve.call_count, 2)
                row["image"] = IMAGE + "?different=1"
                path.write_text(json.dumps({"articles": [row]}), encoding="utf-8")
                captions.main()
                self.assertEqual(resolve.call_count, 3)

    def test_all_public_surfaces_and_manual_upload_have_description(self):
        for name in ("article", "home"):
            html = (ROOT / "templates" / f"{name}.html").read_text(encoding="utf-8")
            self.assertIn("data-image-description", html)
            self.assertIn("圖中主體：", html)
        script = (ROOT / "static" / "manual.js").read_text(encoding="utf-8")
        self.assertNotIn("subject: zh.title || en.title", script)
        self.assertNotIn("subject: article.zh.title || article.en.title", script)
        self.assertIn("subject: manualImageSubject()", script)
        for workflow in ("hourly", "manual-article-deploy"):
            text = (ROOT / ".github" / "workflows" / f"{workflow}.yml").read_text(encoding="utf-8")
            self.assertLess(text.index("python pipeline/image_captions.py"),
                            text.index("python pipeline/build.py"))


if __name__ == "__main__":
    unittest.main()
