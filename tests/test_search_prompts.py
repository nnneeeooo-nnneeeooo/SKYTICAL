"""Offline checks for daily article-grounded search suggestions."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import search_prompts  # noqa: E402


class FakeProvider:
    name = "fake"
    label = "fake:test-model"
    http_calls = 1
    usage = {"inputTokens": 100, "outputTokens": 50, "usageEvents": 1}

    def __init__(self):
        self.calls = 0

    def draft(self, system_prompt, user_prompt, schema):
        self.calls += 1
        assert "ONLY the supplied published articles" in system_prompt
        assert schema == search_prompts.PROMPT_SCHEMA
        candidates = json.loads(user_prompt)
        return {"prompts": [
            {
                "articleId": row["id"],
                "zh": f"關注：{row['zhTitle']}",
                "en": f"Explore {row['enTitle']}",
            }
            for row in candidates[:6]
        ]}


def article(index: int) -> dict:
    return {
        "id": f"a-20260810-000{index}-test-{index}",
        "publishedUtc": f"2026-08-10T00:0{index}:00Z",
        "zh": {
            "title": f"航空{index} A32{index} 抵達桃園",
            "summary": f"航空{index}的 A32{index} 航機抵達桃園機場。",
        },
        "en": {
            "title": f"Airline {index} A32{index} arrives at Taoyuan",
            "summary": f"Airline {index}'s A32{index} arrived at Taoyuan.",
        },
    }


def main() -> None:
    now = datetime(2026, 8, 10, 6, 30, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp)
        articles_dir = data_dir / "articles"
        articles_dir.mkdir()
        (articles_dir / "batch.json").write_text(
            json.dumps({"articles": [article(i) for i in range(8)]},
                       ensure_ascii=False),
            encoding="utf-8",
        )

        candidates, window = search_prompts.collect_candidates(articles_dir, now)
        assert len(candidates) == 8
        assert window == "today"

        provider = FakeProvider()
        changed = search_prompts.update_daily_prompts(
            data_dir=data_dir, now=now, providers=[provider],
            record_usage=False)
        assert changed is True and provider.calls == 1
        payload = json.loads(
            (data_dir / "search-prompts.json").read_text(encoding="utf-8"))
        assert payload["targetDateTpe"] == "2026-08-10"
        assert payload["version"] == search_prompts.OUTPUT_VERSION
        assert payload["generationMode"] == "llm"
        assert payload["provider"] == "fake:test-model"
        assert len(payload["prompts"]["zh"]) == 6
        assert len(payload["sourceArticleIds"]) == 6

        second_provider = FakeProvider()
        assert search_prompts.update_daily_prompts(
            data_dir=data_dir, now=now, providers=[second_provider],
            record_usage=False) is False
        assert second_provider.calls == 0

        fallback_dir = data_dir / "fallback"
        fallback_articles = fallback_dir / "articles"
        fallback_articles.mkdir(parents=True)
        (fallback_articles / "batch.json").write_text(
            json.dumps({"articles": [article(i) for i in range(8)]},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        invalid = FakeProvider()
        invalid.draft = lambda *_args: {"prompts": []}
        search_prompts.update_daily_prompts(
            data_dir=fallback_dir, now=now, force=True, providers=[invalid],
            record_usage=False)
        fallback = json.loads(
            (fallback_dir / "search-prompts.json").read_text(encoding="utf-8"))
        assert fallback["generationMode"] == "deterministic"
        assert fallback["provider"] is None
        assert fallback["prompts"]["zh"][0].startswith("搜尋：航空7 A327")

        # A bad key can expose several models from one platform.  Only the
        # first model from each API platform may consume the daily budget.
        class NamedProvider:
            def __init__(self, name, model):
                self.name = name
                self.label = f"{name}:{model}"

        selected = search_prompts._providers_for_attempts([
            NamedProvider("opencode", "one"),
            NamedProvider("opencode", "two"),
            NamedProvider("gemini", "flash"),
            NamedProvider("nvidia", "model"),
            NamedProvider("openrouter", "free"),
            NamedProvider("anthropic", "sonnet"),
        ])
        assert [provider.name for provider in selected] == [
            "opencode", "gemini", "nvidia", "openrouter"]

    workflow = (ROOT / ".github" / "workflows" / "hourly.yml").read_text(
        encoding="utf-8")
    assert 'cron: "1 * * * *"' in workflow
    assert "python pipeline/search_prompts.py --daily-if-due" in workflow
    print("test_search_prompts: OK")


if __name__ == "__main__":
    main()
