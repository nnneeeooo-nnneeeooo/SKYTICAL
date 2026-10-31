"""Offline cloud scheduling, coverage, code verification and spend safety."""
import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import iata_audit as audit


def article(identity="a-test", stamp="2026-11-01T00:01:00+08:00"):
    return {"id": identity, "publishedUtc": stamp, "zh": {"title": "桃園國際機場（TPE）增班", "body": ["桃園國際機場（TPE）公布航班。"]},
            "en": {"title": "Taiwan Taoyuan International Airport (TPE) adds flights", "body": ["Taiwan Taoyuan International Airport (TPE) announces flights."]}}


def mention(**changes):
    return {"language": "zh", "surface": "body", "paragraphIndex": 0,
            "name": "桃園國際機場", "quote": "桃園國際機場（TPE）公布航班。", "proposedIata": "TPE", **changes}


def test_first_run_is_four_am_taipei_and_never_earlier():
    assert audit.START.astimezone(audit.TPE).isoformat() == "2026-11-01T04:00:00+08:00"
    assert not audit.due_windows(audit.START - timedelta(seconds=1))
    assert audit.due_windows(audit.START) == [(audit.START-audit.STEP, audit.START)]


def test_late_runs_and_outages_cover_fixed_windows_without_gaps():
    now = audit.START + timedelta(hours=8, minutes=37)
    windows = audit.due_windows(now)
    assert len(windows) == 3
    assert windows[-1][1] == audit.START + timedelta(hours=8)
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))
    assert audit.due_windows(now, audit.START.isoformat()) == windows[1:]


def test_candidate_window_includes_revisions_and_preserves_data(tmp_path):
    start, end = audit.START-audit.STEP, audit.START
    old = article("old", "2026-01-01T00:00:00Z")
    revised = copy.deepcopy(old)
    revised["id"], revised["updatedUtc"] = "revised", "2026-11-01T02:00:00+08:00"
    new = article("new")
    edge = article("end", "2026-11-01T04:00:00+08:00")
    path = tmp_path / "articles.json"
    path.write_text(json.dumps({"articles": [old, revised, new, edge]}), encoding="utf-8")
    before = path.read_bytes()
    rows, removed = audit.candidates(start, end, {"old", "deleted"}, tmp_path)
    assert {a["id"] for a in rows} == {"old", "revised", "new"}
    assert removed == ["deleted"]
    assert path.read_bytes() == before


def test_git_changes_detect_body_edits_without_updated_stamp():
    start, end = audit.START-audit.STEP, audit.START
    old, new = article(), article()
    new["zh"]["body"][0] = "桃園國際機場公布航班。"
    def git(*args):
        if args[0] == "log":
            return "one\t" + start.isoformat() + "\ntwo\t" + end.isoformat()
        if args[0] == "diff-tree":
            assert "one" in args
            return "data/articles/a.json\n"
        if args[0] == "show":
            return json.dumps({"articles": [old if args[1].startswith("one^") else new]})
        raise AssertionError(args)
    with patch.object(audit, "git", side_effect=git):
        assert audit.changed_ids(start, end) == {"a-test"}


def test_model_must_return_every_article_and_quote_real_field():
    rows = [audit.visible(article())]
    good = {"articles": [{"id": "a-test", "mentions": [mention()]}]}
    assert audit.validate_mentions(good, rows)["a-test"]
    for bad in ({"articles": []}, {"articles": good["articles"]*2},
                {"articles": [{"id": "unknown", "mentions": []}]},
                {"articles": [{"id": "a-test", "mentions": [mention(quote="fabricated")]}]}):
        with pytest.raises(ValueError):
            audit.validate_mentions(bad, rows)


def test_correct_codes_pass_and_missing_first_body_code_is_found():
    a = article()
    before = copy.deepcopy(a)
    assert audit.findings(a, [mention()]) == []
    assert a == before
    a["zh"]["body"][0] = "桃園國際機場公布航班。"
    issues = audit.findings(a, [mention(quote="桃園國際機場公布航班。")])
    assert any(i["kind"] == "missing_or_wrong_first_code" and i["verifiedIata"] == "TPE" for i in issues)


def test_wrong_later_code_and_model_conflicts_are_not_accepted():
    a = article()
    a["zh"]["body"].append("桃園國際機場（KHH）另有公告。")
    issues = audit.findings(a, [mention(proposedIata="KHH")])
    assert any(i["kind"] == "placement_or_identity" for i in issues)
    assert any(i["kind"] == "model_code_conflict" for i in issues)


def test_city_only_and_unknown_airport_are_not_guessed():
    a = article()
    unknown = mention(name="Unverifiable Airport", proposedIata="TPE")
    issues = audit.findings(a, [unknown])
    assert any(i["kind"] == "unverified_airport" for i in issues)


def test_code_only_does_not_require_duplicate_parenthesis():
    a = article()
    a["en"] = {"title": "TPE adds flights", "body": ["TPE announces flights."]}
    issues = audit.findings(a, [mention(language="en", name="TPE", quote="TPE announces flights.")])
    assert not any(i["kind"] == "missing_or_wrong_first_code" for i in issues)


def test_complete_batches_do_not_silently_truncate_large_articles():
    with patch.object(audit, "MAX_BATCH_BYTES", 100):
        with pytest.raises(ValueError):
            list(audit.batches([article()]))


def test_budget_reservation_precedes_paid_call_and_max_is_pinned():
    state = audit.State()
    events = []
    state.save = lambda: events.append("persist")
    p = audit.AuditProvider(state)
    response = Mock()
    response.json.return_value = {"usage": {"input_tokens": 20, "output_tokens": 50}}
    def send(*args, **kwargs):
        assert events == ["persist"]
        events.append("paid")
        return response
    with patch.object(audit.OpenAIProvider, "_post_json", side_effect=send):
        p._post_json("unused", {"max_output_tokens": 48000, "input": "test"}, {}, False)
    assert events == ["persist", "paid", "persist"]
    assert p._effort(False) == p._effort(True) == "max"


def test_unknown_spend_stays_reserved_and_monthly_limit_blocks_http():
    state = audit.State()
    hold = state.reserve({"max_output_tokens": 48000}, audit.START)
    before = copy.deepcopy(state.data)
    state.settle(hold, {})
    assert state.data == before
    state.data["months"]["2026-11"] = 8000000
    with pytest.raises(RuntimeError, match="budget"):
        state.reserve({"max_output_tokens": 48000}, audit.START)


def test_persistence_failure_blocks_before_paid_request():
    state = audit.State()
    state.save = Mock(side_effect=ConnectionError())
    p = audit.AuditProvider(state)
    with patch.object(audit.OpenAIProvider, "_post_json") as post:
        with pytest.raises(ConnectionError):
            p._post_json("unused", {"max_output_tokens": 48000}, {}, False)
    post.assert_not_called()


def test_cache_uses_visible_copy_not_image_or_timestamp():
    a = article()
    b = copy.deepcopy(a)
    b["image"], b["updatedUtc"] = "new photo", "2026-11-01T03:00:00+08:00"
    assert audit.digest(a) == audit.digest(b)
    b["zh"]["body"].append("新內容。")
    assert audit.digest(a) != audit.digest(b)


def test_cloud_workflow_is_independent_and_does_not_build_or_deploy():
    text = (audit.ROOT / ".github/workflows/iata-audit.yml").read_text(encoding="utf-8")
    assert 'cron: "0 */4 * * *"' in text
    assert "fetch-depth: 0" in text
    assert "secrets.OPENAI_API" in text and "secrets.OPENAI_MODEL_ID" in text
    assert "pipeline/build.py" not in text and "deploy-pages" not in text
    assert "if: always()" in text and "actions/upload-artifact" in text


@pytest.mark.parametrize("complete", [True, False])
@pytest.mark.parametrize("request_mode", [True, False])
def test_cloud_run_advances_only_after_complete_model_coverage(tmp_path, monkeypatch, complete, request_mode):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setenv("AVWIRE_OPENAI_API_MODEL", "fake-private-mapping")
    monkeypatch.setenv("IATA_AUDIT_OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("IATA_AUDIT_REQUESTS_DIR", str(tmp_path / "requests"))
    if request_mode:
        (tmp_path / "requests").mkdir()
        (tmp_path / "requests/day.json").write_text(json.dumps({"id": "day", "start": (audit.START-audit.STEP).isoformat(), "end": audit.START.isoformat()}))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    state = audit.State()
    state.save = Mock()
    p = Mock()
    p.meter = {}
    p._responses_call.return_value = json.dumps({"articles": [{"id": "a-test", "mentions": [mention()]}] if complete else []})
    source = article()
    original = copy.deepcopy(source)
    with patch.object(audit, "State", return_value=state), patch.object(audit, "AuditProvider", return_value=p), \
            patch.object(audit, "changed_ids", return_value=set()), patch.object(audit, "candidates", return_value=([source], [])), \
            patch.object(audit, "git", return_value="test-snapshot"):
        if complete:
            assert audit.run(audit.START) == 0
            if request_mode:
                assert state.data["lastSuccessEnd"] is None
                assert state.data["completedRequests"]["day"]["checkedCount"] == 1
            else:
                assert state.data["lastSuccessEnd"] == audit.START.isoformat()
        else:
            with pytest.raises(RuntimeError, match="incomplete"):
                audit.run(audit.START)
            assert state.data["lastSuccessEnd"] is None
    report = json.loads(next(tmp_path.glob("*Z.json")).read_text(encoding="utf-8"))
    assert report["candidateCount"] == 1
    assert report["checkedCount"] == int(complete)
    assert report["incompleteCount"] == int(not complete)
    assert source == original
