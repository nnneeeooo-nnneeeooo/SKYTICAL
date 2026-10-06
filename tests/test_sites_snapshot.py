"""Boundary checks: a reading snapshot must never pretend to be live failover."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backup"))
from export_sites import sanitize_snapshot, snapshot_html


@pytest.mark.parametrize("lang,label", [("zh-Hant-TW", "閱讀快照"), ("en", "Reading snapshot")])
def test_snapshot_notice_and_primary_canonical(lang, label):
    page = (f'<html lang="{lang}"><head><meta name="robots" content="index,follow">'
            '<link rel="canonical" href="https://skytical.tech/news/">'
            '</head><body class="page"><a href="/search/">Search</a>'
            '<span>● LIVE</span><div> NEAR-LIVE ADS-B</div></body></html>')
    rendered = snapshot_html(page, "2026-10-06T12:00:00Z")
    assert label in rendered
    assert 'content="index,follow"' not in rendered
    assert 'content="noindex,nofollow"' in rendered
    assert 'href="https://skytical.tech/news/"' in rendered
    assert 'href="/search/"' in rendered
    assert "● LIVE</span>" not in rendered
    assert "NEAR-LIVE ADS-B</div>" not in rendered


@pytest.mark.parametrize("name", ["m", "u"])
def test_refuse_private_outputs(tmp_path, name):
    (tmp_path / name).mkdir()
    with pytest.raises(RuntimeError, match="Private"):
        sanitize_snapshot(tmp_path, "2026-10-06T12:00:00Z")


def test_search_data_kept_and_github_writing_ui_omitted(tmp_path):
    (tmp_path / "assets").mkdir()
    for name in ("manual.js", "copilot.js", "copilot.css", "search.js"):
        (tmp_path / "assets" / name).write_text("fixture", encoding="utf-8")
    records = {"articles": [{"id": "article-1", "title": "Flight"}]}
    (tmp_path / "search-index.json").write_text(json.dumps(records), encoding="utf-8")
    (tmp_path / "index.html").write_text('<html lang="en"><head></head><body></body></html>',
                                         encoding="utf-8")
    (tmp_path / "googleabcdef.html").write_text("domain proof", encoding="utf-8")
    assert sanitize_snapshot(tmp_path, "2026-10-06T12:00:00Z") == 1
    assert not (tmp_path / "assets/manual.js").exists()
    assert not (tmp_path / "assets/copilot.js").exists()
    assert not (tmp_path / "googleabcdef.html").exists()
    assert (tmp_path / "assets/search.js").exists()
    assert json.loads((tmp_path / "search-index.json").read_text()) == records
    assert "Disallow: /" in (tmp_path / "robots.txt").read_text()
