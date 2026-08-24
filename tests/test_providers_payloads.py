"""Offline tests for pipeline/providers.py request payloads and parsing.

Run from the repo root:  py tests\\test_providers_payloads.py

requests.post is monkeypatched to capture exactly what each model profile
sends and to feed canned responses back - no network, no API keys, no
NVIDIA/Gemini quota. Verifies:
  - per-model reasoning/sampling fields (MODEL_PROFILES)
  - the no-thinking format-repair path (JSON syntax only)
  - reasoning traces (reasoning_content / thought parts) never reach the
    JSON parser or the returned draft
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
os.environ.setdefault("NVIDIA_API_KEY", "test-key-not-real")
os.environ.setdefault("GEMINI_API_KEY", "test-key-not-real")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key-not-real")
os.environ.setdefault("OPENCODE_API_KEY", "oc_sk_test-not-real")

import providers  # noqa: E402

_pass = 0
_fail = 0


def check(cond, label):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"FAIL: {label}")


class FakeResponse:
    def __init__(self, payload, status=200, headers=None):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)
        self.headers = headers or {}

    def json(self):
        return self._payload


def nvidia_ok(content, reasoning="LEAKED-REASONING-TRACE {not json"):
    return FakeResponse({"choices": [{
        "finish_reason": "stop",
        "message": {"content": content, "reasoning_content": reasoning},
    }]})


def gemini_ok(parts):
    return FakeResponse({"candidates": [{
        "finishReason": "STOP", "content": {"parts": parts},
    }]})


def with_post(fake_post, fn):
    original = providers.requests.post
    providers.requests.post = fake_post
    try:
        return fn()
    finally:
        providers.requests.post = original


SCHEMA = {"type": "object"}
GOOD = '{"ok": 1}'


def test_nvidia_model_profiles():
    """Each NIM model sends exactly its documented reasoning controls."""
    reasoning_keys = ("reasoning_effort", "chat_template_kwargs", "thinking",
                     "enable_thinking", "thinking_level", "reasoningMode")
    cases = {
        "nvidia/nemotron-3-ultra-550b-a55b": dict(
            ctk={"enable_thinking": True, "medium_effort": True},
            temperature=1.0, top_p=0.95),
        "nvidia/nemotron-3-super-120b-a12b": dict(
            effort="low", temperature=1.0, top_p=0.95),
        "deepseek-ai/deepseek-v4-pro": dict(
            effort="high", temperature=1.0, top_p=0.95),
        "qwen/qwen3.5-397b-a17b": dict(
            ctk={"enable_thinking": True}, temperature=0.6, top_p=0.95,
            top_k=20, presence_penalty=0.0),
        "z-ai/glm-5.2": dict(temperature=0.1),  # provider-default reasoning
        "mistralai/mistral-medium-3.5-128b": dict(
            effort="high", temperature=0.7),
    }
    for model, want in cases.items():
        captured = []

        def fake_post(url, json=None, timeout=None, headers=None):
            captured.append(json)
            return nvidia_ok(GOOD)

        provider = providers.NvidiaProvider(model)
        result = with_post(fake_post,
                           lambda: provider.draft("sys", "user", SCHEMA))
        check(result == {"ok": 1}, f"{model}: draft parsed")
        p = captured[0]
        # drafts get 16384 out (NIM reasoning counts against max_tokens
        # and fulltext groups need long bilingual answers); repair stays 8192
        check(p["model"] == model and p["max_tokens"] == 16384
              and p["stream"] is False, f"{model}: base payload")
        check(p.get("temperature") == want["temperature"],
              f"{model}: temperature {p.get('temperature')}")
        if "top_p" in want:
            check(p.get("top_p") == want["top_p"], f"{model}: top_p")
        if "top_k" in want:
            check(p.get("top_k") == want["top_k"]
                  and p.get("presence_penalty") == want["presence_penalty"],
                  f"{model}: qwen thinking-mode sampling")
        if "ctk" in want:
            check(p.get("chat_template_kwargs") == want["ctk"]
                  and "reasoning_effort" not in p,
                  f"{model}: chat_template_kwargs {p.get('chat_template_kwargs')}")
        elif "effort" in want:
            check(p.get("reasoning_effort") == want["effort"]
                  and "chat_template_kwargs" not in p,
                  f"{model}: reasoning_effort {p.get('reasoning_effort')}")
        else:  # GLM: no reasoning field of any kind on the wire
            check(all(k not in p for k in reasoning_keys),
                  f"{model}: no invented reasoning fields, got {sorted(p)}")
    print("test_nvidia_model_profiles: done")


def test_model_priority_defaults():
    expected = (
        "wechat:Deepseek-v4-flash",
        "opencode:claude-sonnet-4-6",
        "opencode:gpt-5.5",
        "gemini:gemini-3.6-flash",
        "opencode:gemini-3.1-pro",
        "opencode:qwen3.6-plus",
        "nvidia:z-ai/glm-5.2",
        "opencode:glm-5.1",
        "opencode:kimi-k2.6",
        "gemini:gemini-3.5-flash",
        "nvidia:deepseek-ai/deepseek-v4-pro",
        "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
        "nvidia:qwen/qwen3.5-397b-a17b",
        "nvidia:nvidia/nemotron-3-super-120b-a12b",
        "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
        "nvidia:mistralai/mistral-medium-3.5-128b",
        "openrouter:google/gemma-4-31b-it:free",
        "openrouter:inclusionai/ling-3.0-flash:free",
        "openrouter:google/gemma-4-26b-a4b-it:free",
        "openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "openrouter:openai/gpt-oss-20b:free",
        "openrouter:nvidia/nemotron-3-nano-30b-a3b:free",
        "openrouter:nvidia/nemotron-nano-12b-v2-vl:free",
        "openrouter:nvidia/nemotron-nano-9b-v2:free",
        "openrouter:poolside/laguna-s-2.1:free",
        "openrouter:cohere/north-mini-code:free",
        "openrouter:poolside/laguna-xs-2.1:free",
    )
    check(providers.MODEL_ORDER == expected,
          "model priority order matches the configured product order")
    check(providers.DEFAULT_ORDER == ",".join(expected),
          "fallback default derives from model priority order")
    check(providers.GEMINI_DEFAULT_MODEL == "gemini-3.6-flash",
          "Gemini 3.6 Flash is the default model")
    check(providers.NVIDIA_DEFAULT_MODEL == "z-ai/glm-5.2",
          "GLM 5.2 is the highest-priority NVIDIA default")
    check(providers.OPENROUTER_DEFAULT_MODEL
          == "nvidia/nemotron-3-ultra-550b-a55b:free",
          "Nemotron Ultra is the highest-priority OpenRouter default")
    check(providers.OPENCODE_DEFAULT_MODEL == "claude-sonnet-4-6",
          "Claude Sonnet 4.6 is the highest-priority OpenCode default")
    check(providers.WECHAT_DEFAULT_MODEL == "Deepseek-v4-flash",
          "DeepSeek V4 Flash is the WeChat Coding Plan default")
    check(expected[11:13] == (
        "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
        "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    ) and expected[14:16] == (
        "nvidia:nvidia/nemotron-3-super-120b-a12b",
        "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
    ), "equivalent Nemotron models are adjacent with native NVIDIA first")
    print("test_model_priority_defaults: done")


def test_wechat_protocol_and_payloads():
    """The contest token uses the WeChat OpenAI-compatible gateway."""
    saved_key = os.environ.get("WECHAT_API_KEY")
    saved_model = os.environ.get("AVWIRE_WECHAT_MODEL")
    saved_order = os.environ.get("AVWIRE_PROVIDER_ORDER")
    os.environ["WECHAT_API_KEY"] = "wechat-test-token"
    os.environ.pop("AVWIRE_WECHAT_MODEL", None)
    os.environ.pop("AVWIRE_PROVIDER_ORDER", None)
    try:
        captured = []

        def fake_post(url, json=None, timeout=None, headers=None):
            captured.append((url, json, headers))
            return FakeResponse({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": GOOD,
                        "reasoning_content": "PRIVATE-TRACE",
                    },
                }],
                "usage": {"prompt_tokens": 17, "completion_tokens": 9},
            }, headers={"x-request-id": "wechat-safe"})

        provider = providers.WechatProvider()
        result = with_post(
            fake_post, lambda: provider.draft("sys", "user", SCHEMA))
        url, payload, headers = captured[0]
        check(result == {"ok": 1}, "WeChat draft parsed")
        check(url == ("https://chatapi.weixin.qq.com/openai/v1/"
                      "chat/completions"), "WeChat endpoint is exact")
        check(payload["model"] == "Deepseek-v4-flash"
              and payload["max_tokens"] == 16384
              and payload["stream"] is False,
              "WeChat OpenAI payload uses the contest model")
        check(payload.get("thinking") == {"type": "disabled"},
              "WeChat disables hidden reasoning for JSON drafting")
        check(headers.get("Authorization") ==
              "Bearer wechat-test-token"
              and headers.get("Content-Type") == "application/json",
              "WeChat uses bearer authentication without rewriting the token")
        check(provider.usage["inputTokens"] == 17
              and provider.usage["outputTokens"] == 9
              and provider.request_log[0]["headers"]
              == {"x-request-id": "wechat-safe"},
              "WeChat usage and safe telemetry are recorded")

        calls = []

        def fake_repair(url, json=None, timeout=None, headers=None):
            calls.append(json)
            content = '{"ok": 1,,}' if len(calls) == 1 else GOOD
            return FakeResponse({"choices": [{
                "finish_reason": "stop",
                "message": {"content": content},
            }]})

        provider = providers.WechatProvider()
        result = with_post(
            fake_repair, lambda: provider.draft("sys", "user", SCHEMA))
        check(result == {"ok": 1} and len(calls) == 2,
              "WeChat malformed JSON gets one syntax repair")
        check(calls[1].get("thinking") == {"type": "disabled"}
              and calls[1]["max_tokens"] == 8192,
              "WeChat repair keeps hidden reasoning disabled")

        automatic = [
            row.label for row in providers.build_providers()
            if row.name == "wechat"
        ]
        check(automatic == ["wechat:Deepseek-v4-flash"],
              "automatic writer exposes the WeChat provider in priority order")
        try:
            provider._final_text(FakeResponse({"error": {"code": 401}}))
            check(False, "embedded WeChat 401 must disable the bad token")
        except providers.ProviderAuthError:
            check(True, "embedded WeChat auth error is classified safely")
        check("wechat-test-token" not in providers.safe_failure_message(
            "failed token=wechat-test-token"),
              "WeChat token is redacted from diagnostics")
    finally:
        if saved_key is None:
            os.environ.pop("WECHAT_API_KEY", None)
        else:
            os.environ["WECHAT_API_KEY"] = saved_key
        if saved_model is None:
            os.environ.pop("AVWIRE_WECHAT_MODEL", None)
        else:
            os.environ["AVWIRE_WECHAT_MODEL"] = saved_model
        if saved_order is None:
            os.environ.pop("AVWIRE_PROVIDER_ORDER", None)
        else:
            os.environ["AVWIRE_PROVIDER_ORDER"] = saved_order
    print("test_wechat_protocol_and_payloads: done")


def test_openrouter_models_and_payloads():
    models = [
        token.split(":", 1)[1]
        for token in providers.MODEL_ORDER
        if token.startswith("openrouter:")
    ]
    check(len(models) == 13, "all 13 OpenRouter models are configured")
    for model in models:
        captured = []

        def fake_post(url, json=None, timeout=None, headers=None):
            captured.append((url, json, headers))
            return FakeResponse({
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "content": GOOD,
                        "reasoning": "PRIVATE-TRACE",
                    },
                }],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            }, headers={
                "x-ratelimit-remaining": "4",
                "authorization": "must-not-be-captured",
            })

        provider = providers.OpenRouterProvider(model)
        result = with_post(
            fake_post, lambda: provider.draft("sys", "user", SCHEMA))
        url, payload, headers = captured[0]
        check(result == {"ok": 1}, f"{model}: OpenRouter draft parsed")
        check(url == "https://openrouter.ai/api/v1/chat/completions"
              and payload["model"] == model
              and payload["max_tokens"] == 16384,
              f"{model}: OpenRouter endpoint and model")
        check((payload.get("reasoning") or {}).get("exclude") is True,
              f"{model}: reasoning trace excluded")
        check(headers.get("X-Title") == "AVWIRE"
              and headers.get("HTTP-Referer") == "https://skytical.tech/",
              f"{model}: optional attribution headers")
        check(provider.usage["inputTokens"] == 11
              and provider.usage["outputTokens"] == 7
              and provider.request_log[0]["headers"]
              == {"x-ratelimit-remaining": "4"},
              f"{model}: usage and safe rate-limit telemetry")

    calls = []

    def fake_repair(url, json=None, timeout=None, headers=None):
        calls.append(json)
        return nvidia_ok('{"ok": 1,,}' if len(calls) == 1 else GOOD)

    provider = providers.OpenRouterProvider(models[0])
    result = with_post(
        fake_repair, lambda: provider.draft("sys", "user", SCHEMA))
    check(result == {"ok": 1} and len(calls) == 2,
          "OpenRouter malformed JSON gets one syntax repair")
    check(calls[1].get("reasoning")
          == {"effort": "low", "exclude": True},
          "OpenRouter repair uses low hidden reasoning")

    try:
        provider._check_status(FakeResponse({}, status=429))
        check(False, "OpenRouter 429 must trigger model fallback")
    except providers.ProviderQuotaError:
        check(False, "OpenRouter 429 must not disable every model")
    except providers.ProviderError:
        check(True, "OpenRouter 429 keeps the shared key for next model")
    check("sk-or-v1-SECRET" not in providers.safe_failure_message(
        "failed key=sk-or-v1-SECRET"),
        "OpenRouter key is redacted from diagnostics")

    saved = {
        key: os.environ.get(key)
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                    "NVIDIA_API_KEY", "OPENROUTER_API_KEY",
                    "AVWIRE_PROVIDER_ORDER")
    }
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY",
                "AVWIRE_PROVIDER_ORDER"):
        os.environ.pop(key, None)
    os.environ["OPENROUTER_API_KEY"] = "test-key-not-real"
    try:
        automatic = [
            row.label for row in providers.build_providers()
            if row.name == "openrouter"
        ]
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check(automatic == [
        token for token in providers.MODEL_ORDER
        if token.startswith("openrouter:")
    ], "automatic writer exposes all OpenRouter fallbacks in owner order")

    try:
        provider._final_text(FakeResponse({"error": {"code": 401}}))
        check(False, "embedded OpenRouter 401 must disable the bad key")
    except providers.ProviderAuthError:
        check(True, "embedded OpenRouter auth error is classified safely")
    print("test_openrouter_models_and_payloads: done")


def test_opencode_protocols_and_payloads():
    """Console models use their documented provider-compatible endpoints."""
    cases = {
        "claude-sonnet-4-6": "anthropic/v1/messages",
        "gpt-5.5": "openai/v1/responses",
        "gemini-3.1-pro": "gemini/v1beta/models/",
        "qwen3.6-plus": "anthropic/v1/messages",
        "glm-5.1": "openai/v1/chat/completions",
        "kimi-k2.6": "openai/v1/chat/completions",
    }
    for model, endpoint in cases.items():
        captured = []

        def fake_post(url, json=None, timeout=None, headers=None):
            captured.append((url, json, headers))
            if url.endswith("/responses"):
                payload = {
                    "status": "completed",
                    "output": [{"type": "message", "content": [{
                        "type": "output_text", "text": GOOD,
                    }]}],
                    "usage": {"input_tokens": 13, "output_tokens": 8},
                }
            elif "/anthropic/" in url:
                payload = {
                    "stop_reason": "end_turn",
                    "content": [{"type": "text", "text": GOOD}],
                    "usage": {"input_tokens": 13, "output_tokens": 8},
                }
            elif "/gemini/" in url:
                payload = {
                    "candidates": [{"finishReason": "STOP", "content": {
                        "parts": [{"thought": True, "text": "PRIVATE"},
                                  {"text": GOOD}],
                    }}],
                    "usageMetadata": {
                        "promptTokenCount": 13, "candidatesTokenCount": 8,
                    },
                }
            else:
                payload = {
                    "choices": [{"finish_reason": "stop", "message": {
                        "content": GOOD, "reasoning_content": "PRIVATE",
                    }}],
                    "usage": {"prompt_tokens": 13,
                              "completion_tokens": 8},
                }
            return FakeResponse(payload, headers={
                "x-request-id": "req-safe",
                "authorization": "must-not-be-captured",
            })

        provider = providers.OpenCodeProvider(model)
        result = with_post(
            fake_post, lambda: provider.draft("sys", "user", SCHEMA))
        url, payload, headers = captured[0]
        check(result == {"ok": 1}, f"{model}: OpenCode draft parsed")
        check(endpoint in url, f"{model}: routed to {endpoint}")
        check(provider.usage["inputTokens"] == 13
              and provider.usage["outputTokens"] == 8,
              f"{model}: usage recorded")
        check(provider.request_log[0]["headers"]
              == {"x-request-id": "req-safe"},
              f"{model}: credentials excluded from telemetry")
        if model.startswith("gpt-"):
            check(payload["text"]["format"]["schema"] == SCHEMA
                  and headers.get("Authorization", "").startswith("Bearer "),
                  f"{model}: Responses schema and bearer auth")
        elif model.startswith("claude-"):
            check(payload["output_config"]["format"]["schema"] == SCHEMA
                  and headers.get("x-api-key", "").startswith("oc_sk_"),
                  f"{model}: Messages schema and x-api-key auth")
        elif model.startswith("gemini-"):
            check(payload["generationConfig"]["responseJsonSchema"] == SCHEMA
                  and headers.get("x-goog-api-key", "").startswith("oc_sk_"),
                  f"{model}: Gemini schema and x-goog auth")
        else:
            system = payload.get("system") or (
                payload.get("messages") or [{}])[0].get("content", "")
            check("JSON Schema" in system,
                  f"{model}: prompt-enforced JSON schema")

    provider = providers.OpenCodeProvider("gpt-5.5")
    try:
        provider._check_status(FakeResponse({}, status=401))
        check(False, "OpenCode 401 must disable the service account")
    except providers.ProviderAuthError:
        check(True, "OpenCode 401 is classified as authentication failure")
    try:
        provider._check_status(FakeResponse({}, status=429))
        check(False, "OpenCode 429 must trigger model fallback")
    except providers.ProviderQuotaError:
        check(False, "OpenCode 429 must not disable every model")
    except providers.ProviderError:
        check(True, "OpenCode 429 preserves the key for the next model")
    check("oc_sk_SECRET" not in providers.safe_failure_message(
        "failed key=oc_sk_SECRET"),
        "OpenCode key is redacted from diagnostics")

    saved = {
        key: os.environ.get(key)
        for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                    "NVIDIA_API_KEY", "OPENROUTER_API_KEY",
                    "OPENCODE_API_KEY", "AVWIRE_PROVIDER_ORDER")
    }
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY",
                "OPENROUTER_API_KEY", "AVWIRE_PROVIDER_ORDER"):
        os.environ.pop(key, None)
    os.environ["OPENCODE_API_KEY"] = "oc_sk_test-not-real"
    try:
        automatic = [
            row.label for row in providers.build_providers()
            if row.name == "opencode"
        ]
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check(automatic == [
        token for token in providers.MODEL_ORDER
        if token.startswith("opencode:")
    ], "automatic writer exposes all OpenCode fallbacks in owner order")
    print("test_opencode_protocols_and_payloads: done")


def test_nvidia_reasoning_trace_never_parsed():
    """reasoning_content is ignored; empty final content is a failure."""
    def fake_post(url, json=None, timeout=None, headers=None):
        return nvidia_ok(GOOD, reasoning='{"leak": true}')

    provider = providers.NvidiaProvider("nvidia/nemotron-3-ultra-550b-a55b")
    result = with_post(fake_post,
                       lambda: provider.draft("sys", "user", SCHEMA))
    check(result == {"ok": 1} and "leak" not in result,
          "final content parsed, reasoning trace ignored")

    def fake_post_empty(url, json=None, timeout=None, headers=None):
        return nvidia_ok("", reasoning=GOOD)

    try:
        with_post(fake_post_empty,
                  lambda: provider.draft("sys", "user", SCHEMA))
        check(False, "empty final content must raise, not fall back to trace")
    except providers.ProviderError:
        check(True, "empty final content raises ProviderError")
    print("test_nvidia_reasoning_trace_never_parsed: done")


def test_nvidia_format_repair():
    """Broken JSON syntax triggers ONE no-thinking repair call."""
    calls = []

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append(json)
        if len(calls) == 1:
            return nvidia_ok('{"ok": 1,,}')  # syntax error
        return nvidia_ok(GOOD)

    provider = providers.NvidiaProvider("nvidia/nemotron-3-super-120b-a12b")
    result = with_post(fake_post,
                       lambda: provider.draft("sys", "user", SCHEMA))
    check(result == {"ok": 1}, "repair produced a parseable draft")
    check(len(calls) == 2, f"exactly one repair call, got {len(calls)}")
    check(provider.http_calls == 2 and provider.repair_calls == 1
          and provider.http_duration_ms >= provider.repair_duration_ms >= 0,
          "NVIDIA counters separate total HTTP and repair calls")
    repair = calls[1]
    check(repair["messages"][0]["content"] == providers.REPAIR_SYSTEM_PROMPT,
          "repair uses the syntax-only system prompt")
    check(repair.get("reasoning_effort") == "none",
          f"repair disables reasoning, got {repair.get('reasoning_effort')}")
    check(calls[0].get("reasoning_effort") == "low",
          "normal call keeps its configured reasoning")
    print("test_nvidia_format_repair: done")


def test_gemini_model_profiles():
    """Gemini 3.6/3.5 send thinkingLevel high; unknown models send none."""
    for model in ("gemini-3.6-flash", "gemini-3.5-flash"):
        captured = []

        def fake_post(url, json=None, timeout=None, headers=None):
            captured.append(json)
            return gemini_ok([{"text": GOOD}])

        provider = providers.GeminiProvider(model)
        result = with_post(fake_post,
                           lambda: provider.draft("sys", "user", SCHEMA))
        check(result == {"ok": 1}, f"{model}: draft parsed")
        config = captured[0]["generationConfig"]
        check(config.get("thinkingConfig") == {"thinkingLevel": "high"},
              f"{model}: thinkingLevel high")
        check("temperature" not in config
              and config.get("maxOutputTokens") == 16384,
              f"{model}: no temperature on Gemini 3.x (tuned defaults)")
        check(config.get("responseMimeType") == "application/json"
              and config.get("responseJsonSchema") == SCHEMA,
              f"{model}: structured output config kept")

    captured = []

    def fake_post(url, json=None, timeout=None, headers=None):
        captured.append(json)
        return gemini_ok([{"text": GOOD}])

    provider = providers.GeminiProvider("gemini-2.5-flash")
    with_post(fake_post, lambda: provider.draft("sys", "user", SCHEMA))
    check("thinkingConfig" not in captured[0]["generationConfig"],
          "unprofiled Gemini model sends no thinkingConfig")
    print("test_gemini_model_profiles: done")


def test_gemini_thought_parts_excluded():
    """Thought parts (reasoning trace) never reach the parser or output."""
    def fake_post(url, json=None, timeout=None, headers=None):
        return gemini_ok([
            {"thought": True, "text": '{"leak": "reasoning JSON"}'},
            {"text": GOOD},
        ])

    provider = providers.GeminiProvider("gemini-3.6-flash")
    result = with_post(fake_post,
                       lambda: provider.draft("sys", "user", SCHEMA))
    check(result == {"ok": 1} and "leak" not in result,
          "only final (non-thought) parts are parsed")

    def fake_post_only_thought(url, json=None, timeout=None, headers=None):
        return gemini_ok([{"thought": True, "text": GOOD}])

    try:
        with_post(fake_post_only_thought,
                  lambda: provider.draft("sys", "user", SCHEMA))
        check(False, "thought-only response must raise")
    except providers.ProviderError:
        check(True, "thought-only response raises ProviderError")
    print("test_gemini_thought_parts_excluded: done")


def test_gemini_format_repair():
    calls = []

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.append(json)
        if len(calls) == 1:
            return gemini_ok([{"text": '{"ok": 1'}])  # truncated syntax
        return gemini_ok([{"text": GOOD}])

    provider = providers.GeminiProvider("gemini-3.6-flash")
    result = with_post(fake_post,
                       lambda: provider.draft("sys", "user", SCHEMA))
    check(result == {"ok": 1}, "gemini repair produced a parseable draft")
    check(len(calls) == 2, f"exactly one repair call, got {len(calls)}")
    check(provider.http_calls == 2 and provider.repair_calls == 1
          and provider.http_duration_ms >= provider.repair_duration_ms >= 0,
          "Gemini counters separate total HTTP and repair calls")
    repair_config = calls[1]["generationConfig"]
    check(repair_config.get("thinkingConfig") == {"thinkingLevel": "minimal"},
          "repair drops to minimal thinking")
    check(calls[1]["systemInstruction"]["parts"][0]["text"]
          == providers.REPAIR_SYSTEM_PROMPT,
          "repair uses the syntax-only system prompt")
    print("test_gemini_format_repair: done")


def main():
    tests = [
        test_model_priority_defaults,
        test_wechat_protocol_and_payloads,
        test_opencode_protocols_and_payloads,
        test_openrouter_models_and_payloads,
        test_nvidia_model_profiles,
        test_nvidia_reasoning_trace_never_parsed,
        test_nvidia_format_repair,
        test_gemini_model_profiles,
        test_gemini_thought_parts_excluded,
        test_gemini_format_repair,
    ]
    for test in tests:
        test()
    print(f"{_pass} checks passed, {_fail} failed")
    if _fail:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()

