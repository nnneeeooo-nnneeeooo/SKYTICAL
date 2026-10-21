"""Offline tests for same-event article revision helpers in write.py."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(tempfile.mkdtemp(prefix="avwire-article-update-"))
os.environ["AVWIRE_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT / "pipeline"))

import write  # noqa: E402


def test_match_and_revision_preserve_stable_article() -> None:
    articles_dir = DATA / "articles"
    articles_dir.mkdir(parents=True)
    path = articles_dir / "2026-07-29T19.json"
    existing = {
        "id": "a-stable-ana-e190-e2",
        "publishedUtc": "2026-07-29T19:00Z",
        "cat": "biz",
        "primarySource": "AeroTime",
        "image": {"url": "https://example.com/ana.jpg"},
        "zh": {"title": "全日空增購8架Embraer E190-E2"},
        "en": {"title": "ANA orders eight more Embraer E190-E2 aircraft"},
        "sources": [{
            "name": "AeroTime — ANA orders eight additional Embraer E190-E2 aircraft",
            "url": "https://www.aerotime.aero/articles/ana-e190-e2-order",
        }],
        "articleFormat": "brief",
    }
    path.write_text(
        json.dumps({"articles": [existing]}, ensure_ascii=False),
        encoding="utf-8",
    )

    records = write._load_existing_articles()
    group = {
        "id": "g-update",
        "updateCandidate": True,
        "primarySource": "Aerospace Global News",
        "items": [
            {
                "title": "ANA orders eight additional Embraer E190-E2 aircraft",
                "summary": "ANA expanded the order by eight aircraft.",
                "url": "https://www.aerotime.aero/articles/ana-e190-e2-order",
                "source": "AeroTime",
                "publishedUtc": "2026-07-29T18:00Z",
            },
            {
                "title": "ANA boosts E190-E2 order with eight more aircraft",
                "summary": "Embraer and ANA announced an expanded order.",
                "url": "https://aerospaceglobalnews.com/news/ana-e190-e2-order/",
                "source": "Aerospace Global News",
                "publishedUtc": "2026-07-30T01:00Z",
            },
        ],
    }
    matched = write._match_existing_article(group, records)
    assert matched is not None
    assert matched["article"]["id"] == existing["id"]

    draft = {
        "cat": "biz",
        "zh": {
            "title": "全日空擴大E190-E2訂單",
            "summary": "全日空擴大Embraer E190-E2訂單。",
            "body": ["第一段", "第二段", "第三段", "第四段"],
        },
        "en": {
            "title": "ANA expands its Embraer E190-E2 order",
            "summary": "ANA expanded its Embraer E190-E2 aircraft order.",
            "body": ["One", "Two", "Three", "Four"],
        },
        "riskFlags": [],
        "eventStatus": "confirmed",
    }
    now = datetime(2026, 7, 30, 2, 0, tzinfo=timezone.utc)
    revised = write.build_article(
        draft,
        group,
        now,
        set(),
        writer="test:model",
        facts=[],
        existing_article=matched["article"],
    )
    assert revised is not None
    assert revised["id"] == existing["id"]
    assert revised["publishedUtc"] == existing["publishedUtc"]
    assert revised["updatedUtc"] == "2026-07-30T02:00Z"
    assert revised["revision"] == 2
    assert revised["image"] == existing["image"]
    assert len(revised["sources"]) == 2

    write._write_article_updates([(path, revised)])
    stored = json.loads(path.read_text(encoding="utf-8"))["articles"]
    assert len(stored) == 1
    assert stored[0]["id"] == existing["id"]
    assert stored[0]["revision"] == 2


def test_editorial_updates_match_without_becoming_duplicate_articles() -> None:
    source = "https://www.faa.gov/newsroom/737-max-10"
    group = {"id": "g-max10", "updateCandidate": True, "items": [
        {"url": source, "title": "FAA certifies Boeing 737 MAX 10"}]}
    for metadata in ({"writer": "manual:GPT 6.1 Sol"},
                     {"writer": "openai:auto", "editorialLocked": True}):
        article = {"id": "a-editorial-max10", **metadata}
        record = {"article": article, "urls": {source}, "titles": []}
        assert write._match_existing_article(group, [record]) == record
        assert write._is_editorially_managed(article)
        used_ids = set()
        assert write.build_article(
            {"zh": {"body": ["short replacement"]}}, group,
            datetime.now(timezone.utc), used_ids, writer="openai:auto",
            existing_article=article) is None
        assert not used_ids
    assert not write._is_editorially_managed({"writer": "openai:auto"})
    assert not write._is_editorially_managed(None)


def test_persistence_preserves_manual_edit_made_after_update_was_drafted() -> None:
    path = DATA / "articles" / "editorial-protection.json"
    protected = {
        "id": "a-editorial", "writer": "manual:GPT 6.1 Sol",
        "revision": 5, "zh": {"body": ["完整人工擴寫版"]},
        "en": {"body": ["Full editorial copy"]},
    }
    automatic = {"id": "a-auto", "writer": "openai:auto", "revision": 1}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"articles": [protected, automatic]}),
                    encoding="utf-8")
    stale = {"id": "a-editorial", "writer": "openai:auto", "revision": 2}
    revised_auto = {**automatic, "revision": 2}
    for _ in range(2):
        write._write_article_updates([(path, stale), (path, revised_auto)])
        rows = json.loads(path.read_text(encoding="utf-8"))["articles"]
        assert rows == [protected, revised_auto]


if __name__ == "__main__":
    test_match_and_revision_preserve_stable_article()
    print("PASS test_match_and_revision_preserve_stable_article")
    test_editorial_updates_match_without_becoming_duplicate_articles()
    print("PASS test_editorial_updates_match_without_becoming_duplicate_articles")
    test_persistence_preserves_manual_edit_made_after_update_was_drafted()
    print("PASS test_persistence_preserves_manual_edit_made_after_update_was_drafted")
