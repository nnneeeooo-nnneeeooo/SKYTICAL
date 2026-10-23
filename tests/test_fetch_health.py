"""Offline regression tests for safety discovery and empty-source warnings."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from jinja2 import DictLoader, Environment

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
import common
import dedupe
import fetch
import fulltext


def response(status=200, text="", location=None):
    return SimpleNamespace(status_code=status, text=text,
                           headers={"Location": location} if location else {})


class DiscoveryTests(unittest.TestCase):
    def test_publisher_survives_snapshot_and_dedupe_loading(self):
        stamp = datetime(2026, 10, 23, tzinfo=timezone.utc)
        raw = fetch._finalize([{
            "title": "中部空港 貨物機から炎", "published": stamp,
            "url": "https://www.chunichi.co.jp/article/123",
            "publisher": "中日新聞Web",
        }], "2026-10-23T00:00Z", None)
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            common.save_json(directory / "japansafety.json", {"items": raw})
            with patch.object(dedupe, "RAW_DIR", directory), \
                    patch.object(dedupe, "DATA_DIR", directory), \
                    patch.object(dedupe, "SOURCES", {
                        "japansafety": common.SOURCES["japansafety"]}):
                items = dedupe._load_raw_items()
        self.assertEqual(items[0]["source"], "中日新聞Web")

    def test_japanese_safety_headlines_and_attribution(self):
        source = common.SOURCES["japansafety"]
        query = parse_qs(urlsplit(source["endpoint"]).query)
        self.assertEqual(query["ceid"], ["JP:ja"])
        self.assertIn("緊急着陸", query["q"][0])
        self.assertTrue(source["scope_filter"])
        for title in ("中部空港 着陸した貨物機から炎 滑走路を一時閉鎖",
                      "ヘリコプターが緊急着陸", "旅客機が胴体着陸"):
            self.assertTrue(common.is_transport_headline({"title": title}))
        self.assertFalse(common.is_transport_headline({
            "title": "名古屋市の住宅で火災", "summary": "空港の近く。"}))
        self.assertEqual(dedupe._source_label(source, {"publisher": "中日新聞Web"}),
                         "中日新聞Web")
        self.assertNotIn("www.chunichi.co.jp", fulltext.ALLOWED_HOSTS)
        self.assertNotIn("news.google.com", fulltext.ALLOWED_HOSTS)

    def test_member_only_publisher_cannot_supply_unrelated_fulltext(self):
        with patch.object(fulltext.requests, "get") as request:
            self.assertIsNone(fulltext.fetch_fulltext(
                "https://www.chunichi.co.jp/article/1328893"))
            request.assert_not_called()

    def test_signed_resolution_after_internal_redirect(self):
        session = Mock()
        session.get.side_effect = [
            response(302, location="https://news.google.com/rss/articles/id?hl=ja"),
            response(text='<div data-n-a-id="id" data-n-a-ts="123" '
                          'data-n-a-sg="signature"></div>'),
        ]
        session.post.return_value = response(text=
            ")]}'\n\n123\n" + json.dumps([[
                "wrb.fr", "Fbv4je", json.dumps([
                    "garturlres", "https://www.chunichi.co.jp/article/123"])
            ]]) + "\n")
        self.assertEqual(fetch._resolve_gnews_link(
            session, "https://news.google.com/rss/articles/id"),
            "https://www.chunichi.co.jp/article/123")
        self.assertFalse(session.post.call_args.kwargs["allow_redirects"])
        payload = json.loads(session.post.call_args.kwargs["data"]["f.req"])
        self.assertEqual(json.loads(payload[0][0][1])[-3:],
                         ["id", 123, "signature"])

    def test_failed_or_unsafe_resolution_never_enters_raw_items(self):
        for target in ("https://news.google.com/read/id", "javascript:alert(1)"):
            session = Mock()
            session.get.return_value = response(
                text='<div data-n-a-id="id" data-n-a-ts="123" '
                     'data-n-a-sg="sig"></div>')
            session.post.return_value = response(text=json.dumps([[
                "wrb.fr", "Fbv4je", json.dumps(["garturlres", target])]]))
            self.assertEqual(fetch._rss_items(session, "japansafety", [{
                "title": "中部空港 貨物機から炎", "link":
                "https://news.google.com/rss/articles/id"}],
                common.SOURCES["japansafety"]["endpoint"]), [])

    def test_redirect_loop_and_malformed_rpc_are_bounded(self):
        session = Mock()
        session.get.return_value = response(
            302, location="https://news.google.com/rss/articles/id")
        self.assertIsNone(fetch._resolve_gnews_link(
            session, "https://news.google.com/rss/articles/id"))
        self.assertEqual(session.get.call_count, 3)
        session.get.return_value = response(
            text='<div data-n-a-id="id" data-n-a-ts="123" data-n-a-sg="s"></div>')
        session.post.return_value = response(text="[[broken")
        self.assertIsNone(fetch._resolve_gnews_link(
            session, "https://news.google.com/rss/articles/id"))


class SourceHealthTests(unittest.TestCase):
    def test_empty_snapshot_is_reparsed_instead_of_cached_304(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "avherald.json").write_text('{"items": []}')
            url = common.SOURCES["avherald"]["endpoint"]
            cache = {"avherald": {"url": url, "etag": "old"}}
            with patch.object(fetch, "RAW_DIR", directory), \
                    patch.object(fetch, "_request", return_value=response()) as request:
                fetch._conditional_get(object(), "avherald", url, cache)
                self.assertEqual(request.call_args.args[2], {})

    def test_legacy_discovery_snapshot_refreshes_missing_publisher(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "japansafety.json").write_text('{"items": [{"title": "old"}]}')
            url = common.SOURCES["japansafety"]["endpoint"]
            cache = {"japansafety": {"url": url, "etag": "old"}}
            with patch.object(fetch, "RAW_DIR", directory), \
                    patch.object(fetch, "_request", return_value=response()) as request:
                fetch._conditional_get(object(), "japansafety", url, cache)
                self.assertEqual(request.call_args.args[2], {})

    def test_empty_streak_warning_recovery_and_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            raw = directory / "raw"
            raw.mkdir()
            with patch.object(fetch, "DATA_DIR", directory), \
                    patch.object(fetch, "RAW_DIR", raw), \
                    patch.object(fetch, "SOURCES", {"aerotime": common.SOURCES["aerotime"]}):
                def run(stamp, items, success=True):
                    (raw / "aerotime.json").write_text(json.dumps({"items": items}))
                    stream = io.StringIO()
                    with contextlib.redirect_stdout(stream):
                        fetch._write_sources({"aerotime": stamp if success else None})
                    row = json.loads((directory / "sources.json").read_text(encoding="utf-8"))
                    return row[0], stream.getvalue()

                for n in range(1, 4):
                    row, log = run(f"2026-10-23T0{n}:00Z", [])
                    self.assertEqual(row["emptyRuns"], n)
                    self.assertEqual(row["emptyWarning"], n == 3)
                    self.assertEqual("::warning" in log, n == 3)
                    self.assertTrue(row["ok"])
                merged = build.merged_sources([row])
                env = Environment(loader=DictLoader({
                    "base.html": "{% block content %}{% endblock %}",
                    "sources.html": (ROOT / "templates/sources.html").read_text(encoding="utf-8"),
                }), autoescape=True)
                for language, expected in [("zh", "連續 3 次"), ("en", "3 consecutive")]:
                    view = build.sources_rows_view(
                        merged, language, datetime.now(timezone.utc))
                    alert = next(s for s in view if s["name"] == "AeroTime")
                    self.assertTrue(alert["emptyWarning"])
                    rendered = env.get_template("sources.html").render(rows=[alert], t={})
                    self.assertIn(expected, rendered)
                    self.assertNotIn(">OK</span>", rendered)

                row, _ = run("2026-10-23T04:00Z", [{"title": "Aircraft update"}])
                self.assertEqual(row["emptyRuns"], 0)
                self.assertFalse(row["emptyWarning"])
                self.assertEqual(row["lastNonEmptyUtc"], "2026-10-23T04:00Z")
                row, _ = run("2026-10-23T05:00Z", [], success=False)
                self.assertFalse(row["ok"])
                self.assertIsNone(row["itemCount"])
                self.assertEqual(row["emptyRuns"], 0)
                self.assertEqual(row["lastFetchUtc"], "2026-10-23T04:00Z")

    def test_low_cadence_official_sources_do_not_warn(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "faa.json").write_text('{"items": []}')
            with patch.object(fetch, "DATA_DIR", directory), \
                    patch.object(fetch, "RAW_DIR", directory), \
                    patch.object(fetch, "SOURCES", {"faa": common.SOURCES["faa"]}):
                for _ in range(4):
                    fetch._write_sources({"faa": "2026-10-23T01:00Z"})
                row = json.loads((directory / "sources.json").read_text(encoding="utf-8"))[0]
                self.assertFalse(row["emptyWarning"])


if __name__ == "__main__":
    unittest.main()
