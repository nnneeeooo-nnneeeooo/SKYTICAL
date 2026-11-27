"""Actual Luna routing, migration of stale Terra settings and public credit."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build
import model_config
import providers
from briefing_writer import make_provider
from iata_audit import AuditProvider, State
import paid_budget


@pytest.mark.parametrize("old", [None, "gpt-6", "gpt-6-luna", "gpt-6.1-terra"])
def test_actual_http_uses_luna_even_with_obsolete_private_mapping(monkeypatch, old):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("AVWIRE_OPENAI_MODEL", "gpt-6.1-terra")
    monkeypatch.setenv("AVWIRE_OPENAI_API_MODEL", "gpt-6-luna")
    monkeypatch.delenv("AVWIRE_PAID_BUDGET_ENABLED", raising=False)
    provider = providers.OpenAIProvider(old)
    response = Mock(status_code=200, headers={})
    response.json.return_value = {"status": "completed", "output_text": '{"ok": true}',
                                  "usage": {"input_tokens": 10, "output_tokens": 10}}
    with patch("requests.post", return_value=response) as post:
        assert provider.draft("system", "source", {"type": "object"}) == {"ok": True}
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "gpt-6-luna"
    assert payload["reasoning"]["effort"] == "max"
    assert "max_output_tokens" not in payload
    assert provider.label == "openai:gpt-6-luna"
    assert build.writer_model(provider.label) == "GPT 6 Luna"


def test_stale_provider_list_migrates_and_deduplicates(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    monkeypatch.setenv("AVWIRE_PROVIDER_ORDER", "openai:gpt-6,openai:gpt-6-luna,openai:gpt-6.1-terra")
    assert [p.label for p in providers.build_providers()] == ["openai:gpt-6-luna"]


def test_every_direct_openai_default_and_public_credit_is_luna(monkeypatch):
    monkeypatch.delenv("AVWIRE_OPENAI_MODEL", raising=False)
    monkeypatch.setenv("BRIEFING_WRITER_MODEL", "gpt-6")
    assert make_provider().model == AuditProvider(State()).model == "gpt-6-luna"
    assert model_config.OPENAI_MODEL_ORDER == ("openai:gpt-6-luna",)
    assert model_config.MODEL_DISPLAY_NAMES["openai:gpt-6-luna"] == "GPT 6 Luna"
    assert build.writer_model(None, ["gpt-6-luna"]) == "GPT 6 Luna"
    assert build.writer_model("openai:gpt-6.1-terra") == "GPT 6.1 Terra"
    # Preserve historical provenance.
    assert build.writer_model("openai:gpt-6") == "GPT 6"
    assert paid_budget.policy()["input_usd_per_million"] == 0.1
    assert paid_budget.policy()["output_usd_per_million"] == 0.5


def test_production_workflows_never_restore_the_old_wire_mapping():
    root = Path(__file__).resolve().parents[1]
    for path in (root / ".github/workflows").glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "AVWIRE_OPENAI_API_MODEL:" not in text, path
        assert "openai:gpt-6\n" not in text and "MODEL: gpt-6\n" not in text, path
