"""Offline, import-safe tests for manufacturer sources and UI visibility.

Run from the repository root:

    python tests/test_manufacturer_sources.py
    python -m pytest -q tests/test_manufacturer_sources.py
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parent.parent
EXPECTED = {
    "airbus", "boeing", "embraer", "rollsroyce", "geaerospace",
    "prattwhitney", "iae", "cfm", "atr", "safran", "bombardier", "comac",
}
SOCIAL_HOSTS = {
    "x.com", "twitter.com", "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
}
OFFICIAL_HOSTS = {
    "airbus.com", "boeing.mediaroom.com", "embraer.com",
    "rolls-royce.com", "geaerospace.com", "prattwhitney.com",
    "cfmaeroengines.com", "atr-aircraft.com", "safran-group.com",
    "bombardier.com", "comac.cc",
}
AIRBUS_HTML = """
<article class="awx-card">
  <a href="/en/newsroom/press-releases/2026-07-example"
     title="Example release">
    <h3 class="awx-card__title">Example Airbus release</h3>
    <p class="awx-card__summary">Airbus announced a verifiable new update.</p>
    <time datetime="2026-07-28T08:00:00Z">28 July 2026</time>
    <img src="/media/example.jpg">
  </a>
</article>
<article class="awx-card">
  <a href="/en/newsroom/events/example">
    <h3 class="awx-card__title">Event card must not enter news</h3>
    <time datetime="2026-07-29T08:00:00Z">29 July 2026</time>
  </a>
</article>
"""


def _pipeline_modules():
    """Import lazily and restore the caller's search path immediately."""
    previous_path = sys.path[:]
    try:
        sys.path.insert(0, str(REPO / "pipeline"))
        return SimpleNamespace(**{
            name: importlib.import_module(name)
            for name in ("common", "fetch", "briefing", "build", "fulltext")
        })
    finally:
        sys.path[:] = previous_path


@contextmanager
def _isolated_source_data(modules):
    """Patch the names used by readers/writers, not just the environment.

    Other tests may already have imported common, fetch, or briefing with a
    different DATA_DIR. Changing AVWIRE_DATA_DIR cannot update those cached
    names. Restore all three bindings before deleting the temporary directory,
    including when a check raises. No process environment changes are needed.
    """
    with ExitStack() as stack:
        data_dir = Path(stack.enter_context(
            tempfile.TemporaryDirectory(prefix="avwire-manufacturers-")))
        for module in (modules.common, modules.fetch, modules.briefing):
            stack.enter_context(patch.object(module, "DATA_DIR", data_dir))
        yield data_dir


class ManufacturerSourceTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        # These tests must never make real HTTP or model requests.
        self.stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Network access is forbidden in these tests")))
        self.stack.enter_context(patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Network access is forbidden in these tests")))
        self.modules = _pipeline_modules()
        self.tmp = self.stack.enter_context(_isolated_source_data(self.modules))
        self.feeds = {
            row["key"]: row
            for row in self.modules.common.MANUFACTURER_SOURCE_CATALOG.get("feeds", [])
        }

    def source_rows(self):
        self.modules.fetch._write_sources({
            "airbus": "2026-07-28T08:00Z", "boeing": "2026-07-28T08:00Z",
        })
        return json.loads((self.tmp / "sources.json").read_text(encoding="utf-8"))

    def test_catalog_version(self):
        self.assertEqual(
            self.modules.common.MANUFACTURER_SOURCE_CATALOG.get("schemaVersion"), 1)

    def test_registered_manufacturers(self):
        self.assertEqual(EXPECTED, set(self.feeds))
        self.assertTrue(EXPECTED.issubset(self.modules.common.SOURCES))

    def test_airbus_and_boeing_are_public(self):
        for key in ("airbus", "boeing"):
            with self.subTest(key=key):
                self.assertIs(self.feeds[key].get("public"), True)

    def test_other_manufacturers_are_private(self):
        for key in EXPECTED - {"airbus", "boeing"}:
            with self.subTest(key=key):
                self.assertIs(self.feeds[key].get("public"), False)

    def test_feed_urls_use_https(self):
        for key, row in self.feeds.items():
            for field in ("url", "endpoint"):
                with self.subTest(key=key, field=field):
                    self.assertEqual(urlsplit(row[field]).scheme, "https")

    def test_social_accounts_are_metadata_only(self):
        rows = self.modules.common.MANUFACTURER_SOURCE_CATALOG.get("socialAccounts", [])
        self.assertTrue(rows)
        for row in rows:
            with self.subTest(url=row.get("url")):
                self.assertIs(row.get("crawl"), False)
                self.assertIn(urlsplit(row.get("url", "")).netloc.lower(), SOCIAL_HOSTS)

    def test_social_platforms_are_not_fetch_endpoints(self):
        for key, row in self.feeds.items():
            with self.subTest(key=key):
                self.assertNotIn(urlsplit(row["endpoint"]).netloc.lower(), SOCIAL_HOSTS)

    def test_social_platforms_are_not_fulltext_sources(self):
        self.assertTrue(self.modules.fulltext.ALLOWED_HOSTS.isdisjoint(SOCIAL_HOSTS))

    def test_airbus_parser_keeps_dated_news_not_events(self):
        from bs4 import BeautifulSoup
        parsed = self.modules.fetch._parse_airbus(
            BeautifulSoup(AIRBUS_HTML, "lxml"), self.feeds["airbus"]["endpoint"])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["title"], "Example Airbus release")
        self.assertTrue(parsed[0]["summary"].startswith("Airbus announced"))
        self.assertTrue(parsed[0]["url"].startswith("https://www.airbus.com/"))

    def test_source_status_persists_visibility(self):
        by_key = {row["key"]: row for row in self.source_rows()}
        self.assertIs(by_key["airbus"]["public"], True)
        self.assertIs(by_key["boeing"]["public"], True)
        self.assertIs(by_key["embraer"]["public"], False)

    def test_public_pages_show_airbus_and_boeing(self):
        rows = self.modules.build.merged_sources(self.source_rows())
        self.assertTrue({"airbus", "boeing"}.issubset({row["key"] for row in rows}))

    def test_public_pages_hide_other_manufacturers(self):
        rows = self.modules.build.merged_sources(self.source_rows())
        self.assertFalse((EXPECTED - {"airbus", "boeing"}) & {row["key"] for row in rows})

    def test_briefing_uses_the_same_visibility_rules(self):
        self.source_rows()
        rows, _warnings = self.modules.briefing.checked_sources_snapshot()
        names = {row["name"] for row in rows}
        self.assertIn(self.feeds["airbus"]["name"], names)
        self.assertIn(self.feeds["boeing"]["name"], names)
        self.assertNotIn(self.feeds["embraer"]["name"], names)

    def test_legacy_rows_without_public_remain_visible(self):
        rows = self.modules.build.merged_sources([{"key": "faa", "ok": True}])
        self.assertIn("faa", {row["key"] for row in rows})

    def test_official_hosts_allow_fulltext_enrichment(self):
        self.assertTrue(OFFICIAL_HOSTS.issubset(self.modules.fulltext.ALLOWED_HOSTS))

    def test_cached_data_directories_do_not_leak_between_tests(self):
        # Reproduce a previous test leaving already-imported modules pointed
        # at directories that no longer exist. Also use different cached
        # values to ensure neither the writer nor the reader is overlooked.
        modules = (self.modules.common, self.modules.fetch, self.modules.briefing)
        stale_paths = [self.tmp / f"deleted-previous-test-{index}" for index in range(3)]
        with ExitStack() as stale:
            for module, path in zip(modules, stale_paths):
                stale.enter_context(patch.object(module, "DATA_DIR", path))
            stale.enter_context(patch.dict(os.environ, {
                "AVWIRE_DATA_DIR": str(self.tmp / "different-environment-path"),
            }))
            original_env = dict(os.environ)
            with _isolated_source_data(self.modules) as fresh:
                self.modules.fetch._write_sources({"airbus": "2026-07-28T08:00Z"})
                self.assertTrue((fresh / "sources.json").is_file())
                rows, _warnings = self.modules.briefing.checked_sources_snapshot()
                self.assertIn(self.feeds["airbus"]["name"], {row["name"] for row in rows})
                self.assertEqual(dict(os.environ), original_env)
            self.assertFalse(fresh.exists())
            for module, path in zip(modules, stale_paths):
                self.assertEqual(module.DATA_DIR, path)
                self.assertFalse(path.exists())
        for module in modules:
            self.assertEqual(module.DATA_DIR, self.tmp)

    def test_isolation_restores_directories_after_an_exception(self):
        modules = (self.modules.common, self.modules.fetch, self.modules.briefing)
        before = [module.DATA_DIR for module in modules]
        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            with _isolated_source_data(self.modules) as fresh:
                (fresh / "marker.txt").write_text("test only", encoding="utf-8")
                raise RuntimeError("simulated failure")
        self.assertFalse(fresh.exists())
        self.assertEqual([module.DATA_DIR for module in modules], before)

    def test_import_has_no_pipeline_or_process_side_effects(self):
        before_env, before_path = dict(os.environ), sys.path[:]
        output = io.StringIO()
        spec = importlib.util.spec_from_file_location("manufacturer_import_probe", __file__)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        with patch("tempfile.mkdtemp", side_effect=AssertionError("import created temp data")), \
                patch("importlib.import_module", side_effect=AssertionError("import loaded pipeline")), \
                redirect_stdout(output):
            spec.loader.exec_module(module)
        self.assertEqual(dict(os.environ), before_env)
        self.assertEqual(sys.path, before_path)
        self.assertEqual(output.getvalue(), "")
        self.assertTrue(issubclass(module.ManufacturerSourceTests, unittest.TestCase))


if __name__ == "__main__":
    unittest.main(verbosity=2)
