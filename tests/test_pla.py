"""Isolated offline tests for PLA-activity comparison context.

Run from the repository root with either runner:

    python tests/test_pla.py
    python -m pytest -q tests/test_pla.py

Importing this module only defines tests; it never writes fixture data or
changes the pipeline's environment. All dates and counts below are fixtures.
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
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent

CNA_TEXT = ("國防部今天發布共機艦動態，統計自昨天上午6時起至今天上午6時止。"
            "偵獲7艘共艦、3艘公務船及4架次共機，持續在台海周邊活動。"
            "期間並無共機逾越台灣海峽中線。")
MND_TEXT = "偵獲中共軍機12架次、軍艦9艘及公務船2艘，其中5架次逾越海峽中線。"
DAY = "2026-07-27"
NOW = datetime(2026, 7, 27, 0, 30, tzinfo=timezone.utc)
HISTORY = (
    ("2026-06-27", 20, 8), ("2026-07-20", 6, 5), ("2026-07-21", 9, 6),
    ("2026-07-22", 30, 12), ("2026-07-23", 8, 7), ("2026-07-24", 10, 6),
    ("2026-07-25", 7, 5), ("2026-07-26", 5, 7),
)


@contextmanager
def _isolated_series(pla):
    """Patch the actual cached read/write path, then restore it on every exit."""
    with ExitStack() as stack:
        directory = stack.enter_context(
            tempfile.TemporaryDirectory(prefix="skytical-pla-test-"))
        root = Path(directory)
        stack.enter_context(patch.object(pla, "DATA_DIR", root))
        stack.enter_context(patch.object(pla, "SERIES_PATH",
                                        root / "pla_activity.json"))
        yield root


class PLASeriesTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        # No live requests or provider calls belong in these offline tests.
        for target in ("requests.sessions.Session.request",
                       "urllib.request.urlopen",
                       "socket.create_connection"):
            stack.enter_context(patch(
                target, side_effect=AssertionError("unexpected network call")))
        # Import only while running a test, and restore sys.path afterwards.
        # Do not reload cached modules or rewrite AVWIRE_DATA_DIR: other tests
        # may own those values. SERIES_PATH must be patched directly instead.
        with patch.object(sys, "path", [str(REPO / "pipeline"), *sys.path]):
            self.pla = importlib.import_module("pla_series")
            self.writer = importlib.import_module("write")
        self.root = stack.enter_context(_isolated_series(self.pla))
        self.series_path = self.root / "pla_activity.json"

    def _stats(self):
        return {"aircraft": 4, "ships": 7, "official": 3,
                "medianNote": "未逾越海峽中線"}

    def _seed_history(self):
        self.pla.record(DAY, self._stats())
        for day, aircraft, ships in HISTORY:
            self.pla.record(day, {"aircraft": aircraft, "ships": ships,
                                  "official": 3})

    def _group(self):
        return {"id": "g1", "items": [{
            "title": "國防部公布共機艦動態", "summary": CNA_TEXT,
            "url": "https://www.cna.com.tw/x", "source": "CNA",
            "publishedUtc": "2026-07-27T00:10Z"}]}

    def _enriched_group(self):
        self._seed_history()
        group = self._group()
        self.assertEqual(self.pla.enrich_groups([group], NOW), 1)
        return group

    # Preserve all 16 original checks as individually discoverable tests.
    def test_number_first_wording_extracts_counts_and_no_crossing_note(self):
        self.assertEqual(self.pla.extract_stats(CNA_TEXT), self._stats())

    def test_noun_first_wording_extracts_counts_and_crossing_note(self):
        self.assertEqual(self.pla.extract_stats(MND_TEXT), {
            "aircraft": 12, "ships": 9, "official": 2,
            "medianNote": "有逾越中線相關敘述"})

    def test_non_pla_text_returns_none(self):
        self.assertIsNone(self.pla.extract_stats("民航局公布中秋加班機 1340 架次"))

    def test_first_record_writes(self):
        self.assertIs(self.pla.record(DAY, self._stats()), True)
        saved = json.loads(self.series_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["days"][DAY], self._stats())

    def test_identical_record_is_idempotent(self):
        self.assertIs(self.pla.record(DAY, self._stats()), True)
        before = self.series_path.read_bytes()
        self.assertIs(self.pla.record(DAY, self._stats()), False)
        self.assertEqual(self.series_path.read_bytes(), before)

    def test_context_cites_previous_record(self):
        self._seed_history()
        block = self.pla.context_block(DAY)
        self.assertIn("前一次紀錄（7 月 26 日）", block)
        self.assertIn("共機 5 架次", block)

    def test_context_carries_seven_and_thirty_day_averages(self):
        self._seed_history()
        block = self.pla.context_block(DAY)
        self.assertIn("近 7 日", block)
        self.assertIn("近 30 日", block)

    def test_context_names_thirty_day_peak_and_date(self):
        self._seed_history()
        self.assertIn("共機 30 架次（7 月 22 日）", self.pla.context_block(DAY))

    def test_context_includes_recorded_month_comparison(self):
        self._seed_history()
        block = self.pla.context_block(DAY)
        self.assertIn("上月同期（6 月 27 日）", block)
        self.assertIn("共機 20 架次", block)

    def test_context_excludes_current_day(self):
        self._seed_history()
        block = self.pla.context_block(DAY)
        self.assertNotIn("7 月 27 日）", block.replace("上月同期", ""))

    def test_empty_history_is_not_invented(self):
        self.assertIn("尚無更早", self.pla.context_block("2020-01-01"))

    def test_group_gains_database_context(self):
        group = self._enriched_group()
        self.assertEqual(group["items"][-1]["source"], "SKYTICAL 資料庫")
        self.assertIn("近 30 日", group["items"][-1]["summary"])

    def test_reenrichment_is_skipped(self):
        group = self._enriched_group()
        before = deepcopy(group)
        self.assertEqual(self.pla.enrich_groups([group], NOW), 0)
        self.assertEqual(group, before)

    def test_non_pla_groups_remain_untouched(self):
        groups = [{"id": "g2", "items": [{
            "title": "航線新聞", "summary": "航空公司開新航線"}]}]
        before = deepcopy(groups)
        self.assertEqual(self.pla.enrich_groups(groups, NOW), 0)
        self.assertEqual(groups, before)
        self.assertFalse(self.series_path.exists())

    def test_database_quote_is_machine_verifiable(self):
        group = self._enriched_group()
        draft = {"facts": [{
            "factId": "F1", "claim": "30-day peak was 30 sorties",
            "sourceQuote": "近 30 日單日最高：共機 30 架次（7 月 22 日）"}]}
        self.assertEqual(len(self.writer.verify_facts(draft, group, "test")), 1)

    def test_database_item_is_not_a_footer_source(self):
        group = self._enriched_group()
        sources = self.writer.build_sources(group["items"])
        self.assertTrue(sources)
        self.assertTrue(all("SKYTICAL" not in row["name"] for row in sources))

    # Regression coverage for the old import-time and cached-path behavior.
    def test_cached_deleted_series_path_is_isolated_and_restored(self):
        with tempfile.TemporaryDirectory(prefix="skytical-pla-stale-") as name:
            stale_root = Path(name)
        stale_path = stale_root / "pla_activity.json"
        self.assertFalse(stale_root.exists())
        with patch.object(self.pla, "DATA_DIR", stale_root), \
                patch.object(self.pla, "SERIES_PATH", stale_path):
            with _isolated_series(self.pla) as root:
                self.assertIs(self.pla.record(DAY, self._stats()), True)
                self.assertTrue((root / "pla_activity.json").is_file())
                self.assertFalse(stale_root.exists())
            self.assertFalse(root.exists())
            self.assertIs(self.pla.DATA_DIR, stale_root)
            self.assertIs(self.pla.SERIES_PATH, stale_path)
        self.assertFalse(stale_root.exists())
        self.assertFalse(self.series_path.exists())

    def test_isolation_restores_paths_and_cleans_up_after_exception(self):
        original_data = self.pla.DATA_DIR
        original_series = self.pla.SERIES_PATH
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with _isolated_series(self.pla) as root:
                self.pla.record(DAY, self._stats())
                raise RuntimeError("fixture failure")
        self.assertIs(self.pla.DATA_DIR, original_data)
        self.assertIs(self.pla.SERIES_PATH, original_series)
        self.assertFalse(root.exists())
        self.assertFalse(self.series_path.exists())

    def test_import_has_no_data_environment_or_process_side_effects(self):
        spec = importlib.util.spec_from_file_location(
            "_pla_import_probe", Path(__file__))
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        environment = dict(os.environ)
        search_path = list(sys.path)
        original_series = self.pla.SERIES_PATH
        output = io.StringIO()
        with ExitStack() as stack:
            for target in ("tempfile.mkdtemp", "tempfile.TemporaryDirectory"):
                stack.enter_context(patch(
                    target, side_effect=AssertionError("fixture created on import")))
            stack.enter_context(patch.object(
                self.pla, "record",
                side_effect=AssertionError("record written on import")))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(output))
            spec.loader.exec_module(module)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual(sys.path, search_path)
        self.assertIs(self.pla.SERIES_PATH, original_series)
        self.assertFalse(self.series_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
