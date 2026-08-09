"""Offline checks for public model names on the bilingual Methodology page."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def _copy(lang: str) -> str:
    about = build.ABOUT[lang]
    values = list(about["intro"])
    for section in about["sections"]:
        values.append(section["heading"])
        for block in section["blocks"]:
            values.append(block.get("x", ""))
            values.extend(block.get("items", []))
    return "\n".join(values)


def main() -> None:
    zh = _copy("zh")
    en = _copy("en")
    combined = f"{zh}\n{en}"

    for expected in ("Claude", "Anthropic", "GPT", "OpenAI", "Gemini", "Google"):
        assert expected in zh
        assert expected in en

    for internal_name in (
            "Nemotron", "NVIDIA", "OpenCode", "OpenRouter", "Qwen", "GLM", "Kimi"):
        assert internal_name not in combined

    assert "使用的模型與供應商" in zh
    assert "Models and providers" in en
    print("methodology: public model names verified")


if __name__ == "__main__":
    main()
