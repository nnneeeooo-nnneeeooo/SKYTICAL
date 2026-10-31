"""Offline source-bound audit, stable sampling and adaptive routing."""
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import luna_editorial as editorial
from editorial_policy import eligible_providers, news_policy


def story(title="Airline announces a new route to Paris", n=1):
    return {"id": str(n), "items": [{"title": title, "summary": "The airline will operate three flights per week.", "url": f"https://example.com/{n}"}]}


def provider(name, model="test"):
    return SimpleNamespace(name=name, model=model)


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setenv("AVWIRE_LUNA_EDITORIAL", "true")


def test_ordinary_story_switches_after_two_distinct_failed_platforms():
    rows = [provider("gemini", "gemini-3.6-flash"), provider("gemini", "gemini-3.5-flash"),
            provider("nvidia"), provider("groq"), provider("openai", "gpt-6")]
    assert [p.name for p in editorial.routes(story(), rows, rows)] == ["gemini", "nvidia", "openai", "gemini", "groq"]


@pytest.mark.parametrize("title", ["EVA Air announces Taipei flights", "Airliner crash at airport", "FAA issues emergency airworthiness directive"])
def test_important_story_switches_after_primary_failure_and_always_reviews(title):
    rows = [provider("gemini"), provider("nvidia"), provider("openai")]
    assert [p.name for p in editorial.routes(story(title), rows, rows)][:2] == ["gemini", "openai"]
    assert editorial.selected(story(title))


def test_elapsed_time_promotes_luna_before_second_platform():
    rows = [provider("gemini"), provider("nvidia"), provider("openai")]
    with patch.object(editorial.time, "monotonic", side_effect=[0, 0, 61, 62]):
        assert [p.name for p in editorial.routes(story(), rows, rows)][:2] == ["gemini", "openai"]


def test_dead_routes_do_not_receive_calls():
    rows = [provider("gemini"), provider("nvidia"), provider("openai")]
    assert [p.name for p in editorial.routes(story(), rows, rows[1:])] == ["nvidia", "openai"]


def test_ordinary_only_grants_luna_not_other_paid_providers():
    rows = [provider("openai"), provider("anthropic"), provider("wechat"), provider("nvidia")]
    assert eligible_providers(story(), rows) == [rows[0], rows[3]]
    niche = story("Airbus completes aircraft flight tests")
    assert news_policy(niche).priority == "niche"
    assert eligible_providers(niche, rows) == [rows[3]]
    assert not editorial.selected(niche)


def test_sampling_is_stable_and_near_seventy_percent():
    rows = [story(n=n) for n in range(1000)]
    selected = sum(editorial.selected(row) for row in rows)
    assert 660 <= selected <= 740
    assert all(editorial.selected(row) == editorial.selected(copy.deepcopy(row)) for row in rows[:40])


def audit_fixture():
    draft = {"zh": {"title": "每週五班", "summary": "", "body": []},
             "en": {"title": "Five weekly flights", "summary": "", "body": []}}
    sources = [{"text": "The airline will operate three flights per week."}]
    issue = {"path": "en.title", "draftQuote": "Five weekly flights", "sourceIndex": 0,
             "sourceQuote": "operate three flights per week", "explanation": "Frequency differs from the source."}
    return draft, sources, {"status": "issues", "issues": [issue]}


def test_audit_requires_both_source_and_affected_field_quotes():
    draft, sources, result = audit_fixture()
    assert editorial.validate(result, draft, sources) == result
    for key, value in (("sourceIndex", 2), ("sourceQuote", "fabricated evidence"),
                       ("draftQuote", "Not in the draft"), ("path", "facts.0")):
        bad = copy.deepcopy(result)
        bad["issues"][0][key] = value
        with pytest.raises(ValueError):
            editorial.validate(bad, draft, sources)
    with pytest.raises(ValueError):
        editorial.validate({"status": "pass", "issues": result["issues"]}, draft, sources)


def test_audit_does_not_persist_sources_or_private_model_names(tmp_path, monkeypatch):
    monkeypatch.setattr(editorial, "DATA_DIR", tmp_path)
    p = Mock()
    p.budget_purpose = "draft"
    p.available.return_value = True
    p._responses_call.return_value = json.dumps({"status": "pass", "issues": []})
    draft, _, _ = audit_fixture()
    assert editorial.audit(p, draft, story())["status"] == "pass"
    assert p.budget_purpose == "draft"
    text = (tmp_path / "luna-editorial.json").read_text(encoding="utf-8")
    assert "flights per week" not in text and "sourceQuote" not in text


def test_refusal_invalid_result_or_budget_failure_holds_review(tmp_path, monkeypatch):
    monkeypatch.setattr(editorial, "DATA_DIR", tmp_path)
    p = Mock()
    p.budget_purpose = "draft"
    p._responses_call.side_effect = RuntimeError("budget exhausted")
    draft, _, _ = audit_fixture()
    assert editorial.audit(p, draft, story())["status"] == "unavailable"
    assert editorial.audit(None, draft, story())["status"] == "unavailable"


@pytest.mark.parametrize("tier", [None, "fast", "standard", "deep"])
@pytest.mark.parametrize("repair", [False, True])
def test_luna_always_uses_max_for_manual_drafting_and_repairs(tier, repair):
    from providers import OpenAIProvider
    from model_config import manual_reasoning_profile
    p = OpenAIProvider(reasoning_tier=tier)
    assert p._effort(repair) == "max"
    assert p.reasoning_effective == "reasoning.effort=max"
    if tier:
        assert manual_reasoning_profile("openai", "gpt-6", tier)["wire"]["reasoning"]["effort"] == "max"
    p.budget_purpose = "review"
    assert p._responses_output_tokens(repair) == 48000


def test_briefing_and_its_repairs_keep_max_despite_stale_environment(monkeypatch):
    import briefing_writer
    monkeypatch.setenv("BRIEFING_WRITER_EFFORT", "low")
    p = briefing_writer.make_provider()
    assert p._effort(False) == p._effort(True) == "max"
    assert p._responses_output_tokens(False) == p._responses_output_tokens(True) == 48000
