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

The write stage tries providers in AVWIRE_PROVIDER_ORDER (default
"anthropic,gemini,nvidia") and falls through to the next on failure.
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

try:
    import anthropic
except ImportError:  # pragma: no cover - anthropic is in requirements.txt
    anthropic = None

DEFAULT_ORDER = "anthropic,gemini,nvidia"
HTTP_TIMEOUT = (10, 120)  # (connect, read) seconds

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


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model=None) -> None:
        # `or` (not a get() default) so an empty env var still falls back.
        self.model = model or os.environ.get("AVWIRE_MODEL") or "claude-opus-5"
        self.label = f"{self.name}:{self.model}"
        self._client = None

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY")) and anthropic is not None

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        if self._client is None:
            self._client = anthropic.Anthropic()
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
                      or "gemini-2.5-flash")
        self.label = f"{self.name}:{self.model}"

    def available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent")
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseJsonSchema": schema,
            },
        }
        try:
            response = requests.post(
                url, json=payload, timeout=HTTP_TIMEOUT,
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            )
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
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
        data = response.json()
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
        text = "".join(p.get("text", "") for p in parts)
        if not text.strip():
            raise ProviderError("empty response text")
        try:
            return extract_json(text)
        except ValueError as exc:
            raise ProviderError(f"bad JSON from model: {exc}") from exc


class NvidiaProvider:
    name = "nvidia"

    def __init__(self, model=None) -> None:
        self.model = (model or os.environ.get("AVWIRE_NVIDIA_MODEL")
                      or "deepseek-ai/deepseek-v3.1")
        self.label = f"{self.name}:{self.model}"

    def available(self) -> bool:
        return bool(os.environ.get("NVIDIA_API_KEY"))

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        # No guided decoding on NIM across all models: enforce JSON by prompt
        # and recover it with extract_json; the caller validates the shape.
        instruction = (
            "\n\nReturn ONLY one JSON object (no markdown fences, no prose) "
            "conforming exactly to this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt + instruction},
            ],
            "temperature": 0.2,
            "max_tokens": 8192,
            "stream": False,
        }
        try:
            response = requests.post(
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
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"HTTP {response.status_code}")
        if response.status_code in (402, 429):
            raise ProviderQuotaError(
                f"HTTP {response.status_code} (credits exhausted?)")
        if response.status_code == 404:
            raise ProviderError(
                f"model not found: {self.model} "
                "(set repo variable AVWIRE_NVIDIA_MODEL)")
        if response.status_code >= 400:
            raise ProviderError(
                f"HTTP {response.status_code}: {_body_snippet(response)}")
        data = response.json()
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
        try:
            return extract_json(text)
        except ValueError as exc:
            raise ProviderError(f"bad JSON from model: {exc}") from exc


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
