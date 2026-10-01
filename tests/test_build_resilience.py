"""Regression checks for article schema evolution and build fail-closed guards."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import article_schema  # noqa: E402
import build  # noqa: E402


def main() -> None:
    legacy = {
        "id": "a-20260701-1200-legacy-schema",
        "publishedUtc": "2026-07-01T12:00Z",
        "cat": "ops",
        "zh": {
            "title": "舊格式文章",
            "summary": "驗證歷史文章缺少新欄位時仍能正常讀取。",
            "body": "舊格式曾允許單一字串正文。",
        },
        "sources": [{
            "name": "Example Aviation",
            "url": "https://example.com/aviation/legacy",
        }],
    }
    untouched = copy.deepcopy(legacy)
    normalized = article_schema.normalize_article_record(legacy)
    assert legacy == untouched
    assert normalized is not legacy
    assert normalized["schemaVersion"] == article_schema.ARTICLE_SCHEMA_VERSION
    assert normalized["archived"] is False
    assert normalized["primarySource"] == ""
    assert normalized["image"] is None
    assert normalized["zh"]["body"] == ["舊格式曾允許單一字串正文。"]
    assert normalized["en"] == {"title": "", "summary": "", "body": []}
    assert normalized["availableLanguages"] == []
    assert normalized["writerModels"] == []
    assert normalized["sourceImageCandidates"] == []
    assert normalized["facts"] == []
    assert normalized["riskFlags"] == []
    assert normalized["entityEvidence"] == []
    assert normalized["entities"]["airlines"] == []
    assert normalized["writer"] is None
    assert normalized["articleFormat"] == "full"

    prepared = build.prep_article(legacy)
    assert prepared is not None
    assert prepared["late_ingest"] is False
    assert prepared["article_format"] == "full"
    assert prepared["writer_model"] is None
    assert prepared["image"] is None
    assert prepared["airline_entities"] == []
    assert prepared["available_languages"] == ["zh", "en"]
    assert prepared["en"]["title"] == prepared["zh"]["title"]

    # Every currently persisted article generation must cross the same
    # normalization boundary and expose a complete prepared-view contract.
    required_view_keys = {
        "id", "dt", "news_dt", "published_dt", "modified_dt",
        "published_iso", "modified_iso", "published_meta_ts",
        "modified_meta_ts", "late_ingest", "cat", "tag_class", "image",
        "source", "time", "meta_ts", "zh", "en", "sources",
        "airline_entities", "writer_model", "available_languages",
        "article_format",
    }
    accepted = 0
    for path in sorted((ROOT / "data" / "articles").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("articles") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            normalized = article_schema.normalize_article_record(raw)
            assert normalized is not None
            assert normalized["schemaVersion"] == article_schema.ARTICLE_SCHEMA_VERSION
            prepared = build.prep_article(raw)
            if prepared is None:
                continue
            accepted += 1
            assert required_view_keys <= set(prepared)
            assert prepared["article_format"] in {"full", "brief", "roundup"}
            assert isinstance(prepared["late_ingest"], bool)
            assert all(lang in {"zh", "en"} for lang in prepared["available_languages"])
    assert accepted > 900

    # Isolated failures remain degradable, but either safety bound blocks a
    # partial site from being published.
    assert build.render_failures_are_catastrophic(0, 2000) is False
    assert build.render_failures_are_catastrophic(5, 2000) is False
    assert build.render_failures_are_catastrophic(6, 2000) is True
    assert build.render_failures_are_catastrophic(2, 200) is False
    assert build.render_failures_are_catastrophic(3, 200) is True
    assert build.render_failures_are_catastrophic(1, 50) is True

    source = (ROOT / "pipeline" / "build.py").read_text(encoding="utf-8")
    assert "if catastrophic:" in source
    assert "::error::Build blocked: render failures exceeded the safety budget" in source
    assert "return 1" in source

    print(f"test_build_resilience: OK ({accepted} historical article rows accepted)")


if __name__ == "__main__":
    main()
