"""LLM provider adapters for the write stage.

Three interchangeable writers behind one interface:

    anthropic  Anthropic Messages API with native structured outputs
    gemini     Google Gemini API (REST) with responseJsonSchema
    nvidia     NVIDIA NIM (integrate.api.nvidia.com, OpenAI-compatible REST),
               JSON enforced by prompt + local extraction

Each provider exposes:
    name         registry key
    label        "name:model" for logs and the article's "writer" field
    available()  True when its API key env var is set (and deps import)
    draft(system_prompt, user_prompt, schema) -> dict | None
        dict = parsed draft JSON (caller validates the shape)
        None = genuine content refusal / safety block (do NOT retry the
               group on another provider)
        raises ProviderAuthError  key rejected -> disable provider this run
        raises ProviderQuotaError quota/credits gone -> disable this run
        raises ProviderError      failure of this one call (truncation,
               bad JSON, transient HTTP) -> try the next provider

The write stage tries providers in AVWIRE_PROVIDER_ORDER (defaulting to the
configured MODEL_ORDER below) and falls through to the next on failure.
An order token may pin a model with "name:model", and the same platform
may appear multiple times with different models, e.g.:

    nvidia:nvidia/nemotron-3-ultra-550b-a55b,
    nvidia:nvidia/nemotron-3-super-120b-a12b,
    gemini,
    nvidia:qwen/qwen3.5-397b-a17b

A bare name uses the platform's AVWIRE_*_MODEL env var / default.
"""
from __future__ import annotations

import json
import os
import re

import requests
from model_config import DEFAULT_PROVIDER_ORDER, MODEL_ORDER

try:
    import anthropic
except ImportError:  # pragma: no cover - anthropic is in requirements.txt
    anthropic = None

DEFAULT_ORDER = DEFAULT_PROVIDER_ORDER
# 550B-class NIM models regularly need >120s on the free tier.
HTTP_TIMEOUT = (10, 180)  # (connect, read) seconds

# --------------------------------------------------------------------------
# Centralized per-model configuration - the single source of truth for
# model ids, reasoning controls and sampling. Do NOT scatter these fields
# into request builders. Each profile has:
#   payload / generationConfig  extras merged into normal verification calls
#   repair  reasoning overrides for the no-thinking "format repair" call
#           (JSON syntax only - content failures NEVER take this path)
# Only fields the respective endpoint documents are sent; models without a
# profile fall back to conservative generic settings.
NVIDIA_DEFAULT_MODEL = "z-ai/glm-5.2"
GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"

MODEL_PROFILES: dict = {
    # Gemini thinking is high for fact-sensitive bilingual drafting. Format
    # repair remains minimal because that call may only fix JSON syntax.
    # Temperature is intentionally omitted: Gemini 3.x uses its tuned default.
    "gemini-3.6-flash": {
        "generationConfig": {"maxOutputTokens": 16384,
                             "thinkingConfig": {"thinkingLevel": "high"}},
        "repairGenerationConfig": {
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingLevel": "minimal"}},
    },
    "gemini-3.5-flash": {
        "generationConfig": {"maxOutputTokens": 16384,
                             "thinkingConfig": {"thinkingLevel": "high"}},
        "repairGenerationConfig": {
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingLevel": "minimal"}},
    },
    "z-ai/glm-5.2": {
        # The public NIM schema for GLM exposes no reasoning control.
        # Low temperature improves factual consistency and JSON stability.
        "reasoningMode": "provider_default",
        "payload": {"temperature": 0.1},
        "repair": {},
    },
    "deepseek-ai/deepseek-v4-pro": {
        # High reasoning is retained for evidence-heavy verification work.
        "payload": {"temperature": 1.0, "top_p": 0.95,
                    "reasoning_effort": "high"},
        "repair": {"reasoning_effort": "none"},
    },
    "nvidia/nemotron-3-ultra-550b-a55b": {
        # Medium thinking balances verification quality with usable output.
        "payload": {"temperature": 1.0, "top_p": 0.95,
                    "chat_template_kwargs": {"enable_thinking": True,
                                             "medium_effort": True}},
        "repair": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "qwen/qwen3.5-397b-a17b": {
        # NIM exposes thinking on/off only for Qwen; thinking-mode sampling
        # per the model card.
        "payload": {"temperature": 0.6, "top_p": 0.95, "top_k": 20,
                    "presence_penalty": 0.0,
                    "chat_template_kwargs": {"enable_thinking": True}},
        "repair": {"chat_template_kwargs": {"enable_thinking": False}},
    },
    "nvidia/nemotron-3-super-120b-a12b": {
        # Low effort avoids consuming the full output budget before the
        # bilingual JSON answer, a failure observed with full reasoning.
        "payload": {"temperature": 1.0, "top_p": 0.95,
                    "reasoning_effort": "low"},
        "repair": {"reasoning_effort": "none"},
    },
    "mistralai/mistral-medium-3.5-128b": {
        # NIM offers none|high only; keep high for the final fallback.
        "payload": {"temperature": 0.7, "reasoning_effort": "high"},
        "repair": {"reasoning_effort": "none"},
    },
}

REPAIR_SYSTEM_PROMPT = (
    "You are a JSON syntax fixer. The user message is a single JSON object "
    "with broken syntax (quoting, escaping, commas, brackets or field "
    "arrangement). Return ONLY the corrected JSON object. Do not add, "
    "remove, reorder facts or change ANY content, field name or value - "
    "repair the syntax only."
)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


class ProviderError(Exception):
    """Transient failure of a single call; try the next provider."""


class ProviderAuthError(ProviderError):
    """Key invalid/forbidden; every later call is doomed this run."""


class ProviderQuotaError(ProviderError):
    """Rate/credit quota exhausted; stop using this provider this run."""


def extract_json(text: str) -> dict:
    """Parse a JSON object out of possibly-decorated model output.

    Tolerates <think> blocks, markdown fences and stray prose around the
    object. Raises ValueError when no JSON object can be recovered.
    """
    cleaned = _THINK_RE.sub("", str(text))
    cleaned = _FENCE_RE.sub("", cleaned.strip())
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in model output")
    parsed = json.loads(cleaned[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    return parsed


def _body_snippet(response) -> str:
    return response.text[:200].replace("\n", " ")


def _blank_usage() -> dict:
    """Per-provider token ledger, flushed to data/usage.json by usage.py.

    usageEvents counts responses that actually carried usage metadata;
    http_calls - usageEvents = calls whose token spend is unknown."""
    return {"inputTokens": 0, "outputTokens": 0, "usageEvents": 0}


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model=None) -> None:
        # `or` (not a get() default) so an empty env var still falls back.
        self.model = model or os.environ.get("AVWIRE_MODEL") or "claude-opus-5"
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0
        self.usage = _blank_usage()
        self._client = None

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY")) and anthropic is not None

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        if self._client is None:
            self._client = anthropic.Anthropic()
        self.http_calls += 1
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                # "medium" effort bounds adaptive-thinking spend so thinking
                # cannot eat the 16000-token cap on this bounded task.
                output_config={"effort": "medium",
                               "format": {"type": "json_schema",
                                          "schema": schema}},
            )
        except (anthropic.AuthenticationError,
                anthropic.PermissionDeniedError) as exc:
            raise ProviderAuthError(type(exc).__name__) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderQuotaError(type(exc).__name__) from exc
        except anthropic.APIStatusError as exc:
            # Out-of-credits surfaces as 400/402, not as an auth error.
            if exc.status_code == 402 or "credit balance" in str(exc).lower():
                raise ProviderQuotaError(
                    f"{type(exc).__name__} (credits exhausted)") from exc
            raise ProviderError(type(exc).__name__) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(type(exc).__name__) from exc
        usage = getattr(response, "usage", None)
        if usage is not None:
            self.usage["inputTokens"] += int(
                getattr(usage, "input_tokens", 0) or 0)
            self.usage["outputTokens"] += int(
                getattr(usage, "output_tokens", 0) or 0)
            self.usage["usageEvents"] += 1
        if response.stop_reason == "refusal":
            print(f"write: {self.label} refused")
            return None
        if response.stop_reason == "max_tokens":
            # Truncation is a provider limitation, not a property of the
            # story: raise so the failover loop can try the next provider.
            raise ProviderError("response truncated (max_tokens)")
        text = next(
            (block.text for block in response.content
             if getattr(block, "type", None) == "text"),
            None,
        )
        if text is None:
            raise ProviderError("no text block in response")
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ProviderError(f"bad JSON from model: {exc}") from exc


class GeminiProvider:
    name = "gemini"

    def __init__(self, model=None) -> None:
        self.model = (model or os.environ.get("AVWIRE_GEMINI_MODEL")
                      or GEMINI_DEFAULT_MODEL)
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0  # real API spend incl. format-repair calls
        self.usage = _blank_usage()

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def _check_status(self, response) -> None:
        """Shared auth/quota classification - the repair path must classify
        failures exactly like the draft path, or a dead key survives one
        extra doomed call per group."""
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"HTTP {response.status_code}")
        if response.status_code == 400 and (
                "API_KEY_INVALID" in response.text
                or "API key expired" in response.text):
            # Gemini reports a bad/expired key as 400 INVALID_ARGUMENT,
            # not 401/403 - it must still disable the provider.
            raise ProviderAuthError("HTTP 400 (invalid or expired API key)")
        if response.status_code == 429:
            # 429 covers per-minute RPM/TPM (clears in seconds) and per-day
            # quota alike; only the latter should kill the provider.
            if "PerMinute" in response.text:
                raise ProviderError("HTTP 429 (per-minute rate limit)")
            raise ProviderQuotaError("HTTP 429 (free-tier quota exhausted?)")
        if response.status_code >= 400:
            raise ProviderError(
                f"HTTP {response.status_code}: {_body_snippet(response)}")

    def _generation_config(self, schema: dict, repair: bool) -> dict:
        profile = MODEL_PROFILES.get(self.model, {})
        key = "repairGenerationConfig" if repair else "generationConfig"
        config = dict(profile.get(key) or {})
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = schema
        return config

    def _post(self, payload: dict):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent")
        self.http_calls += 1
        try:
            return requests.post(
                url, json=payload, timeout=HTTP_TIMEOUT,
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            )
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": self._generation_config(schema, repair=False),
        }
        response = self._post(payload)
        self._check_status(response)
        text = self._final_text(response)
        if text is None:
            return None
        try:
            return extract_json(text)
        except ValueError as exc:
            return self._repair(text, schema, exc)

    def _final_text(self, response):
        """Final-answer text only. Returns None for genuine content blocks;
        raises ProviderError on technical failures. Thought parts (the
        reasoning trace) are excluded and never reach the JSON parser, the
        published data or the logs."""
        data = response.json()
        meta = data.get("usageMetadata") or {}
        if meta:
            self.usage["inputTokens"] += int(
                meta.get("promptTokenCount") or 0)
            # thinking tokens are billed output tokens too
            self.usage["outputTokens"] += (
                int(meta.get("candidatesTokenCount") or 0)
                + int(meta.get("thoughtsTokenCount") or 0))
            self.usage["usageEvents"] += 1
        feedback = data.get("promptFeedback") or {}
        if feedback.get("blockReason"):
            print(f"write: {self.label} blocked ({feedback['blockReason']})")
            return None
        candidates = data.get("candidates") or []
        if not candidates:
            raise ProviderError("no candidates in response")
        candidate = candidates[0]
        finish = candidate.get("finishReason")
        if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST",
                      "IMAGE_SAFETY", "SPII"):
            # Content-based block: a genuine refusal, not a provider fault.
            print(f"write: {self.label} blocked ({finish})")
            return None
        if finish not in (None, "STOP"):
            # MAX_TOKENS, RECITATION, ...: provider-specific failure - let
            # the failover loop try the next provider.
            raise ProviderError(f"finishReason {finish}")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            p.get("text", "") for p in parts
            if isinstance(p, dict) and not p.get("thought"))
        if not text.strip():
            raise ProviderError("empty response text")
        return text

    def _repair(self, broken: str, schema: dict, exc) -> dict:
        """One minimal-thinking retry that fixes JSON SYNTAX only.

        Content problems (missing quotes, unsupported claims) never take
        this path - they surface after parsing and are handled by the
        failover policy in write.py.
        """
        print(f"write: {self.label} returned malformed JSON ({exc}); "
              "attempting format repair")
        payload = {
            "systemInstruction": {"parts": [{"text": REPAIR_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": broken}]}],
            "generationConfig": self._generation_config(schema, repair=True),
        }
        response = self._post(payload)
        self._check_status(response)
        text = self._final_text(response)
        if not text:
            raise ProviderError("format repair returned no text")
        try:
            return extract_json(text)
        except ValueError as repair_exc:
            raise ProviderError(
                f"bad JSON even after format repair: {repair_exc}"
            ) from repair_exc


class NvidiaProvider:
    name = "nvidia"

    def __init__(self, model=None) -> None:
        self.model = (model or os.environ.get("AVWIRE_NVIDIA_MODEL")
                      or NVIDIA_DEFAULT_MODEL)
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0  # real API spend incl. format-repair calls
        self.usage = _blank_usage()

    def available(self) -> bool:
        return bool(os.environ.get("NVIDIA_API_KEY"))

    def _payload_extras(self, repair: bool) -> dict:
        profile = MODEL_PROFILES.get(self.model, {})
        extras = dict(profile.get("payload") or {"temperature": 0.2})
        if repair:
            # Repair overrides replace the reasoning control wholesale;
            # sampling stays as configured for the model.
            extras.update(profile.get("repair") or {})
        return extras

    def _post(self, messages: list, repair: bool):
        payload = {
            "model": self.model,
            "messages": messages,
            # 16384 for drafts: NIM reasoning tokens count against
            # max_tokens, and fulltext-enriched groups need a long
            # bilingual answer on top (Super truncated at 8192 before).
            "max_tokens": 8192 if repair else 16384,
            "stream": False,
            **self._payload_extras(repair),
        }
        self.http_calls += 1
        try:
            return requests.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                json=payload, timeout=HTTP_TIMEOUT,
                headers={
                    "Authorization":
                        f"Bearer {os.environ['NVIDIA_API_KEY']}",
                    "Accept": "application/json",
                },
            )
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc

    def _final_text(self, response):
        """Final-answer text only; message.reasoning_content (the reasoning
        trace some NIM models emit) is never read, parsed, published or
        logged. Returns None for content blocks; raises on failures."""
        data = response.json()
        usage = data.get("usage") or {}
        if usage:
            self.usage["inputTokens"] += int(usage.get("prompt_tokens") or 0)
            self.usage["outputTokens"] += int(
                usage.get("completion_tokens") or 0)
            self.usage["usageEvents"] += 1
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("no choices in response")
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish == "content_filter":
            print(f"write: {self.label} blocked (content_filter)")
            return None
        if finish == "length":
            # Truncation (possibly reasoning eating the cap): provider
            # limitation, so let the failover loop try the next provider.
            raise ProviderError("response truncated (length)")
        text = (choice.get("message") or {}).get("content") or ""
        if not text.strip():
            raise ProviderError("empty response content")
        return text

    def _check_status(self, response) -> None:
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"HTTP {response.status_code}")
        if response.status_code in (402, 429):
            raise ProviderQuotaError(
                f"HTTP {response.status_code} (credits exhausted?)")
        if response.status_code == 404:
            raise ProviderError(
                f"model not found: {self.model} "
                "(not in this key's catalog yet?)")
        if response.status_code >= 400:
            raise ProviderError(
                f"HTTP {response.status_code}: {_body_snippet(response)}")

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        # No guided decoding on NIM across all models: enforce JSON by prompt
        # and recover it with extract_json; the caller validates the shape.
        instruction = (
            "\n\nReturn ONLY one JSON object (no markdown fences, no prose) "
            "conforming exactly to this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        response = self._post(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": user_prompt + instruction}],
            repair=False,
        )
        self._check_status(response)
        text = self._final_text(response)
        if text is None:
            return None
        try:
            return extract_json(text)
        except ValueError as exc:
            return self._repair(text, exc)

    def _repair(self, broken: str, exc) -> dict:
        """One no-thinking retry that fixes JSON SYNTAX only; content
        failures never take this path (see GeminiProvider._repair)."""
        print(f"write: {self.label} returned malformed JSON ({exc}); "
              "attempting format repair")
        response = self._post(
            [{"role": "system", "content": REPAIR_SYSTEM_PROMPT},
             {"role": "user", "content": broken}],
            repair=True,
        )
        self._check_status(response)
        text = self._final_text(response)
        if not text:
            raise ProviderError("format repair returned no text")
        try:
            return extract_json(text)
        except ValueError as repair_exc:
            raise ProviderError(
                f"bad JSON even after format repair: {repair_exc}"
            ) from repair_exc


_REGISTRY = {
    AnthropicProvider.name: AnthropicProvider,
    GeminiProvider.name: GeminiProvider,
    NvidiaProvider.name: NvidiaProvider,
}


def build_providers() -> list:
    """Instantiate available providers in AVWIRE_PROVIDER_ORDER order.

    A token is either a platform name ("nvidia") or a pinned model
    ("nvidia:nvidia/nemotron-3-ultra-550b-a55b"); the same platform may
    appear multiple times with different models.
    """
    order = os.environ.get("AVWIRE_PROVIDER_ORDER") or DEFAULT_ORDER
    providers, seen = [], set()
    for token in order.split(","):
        name, _, model = token.strip().partition(":")
        key = name.strip().lower()
        model = model.strip() or None
        if not key or (key, model) in seen:
            continue
        seen.add((key, model))
        cls = _REGISTRY.get(key)
        if cls is None:
            print(f"write: unknown provider '{key}' in AVWIRE_PROVIDER_ORDER; "
                  "ignoring")
            continue
        provider = cls(model)
        if provider.available():
            providers.append(provider)
    return providers
