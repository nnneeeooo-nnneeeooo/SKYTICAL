"""Regression checks for the seven-day manual image visual-review queue."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from pipeline import image_qa


def _write_batch(path: Path) -> None:
    path.write_text(json.dumps({"articles": [{
        "id": "a-qa",
        "publishedUtc": "2026-08-26T08:00:00Z",
        "zh": {"title": "華航航班調整"},
        "en": {"title": "China Airlines flight adjustment"},
        "image": {
            "url": "https://example.com/aircraft.jpg",
            "provider": "Wikimedia Commons",
            "kind": "file_photo",
            "subject": "China Airlines Boeing 777-300ER",
        },
    }]}), encoding="utf-8")


def test_queue_records_current_image_and_preserves_decision(tmp_path):
    articles = tmp_path / "articles"
    articles.mkdir()
    _write_batch(articles / "2026-08-26T08.json")
    now = datetime(2026, 8, 26, 9, tzinfo=timezone.utc)
    existing = {
        "items": [{
            "key": "a-qa|https://example.com/aircraft.jpg",
            "status": "approved",
            "createdUtc": "2026-08-26T08:30:00+00:00",
        }]
    }
    payload = image_qa.build_queue(now, articles_dir=articles,
                                   existing=existing)
    assert payload["windowDays"] == 7
    assert len(payload["items"]) == 1
    row = payload["items"][0]
    assert row["status"] == "approved"
    assert row["image"]["subject"].endswith("777-300ER")
    assert row["createdUtc"] == "2026-08-26T08:30:00+00:00"


def test_malformed_existing_items_are_reset_safely(tmp_path):
    articles = tmp_path / "articles-malformed"
    articles.mkdir()
    payload = image_qa.build_queue(
        datetime(2026, 8, 26, 9, tzinfo=timezone.utc),
        articles_dir=articles,
        existing={"items": None},
    )
    assert payload["items"] == []


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        test_queue_records_current_image_and_preserves_decision(root)
        test_malformed_existing_items_are_reset_safely(root)
    print("PASS test_image_qa: 2 checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
