"""Private route generation never embeds the ADMIN_KEY or changes public pages."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from admin_page import render_admin_page, editorial_article, override_path


class AdminPageTests(unittest.TestCase):
    def test_private_route_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            site, articles = Path(tmp) / "site", Path(tmp) / "articles"
            site.mkdir()
            articles.mkdir()
            public = site / "index.html"
            public.write_text("public site stays intact")
            (articles / "batch.json").write_text(json.dumps({"articles": [
                {"id": "a-manual-example", "zh": {"title": "測試"}},
            ]}))
            env = Environment(loader=FileSystemLoader(ROOT / "templates"),
                              undefined=StrictUndefined, autoescape=True)
            key = "test-admin-key-not-a-real-secret-123456789"
            with patch.dict(os.environ, {"ADMIN_KEY": ""}):
                self.assertEqual(render_admin_page(env, site, articles, "/SKYTICAL"), 0)
            self.assertFalse((site / "admin").exists())
            with patch.dict(os.environ, {"ADMIN_KEY": key}):
                self.assertEqual(render_admin_page(env, site, articles, "/SKYTICAL"), 2)
            slug = hashlib.sha256(key.encode()).hexdigest()
            folder = site / "admin" / slug
            manifest = json.loads((folder / "articles.json").read_text())
            self.assertEqual(manifest["a-example"], {
                "id": "a-manual-example", "path": "data/articles/batch.json",
                "overridePath": "data/" + override_path("a-manual-example")})
            html = (folder / "index.html").read_text()
            self.assertIn('data-base="/SKYTICAL"', html)
            self.assertIn('admin-activate.js', html)
            self.assertNotIn('<iframe', html)
            self.assertIn('noindex,nofollow,noarchive', html)
            self.assertIn('no-referrer', html)
            self.assertEqual(public.read_text(), "public site stays intact")
            for path in site.rglob("*"):
                self.assertNotIn(key, str(path))
                if path.is_file():
                    self.assertNotIn(key, path.read_text())

    def test_short_key_does_not_generate_editor(self):
        with patch.dict(os.environ, {"ADMIN_KEY": "short"}):
            self.assertEqual(render_admin_page(None, Path("unused"), Path("unused"), ""), 0)

    def test_editorial_record_survives_stale_bot_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            stale = {"id": "a-test", "zh": {"title": "舊自動稿"}}
            self.assertEqual(editorial_article(stale, data), stale)
            edited = {**stale, "zh": {"title": "人工修訂"}, "editorialLocked": True}
            path = data / override_path(stale["id"])
            path.parent.mkdir()
            path.write_text(json.dumps(edited))
            self.assertEqual(editorial_article(stale, data), edited)
            path.write_text(json.dumps({"id": "a-wrong"}))
            with self.assertRaises(ValueError):
                editorial_article(stale, data)

    def test_manual_image_and_removal_survive_automatic_photo_steps(self):
        import images
        import image_fallbacks
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            path = directory / "batch.json"
            stamp = datetime.now(timezone.utc).isoformat()
            payload = {"articles": [
                {"id": "a-no-photo", "publishedUtc": stamp,
                 "editorialImageLocked": True, "image": None},
                {"id": "a-photo", "publishedUtc": stamp,
                 "editorialImageLocked": True,
                 "image": {"url": "https://example.com/photo.jpg", "subject": "人工配圖"}},
            ]}
            path.write_text(json.dumps(payload))
            with patch.object(images, "ARTICLES_DIR", directory), \
                    patch.object(images, "CACHE_PATH", directory / "cache.json"), \
                    patch.object(images, "resolve_image", side_effect=AssertionError("must not fetch")):
                self.assertEqual(images.main(), 0)
            with patch.object(image_fallbacks, "ARTICLES_DIR", directory), \
                    patch.object(image_fallbacks, "topic_image", side_effect=AssertionError("must not replace")):
                self.assertEqual(image_fallbacks.main(), 0)
            self.assertEqual(json.loads(path.read_text()), payload)


if __name__ == "__main__":
    unittest.main()
