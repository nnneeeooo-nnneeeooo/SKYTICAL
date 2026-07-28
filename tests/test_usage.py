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
from datetime import timedelta, timezone
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

# ── pricing math + dashboard gating ─────────────────────────────────────────

prices = json.loads((REPO / "config" / "model_prices.json")
                    .read_text(encoding="utf-8"))
rows, totals = build.usage_rows(usage.load_ledger(), prices)
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
check("page is noindex and shows totals",
      "noindex" in page and "API 用量" in page and "$0" in page)
check("page shows separate GPT-5.6 Sol non-API reference rows",
      "GPT-5.6 Sol 非 API 理論牌價" in page
      and "新聞撰稿（手動補稿）" in page
      and "網站修改（Codex）" in page
      and page.count("$30.00") == 2
      and "不計入上方呼叫次數" in page)
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
