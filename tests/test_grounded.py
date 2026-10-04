"""Tests for pipeline/grounded.py (BETA search sweep) — offline.

No pytest required — run from the repo root:

    py tests\\test_grounded.py

All HTTP mocked; verifies the hard guard rails: cited URLs only from
grounding chunks, social/video blocked, forum-pairing, dedupe, caps and
the enable gate.
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
TMP = Path(tempfile.mkdtemp(prefix="avwire-grounded-"))
_ENV_KEYS = ("AVWIRE_DATA_DIR", "BRIEFING_GROUNDED", "BRIEFING_GROUNDED_PROVIDER",
             "BRIEFING_GROUNDED_MODEL", "BRIEFING_GROUNDED_MODELS",
             "BRIEFING_GROUNDED_EFFORT", "GEMINI_API_KEY", "OPENAI_API_KEY")
_OLD_ENV = {key: os.environ.get(key) for key in _ENV_KEYS}
os.environ["AVWIRE_DATA_DIR"] = str(TMP)

sys.path.insert(0, str(REPO / "pipeline"))
import grounded  # noqa: E402
_original_requests = grounded.requests

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


NOW = datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc)


def resp_data(items, chunks):
    return {
        "candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps({"items": items},
                                                      ensure_ascii=False)}]},
            "groundingMetadata": {"groundingChunks": [
                {"web": {"uri": u, "title": t}} for u, t in chunks]},
        }],
        "usageMetadata": {"promptTokenCount": 100,
                          "candidatesTokenCount": 50},
    }


def item(section="aviation_incidents", chunks=(0,), **kw):
    base = {
        "section": section,
        "headline_zh": "德國小型飛機墜入民宅屋頂造成兩人罹難",
        "summary_zh": "德國西北部一架私人小型飛機失事撞入民宅屋頂，"
                      "機上兩名乘員罹難，當地警方與調查單位已介入調查。",
        "headline_en": "Two dead after light aircraft hits house roof",
        "summary_en": "A private light aircraft crashed into a residential "
                      "roof in northwest Germany; both occupants died.",
        "severity": "fatal", "taiwan": False, "military": False,
        "sourcePublishedAt": "2026-07-27T04:00:00+00:00",
        "sourceChunks": list(chunks),
    }
    base.update(kw)
    return base


CHUNKS = [("https://vertexaisearch.example/redirect1", "reuters.com"),
          ("https://www.youtube.com/watch?v=x", "youtube.com"),
          ("https://www.pprune.org/thread", "pprune.org"),
          ("https://economictimes.com/article", "economictimes.com"),
          ("https://news.google.com/rss/articles/example?oc=5", "Google News")]

# ── enable gate ──────────────────────────────────────────────────────────────

os.environ.pop("BRIEFING_GROUNDED", None)
check("disabled without the env flag", not grounded.enabled())
os.environ["BRIEFING_GROUNDED"] = "true"
check("enabled with the env flag", grounded.enabled())

# ── sanitize: chunk-only citations ───────────────────────────────────────────

seen = {}
out, warn = grounded.sanitize_items(
    resp_data([item(chunks=(0,))], CHUNKS), [], seen, NOW)
got = out["aviation_incidents"]
check("valid item accepted with the retrieved source",
      len(got) == 1 and got[0]["origin"] == "grounded"
      and got[0]["sources"][0]["url"]
      == "https://vertexaisearch.example/redirect1")
window_for_items = types.SimpleNamespace(
    window_start=NOW, window_end=NOW + timedelta(hours=24))
dated, _ = grounded.sanitize_items(
    resp_data([item()], CHUNKS), [], {}, NOW, window_for_items)
check("grounded item retains its in-window source time",
      dated["aviation_incidents"][0]["source_published_at"]
      == "2026-07-27T04:00:00+00:00")
for bad_date in ("", "2026-07-26T23:59:59+00:00",
                 "2026-07-28T00:00:00+00:00", "2026-07-27T04:00:00"):
    rejected, _ = grounded.sanitize_items(
        resp_data([item(sourcePublishedAt=bad_date)], CHUNKS),
        [], {}, NOW, window_for_items)
    check(f"missing, out-of-window or timezone-free date rejected: {bad_date!r}",
          rejected["aviation_incidents"] == [])
check("item severity/marks metadata preserved",
      got[0]["severity"] == "fatal" and got[0]["event_id"].startswith("gr-"))

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=(9,))], CHUNKS), [], {}, NOW)
check("out-of-range sourceChunks (hallucinated citation) dropped",
      out["aviation_incidents"] == [])

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=())], CHUNKS), [], {}, NOW)
check("item with no retrieved source dropped",
      out["aviation_incidents"] == [])

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=(1,))], CHUNKS), [], {}, NOW)
check("social/video-only citation dropped",
      out["aviation_incidents"] == [])

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=(4,))], CHUNKS), [], {}, NOW)
check("Google News aggregator citation dropped",
      out["aviation_incidents"] == [])

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=(2,))], CHUNKS), [], {}, NOW)
check("forum-only citation dropped",
      out["aviation_incidents"] == [])

out, _ = grounded.sanitize_items(
    resp_data([item(chunks=(2, 3))], CHUNKS), [], {}, NOW)
check("forum + established-media citation accepted",
      len(out["aviation_incidents"]) == 1
      and len(out["aviation_incidents"][0]["sources"]) == 2)

# ── per-response dedupe + caps ──────────────────────────────────────────────

seen = {}
grounded.sanitize_items(resp_data([item()], CHUNKS), [], seen, NOW)
out2, _ = grounded.sanitize_items(resp_data([item()], CHUNKS), [], seen, NOW)
check("complete snapshots may retain the same story in a later edition",
      len(out2["aviation_incidents"]) == 1)
out_dupe, _ = grounded.sanitize_items(
    resp_data([item(), item()], CHUNKS), [], {}, NOW)
check("duplicate items in one model response are collapsed",
      len(out_dupe["aviation_incidents"]) == 1)
check("seen entries carry a TTL and prune",
      grounded.prune_seen(
          {"old": (NOW - timedelta(hours=1)).isoformat(),
           "new": (NOW + timedelta(hours=1)).isoformat()}, NOW)
      == {"new": (NOW + timedelta(hours=1)).isoformat()})

out, _ = grounded.sanitize_items(
    resp_data([item()], CHUNKS),
    ["德國小型飛機墜入民宅屋頂造成兩人罹難"], {}, NOW)
check("stories the pipeline already covers are not duplicated",
      out["aviation_incidents"] == [])

many = [dict(item(), headline_zh=f"完全不同的事件標題編號第{i}號測試")
        for i in range(8)]
out, warn = grounded.sanitize_items(resp_data(many, CHUNKS), [], {}, NOW)
check("per-section cap enforced with a warning",
      len(out["aviation_incidents"]) == grounded.MAX_PER_SECTION
      and any("dropped" in w for w in warn))

out, warn = grounded.sanitize_items(
    {"candidates": [{"finishReason": "STOP",
                     "content": {"parts": [{"text": "not json at all"}]}}]},
    [], {}, NOW)
check("garbage output degrades with a warning, never crashes",
      all(v == [] for v in out.values()) and warn)

# ── call payload (owner-tuned settings) ──────────────────────────────────────

captured = {}


def fake_post(url, json=None, timeout=None, headers=None):
    captured["url"] = url
    captured["payload"] = json
    return types.SimpleNamespace(
        status_code=200,
        json=lambda: resp_data([], []))


grounded.requests = types.SimpleNamespace(post=fake_post)
os.environ["GEMINI_API_KEY"] = "test-not-real"
window = types.SimpleNamespace(
    window_start=NOW, window_end=NOW + timedelta(hours=24))
data, shim = grounded.call_grounded(window)
del os.environ["GEMINI_API_KEY"]
cfg = captured["payload"]["generationConfig"]
check("grounded call uses google_search tool",
      captured["payload"]["tools"] == [{"google_search": {}}])
check("owner-tuned sampling: temperature 0.2 + high thinking",
      cfg["temperature"] == 0.2
      and cfg["thinkingConfig"] == {"thinkingLevel": "high"})
check("usage shim carries thinking-inclusive token counts",
      shim.usage["inputTokens"] == 100 and shim.http_calls == 1)
check("no key -> no call", grounded.call_grounded(window) == (None, None))
check("grounded call targets a real model id in the URL",
      f"models/{grounded.GROUNDED_MODEL}:generateContent"
      in captured["url"] and grounded.GROUNDED_MODEL)

fallback_calls = []


def fake_post_with_quota_fallback(url, json=None, timeout=None, headers=None):
    fallback_calls.append(url)
    if len(fallback_calls) == 1:
        return types.SimpleNamespace(status_code=429, text="quota")
    return types.SimpleNamespace(
        status_code=200, json=lambda: resp_data([], []))


grounded.requests = types.SimpleNamespace(post=fake_post_with_quota_fallback)
os.environ["GEMINI_API_KEY"] = "test-not-real"
_fallback_data, fallback_shim = grounded.call_grounded(window)
del os.environ["GEMINI_API_KEY"]
check("HTTP 429 falls through to the next grounded Gemini model",
      len(fallback_calls) == 2
      and fallback_shim.model == grounded.GROUNDED_MODELS[1]
      and fallback_shim.http_calls == 2)

hard_quota_calls = []


def fake_post_with_hard_quota(url, json=None, timeout=None, headers=None):
    hard_quota_calls.append(url)
    return types.SimpleNamespace(
        status_code=429,
        text="You exceeded your current quota, please check your plan and billing details.")


grounded.requests = types.SimpleNamespace(post=fake_post_with_hard_quota)
os.environ["GEMINI_API_KEY"] = "test-not-real"
hard_quota_raised = False
try:
    grounded.call_grounded(window)
except RuntimeError:
    hard_quota_raised = True
finally:
    del os.environ["GEMINI_API_KEY"]
check("billing/project quota exhaustion stops model-churn after one call",
      hard_quota_raised and len(hard_quota_calls) == 1)

# the empty-string env CI passes when the repo var is unset must not
# blank the model id (this exact bug produced HTTP 404 in production)
import importlib  # noqa: E402

os.environ["BRIEFING_GROUNDED_MODEL"] = ""
importlib.reload(grounded)
check("empty BRIEFING_GROUNDED_MODEL env falls back to the default",
      grounded.GROUNDED_MODEL == "gemini-3.6-flash"
      and grounded.GROUNDED_MODELS[:2]
      == ("gemini-3.6-flash", "gemini-3.5-flash"))
del os.environ["BRIEFING_GROUNDED_MODEL"]
importlib.reload(grounded)

# ── OpenAI Responses web_search adapter and bounded routing ──────────────────

window = types.SimpleNamespace(
    window_start=NOW, window_end=NOW + timedelta(hours=24))
openai_item = item(sourceChunks=[])  # URLs are mapped from actual retrieval metadata.
openai_payload_text = json.dumps({"items": [dict(openai_item,
    sourceUrls=["https://news.example/actual", "https://fake.example/forged"])]},
    ensure_ascii=False)
openai_response = {
    "status": "completed",
    "output": [
        {"type": "web_search_call", "status": "completed", "action": {
            "sources": [{"url": "https://news.example/actual", "title": "News"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": openai_payload_text,
            "annotations": [{"type": "url_citation", "url": "https://news.example/actual",
                             "title": "News"},
                            ]}]},
    ],
    "usage": {"input_tokens": 123, "output_tokens": 45},
}
captured_openai = {}
usage_calls = []
try:
    import usage  # noqa: E402
    _original_record_providers = usage.record_providers
except Exception:
    usage = None
    _original_record_providers = None


def fake_openai_post(url, json=None, timeout=None, headers=None):
    captured_openai.update(url=url, payload=json, headers=headers, timeout=timeout)
    return types.SimpleNamespace(status_code=200, json=lambda: openai_response)


grounded.requests = types.SimpleNamespace(post=fake_openai_post)
if usage:
    usage.record_providers = lambda providers: usage_calls.append(list(providers))
os.environ["BRIEFING_GROUNDED_PROVIDER"] = "openai"
os.environ["OPENAI_API_KEY"] = "offline-test-key"
os.environ["BRIEFING_GROUNDED_MODEL"] = "gpt-6-luna"
data, shim = grounded.call_grounded(window)
openai_items, openai_warnings = grounded.sanitize_items(
    data, [], {}, NOW, window)
accepted = openai_items["aviation_incidents"]
check("OpenAI result maps only retrieved source URLs into citation chunks",
      len(accepted) == 1
      and accepted[0]["sources"] == [{"name": "News", "url": "https://news.example/actual"}]
      and all(source["url"] != "https://fake.example/forged"
              for source in accepted[0]["sources"]))
check("OpenAI call selects Luna Responses web_search with bounded medium reasoning",
      captured_openai["url"] == "https://api.openai.com/v1/responses"
      and captured_openai["payload"]["model"] == "gpt-6-luna"
      and captured_openai["payload"]["reasoning"] == {"effort": "medium"}
      and captured_openai["payload"]["tools"][0]["type"] == "web_search"
      and captured_openai["payload"]["max_tool_calls"] == 4)
check("OpenAI usage shim records paid call and prevents duplicate upper-layer recording",
      shim.usage_recorded and shim.usage["inputTokens"] == 123
      and shim.usage["outputTokens"] == 45
      and (not usage or len(usage_calls) == 1))

# No key is a clean zero-network result; incomplete responses are not adapted.
del os.environ["OPENAI_API_KEY"]
before = len(captured_openai)
check("OpenAI provider without key returns no data and makes no request",
      grounded.call_grounded(window) == (None, None) and len(captured_openai) == before)
os.environ["OPENAI_API_KEY"] = "offline-test-key"
for label, response in (
        ("non-completed response", dict(openai_response, status="incomplete")),
        ("missing completed search call", {"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": openai_payload_text,
                                                  "annotations": []}]}]}),
):
    try:
        grounded._openai_search_response(response)
        rejected = False
    except ValueError:
        rejected = True
    check("OpenAI " + label + " is rejected", rejected)

# Only sources in the completed search metadata are eligible, including citations
# added by annotations; model-only fake URLs never become a source chunk.
fake_only_text = json.dumps({"items": [dict(openai_item,
    sourceUrls=["https://model-only.example/fake"])]}, ensure_ascii=False)
fake_only = dict(openai_response, output=[
    openai_response["output"][0],
    {"type": "message", "content": [{"type": "output_text", "text": fake_only_text,
                                         "annotations": []}]},
])
adapted_fake = grounded._openai_search_response(fake_only)
fake_out, _ = grounded.sanitize_items(adapted_fake, [], {}, NOW, window)
check("model-typed URL without retrieved metadata cannot be cited",
      fake_out["aviation_incidents"] == [])

# Existing sanitizer continues enforcing timestamp timezone and window limits.
for bad_date in ("2026-07-26T23:59:59+00:00", "2026-07-28T00:00:00+00:00",
                 "2026-07-27T04:00:00"):
    bad_data = grounded._openai_search_response(dict(openai_response, output=[
        openai_response["output"][0],
        {"type": "message", "content": [{"type": "output_text",
          "text": json.dumps({"items": [dict(openai_item, sourcePublishedAt=bad_date,
               sourceUrls=["https://news.example/actual"])]}, ensure_ascii=False),
          "annotations": []}]},
    ]))
    bad_out, _ = grounded.sanitize_items(bad_data, [], {}, NOW, window)
    check("OpenAI source date outside window or without timezone rejected: " + bad_date,
          bad_out["aviation_incidents"] == [])

if usage:
    usage.record_providers = _original_record_providers
grounded.requests = _original_requests
for _key, _value in _OLD_ENV.items():
    if _value is None:
        os.environ.pop(_key, None)
    else:
        os.environ[_key] = _value
try:
    import shutil
    shutil.rmtree(TMP)
except OSError:
    pass

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
if __name__ == "__main__":
    sys.exit(1 if FAILED else 0)
