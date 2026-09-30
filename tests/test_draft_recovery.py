"""Offline regression tests: presentation recovery never rewrites evidence."""
import sys
import unittest
import json
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from draft_recovery import normalize_reader_copy, repair_prompt
import common
import dedupe


class Converter:
    def convert(self, value):
        return value.translate(str.maketrans("国飞机", "國飛機"))


class RecoveryTests(unittest.TestCase):
    def test_conversion_preserves_verbatim_evidence_and_input(self):
        source = {"zh": {"title": "中国飞机", "summary": "飞机", "body": ["中国"]},
                  "en": {"title": "China aircraft"}, "flash": {"zh": "飞机"},
                  "incident": {"desc": {"zh": "中国"}},
                  "facts": [{"sourceQuote": "中国飞机", "claim": "中国"}],
                  "entityEvidence": [{"sourceQuote": "中国"}],
                  "entities": {"airlines": ["中国"]}}
        result = normalize_reader_copy(source, Converter())
        self.assertEqual(result["zh"]["title"], "中國飛機")
        self.assertEqual(result["flash"]["zh"], "飛機")
        self.assertEqual(result["incident"]["desc"]["zh"], "中國")
        for key in ("facts", "entityEvidence", "entities", "en"):
            self.assertEqual(result[key], source[key])
        self.assertEqual(source["zh"]["title"], "中国飞机")

    def test_malformed_shapes_remain_for_validator(self):
        self.assertEqual(normalize_reader_copy({"zh": "bad"}, Converter()), {"zh": "bad"})
        self.assertEqual(normalize_reader_copy({"zh": {"body": [123]}}, Converter()),
                         {"zh": {"body": [123]}})
        self.assertIsNone(normalize_reader_copy(None, Converter()))

    def test_retry_keeps_sources_and_feedback_without_padding_permission(self):
        prompt = repair_prompt("SOURCE: unchanged verbatim material", "en.summary missing")
        self.assertTrue(prompt.startswith("SOURCE: unchanged verbatim material"))
        self.assertIn("en.summary missing", prompt)
        self.assertIn("preserve verbatim source quotes", prompt)
        self.assertIn("Do not add facts", prompt)

    def test_recovery_expiry_original_dates_and_seen_gate(self):
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        old = {"title": "STARLUX launches American Airlines codeshare", "url": "https://example.com/news",
               "publishedUtc": "2026-09-23T00:00Z", "source": "Publisher", "sourceKey": "publisher"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "news-recovery.json"
            path.write_text(json.dumps({"expiresUtc": "2026-10-07T00:00Z", "items": [old]}))
            with patch.object(dedupe, "DATA_DIR", root), patch.object(dedupe, "RAW_DIR", root / "raw"), patch.object(dedupe, "now_utc", lambda: now):
                rows = dedupe._load_raw_items()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["publishedUtc"], old["publishedUtc"])
                stats = {key: 0 for key in ("skipped_untitled", "skipped_too_old", "skipped_future_date")}
                self.assertTrue(dedupe._is_fresh(rows[0], now, stats))
                self.assertFalse(dedupe._is_unseen(rows[0], {common.norm_url(old["url"])}, [])[0])
                future = {**rows[0], "publishedUtc": "2026-11-01T00:00Z"}
                self.assertFalse(dedupe._is_fresh(future, now, stats))
                path.write_text(json.dumps({"expiresUtc": "2026-09-29T00:00Z", "items": [old]}))
                self.assertEqual(dedupe._load_raw_items(), [])
                self.assertFalse(dedupe._is_fresh(rows[0], now + timedelta(days=8), stats))

    def test_safety_findings_and_codeshare_are_retained_before_enrichment(self):
        for title in (
            "Vietnam Airlines Munich runway incident: Investigation reveals brakes activated during takeoff roll",
            "American Airlines and STARLUX Airlines launch codeshare partnership",
        ):
            self.assertTrue(common.is_major_event_story(
                {"title": title, "sourceKey": "aerospaceglobalnews", "summary": ""}))
        self.assertFalse(common.is_major_event_story(
            {"title": "How codeshare flights work", "sourceKey": "aerospaceglobalnews"}))
        self.assertFalse(common.is_major_event_story(
            {"title": "Police investigation into a road accident", "sourceKey": "aerospaceglobalnews"}))
        self.assertFalse(common.is_major_event_story(
            {"title": "Vietnam Airlines runway accident interim report", "sourceKey": "unknown"}))


if __name__ == "__main__":
    unittest.main()
