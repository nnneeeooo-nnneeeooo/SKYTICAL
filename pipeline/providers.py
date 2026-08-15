"""LLM provider adapters for the write stage.

Five interchangeable writers behind one interface:

    anthropic  Anthropic Messages API with native structured outputs
    gemini     Google Gemini API (REST) with responseJsonSchema
    nvidia     NVIDIA NIM (integrate.api.nvidia.com, OpenAI-compatible REST),
               JSON enforced by prompt + local extraction
    openrouter OpenRouter Chat Completions (OpenAI-compatible REST),
               JSON enforced by prompt + local extraction
    opencode   OpenCode Console gateway, routing each model through its
               native Responses, Messages, Gemini or Chat Completions API

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
import time
from urllib.parse import urlsplit

import requests
from model_config import (
    DEFAULT_PROVIDER_ORDER,
    MODEL_ORDER,
    manual_reasoning_profile,
)

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
GEMINI_DEFAULT_MODEL = "gemini-3.7-flash"
OPENROUTER_DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
OPENCODE_DEFAULT_MODEL = "claude-sonnet-4-6"
OPENCODE_BASE_URL = "https://console.opencode.ai/inference"

MODEL_PROFILES: dict = {
    # Gemini thinking is high for fact-sensitive bilingual drafting. Format
    # repair remains minimal because that call may only fix JSON syntax.
    # Temperature is intentionally omitted: Gemini 3.x uses its tuned default.
    "gemini-3.7-flash": {
        "generationConfig": {"maxOutputTokens": 16384,
                             "thinkingConfig": {"thinkingLevel": "high"}},
        "repairGenerationConfig": {
            "maxOutputTokens": 8192,
            "thinkingConfig": {"thinkingLevel": "minimal"}},
    },
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
    "gemini-3.1-pro": {
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
    "nvidia/nemotron-3-ultra-550b-a55b:free": {
        "payload": {
            "temperature": 1.0,
            "top_p": 0.95,
            "reasoning": {"effort": "high", "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "nvidia/nemotron-3-super-120b-a12b:free": {
        "payload": {
            "temperature": 1.0,
            "top_p": 0.95,
            # The model catalog exposes medium as this model's top effort.
            "reasoning": {"effort": "medium", "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "google/gemma-4-31b-it:free": {
        "payload": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "inclusionai/ling-3.0-flash:free": {
        "payload": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "google/gemma-4-26b-a4b-it:free": {
        "payload": {
            "temperature": 0.2,
            "top_p": 0.95,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free": {
        "payload": {
            "temperature": 0.6,
            "top_p": 0.95,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "openai/gpt-oss-20b:free": {
        "payload": {
            "reasoning": {"effort": "high", "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "nvidia/nemotron-3-nano-30b-a3b:free": {
        "payload": {
            "temperature": 0.2,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "nvidia/nemotron-nano-12b-v2-vl:free": {
        "payload": {
            "temperature": 0.2,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "nvidia/nemotron-nano-9b-v2:free": {
        "payload": {
            "temperature": 0.2,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "poolside/laguna-s-2.1:free": {
        "payload": {
            "temperature": 0.2,
            "top_p": 0.9,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "cohere/north-mini-code:free": {
        "payload": {
            "temperature": 0.2,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
    },
    "poolside/laguna-xs-2.1:free": {
        "payload": {
            "temperature": 0.2,
            "top_p": 0.9,
            "reasoning": {"enabled": True, "exclude": True},
        },
        "repair": {"reasoning": {"effort": "low", "exclude": True}},
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


def classify_failure(exc) -> str:
    """Stable, response-free failure class for run-history diagnostics."""
    chain = []
    current = exc
    while current is not None and current not in chain:
        chain.append(current)
        current = getattr(current, "__cause__", None)
    if any(isinstance(item, ProviderAuthError) for item in chain):
        return "auth"
    if any(isinstance(item, ProviderQuotaError) for item in chain):
        return "quota"
    timeout_types = tuple(
        cls for cls in (
            getattr(requests, "Timeout", None),
            getattr(getattr(requests, "exceptions", None), "Timeout", None),
        ) if isinstance(cls, type))
    connection_types = tuple(
        cls for cls in (
            getattr(requests, "ConnectionError", None),
            getattr(getattr(requests, "exceptions", None),
                    "ConnectionError", None),
        ) if isinstance(cls, type))
    if timeout_types and any(isinstance(item, timeout_types) for item in chain):
        return "timeout"
    if connection_types and any(
            isinstance(item, connection_types) for item in chain):
        return "connection"
    text = " ".join(
        f"{type(item).__name__} {item}" for item in chain).casefold()
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection" in text or "connecterror" in text:
        return "connection"
    if "429" in text and ("per-minute" in text or "rate limit" in text):
        return "rate_limit"
    if "truncated" in text or "max_tokens" in text:
        return "truncated"
    if "bad json" in text or "jsondecodeerror" in text:
        return "invalid_json"
    if re.search(r"\bhttp\s+[45]\d\d\b", text):
        return "http_error"
    return "unexpected"


def safe_failure_message(value, limit: int = 180) -> str:
    """Short diagnostic that cannot preserve bodies, headers or secret URLs."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"https?://\S+", "[URL removed]", text,
                  flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\bauthorization\b\s*[:=]?\s*(?:bearer\s+)?\S+",
        "Authorization [redacted]",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[-_ ]?key|token|bearer)\b"
        r"\s*[:=]?\s*\S*",
        r"\1 [redacted]",
        text,
    )
    text = re.sub(
        r"(?i)\b(nvapi-[A-Za-z0-9_-]+|AIza[A-Za-z0-9_-]+|"
        r"sk-or-v1-[A-Za-z0-9_-]+|oc_sk_[A-Za-z0-9_-]+)\b",
        "[redacted]",
        text,
    )
    return text[:max(1, min(int(limit or 180), 300))]


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
        self.repair_calls = 0
        self.http_duration_ms = 0
        self.repair_duration_ms = 0
        self.usage = _blank_usage()
        self._client = None

    def available(self) -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY")) and anthropic is not None

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        if self._client is None:
            self._client = anthropic.Anthropic()
        self.http_calls += 1
        started = time.perf_counter()
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
        finally:
            self.http_duration_ms += max(
                0, round((time.perf_counter() - started) * 1000))
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


_RATE_HEADER_RE = re.compile(
    r"^(?:retry-after|ratelimit-|x-ratelimit-|x-request-id|"
    r"x-goog-request-id|x-openrouter-)",
    re.IGNORECASE,
)


def _safe_response_meta(response, duration_ms: int) -> dict:
    """Whitelist operational headers; never retain bodies or credentials."""
    headers = getattr(response, "headers", {}) or {}
    return {
        "status": int(getattr(response, "status_code", 0) or 0),
        "durationMs": max(0, int(duration_ms or 0)),
        "headers": {
            str(key).lower(): str(value)[:240]
            for key, value in headers.items()
            if _RATE_HEADER_RE.match(str(key))
        },
    }


class GeminiProvider:
    name = "gemini"

    def __init__(self, model=None, reasoning_tier=None) -> None:
        self.model = (model or os.environ.get("AVWIRE_GEMINI_MODEL")
                      or GEMINI_DEFAULT_MODEL)
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0  # real API spend incl. format-repair calls
        self.repair_calls = 0
        self.http_duration_ms = 0
        self.repair_duration_ms = 0
        self.usage = _blank_usage()
        self.reasoning_tier = reasoning_tier
        self.request_log = []
        self.reasoning_effective = "automatic profile"
        self.google_search_used = False
        self.grounding_sources = []
        self.search_suggestions_html = ""
        self.search_query_count = 0

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
            raise ProviderError(f"HTTP {response.status_code}")

    def _generation_config(self, schema: dict, repair: bool) -> dict:
        profile = MODEL_PROFILES.get(self.model, {})
        key = "repairGenerationConfig" if repair else "generationConfig"
        config = dict(profile.get(key) or {})
        if not repair and self.reasoning_tier:
            manual = manual_reasoning_profile(
                self.name, self.model, self.reasoning_tier)
            config.update(manual["wire"])
            self.reasoning_effective = manual["effective"]
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = schema
        return config

    def _post(self, payload: dict, repair: bool = False):
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.model}:generateContent")
        self.http_calls += 1
        if repair:
            self.repair_calls += 1
        started = time.perf_counter()
        response = None
        try:
            response = requests.post(
                url, json=payload, timeout=HTTP_TIMEOUT,
                headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            )
            return response
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        finally:
            elapsed = max(0, round((time.perf_counter() - started) * 1000))
            self.http_duration_ms += elapsed
            if repair:
                self.repair_duration_ms += elapsed
            if response is not None:
                self.request_log.append(_safe_response_meta(response, elapsed))

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        self._reset_grounding()
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": self._generation_config(schema, repair=False),
        }
        response = self._post(payload, repair=False)
        self._check_status(response)
        text = self._final_text(response)
        if text is None:
            return None
        try:
            return extract_json(text)
        except ValueError as exc:
            return self._repair(text, schema, exc)

    def _reset_grounding(self) -> None:
        self.google_search_used = False
        self.grounding_sources = []
        self.search_suggestions_html = ""
        self.search_query_count = 0

    def _capture_grounding(self, response) -> None:
        """Keep only Google-returned citation links and the required widget.

        Search queries, prompt text and retrieved page content are never
        persisted.  The rendered search-suggestion HTML is passed through
        unchanged and must be displayed only inside a sandboxed iframe.
        """
        self._reset_grounding()
        data = response.json()
        candidates = data.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        metadata = candidate.get("groundingMetadata") or {}
        queries = metadata.get("webSearchQueries") or []
        self.search_query_count = len([
            query for query in queries
            if isinstance(query, str) and query.strip()
        ])
        entrypoint = metadata.get("searchEntryPoint") or {}
        rendered = entrypoint.get("renderedContent")
        if isinstance(rendered, str) and 0 < len(rendered) <= 100_000:
            self.search_suggestions_html = rendered

        seen = set()
        for chunk in metadata.get("groundingChunks") or []:
            web = chunk.get("web") if isinstance(chunk, dict) else None
            if not isinstance(web, dict):
                continue
            url = str(web.get("uri") or "").strip()
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.netloc or url in seen:
                continue
            title = re.sub(r"\s+", " ", str(web.get("title") or "")).strip()
            self.grounding_sources.append({
                "title": title[:300] or parsed.netloc,
                "url": url,
            })
            seen.add(url)
            if len(self.grounding_sources) >= 5:
                break
        self.google_search_used = bool(
            self.search_query_count or self.grounding_sources
            or self.search_suggestions_html)

    def draft_grounded(self, system_prompt: str, user_prompt: str,
                       schema: dict):
        """Generate the final answer with Gemini's Google Search grounding.

        The grounded result is not sent through format-repair or another
        model because Google's terms require it to be displayed without
        modification and together with its associated search suggestions.
        """
        self._reset_grounding()
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": self._generation_config(schema, repair=False),
        }
        response = self._post(payload, repair=False)
        self._check_status(response)
        self._capture_grounding(response)
        text = self._final_text(response)
        if text is None:
            return None
        try:
            return extract_json(text)
        except ValueError as exc:
            raise ProviderError(f"bad grounded JSON from model: {exc}") from exc

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
        response = self._post(payload, repair=True)
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

    def __init__(self, model=None, reasoning_tier=None) -> None:
        self.model = (model or os.environ.get("AVWIRE_NVIDIA_MODEL")
                      or NVIDIA_DEFAULT_MODEL)
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0  # real API spend incl. format-repair calls
        self.repair_calls = 0
        self.http_duration_ms = 0
        self.repair_duration_ms = 0
        self.usage = _blank_usage()
        self.reasoning_tier = reasoning_tier
        self.request_log = []
        self.reasoning_effective = "automatic profile"

    def available(self) -> bool:
        return bool(os.environ.get("NVIDIA_API_KEY"))

    def _payload_extras(self, repair: bool) -> dict:
        profile = MODEL_PROFILES.get(self.model, {})
        extras = dict(profile.get("payload") or {"temperature": 0.2})
        if not repair and self.reasoning_tier:
            manual = manual_reasoning_profile(
                self.name, self.model, self.reasoning_tier)
            for key in (
                    "reasoning_effort", "chat_template_kwargs",
                    "thinking", "enable_thinking"):
                extras.pop(key, None)
            extras.update(manual["wire"])
            self.reasoning_effective = manual["effective"]
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
        if repair:
            self.repair_calls += 1
        started = time.perf_counter()
        response = None
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
            return response
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        finally:
            elapsed = max(0, round((time.perf_counter() - started) * 1000))
            self.http_duration_ms += elapsed
            if repair:
                self.repair_duration_ms += elapsed
            if response is not None:
                self.request_log.append(_safe_response_meta(response, elapsed))

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
            raise ProviderError(f"HTTP {response.status_code}")

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


class OpenRouterProvider(NvidiaProvider):
    """OpenRouter's OpenAI-compatible endpoint with explicit model fallback."""

    name = "openrouter"

    def __init__(self, model=None, reasoning_tier=None) -> None:
        self.model = (
            model or os.environ.get("AVWIRE_OPENROUTER_MODEL")
            or OPENROUTER_DEFAULT_MODEL
        )
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0
        self.repair_calls = 0
        self.http_duration_ms = 0
        self.repair_duration_ms = 0
        self.usage = _blank_usage()
        self.reasoning_tier = reasoning_tier
        self.request_log = []
        self.reasoning_effective = "automatic profile"

    def available(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    def _payload_extras(self, repair: bool) -> dict:
        profile = MODEL_PROFILES.get(self.model, {})
        extras = dict(profile.get("payload") or {"temperature": 0.2})
        if not repair and self.reasoning_tier:
            manual = manual_reasoning_profile(
                self.name, self.model, self.reasoning_tier)
            extras.pop("reasoning", None)
            extras.pop("reasoning_effort", None)
            extras.update(manual["wire"])
            self.reasoning_effective = manual["effective"]
        if repair:
            extras.update(profile.get("repair") or {
                "reasoning": {"effort": "low", "exclude": True},
            })
        return extras

    def _post(self, messages: list, repair: bool):
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192 if repair else 16384,
            "stream": False,
            **self._payload_extras(repair),
        }
        self.http_calls += 1
        if repair:
            self.repair_calls += 1
        started = time.perf_counter()
        response = None
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload, timeout=HTTP_TIMEOUT,
                headers={
                    "Authorization":
                        f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "HTTP-Referer":
                        "https://skytical.tech/",
                    "X-Title": "AVWIRE",
                },
            )
            return response
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        finally:
            elapsed = max(0, round((time.perf_counter() - started) * 1000))
            self.http_duration_ms += elapsed
            if repair:
                self.repair_duration_ms += elapsed
            if response is not None:
                self.request_log.append(_safe_response_meta(response, elapsed))

    def _check_status(self, response) -> None:
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"HTTP {response.status_code}")
        if response.status_code == 402:
            raise ProviderQuotaError("HTTP 402 (credits exhausted?)")
        if response.status_code == 429:
            # Free-model limits can be model-specific. Keep trying the next
            # OpenRouter model instead of disabling the shared key.
            raise ProviderError("HTTP 429 rate limit")
        if response.status_code == 404:
            raise ProviderError(
                f"model not found: {self.model} "
                "(not in this key's catalog yet?)")
        if response.status_code >= 400:
            raise ProviderError(f"HTTP {response.status_code}")

    @staticmethod
    def _raise_embedded_error(error, stage: str) -> None:
        code = error.get("code") if isinstance(error, dict) else "unknown"
        try:
            numeric = int(code)
        except (TypeError, ValueError):
            numeric = None
        if numeric in (401, 403):
            raise ProviderAuthError(
                f"OpenRouter {stage} error {numeric}")
        if numeric == 402:
            raise ProviderQuotaError(
                f"OpenRouter {stage} error 402 (credits exhausted?)")
        # 429 remains model-local so the next free model is still attempted.
        raise ProviderError(f"OpenRouter {stage} error {code}")

    def _final_text(self, response):
        data = response.json()
        error = data.get("error")
        if error:
            self._raise_embedded_error(error, "response")
        choices = data.get("choices") or []
        if choices and isinstance(choices[0], dict) and choices[0].get("error"):
            self._raise_embedded_error(choices[0]["error"], "choice")
        # NvidiaProvider parses the same OpenAI-compatible final-answer and
        # usage fields while deliberately ignoring reasoning content.
        return super()._final_text(response)


class OpenCodeProvider(NvidiaProvider):
    """OpenCode Console service-account gateway with native protocol routing.

    Console exposes different provider-compatible paths.  Keeping one AVWIRE
    provider name means an invalid/empty service account disables the whole
    gateway for the run, while model-local failures still fall through to the
    next configured OpenCode model.
    """

    name = "opencode"

    def __init__(self, model=None, reasoning_tier=None) -> None:
        self.model = (
            model or os.environ.get("AVWIRE_OPENCODE_MODEL")
            or OPENCODE_DEFAULT_MODEL
        )
        self.label = f"{self.name}:{self.model}"
        self.http_calls = 0
        self.repair_calls = 0
        self.http_duration_ms = 0
        self.repair_duration_ms = 0
        self.usage = _blank_usage()
        self.reasoning_tier = reasoning_tier
        self.request_log = []
        self.reasoning_effective = "automatic profile"

    def available(self) -> bool:
        return bool(os.environ.get("OPENCODE_API_KEY"))

    def _protocol(self) -> str:
        if self.model.startswith("gpt-"):
            return "responses"
        if self.model.startswith(("claude-", "qwen3.")):
            return "messages"
        if self.model.startswith("gemini-"):
            return "gemini"
        return "chat"

    def _effort(self, repair: bool) -> str:
        if repair:
            return "low"
        if not self.reasoning_tier:
            return "medium"
        effort = {
            "fast": "low", "standard": "medium", "deep": "high",
        }.get(self.reasoning_tier, "medium")
        self.reasoning_effective = f"effort={effort}"
        return effort

    def _post_json(self, url: str, payload: dict, headers: dict,
                   repair: bool):
        self.http_calls += 1
        if repair:
            self.repair_calls += 1
        started = time.perf_counter()
        response = None
        try:
            response = requests.post(
                url, json=payload, timeout=HTTP_TIMEOUT, headers=headers)
            return response
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        finally:
            elapsed = max(0, round((time.perf_counter() - started) * 1000))
            self.http_duration_ms += elapsed
            if repair:
                self.repair_duration_ms += elapsed
            if response is not None:
                self.request_log.append(_safe_response_meta(response, elapsed))

    def _check_status(self, response) -> None:
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"HTTP {response.status_code}")
        if response.status_code == 402:
            raise ProviderQuotaError("HTTP 402 (credits exhausted?)")
        if response.status_code == 429:
            # Console can apply model-specific limits.  Preserve the shared
            # service account so the next OpenCode model can still run.
            raise ProviderError("HTTP 429 rate limit")
        if response.status_code == 404:
            raise ProviderError(
                f"model not found: {self.model} "
                "(not enabled in this Console organization?)")
        if response.status_code >= 400:
            raise ProviderError(f"HTTP {response.status_code}")

    def _record_usage(self, data: dict) -> None:
        usage = data.get("usage") or {}
        if not usage:
            return
        self.usage["inputTokens"] += int(
            usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        self.usage["outputTokens"] += int(
            usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        self.usage["usageEvents"] += 1

    @staticmethod
    def _schema_instruction(schema: dict) -> str:
        return (
            "\n\nReturn ONLY one JSON object (no markdown fences, no prose) "
            "conforming exactly to this JSON Schema:\n"
            + json.dumps(schema, ensure_ascii=False)
        )

    def _responses_call(self, system_prompt: str, user_prompt: str,
                        schema: dict, repair: bool):
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_output_tokens": 8192 if repair else 16384,
            "reasoning": {"effort": self._effort(repair)},
            "text": {"format": {
                "type": "json_schema",
                "name": "avwire_draft",
                "schema": schema,
            }},
        }
        key = os.environ["OPENCODE_API_KEY"]
        response = self._post_json(
            f"{OPENCODE_BASE_URL}/openai/v1/responses",
            payload,
            {"Authorization": f"Bearer {key}",
             "Content-Type": "application/json"},
            repair,
        )
        self._check_status(response)
        data = response.json()
        self._record_usage(data)
        if data.get("status") == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            raise ProviderError(f"incomplete response ({reason or 'unknown'})")
        if isinstance(data.get("output_text"), str):
            text = data["output_text"]
            if text.strip():
                return text
        texts = []
        for item in data.get("output") or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for block in item.get("content") or []:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "refusal":
                    print(f"write: {self.label} refused")
                    return None
                if block.get("type") == "output_text":
                    texts.append(str(block.get("text") or ""))
        text = "".join(texts)
        if not text.strip():
            raise ProviderError("empty Responses output")
        return text

    def _messages_call(self, system_prompt: str, user_prompt: str,
                       schema: dict, repair: bool):
        payload = {
            "model": self.model,
            "max_tokens": 8192 if repair else 16000,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        if self.model.startswith("claude-"):
            payload["output_config"] = {
                "effort": self._effort(repair),
                "format": {"type": "json_schema", "schema": schema},
            }
        else:
            payload["system"] += self._schema_instruction(schema)
            if self.reasoning_tier:
                self.reasoning_effective = "provider_default"
        key = os.environ["OPENCODE_API_KEY"]
        response = self._post_json(
            f"{OPENCODE_BASE_URL}/anthropic/v1/messages",
            payload,
            {"x-api-key": key, "anthropic-version": "2023-06-01",
             "Content-Type": "application/json"},
            repair,
        )
        self._check_status(response)
        data = response.json()
        self._record_usage(data)
        if data.get("stop_reason") == "max_tokens":
            raise ProviderError("response truncated (max_tokens)")
        texts = []
        for block in data.get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "refusal":
                print(f"write: {self.label} refused")
                return None
            if block.get("type") == "text":
                texts.append(str(block.get("text") or ""))
        text = "".join(texts)
        if not text.strip():
            raise ProviderError("empty Messages output")
        return text

    def _gemini_call(self, system_prompt: str, user_prompt: str,
                     schema: dict, repair: bool):
        profile = MODEL_PROFILES.get(self.model, {})
        config_key = (
            "repairGenerationConfig" if repair else "generationConfig")
        config = dict(profile.get(config_key) or {})
        if self.reasoning_tier and not repair:
            level = {
                "fast": "minimal", "standard": "medium", "deep": "high",
            }.get(self.reasoning_tier, "medium")
            config["thinkingConfig"] = {"thinkingLevel": level}
            self.reasoning_effective = f"thinkingLevel={level}"
        config["responseMimeType"] = "application/json"
        config["responseJsonSchema"] = schema
        payload = {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "generationConfig": config,
        }
        key = os.environ["OPENCODE_API_KEY"]
        response = self._post_json(
            f"{OPENCODE_BASE_URL}/gemini/v1beta/models/"
            f"{self.model}:generateContent",
            payload,
            {"x-goog-api-key": key, "Content-Type": "application/json"},
            repair,
        )
        self._check_status(response)
        return GeminiProvider._final_text(self, response)

    def _chat_call(self, system_prompt: str, user_prompt: str,
                   schema: dict, repair: bool):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system",
                 "content": system_prompt + self._schema_instruction(schema)},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 8192 if repair else 16384,
            "stream": False,
            "temperature": 0.2,
        }
        if self.reasoning_tier:
            self.reasoning_effective = "provider_default"
        key = os.environ["OPENCODE_API_KEY"]
        response = self._post_json(
            f"{OPENCODE_BASE_URL}/openai/v1/chat/completions",
            payload,
            {"Authorization": f"Bearer {key}",
             "Accept": "application/json",
             "Content-Type": "application/json"},
            repair,
        )
        self._check_status(response)
        return NvidiaProvider._final_text(self, response)

    def _call(self, system_prompt: str, user_prompt: str, schema: dict,
              repair: bool):
        protocol = self._protocol()
        if protocol == "responses":
            return self._responses_call(
                system_prompt, user_prompt, schema, repair)
        if protocol == "messages":
            return self._messages_call(
                system_prompt, user_prompt, schema, repair)
        if protocol == "gemini":
            return self._gemini_call(
                system_prompt, user_prompt, schema, repair)
        return self._chat_call(system_prompt, user_prompt, schema, repair)

    def draft(self, system_prompt: str, user_prompt: str, schema: dict):
        text = self._call(system_prompt, user_prompt, schema, repair=False)
        if text is None:
            return None
        try:
            return extract_json(text)
        except ValueError as exc:
            print(f"write: {self.label} returned malformed JSON ({exc}); "
                  "attempting format repair")
            repaired = self._call(
                REPAIR_SYSTEM_PROMPT, text, schema, repair=True)
            if repaired is None:
                return None
            try:
                return extract_json(repaired)
            except ValueError as repair_exc:
                raise ProviderError(
                    f"bad JSON even after format repair: {repair_exc}"
                ) from repair_exc


_REGISTRY = {
    AnthropicProvider.name: AnthropicProvider,
    GeminiProvider.name: GeminiProvider,
    NvidiaProvider.name: NvidiaProvider,
    OpenRouterProvider.name: OpenRouterProvider,
    OpenCodeProvider.name: OpenCodeProvider,
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
