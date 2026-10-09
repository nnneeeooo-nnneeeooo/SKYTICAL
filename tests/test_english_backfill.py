"""Guard translated publication routes, image provenance and language chrome."""
import copy
import json
from pathlib import Path
import re
import sys
import unittest

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build


class EnglishBackfillTests(unittest.TestCase):
    def test_previously_chinese_only_articles_are_complete(self):
        expected = {
            "manual-45737aa09878f61b1b9696d0ab536074.json": {
                "a-20260730-1856-manual-45737a": ["NT$10 million", "7.1"]},
            "manual-tigerair-b50031-20260930.json": {
                "a-20260930-0850-manual-tigerair-b50031": ["13167", "F-WWDG", "TTW31", "180"]},
            "manual-starlux-b58310-20261001.json": {
                "a-20261001-manual-starlux-b58310": ["2135", "F-WWYL", "297", "269"],
                "a-20261004-1221-manual-klm-a350-ph-zna": ["PH-ZNA", "331", "34", "26", "271", "25%", "40%"]},
        }
        for filename, ids in expected.items():
            rows = json.loads((ROOT / "data/articles" / filename).read_text(encoding="utf-8"))["articles"]
            for article_id, facts in ids.items():
                article = next(row for row in rows if row["id"] == article_id)
                english = article["en"]
                self.assertEqual(article["availableLanguages"], ["zh", "en"])
                self.assertTrue(english["title"] and english["summary"])
                self.assertEqual(len(english["body"]), len(article["zh"]["body"]))
                text = " ".join([english["title"], english["summary"], *english["body"]])
                self.assertIsNone(re.search(r"[\u3400-\u9fff]", text))
                for fact in facts:
                    self.assertIn(fact, text)
                prepared = build.prep_article(article)
                self.assertIn("en", prepared["available_languages"])
                self.assertEqual(build.art_view(prepared, "en")["title"], english["title"])

    def test_caption_translation_preserves_provenance_and_chinese(self):
        image = {"subject": "臺北松山機場", "credit": "長榮航空提供",
                 "url": "https://example.com/photo.jpg", "link": "https://example.com/source",
                 "license": "CC BY 4.0", "kind": "file_photo", "provider": "Example"}
        original = copy.deepcopy(image)
        translated = build.localized_image(image, "en")
        self.assertEqual(translated["subject"], "Taipei Songshan Airport")
        self.assertEqual(translated["credit"], "Courtesy of EVA Air")
        self.assertEqual(image, original)
        self.assertEqual(build.localized_image(image, "zh"), original)
        for key in ("url", "link", "license", "kind", "provider"):
            self.assertEqual(translated[key], original[key])
        self.assertEqual(build.localized_label("註冊號 B-17812", "en"), "Registration B-17812")
        self.assertEqual(build.localized_label("Unknown photographer", "en"), "Unknown photographer")
        self.assertEqual(build.localized_label("玄史生", "en"), "玄史生")
        self.assertIsNone(build.localized_image(None, "en"))

    def test_english_error_page_and_briefing_accessibility(self):
        env = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=True)
        template = env.get_template("404.html")
        english = template.blocks["content"](template.new_context({"lang": "en", "home_url": "/en/"}))
        text = "".join(english)
        self.assertIn("Page not found", text)
        self.assertIn('href="/en/"', text)
        self.assertIsNone(re.search(r"[\u3400-\u9fff]", text))
        report = env.get_template("_briefing_report.html").render(
            lang="en", base="", fallback_image_url="/fallback.png",
            t=build.L["en"], b={"date_iso": "2026-10-01", "title": "Afternoon Briefing",
                "window_start": "Sep 30", "window_end": "Oct 1", "cutoff": "3 PM",
                "total": 1, "partial": False, "sections": [{"label": "Taiwan Aviation", "items": [{
                    "headline": "Delivery flight", "summary": "The aircraft departed Toulouse.",
                    "url": "/en/news/test/", "keyword": "Delivery"}]}]})
        self.assertIn('aria-label="Read the article: Delivery flight"', report)
        self.assertNotIn("閱讀本站原文", report)


if __name__ == "__main__":
    unittest.main()
