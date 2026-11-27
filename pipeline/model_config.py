"""Authorized SKYTICAL model routes and caller-specific fallback orders."""

BRIEFING_OPENAI_MODEL = "gpt-6-luna"

# Exact provider/model pairs authorized for outbound model requests.
ALLOWED_MODEL_ROUTES = frozenset({
    "cloudflare:@cf/openai/gpt-oss-120b",
    "gemini:gemini-3.6-flash",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    "groq:qwen/qwen3.8-27b",
    "gemini:gemini-4-hydrogen",
    "gemini:gemini-3.8-flash",
    "gemini:gemini-3.5-flash",
    "gemini:gemini-3.5-flash-lite",
    "gemini:gemini-3.1-flash-lite",
    "gemini:gemma-4-31b-it",
    "gemini:gemma-4-26b-a4b-it",
    "nvidia:z-ai/glm-5.3-flash",
    "nvidia:z-ai/glm-5.2",
    "nvidia:deepseek-ai/deepseek-v4.1-flash",
    "nvidia:deepseek-ai/deepseek-v4-pro",
    "nvidia:google/gemma-4-31b-it",
    "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "nvidia:mistralai/mistral-medium-3.5-128b",
    "nvidia:qwen/qwen3.5-397b-a17b",
    "groq:openai/gpt-oss-120b",
    "groq:openai/gpt-oss-20b",
    "cloudflare:@cf/qwen/qwen3.8-27b",
    "cloudflare:@cf/google/gemma-4-26b-a4b-it",
    "cloudflare:@cf/openai/gpt-oss-20b",
    "openrouter:nvidia/nemotron-3.5-super-vl:free",
    "openrouter:nvidia/nemotron-3.5-lightning:free",
    "openrouter:google/gemma-4-31b-it:free",
    "openrouter:google/gemma-4-26b-a4b-it:free",
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openai:gpt-6.1-terra",
})


def model_route_allowed(provider: str, model: str, *, briefing=False) -> bool:
    return ((briefing and provider == "openai" and model == BRIEFING_OPENAI_MODEL)
            or f"{provider}:{model}" in ALLOWED_MODEL_ROUTES)


DIRECT_MODEL_ORDER = (
    "gemini:gemini-3.6-flash",
    "gemini:gemini-3.5-flash",
    "nvidia:z-ai/glm-5.2",
    "nvidia:deepseek-ai/deepseek-v4-pro",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia:qwen/qwen3.5-397b-a17b",
    "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "nvidia:mistralai/mistral-medium-3.5-128b",
)

FREE_HOSTED_MODEL_ORDER = (
    "groq:openai/gpt-oss-120b",
    "cloudflare:@cf/openai/gpt-oss-120b",
)

OPENAI_DEFAULT_MODEL = "gpt-6.1-terra"


def openai_runtime_model(model=None, *, briefing=False):
    """Keep the legacy Terra mapping unless briefing explicitly selects Luna."""
    selected = str(model or OPENAI_DEFAULT_MODEL).strip()
    if briefing and selected == BRIEFING_OPENAI_MODEL:
        return selected
    return (OPENAI_DEFAULT_MODEL if selected in {"gpt-6", BRIEFING_OPENAI_MODEL}
            else selected)


OPENAI_MODEL_ORDER = (f"openai:{OPENAI_DEFAULT_MODEL}",)

WECHAT_MODEL_ORDER = (
    "wechat:Deepseek-v4-flash",
)

OPENCODE_MODEL_ORDER = (
    "opencode:claude-sonnet-4-6",
    "opencode:gpt-5.5",
    "opencode:gemini-3.1-pro",
    "opencode:qwen3.6-plus",
    "opencode:glm-5.1",
    "opencode:kimi-k2.6",
)

OPENROUTER_MODEL_ORDER = (
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter:nvidia/nemotron-3-super-120b-a12b:free",
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

# Model catalog in manual selector order, including historically configured routes.
_MANUAL_MODEL_ORDER = (
    OPENCODE_MODEL_ORDER[0],
    OPENCODE_MODEL_ORDER[1],
    DIRECT_MODEL_ORDER[0],
    OPENCODE_MODEL_ORDER[2],
    OPENCODE_MODEL_ORDER[3],
    DIRECT_MODEL_ORDER[2],
    OPENCODE_MODEL_ORDER[4],
    OPENCODE_MODEL_ORDER[5],
    DIRECT_MODEL_ORDER[1],
    *DIRECT_MODEL_ORDER[3:5],
    WECHAT_MODEL_ORDER[0],
    OPENROUTER_MODEL_ORDER[0],
    *DIRECT_MODEL_ORDER[5:7],
    OPENROUTER_MODEL_ORDER[1],
    DIRECT_MODEL_ORDER[7],
    *OPENROUTER_MODEL_ORDER[2:],
    *FREE_HOSTED_MODEL_ORDER,
)

# Baseline order. Article-specific Terra routing can promote GPT 6.1 Terra after
# primary/two-platform failure while retaining this order for other callers.
_AUTOMATIC_MODEL_ORDER = (
    DIRECT_MODEL_ORDER[0],
    DIRECT_MODEL_ORDER[1],
    DIRECT_MODEL_ORDER[4],
    WECHAT_MODEL_ORDER[0],
    OPENROUTER_MODEL_ORDER[0],
    *FREE_HOSTED_MODEL_ORDER,
    OPENAI_MODEL_ORDER[0],
)

# Candidate routes for the scheduled news writer. The live account catalog and
# publication probe decide which entries can participate in each run.
_FREE_DRAFT_MODEL_ORDER = (
    "gemini:gemini-3.6-flash",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    "cloudflare:@cf/openai/gpt-oss-120b",
    "gemini:gemini-3.8-flash",
    "groq:qwen/qwen3.8-27b",
    "openrouter:inclusionai/ling-3.2-flash:free",
    "gemini:gemini-4-hydrogen",
    "gemini:gemini-3.5-flash",
    "gemini:gemini-3.5-flash-lite",
    "gemini:gemini-3.1-flash-lite",
    "gemini:gemma-4-31b-it",
    "gemini:gemma-4-26b-a4b-it",
    "nvidia:z-ai/glm-5.3-flash",
    "nvidia:z-ai/glm-5.2",
    "nvidia:mistralai/mistral-large-4-1t-a52b",
    "nvidia:deepseek-ai/deepseek-v4.1-flash",
    "nvidia:deepseek-ai/deepseek-v4-pro",
    "nvidia:google/gemma-4-31b-it",
    "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "nvidia:mistralai/mistral-medium-3.5-128b",
    "nvidia:qwen/qwen3.5-397b-a17b",
    "groq:openai/gpt-oss-120b",
    "groq:openai/gpt-oss-20b",
    "cloudflare:@cf/qwen/qwen3.8-27b",
    "cloudflare:@cf/google/gemma-4-26b-a4b-it",
    "cloudflare:@cf/openai/gpt-oss-20b",
    "cloudflare:@cf/aisingapore/gemma-sea-lion-v4-27b-it",
    "openrouter:baidu/ernie-5.5-flash-preview:free",
    "openrouter:thinkingmachines/inkling-2-small:free",
    "openrouter:nvidia/nemotron-3.5-super-vl:free",
    "openrouter:nvidia/nemotron-3.5-lightning:free",
    "openrouter:google/gemma-4-31b-it:free",
    "openrouter:google/gemma-4-26b-a4b-it:free",
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free",
    "openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "openrouter:particle-ai/particle-1:free",
    "openrouter:dots-studio/dots-3-note-preview:free",
    "openrouter:recursive/flint-v1.0:free",
    "openrouter:cohere/north-mini-code:free",
    "openrouter:liquid/lfm-3-1.7b:free",
)
FREE_DRAFT_MODEL_ORDER = tuple(route for route in _FREE_DRAFT_MODEL_ORDER
                               if route in ALLOWED_MODEL_ROUTES)
AUTOMATIC_MODEL_ORDER = tuple(route for route in _AUTOMATIC_MODEL_ORDER
                              if route in ALLOWED_MODEL_ROUTES)
DEFAULT_PROVIDER_ORDER = ",".join(AUTOMATIC_MODEL_ORDER)
MODEL_ORDER = tuple(dict.fromkeys(
    route for route in (*_MANUAL_MODEL_ORDER, *FREE_DRAFT_MODEL_ORDER, *OPENAI_MODEL_ORDER)
    if route in ALLOWED_MODEL_ROUTES
))

FREE_DRAFT_GOOGLE_MODELS = frozenset(
    route.split(":", 1)[1] for route in FREE_DRAFT_MODEL_ORDER if route.startswith("gemini:")
)

MODEL_DISPLAY_NAMES = {
    "gemini:gemini-4-hydrogen": "Google Gemini 4 Hydrogen",
    "gemini:gemini-3.8-flash": "Google Gemini 3.8 Flash",
    "gemini:gemini-3.5-flash-lite": "Google Gemini 3.5 Flash-Lite",
    "gemini:gemini-3.1-flash-lite": "Google Gemini 3.1 Flash-Lite",
    "gemini:gemma-4-31b-it": "Google Gemma 4 31B",
    "gemini:gemma-4-26b-a4b-it": "Google Gemma 4 26B",
    "cloudflare:@cf/openai/gpt-oss-120b": "Cloudflare Workers AI · OpenAI GPT-OSS 120B",
    "cloudflare:@cf/openai/gpt-oss-20b": "Cloudflare Workers AI · OpenAI GPT-OSS 20B",
    "cloudflare:@cf/qwen/qwen3.8-27b": "Cloudflare Workers AI · Qwen 3.8 27B",
    "cloudflare:@cf/google/gemma-4-26b-a4b-it": "Cloudflare Workers AI · Google Gemma 4 26B",
    "cloudflare:@cf/aisingapore/gemma-sea-lion-v4-27b-it": "Cloudflare Workers AI · SEA-LION V4 27B",
    "groq:openai/gpt-oss-20b": "Groq · OpenAI GPT-OSS 20B",
    "groq:qwen/qwen3.8-27b": "Groq · Qwen 3.8 27B",
    "nvidia:z-ai/glm-5.3-flash": "NVIDIA GLM 5.3 Flash",
    "nvidia:mistralai/mistral-large-4-1t-a52b": "NVIDIA Mistral Large 4",
    "nvidia:deepseek-ai/deepseek-v4.1-flash": "NVIDIA DeepSeek V4.1 Flash",
    "nvidia:google/gemma-4-31b-it": "NVIDIA Google Gemma 4 31B",
    "openrouter:inclusionai/ling-3.2-flash:free": "OpenRouter · InclusionAI Ling 3.2 Flash",
    "openrouter:baidu/ernie-5.5-flash-preview:free": "OpenRouter · Baidu ERNIE 5.5 Flash Preview",
    "openrouter:thinkingmachines/inkling-2-small:free": "OpenRouter · Thinking Machines Inkling 2 Small",
    "openrouter:nvidia/nemotron-3.5-super-vl:free": "OpenRouter · NVIDIA Nemotron 3.5 Super VL",
    "openrouter:nvidia/nemotron-3.5-lightning:free": "OpenRouter · NVIDIA Nemotron 3.5 Lightning",
    "openrouter:particle-ai/particle-1:free": "OpenRouter · Particle 1",
    "openrouter:dots-studio/dots-3-note-preview:free": "OpenRouter · Dots 3 Note Preview",
    "openrouter:recursive/flint-v1.0:free": "OpenRouter · Recursive Flint V1.0",
    "openrouter:liquid/lfm-3-1.7b:free": "OpenRouter · Liquid LFM 3 1.7B",
    FREE_HOSTED_MODEL_ORDER[0]: "Groq · OpenAI GPT-OSS 120B",
    "cloudflare:@cf/qwen/qwen3-30b-a3b-fp8": "Cloudflare Workers AI · Qwen3 30B A3B",
    "openai:gpt-6.1-terra": "GPT 6.1 Terra",
    f"openai:{BRIEFING_OPENAI_MODEL}": "GPT 6 Luna",
    "wechat:Deepseek-v4-flash":
        "WeChat Coding Plan · DeepSeek V4 Flash",
    "opencode:claude-sonnet-4-6":
        "OpenCode · Anthropic Claude Sonnet 4.6",
    "opencode:gpt-5.5": "OpenCode · OpenAI GPT-5.5",
    "opencode:gemini-3.1-pro": "OpenCode · Google Gemini 3.1 Pro",
    "opencode:qwen3.6-plus": "OpenCode · Qwen 3.6 Plus",
    "opencode:glm-5.1": "OpenCode · GLM 5.1",
    "opencode:kimi-k2.6": "OpenCode · Kimi K2.6",
    "gemini:gemini-3.6-flash": "Google Gemini 3.6 Flash",
    "gemini:gemini-3.5-flash": "Google Gemini 3.5 Flash",
    "nvidia:z-ai/glm-5.2": "NVIDIA GLM 5.2",
    "nvidia:deepseek-ai/deepseek-v4-pro": "NVIDIA DeepSeek V4 Pro",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b":
        "NVIDIA Nemotron 3 Ultra 550B",
    "nvidia:qwen/qwen3.5-397b-a17b": "NVIDIA Qwen 3.5 397B A17B",
    "nvidia:nvidia/nemotron-3-super-120b-a12b":
        "NVIDIA Nemotron 3 Super 120B",
    "nvidia:mistralai/mistral-medium-3.5-128b":
        "NVIDIA Mistral Medium 3.5 128B",
    "openrouter:nvidia/nemotron-3-ultra-550b-a55b:free":
        "OpenRouter · NVIDIA Nemotron 3 Ultra 550B",
    "openrouter:nvidia/nemotron-3-super-120b-a12b:free":
        "OpenRouter · NVIDIA Nemotron 3 Super 120B",
    "openrouter:google/gemma-4-31b-it:free":
        "OpenRouter · Google Gemma 4 31B",
    "openrouter:inclusionai/ling-3.0-flash:free":
        "OpenRouter · InclusionAI Ling 3.0 Flash",
    "openrouter:google/gemma-4-26b-a4b-it:free":
        "OpenRouter · Google Gemma 4 26B A4B",
    "openrouter:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free":
        "OpenRouter · NVIDIA Nemotron 3 Nano Omni 30B",
    "openrouter:openai/gpt-oss-20b:free":
        "OpenRouter · OpenAI gpt-oss-20b",
    "openrouter:nvidia/nemotron-3-nano-30b-a3b:free":
        "OpenRouter · NVIDIA Nemotron 3 Nano 30B",
    "openrouter:nvidia/nemotron-nano-12b-v2-vl:free":
        "OpenRouter · NVIDIA Nemotron Nano 12B VL",
    "openrouter:nvidia/nemotron-nano-9b-v2:free":
        "OpenRouter · NVIDIA Nemotron Nano 9B V2",
    "openrouter:poolside/laguna-s-2.1:free":
        "OpenRouter · Poolside Laguna S 2.1",
    "openrouter:cohere/north-mini-code:free":
        "OpenRouter · Cohere North Mini Code",
    "openrouter:poolside/laguna-xs-2.1:free":
        "OpenRouter · Poolside Laguna XS 2.1",
}

REASONING_TIERS = ("fast", "standard", "deep")


def manual_reasoning_profile(provider: str, model: str, tier: str) -> dict:
    """Provider-specific controls for the manual drafting workbench.

    The normal automated pipeline does not call this function, so its tuned
    model defaults remain unchanged.  The returned ``wire`` mapping is merged
    into one manual request only; ``effective`` is safe to display in the UI.
    """
    if tier not in REASONING_TIERS:
        tier = "standard"
    if provider == "openai":
        effort = "max"
        return {
            "wire": {"reasoning": {"effort": effort}},
            "effective": f"reasoning.effort={effort}",
        }
    if provider == "openrouter":
        effort = {"fast": "low", "standard": "medium",
                  "deep": "high"}[tier]
        return {
            "wire": {
                "reasoning": {"effort": effort, "exclude": True},
            },
            "effective": f"reasoning.effort={effort}",
        }
    if provider == "gemini":
        level = {"fast": "minimal", "standard": "medium",
                 "deep": "high"}[tier]
        return {
            "wire": {"thinkingConfig": {"thinkingLevel": level}},
            "effective": f"thinkingLevel={level}",
        }
    if provider == "wechat":
        return {
            "wire": {"thinking": {"type": "disabled"}},
            "effective": "thinking.type=disabled",
        }
    if model == "z-ai/glm-5.2":
        return {"wire": {}, "effective": "provider_default"}
    if model == "deepseek-ai/deepseek-v4-pro":
        effort = "none" if tier == "fast" else "high"
        return {
            "wire": {"reasoning_effort": effort},
            "effective": f"reasoning_effort={effort}",
        }
    if model in (
            "nvidia/nemotron-3-ultra-550b-a55b",
            "nvidia/nemotron-3-super-120b-a12b"):
        if tier == "fast":
            wire = {"reasoning_effort": "none"}
        elif tier == "standard":
            wire = {"reasoning_effort": "high"}
        else:
            wire = {"reasoning_effort": "max"}
        return {
            "wire": wire,
            "effective": f"reasoning_effort={wire['reasoning_effort']}",
        }
    if model == "qwen/qwen3.5-397b-a17b":
        enabled = tier != "fast"
        return {
            "wire": {
                "chat_template_kwargs": {"enable_thinking": enabled},
            },
            "effective":
                f"enable_thinking={str(enabled).lower()} (maximum supported)",
        }
    if model == "mistralai/mistral-medium-3.5-128b":
        effort = "none" if tier == "fast" else "high"
        return {
            "wire": {"reasoning_effort": effort},
            "effective": f"reasoning_effort={effort}",
        }
    return {"wire": {}, "effective": "provider_default"}
