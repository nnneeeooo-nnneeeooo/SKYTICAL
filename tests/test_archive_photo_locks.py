"""Archive photo scripts leave image-locked articles alone."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-archive-locks-")
sys.path.insert(0, str(ROOT / "pipeline"))

import archive_photo_backfill  # noqa: E402
import archive_photo_qa  # noqa: E402
import archive_targeted_photos  # noqa: E402

BATCH = "data/articles/2026-11-24T03.json"


def story(article_id, zh_title, **extra):
    return {"id": article_id, "publishedUtc": "2026-11-24T03:00Z", "image": None,
            "zh": {"title": zh_title}, "en": {"title": "Title"}, **extra}


def write_batch(root, *articles):
    path = root / BATCH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"articles": list(articles)}, ensure_ascii=False),
                    encoding="utf-8")
    return path


def images_by_id(path):
    rows = json.loads(path.read_text(encoding="utf-8"))["articles"]
    return {row["id"]: row.get("image") for row in rows}


def test_backfill_treats_a_locked_article_as_settled():
    locked = story("a-locked", "標題", editorialImageLocked=True)
    assert archive_photo_backfill.usable_existing(locked)
    assert not archive_photo_backfill.usable_existing(story("a-open", "標題"))


def test_quality_review_neither_fills_nor_revokes_a_locked_article(tmp_path, monkeypatch):
    loose = {"url": "https://example.org/a.jpg", "link": "https://example.org/a",
             "matched": "archive:verified-real-photo:validated-cache"}
    path = write_batch(
        tmp_path,
        story("a-open", "IATA 上修全球航空業獲利預測"),
        story("a-locked-empty", "IATA 上修全球航空業獲利預測", editorialImageLocked=True),
        story("a-locked-photo", "標題", editorialImageLocked=True, image=dict(loose)))
    (tmp_path / "data/images.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(archive_photo_qa, "ROOT", tmp_path)
    monkeypatch.setattr(archive_photo_qa, "ARTICLES", path.parent)
    monkeypatch.setattr(archive_photo_qa, "BANK", tmp_path / "data/images.json")
    monkeypatch.setattr(archive_photo_qa, "REPORT", tmp_path / "data/report.json")
    archive_photo_qa.main()
    images = images_by_id(path)
    assert images["a-open"]["matched"].endswith("iata-real-headquarters")
    assert images["a-locked-empty"] is None
    assert images["a-locked-photo"] == loose


def test_targeted_recovery_skips_a_locked_article(tmp_path, monkeypatch):
    path = write_batch(
        tmp_path,
        story("a-open", "樟宜機場第五航廈動工"),
        story("a-locked", "樟宜機場第五航廈動工", editorialImageLocked=True))
    backlog = tmp_path / "data/backlog.json"
    backlog.write_text(json.dumps({"unresolved": [
        {"id": "a-open", "path": BATCH}, {"id": "a-locked", "path": BATCH}]}),
        encoding="utf-8")
    monkeypatch.setattr(archive_targeted_photos, "ROOT", tmp_path)
    monkeypatch.setattr(archive_targeted_photos, "PREVIOUS", backlog)
    monkeypatch.setattr(archive_targeted_photos, "OUTPUT", tmp_path / "data/report.json")
    monkeypatch.setattr(archive_targeted_photos, "photo_of", lambda name: {
        "url": "https://example.org/changi.jpg", "link": "https://example.org/changi",
        "raw_title": name})
    archive_targeted_photos.main()
    images = images_by_id(path)
    assert images["a-open"]["link"] == "https://example.org/changi"
    assert images["a-locked"] is None
