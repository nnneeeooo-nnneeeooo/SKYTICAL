"""Publication failures that must be caught before deploying scheduled news."""
import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from scheduled_news import validate_article, validate_directory

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
