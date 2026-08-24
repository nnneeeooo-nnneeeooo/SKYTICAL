"""Shared AVWIRE model priority configuration.

The first entry is the default writer. The same order drives provider
fallback and model ordering on the private usage dashboard.
"""

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

# Rank by model capability first, then by provider for equivalent models.
# The native NVIDIA route remains the first attempt and its OpenRouter
# equivalent follows immediately, instead of collecting every OpenRouter
# model at the end of the chain.
MODEL_ORDER = (
    WECHAT_MODEL_ORDER[0],
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
    OPENROUTER_MODEL_ORDER[0],
    *DIRECT_MODEL_ORDER[5:7],
    OPENROUTER_MODEL_ORDER[1],
    DIRECT_MODEL_ORDER[7],
    *OPENROUTER_MODEL_ORDER[2:],
)

DEFAULT_PROVIDER_ORDER = ",".join(MODEL_ORDER)

MODEL_DISPLAY_NAMES = {
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
