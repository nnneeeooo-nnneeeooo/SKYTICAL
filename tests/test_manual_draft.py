"""Offline contract tests for the encrypted private manual-drafting desk."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import manual_draft  # noqa: E402
from model_config import (  # noqa: E402
    MODEL_DISPLAY_NAMES,
    MODEL_ORDER,
    OPENROUTER_MODEL_ORDER,
    manual_reasoning_profile,
)
from providers import ProviderError  # noqa: E402

passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def sample_payload():
    return {
        "articleType": "incident",
        "language": "bilingual",
        "reasoningTier": "deep",
        "model": "auto",
        "sourceUrls": ["https://8.8.8.8/source"],
        "sourceText": "Official source text with enough evidence.",
        "instruction": "Keep the authority name in English.",
        "conversation": [{"role": "user", "text": "Focus on chronology."}],
        "images": [],
    }


def test_encryption_round_trip():
    token = "A" * 43
    job_id = "0123456789abcdef0123456789abcdef"
    value = {"sourceText": "未公開來源", "images": ["secret"]}
    envelope = manual_draft.encrypt_json(value, token, job_id)
    encoded = json.dumps(envelope, ensure_ascii=False)
    check(set(envelope) == {"version", "alg", "iv", "ciphertext"},
          "encrypted envelope has ciphertext-only contract")
    check("未公開來源" not in encoded and "secret" not in encoded,
          "plaintext never appears in the repository envelope")
    check(manual_draft.decrypt_json(envelope, token, job_id) == value,
          "AES-GCM envelope round-trips")
    try:
        manual_draft.decrypt_json(envelope, "B" * 43, job_id)
        check(False, "wrong private URL token must not decrypt")
    except Exception:
        check(True, "wrong private URL token is rejected")


def test_payload_limits_and_ssrf():
    payload = manual_draft.validate_payload(sample_payload())
    check(payload["articleType"] == "incident"
          and payload["reasoningTier"] == "deep",
          "manual selection contract validates")
    try:
        manual_draft._public_url("http://127.0.0.1/private")
        check(False, "loopback URL must be blocked")
    except ValueError:
        check(True, "loopback URL is blocked")
    check(manual_draft._public_url("https://8.8.8.8/source")
          == "https://8.8.8.8/source",
          "global HTTPS address is accepted")
    bad = sample_payload()
    bad["model"] = "nvidia:not-a-real-model"
    try:
        manual_draft.validate_payload(bad)
        check(False, "unknown model must be rejected")
    except ValueError:
        check(True, "unknown model is rejected")


def test_reasoning_tiers():
    check(manual_reasoning_profile(
        "gemini", "gemini-3.6-flash", "deep")["wire"]
        == {"thinkingConfig": {"thinkingLevel": "high"}},
        "Gemini deep maps to thinkingLevel high")
    check(manual_reasoning_profile(
        "nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "deep")["wire"]
        == {"reasoning_effort": "max"},
        "Nemotron Ultra deep maps to maximum reasoning")
    check(manual_reasoning_profile(
        "nvidia", "z-ai/glm-5.2", "deep")["effective"]
        == "provider_default",
        "GLM reports provider-default when no control exists")
    check(manual_reasoning_profile(
        "nvidia", "qwen/qwen3.5-397b-a17b", "fast")["wire"]
        == {"chat_template_kwargs": {"enable_thinking": False}},
        "Qwen fast disables thinking")
    check(manual_reasoning_profile(
        "openrouter", "openai/gpt-oss-20b:free", "deep")["wire"]
        == {"reasoning": {"effort": "high", "exclude": True}},
        "OpenRouter deep uses high reasoning without returning its trace")


def test_openrouter_manual_provider_order():
    saved = {
        key: os.environ.get(key)
        for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY",
                    "OPENROUTER_API_KEY")
    }
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("NVIDIA_API_KEY", None)
    os.environ["OPENROUTER_API_KEY"] = "test-not-a-real-key"
    try:
        rows = manual_draft._providers_for(
            manual_draft.validate_payload(sample_payload()))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check([row.label for row in rows] == list(OPENROUTER_MODEL_ORDER),
          "manual fallback exposes all OpenRouter models in owner order")
    check(all(row.reasoning_tier == "deep" for row in rows),
          "manual reasoning tier reaches every OpenRouter model")


class FakeProvider:
    def __init__(self, label, answer):
        self.label = label
        self.name, _ = label.split(":", 1)
        self.answer = answer
        self.reasoning_effective = "test"
        self.http_calls = 1
        self.repair_calls = 0
        self.usage = {"inputTokens": 10, "outputTokens": 20}
        self.request_log = [{
            "status": 429 if isinstance(answer, Exception) else 200,
            "durationMs": 1,
            "headers": {"x-ratelimit-remaining": "0"}
            if isinstance(answer, Exception) else {},
        }]

    def draft(self, system, user, schema):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_fallback_and_telemetry():
    first = FakeProvider(
        MODEL_ORDER[0], ProviderError("HTTP 429 per-minute rate limit"))
    second = FakeProvider(MODEL_ORDER[1], {"status": "reject"})
    originals = (
        manual_draft._providers_for,
        manual_draft._build_group,
        manual_draft.usage_ledger.record_providers,
        manual_draft.usage_ledger.record_run,
    )
    manual_draft._providers_for = lambda payload: [first, second]
    manual_draft._build_group = lambda job, payload, log: {
        "id": f"manual-{job}",
        "primarySource": "official",
        "items": [{
            "source": "official",
            "title": "Source",
            "summary": "Source material",
            "fulltext": "Source material",
            "url": "https://8.8.8.8/source",
        }],
    }
    manual_draft.usage_ledger.record_providers = lambda rows: None
    manual_draft.usage_ledger.record_run = lambda row: None
    try:
        result = manual_draft.generate(
            "0123456789abcdef0123456789abcdef",
            manual_draft.validate_payload(sample_payload()))
    finally:
        (manual_draft._providers_for,
         manual_draft._build_group,
         manual_draft.usage_ledger.record_providers,
         manual_draft.usage_ledger.record_run) = originals
    check(result["fallbackUsed"] is True
          and result["finalModel"] == MODEL_ORDER[1],
          "failed first model falls back in configured order")
    check(result["attempts"][0]["failureClass"] == "rate_limit"
          and result["attempts"][0]["requests"][0]["headers"]
          ["x-ratelimit-remaining"] == "0",
          "safe rate-limit and failure telemetry reach encrypted result")


def test_private_page_render_contract():
    captured = []
    original_render = build.render
    original_token = os.environ.get("AVWIRE_MANUAL_TOKEN")
    build.render = lambda env, template, out, ctx: captured.append(
        (template, out, ctx))
    try:
        os.environ.pop("AVWIRE_MANUAL_TOKEN", None)
        check(build.render_manual_workbench(None, {}) == 0,
              "manual page is absent without its secret")
        os.environ["AVWIRE_MANUAL_TOKEN"] = "x" * 43
        check(build.render_manual_workbench(None, {}) == 1,
              "manual page renders with a valid secret")
    finally:
        build.render = original_render
        if original_token is None:
            os.environ.pop("AVWIRE_MANUAL_TOKEN", None)
        else:
            os.environ["AVWIRE_MANUAL_TOKEN"] = original_token
    template, out, ctx = captured[0]
    check(template == "manual.html" and out == f"m/{'x' * 43}/index.html",
          "private route embeds the unguessable token")
    check([row["id"] for row in ctx["models"]] == list(MODEL_ORDER)
          and [row["name"] for row in ctx["models"]]
          == [MODEL_DISPLAY_NAMES[item] for item in MODEL_ORDER],
          "UI exposes every model in exact fallback order")


def test_static_security_contract():
    html = (ROOT / "templates" / "manual.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "manual.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows"
                / "manual-draft.yml").read_text(encoding="utf-8")
    hourly = (ROOT / ".github" / "workflows"
              / "hourly.yml").read_text(encoding="utf-8")
    briefing = (ROOT / ".github" / "workflows"
                / "briefing.yml").read_text(encoding="utf-8")
    check("noindex,nofollow,noarchive,nosnippet" in html
          and "Content-Security-Policy" in html,
          "private page is noindex and has a restrictive CSP")
    check('<option value="deep" selected>' in html
          and '<option value="standard" selected>' not in html,
          "private page defaults to the highest reasoning tier")
    check("localStorage" not in js and "sessionStorage" in js,
          "PAT is session-only, never persistent local storage")
    check("AES-GCM" in js and "data/manual-jobs/inbox/" in js,
          "browser encrypts before writing a job")
    check("secrets.AVWIRE_MANUAL_TOKEN" in workflow
          and "secrets.OPENROUTER_API_KEY" in workflow
          and "encrypted envelopes only" in workflow
          and "data/manual-jobs/outbox 2>/dev/null || true" in workflow,
          "Actions uses Secrets, checks ciphertext and tolerates empty queues")
    configured_order = f"AVWIRE_PROVIDER_ORDER: {','.join(MODEL_ORDER)}"
    check(configured_order in hourly and configured_order in briefing,
          "automatic workflows use the complete shared fallback order")
    check("secrets.OPENROUTER_API_KEY" in hourly
          and "secrets.OPENROUTER_API_KEY" in briefing
          and "sk-or-v1-" in hourly and "sk-or-v1-" in briefing,
          "automatic workflows receive and scan for the OpenRouter secret")


def main():
    for test in (
        test_encryption_round_trip,
        test_payload_limits_and_ssrf,
        test_reasoning_tiers,
        test_openrouter_manual_provider_order,
        test_fallback_and_telemetry,
        test_private_page_render_contract,
        test_static_security_contract,
    ):
        test()
    print(f"{passed} checks passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
