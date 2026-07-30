"""Shared AVWIRE model priority configuration.

The first entry is the default writer. The same order drives provider
fallback and model ordering on the private usage dashboard.
"""

MODEL_ORDER = (
    "gemini:gemini-3.6-flash",
    "gemini:gemini-3.5-flash",
    "nvidia:z-ai/glm-5.2",
    "nvidia:deepseek-ai/deepseek-v4-pro",
    "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
    "nvidia:qwen/qwen3.5-397b-a17b",
    "nvidia:nvidia/nemotron-3-super-120b-a12b",
    "nvidia:mistralai/mistral-medium-3.5-128b",
)

DEFAULT_PROVIDER_ORDER = ",".join(MODEL_ORDER)
