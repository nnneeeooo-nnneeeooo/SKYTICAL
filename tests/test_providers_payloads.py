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
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

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
        "gemini:gemini-3.6-flash",
        "gemini:gemini-3.5-flash",
        "nvidia:z-ai/glm-5.2",
        "nvidia:deepseek-ai/deepseek-v4-pro",
        "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
        "nvidia:qwen/qwen3.5-397b-a17b",
        "nvidia:nvidia/nemotron-3-super-120b-a12b",
        "nvidia:mistralai/mistral-medium-3.5-128b",
    )
    check(providers.MODEL_ORDER == expected,
          "model priority order matches the configured product order")
    check(providers.DEFAULT_ORDER == ",".join(expected),
          "fallback default derives from model priority order")
    check(providers.GEMINI_DEFAULT_MODEL == "gemini-3.6-flash",
          "Gemini 3.6 Flash is the default model")
    check(providers.NVIDIA_DEFAULT_MODEL == "z-ai/glm-5.2",
          "GLM 5.2 is the highest-priority NVIDIA default")
    print("test_model_priority_defaults: done")


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
