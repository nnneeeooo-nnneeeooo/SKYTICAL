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
os.environ["AVWIRE_DATA_DIR"] = str(TMP)

sys.path.insert(0, str(REPO / "pipeline"))
import grounded  # noqa: E402

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

# ── dedupe + caps ────────────────────────────────────────────────────────────

seen = {}
grounded.sanitize_items(resp_data([item()], CHUNKS), [], seen, NOW)
out2, _ = grounded.sanitize_items(resp_data([item()], CHUNKS), [], seen, NOW)
check("seen-set blocks the same story in a later edition",
      out2["aviation_incidents"] == [])
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
    window_start=NOW, window_end=NOW + timedelta(hours=8))
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

# the empty-string env CI passes when the repo var is unset must not
# blank the model id (this exact bug produced HTTP 404 in production)
import importlib  # noqa: E402

os.environ["BRIEFING_GROUNDED_MODEL"] = ""
importlib.reload(grounded)
check("empty BRIEFING_GROUNDED_MODEL env falls back to the default",
      grounded.GROUNDED_MODEL == "gemini-3.6-flash")
del os.environ["BRIEFING_GROUNDED_MODEL"]
importlib.reload(grounded)

del os.environ["BRIEFING_GROUNDED"]

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
