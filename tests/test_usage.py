"""Tests for the API-usage ledger + private dashboard (offline).

No pytest required — run from the repo root:

    py tests\\test_usage.py

Provider HTTP is mocked; no real API endpoint is touched and no real
key is used.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-usage-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)
os.environ["NVIDIA_API_KEY"] = "test-not-a-real-key"
os.environ["GEMINI_API_KEY"] = "test-not-a-real-key"

sys.path.insert(0, str(REPO / "pipeline"))
import build  # noqa: E402
import providers  # noqa: E402
import usage  # noqa: E402
from common import now_utc  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


class FakeResp:
    def __init__(self, data):
        self.status_code = 200
        self._data = data
        self.text = json.dumps(data)

    def json(self):
        return self._data


GOOD = json.dumps({"ok": 1})

# ── provider-side token capture ──────────────────────────────────────────────

nim_resp = FakeResp({
    "choices": [{"finish_reason": "stop", "message": {"content": GOOD}}],
    "usage": {"prompt_tokens": 1200, "completion_tokens": 340},
})
providers.requests = types.SimpleNamespace(
    post=lambda *a, **k: nim_resp,
    RequestException=Exception)
nv = providers.NvidiaProvider("nvidia/nemotron-3-ultra-550b-a55b")
nv.draft("sys", "user", {"type": "object"})
nv.draft("sys", "user", {"type": "object"})
check("NIM usage captured per call and accumulated",
      nv.usage == {"inputTokens": 2400, "outputTokens": 680,
                   "usageEvents": 2} and nv.http_calls == 2)

gem_resp = FakeResp({
    "candidates": [{"finishReason": "STOP",
                    "content": {"parts": [{"text": GOOD}]}}],
    "usageMetadata": {"promptTokenCount": 900,
                      "candidatesTokenCount": 210,
                      "thoughtsTokenCount": 400},
})
providers.requests = types.SimpleNamespace(
    post=lambda *a, **k: gem_resp,
    RequestException=Exception)
gm = providers.GeminiProvider("gemini-3.6-flash")
gm.draft("sys", "user", {"type": "object"})
check("Gemini usage counts thinking tokens as output",
      gm.usage == {"inputTokens": 900, "outputTokens": 610,
                   "usageEvents": 1})

# response without usage metadata -> call counted, tokens unknown
nim_nousage = FakeResp({
    "choices": [{"finish_reason": "stop", "message": {"content": GOOD}}]})
providers.requests = types.SimpleNamespace(
    post=lambda *a, **k: nim_nousage,
    RequestException=Exception)
nv2 = providers.NvidiaProvider("nvidia/nemotron-3-super-120b-a12b")
nv2.draft("sys", "user", {"type": "object"})
check("missing usage metadata leaves tokens at 0 but counts the call",
      nv2.usage["usageEvents"] == 0 and nv2.http_calls == 1)

# ── ledger merge ─────────────────────────────────────────────────────────────

try:
    (TMP / "usage.json").unlink()
except FileNotFoundError:
    pass
usage.record_providers([nv, gm, nv2])
led = usage.load_ledger()
m = led["models"]["nvidia:nvidia/nemotron-3-ultra-550b-a55b"]
check("ledger stores calls and token totals per model label",
      m == {"calls": 2, "inputTokens": 2400, "outputTokens": 680,
            "unknownCalls": 0})
check("calls without usage metadata become unknownCalls",
      led["models"]["nvidia:nvidia/nemotron-3-super-120b-a12b"]
      ["unknownCalls"] == 1)
day = now_utc().strftime("%Y-%m-%d")
check("daily bucket accumulates across providers",
      led["daily"][day]["calls"] == 4
      and led["daily"][day]["inputTokens"] == 3300)
check("tracking start stamped once", bool(led["trackingSinceUtc"]))
check("old ledger without recentRuns loads compatibly",
      led["recentRuns"] == [])

fixed_now = datetime(2026, 7, 30, 10, 20, tzinfo=timezone.utc)
sample_run = {
    "startedUtc": usage.iso_minute(fixed_now),
    "finishedUtc": usage.iso_minute(fixed_now),
    "workflow": "hourly",
    "taskType": "article",
    "groupId": "boeing-777-9-test-hours",
    "eventId": None,
    "sourceCount": 4,
    "primarySource": "Boeing <script>alert(1)</script>",
    "result": "published",
    "articleId": "a-boeing-777-9-test-hours",
    "finalStatus": "publish",
    "finalModel": "gemini:gemini-3.6-flash",
    "fallbackUsed": True,
    "prompt": "PROMPT MUST NEVER BE STORED",
    "durationsMs": {
        "archiveRetrieval": 80,
        "promptAssembly": 10,
        "drafting": 223400,
        "validation": 22,
        "factVerification": 15,
        "articleBuild": 8,
        "total": 223400,
    },
    "attempts": [
        {
            "label": "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
            "outcome": "failed",
            "durationMs": 180100,
            "httpCalls": 1,
            "repairCalls": 0,
            "failureClass": "timeout",
            "failureStage": "draft",
            "failureMessage":
                "ReadTimeout\nAuthorization: Bearer secret-value",
            "retryPlanned": False,
            "disabledForRun": False,
        },
        {
            "label": "nvidia:nvidia/nemotron-3-super-120b-a12b",
            "outcome": "failed",
            "durationMs": 28300,
            "httpCalls": 2,
            "repairCalls": 1,
            "failureClass": "invalid_json",
            "failureStage": "validation",
            "failureMessage": "bad JSON from model",
            "retryPlanned": False,
            "disabledForRun": False,
        },
        {
            "label": "gemini:gemini-3.6-flash",
            "outcome": "success",
            "durationMs": 15000,
            "httpCalls": 1,
            "repairCalls": 0,
            "failureClass": None,
            "failureStage": None,
            "failureMessage": None,
            "retryPlanned": False,
            "disabledForRun": False,
        },
    ],
}
usage.record_run(sample_run)
check("record_run appends one detailed run",
      usage.load_ledger()["recentRuns"][0]["groupId"]
      == "boeing-777-9-test-hours"
      and "prompt" not in usage.load_ledger()["recentRuns"][0])
boundary = {**sample_run,
            "groupId": "boundary",
            "startedUtc": usage.iso_minute(
                fixed_now - timedelta(days=usage.RECENT_RUN_KEEP_DAYS))}
expired = {**sample_run,
           "groupId": "expired",
           "startedUtc": usage.iso_minute(
               fixed_now - timedelta(days=usage.RECENT_RUN_KEEP_DAYS,
                                     minutes=1))}
pruned = usage._prune_recent_runs(
    [sample_run, boundary, expired, "bad", {"startedUtc": "bad"}],
    fixed_now)
check("30-day boundary is inclusive and older/malformed rows are pruned",
      {row["groupId"] for row in pruned}
      == {"boeing-777-9-test-hours", "boundary"})
many = [{**sample_run, "groupId": f"g-{i}"}
        for i in range(usage.RECENT_RUN_MAX + 5)]
check("recent run hard cap prevents unbounded growth",
      len(usage._prune_recent_runs(many, fixed_now))
      == usage.RECENT_RUN_MAX)

usage.record_providers([nv])  # second run with the same totals object
led2 = usage.load_ledger()
check("second record adds on top (caller flushes once per run)",
      led2["models"]["nvidia:nvidia/nemotron-3-ultra-550b-a55b"]["calls"]
      == 4)

# stale daily rows pruned
led2["daily"]["2020-01-01"] = {"calls": 1, "inputTokens": 1,
                               "outputTokens": 1}
usage.save_json(usage.USAGE_PATH, led2)
usage.record_providers([nv])
check("daily series pruned to the retention window",
      "2020-01-01" not in usage.load_ledger()["daily"])

check("idle providers write nothing",
      usage.record_providers([]) is None)

check("provider failures have stable classes",
      providers.classify_failure(
          providers.ProviderAuthError("HTTP 401")) == "auth"
      and providers.classify_failure(
          providers.ProviderQuotaError("HTTP 429")) == "quota"
      and providers.classify_failure(
          providers.ProviderError("HTTP 429 per-minute rate limit"))
      == "rate_limit"
      and providers.classify_failure(
          providers.ProviderError("ReadTimeout")) == "timeout")
cleaned = providers.safe_failure_message(
    "line one\nAuthorization: Bearer very-secret "
    "https://example.com/?key=secret", 80)
check("failure messages are flattened, redacted and truncated",
      "\n" not in cleaned and "very-secret" not in cleaned
      and "key=secret" not in cleaned and len(cleaned) <= 80)

# ── pricing math + dashboard gating ─────────────────────────────────────────

prices = json.loads((REPO / "config" / "model_prices.json")
                    .read_text(encoding="utf-8"))
rows, totals = build.usage_rows(usage.load_ledger(), prices)
priority_ledger = {
    "models": {
        label: {"calls": 1, "inputTokens": 0, "outputTokens": 0,
                "unknownCalls": 0}
        for label in reversed(providers.MODEL_ORDER)
    }
}
priority_rows, _ = build.usage_rows(priority_ledger, prices)
check("usage dashboard follows the configured model priority",
      [row["label"] for row in priority_rows]
      == list(providers.MODEL_ORDER))
ultra = next(r for r in rows if "ultra" in r["label"])
expect_usd = (ultra["in"] / 1e6 * 0.423) + (ultra["out"] / 1e6 * 2.61)
check("theoretical USD uses the reference price table",
      abs(ultra["usd"] - expect_usd) < 1e-9 and ultra["kind"] == "reference")
gpt_rows = build.non_api_reference_rows(prices)
check("GPT-5.6 Sol non-API pricing separates drafting and site editing",
      [r["purpose"] for r in gpt_rows]
      == ["新聞撰稿（手動補稿）", "網站修改（Codex）"]
      and all(r["in"] == 5.0 and r["cached_in"] == 0.5
              and r["out"] == 30.0 for r in gpt_rows))
family_rows = build.gpt_family_reference_rows(prices)
check("GPT-5 family reference catalogue covers official text models",
      len(family_rows) == 16
      and family_rows[0] == {
          "model": "GPT-5.6 Sol", "in": 5.0, "cached_in": 0.5,
          "out": 30.0,
          "source":
              "https://developers.openai.com/api/docs/models/gpt-5.6-sol",
      }
      and family_rows[-1]["model"] == "GPT-5 nano"
      and family_rows[-1]["in"] == 0.05
      and family_rows[-1]["out"] == 0.4)
check("GPT Pro catalogue rows show no nonexistent cached-input discount",
      all(r["cached_in"] is None for r in family_rows
          if r["model"].endswith(" Pro")))
codex_rows, codex_totals = build.codex_usage_rows({
    "actualAdditionalApiSpendUsd": 0,
    "entries": [{
        "model": "GPT-5.6 Sol",
        "inputTokens": 1_000_000,
        "cachedInputTokens": 800_000,
        "outputTokens": 100_000,
        "reasoningOutputTokens": 25_000,
    }],
}, prices)
check("Codex snapshot prices uncached, cached and output tokens separately",
      len(codex_rows) == 1
      and codex_rows[0]["uncached_in"] == 200_000
      and abs(codex_totals["usd"] - 4.4) < 1e-9)
check("Codex total tokens do not double-count cache or reasoning",
      codex_totals["tokens"] == 1_100_000
      and codex_totals["reasoning"] == 25_000
      and codex_totals["actual_usd"] == 0)
bad_codex_rows, _ = build.codex_usage_rows({
    "entries": [
        {"model": "GPT-5.6 Sol", "inputTokens": 10,
         "cachedInputTokens": 11, "outputTokens": 1,
         "reasoningOutputTokens": 0},
        {"model": "GPT-5.6 Sol", "inputTokens": 10,
         "cachedInputTokens": 5, "outputTokens": 1,
         "reasoningOutputTokens": 2},
    ],
}, prices)
check("Codex snapshot rejects impossible token subsets",
      bad_codex_rows == [])
unsafe_prices = {
    "gptFamilyReference": [
        {"model": "bad host", "in": 1, "cachedIn": 0.1, "out": 2,
         "source": "https://example.com/api/docs/models/gpt"},
        {"model": "bad type", "in": "1", "cachedIn": 0.1, "out": 2,
         "source": "https://developers.openai.com/api/docs/models/gpt"},
        {"model": "good", "in": 1, "cachedIn": None, "out": 2,
         "source": "https://developers.openai.com/api/docs/models/good"},
        {"model": "good", "in": 9, "cachedIn": 9, "out": 9,
         "source": "https://developers.openai.com/api/docs/models/duplicate"},
    ]
}
check("GPT reference catalogue rejects unsafe, malformed and duplicate rows",
      build.gpt_family_reference_rows(unsafe_prices)
      == [{"model": "good", "in": 1.0, "cached_in": None, "out": 2.0,
           "source":
               "https://developers.openai.com/api/docs/models/good"}])
gpt_api_rows, _ = build.usage_rows(
    {"models": {"openai:gpt-5.6-sol":
                {"calls": 1, "inputTokens": 1_000_000,
                 "outputTokens": 1_000_000, "unknownCalls": 0}}}, prices)
check("GPT-5.6 Sol API usage would use the official $5/$30 rates",
      gpt_api_rows[0]["usd"] == 35.0
      and gpt_api_rows[0]["kind"] == "reference")
check("totals aggregate across models",
      totals["calls"] == 8 and totals["usd"] > 0)
rows2, _ = build.usage_rows(
    {"models": {"anthropic:claude-opus-5":
                {"calls": 1, "inputTokens": 10, "outputTokens": 10,
                 "unknownCalls": 0}}}, prices)
check("model without a listed price shows no cost instead of a fake one",
      rows2[0]["usd"] is None)

check("dashboard token format enforced",
      build._USAGE_TOKEN_RE.fullmatch("a" * 16)
      and not build._USAGE_TOKEN_RE.fullmatch("short")
      and not build._USAGE_TOKEN_RE.fullmatch("has space" + "a" * 16)
      and not build._USAGE_TOKEN_RE.fullmatch("x" * 200))

from jinja2 import Environment, FileSystemLoader, StrictUndefined  # noqa: E402

env = Environment(loader=FileSystemLoader(str(REPO / "templates")),
                  autoescape=True, undefined=StrictUndefined,
                  trim_blocks=True, lstrip_blocks=True)
build.SITE_DIR = TMP / "site"
fake_build = {"date": "2026-07-27 MON", "utc_hm": "00:00",
              "tpe_hm": "08:00", "stamp": "2026-07-27 00:00"}

os.environ.pop("AVWIRE_USAGE_TOKEN", None)
check("no token -> no dashboard page",
      build.render_usage_dashboard(env, fake_build) == 0)
os.environ["AVWIRE_USAGE_TOKEN"] = "bad token!"
check("malformed token -> refused",
      build.render_usage_dashboard(env, fake_build) == 0)
os.environ["AVWIRE_USAGE_TOKEN"] = "testtoken-1234567890abc"
check("valid token renders the private page",
      build.render_usage_dashboard(env, fake_build) == 1
      and (TMP / "site" / "u" / "testtoken-1234567890abc"
           / "index.html").exists())
page = (TMP / "site" / "u" / "testtoken-1234567890abc"
        / "index.html").read_text(encoding="utf-8")
codex_snapshot = json.loads(
    (REPO / "config" / "codex_usage.json").read_text(encoding="utf-8"))
snapshot_entry = codex_snapshot["entries"][0]
snapshot_total = (snapshot_entry["inputTokens"]
                  + snapshot_entry["outputTokens"])
check("page shows thirty-day history, fallback chain and final model",
      "最近 30 天模型執行與失敗紀錄" in page
      and "2026-07-30 18:20 TPE" in page
      and "Nemotron 3 Ultra 550B A55B" in page
      and "JSON 格式錯誤" in page
      and "Gemini 3.6 Flash" in page
      and "→ 改用" in page)
check("page shows stage duration and repair count",
      "Archive Context retrieval" in page
      and "223.4 秒" in page
      and "HTTP 2 · Repair 1" in page)
check("dashboard sanitizes secrets and escapes HTML",
      "very-secret" not in page
      and "secret-value" not in page
      and "<script>alert(1)</script>" not in page
      and "&lt;script&gt;alert(1)&lt;/script&gt;" in page)
view_with_old = build.recent_run_view({
    "recentRuns": [
        sample_run,
        {**sample_run, "groupId": "old-hidden",
         "startedUtc": "2020-01-01T00:00Z"},
        {"startedUtc": "bad", "result": "published"},
        {**sample_run, "groupId": "nan",
         "durationsMs": {"total": float("nan")}},
    ]
}, fixed_now)
check("dashboard skips old/malformed rows without crashing on NaN",
      [row["group_id"] for row in view_with_old["runs"]]
      == ["boeing-777-9-test-hours", "nan"]
      and view_with_old["runs"][1]["durations"]["total"] is None)
check("recent model statistics follow configured model priority",
      [row["label"] for row in view_with_old["models"]]
      == ["gemini:gemini-3.6-flash",
          "nvidia:nvidia/nemotron-3-ultra-550b-a55b",
          "nvidia:nvidia/nemotron-3-super-120b-a12b"])
check("page is noindex and shows totals",
      "noindex" in page and "API 用量" in page and "$0" in page)
check("page shows exact Codex GPT-5 task totals and cost semantics",
      "GPT-5 網站製作累計（Codex）" in page
      and f"{snapshot_total:,}" in page
      and f"{snapshot_entry['cachedInputTokens']:,}" in page
      and "推理 tokens 已包含在輸出 tokens 內，不重複加總" in page
      and "實際新增 API 支出" in page)
check("page shows separate GPT-5.6 Sol non-API reference rows",
      "方案內 GPT-5.6 Sol 用途與單價" in page
      and "新聞撰稿（手動補稿）" in page
      and "網站修改（Codex）" in page
      and page.count("<td>$30.00</td>") == 2
      and "不重複計入任何總額" in page)
check("page shows GPT-5 family official rates without adding them to totals",
      "GPT-5 系列 API 理論牌價" in page
      and "GPT-5.6 Terra" in page
      and "GPT-5.4 Pro" in page
      and "GPT-5 nano" in page
      and "$0.500" in page
      and "$0.025" in page
      and "不計入上方實際用量與理論總值" in page
      and page.count("官方牌價") == 19)
check("page never contains key-shaped strings",
      "test-not-a-real-key" not in page and "nvapi-" not in page)
del os.environ["AVWIRE_USAGE_TOKEN"]

# the dashboard is linked from NOWHERE in the public site templates
linked = False
for tpl in (REPO / "templates").glob("*.html"):
    if tpl.name == "usage.html":
        continue
    if "/u/" in tpl.read_text(encoding="utf-8"):
        linked = True
check("no public template links to the private path", not linked)

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
