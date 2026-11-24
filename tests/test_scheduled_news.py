"""Publication failures that must be caught before deploying scheduled news."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from scheduled_news import validate_article, validate_chronology, validate_directory

NOW = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)


def article():
    return {
        "id": "a-20261001-test", "publishedUtc": "2026-10-01T07:00:00Z",
        "sourcePublishedUtc": "2026-09-30T00:00:00Z", "cat": "biz",
        "availableLanguages": ["zh", "en"], "primarySource": "Airbus",
        "writer": "scheduled:GPT", "writerModels": ["GPT"],
        "sources": [{"name": "Airbus", "url": "https://www.airbus.com/news"}],
        "zh": {"title": "航空新聞", "summary": "已查證。", "body": ["段落一。", "段落二。"]},
        "en": {"title": "News", "summary": "Verified.", "body": ["One.", "Two."]},
        "scheduledNews": {"version": 1, "eventKey": "airbus-test-event",
                          "checkedUtc": "2026-10-01T06:59:00Z",
                          "facts": [{"claim": "Verified fact", "sourceUrl": "https://www.airbus.com/news"}]},
    }


class ScheduledNewsTest(unittest.TestCase):
    def test_manual_chronology_distinguishes_dates_and_keeps_image_times(self):
        previous = article() | {
            "sortUtc": "2026-09-30T00:00:00Z",
            "sourceDateOnly": True,
            "sortDateOnly": True,
        }
        validate_chronology(previous, manual=True, now=NOW)
        for key in ("sortUtc", "sourceDateOnly", "sortDateOnly"):
            with self.assertRaisesRegex(ValueError, key):
                validate_chronology(
                    {name: value for name, value in previous.items() if name != key},
                    manual=True, now=NOW,
                )
        with self.assertRaisesRegex(ValueError, "sortUtc"):
            validate_chronology(
                previous | {"sortUtc": "2026-10-01T07:01:00Z"}, manual=True, now=NOW)
        image_only = previous | {"image": {"url": "https://example.test/new.jpg"}}
        validate_chronology(image_only, previous, manual=True, now=NOW)
        for change in (
            {"publishedUtc": "2026-10-01T07:05:00Z"},
            {"sortUtc": "2026-10-01T00:00:00Z"},
            {"sortDateOnly": False},
            {"updatedUtc": "2026-10-01T07:59:00Z"},
            {"scheduledNews": {**previous["scheduledNews"], "checkedUtc": "2026-10-01T07:01:00Z"}},
        ):
            with self.assertRaisesRegex(ValueError, "image-only"):
                validate_chronology(image_only | change, previous, manual=True, now=NOW)
        followup = previous | {
            "zh": {**previous["zh"], "body": ["更新後正文。"]},
            "updatedUtc": "2026-10-01T07:59:00Z",
            "sourcePublishedUtc": "2026-10-01T07:40:00Z",
            "sourceDateOnly": False,
        }
        validate_chronology(followup, previous, manual=True, now=NOW)
        with self.assertRaisesRegex(ValueError, "content updates"):
            validate_chronology(followup | {"sortUtc": "2026-10-01T00:00:00Z"},
                                previous, manual=True, now=NOW)

    def test_valid_article(self):
        validate_article(article(), NOW)

    def test_missing_language_or_original_source(self):
        for change in ({"en": {}}, {"availableLanguages": ["zh"]},
                       {"sources": []}, {"writerModels": []}):
            row = article()
            row.update(change)
            with self.assertRaises(ValueError):
                validate_article(row, NOW)

    def test_unsafe_source_and_unbound_facts(self):
        for url in ("javascript:alert(1)", "https://news.google.com/articles/a", "https://user:password@example.com/a"):
            row = article()
            row["sources"][0]["url"] = url
            with self.assertRaises(ValueError):
                validate_article(row, NOW)
        row = article()
        row["scheduledNews"]["facts"][0]["sourceUrl"] = "https://other.example/a"
        with self.assertRaises(ValueError):
            validate_article(row, NOW)

    def test_future_and_naive_dates(self):
        for date in ("2026-10-02T00:00:00Z", "2026-10-01T07:00:00"):
            row = article()
            row["publishedUtc"] = date
            with self.assertRaises(ValueError):
                validate_article(row, NOW)

    def test_follow_up_sources_bounded_by_update_time(self):
        row = article()
        row["sourcePublishedUtc"] = "2026-10-01T07:30:00Z"
        row["scheduledNews"]["checkedUtc"] = "2026-10-01T07:40:00Z"
        with self.assertRaises(ValueError):
            validate_article(row, NOW)
        row["updatedUtc"] = "2026-10-01T07:40:00Z"
        validate_article(row, NOW)
        for change in ({"sourcePublishedUtc": "2026-10-01T07:41:00Z"},
                       {"updatedUtc": "2026-10-01T09:00:00Z"},
                       {"updatedUtc": "2026-10-01T07:40:00"},
                       {"updatedUtc": "2026-09-30T00:00:00Z"}):
            with self.assertRaises(ValueError):
                validate_article(row | change, NOW)
        row["scheduledNews"]["checkedUtc"] = "2026-10-01T07:46:00Z"
        with self.assertRaises(ValueError):
            validate_article(row, NOW)

    def test_duplicate_event_and_cross_pipeline_id(self):
        for duplicate_id in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                row = article()
                other = copy.deepcopy(row)
                if duplicate_id:
                    other.pop("scheduledNews")
                    filename = "ordinary.json"
                else:
                    other["id"] = "a-20261001-other"
                    filename = "scheduled-other.json"
                Path(tmp, "scheduled-test.json").write_text(json.dumps({"articles": [row]}))
                Path(tmp, filename).write_text(json.dumps({"articles": [other]}))
                with self.assertRaises(ValueError):
                    validate_directory(tmp, NOW)

    def test_bad_payload_rejected(self):
        for data in ("broken", "{}", '{"articles": []}'):
            with tempfile.TemporaryDirectory() as tmp:
                Path(tmp, "scheduled-test.json").write_text(data)
                with self.assertRaises(ValueError):
                    validate_directory(tmp, NOW)


if __name__ == "__main__":
    unittest.main()
