"""grounded.py — BETA model-assisted search sweep for the daily briefing.

Owner policy (2026-07-27): the briefing MAY use a search-capable model to
widen coverage beyond the fetch pipeline, clearly labelled BETA on the
site. This is deliberately scoped to the briefing only - articles are
still written exclusively from pipeline-fetched material.

Guard rails (code, not prompt-trust):
- Only Gemini grounding (google_search tool) is used; temperature 0.2 and
  a high thinking level per the owner's tuning request.
- Cited URLs NEVER come from model text: each item must reference the
  grounding chunks Google actually retrieved (sourceChunks indices), and
  the rendered links are those chunk URIs. A typed/hallucinated URL has
  no path into the page.
- Social/video domains are rejected; forum sources are allowed only
  alongside at least one non-forum source (owner's relaxation, kept one
  notch conservative).
- Items are deduped against the pipeline's own items and within each model
  response. Because every edition is a complete trailing-24-hour snapshot,
  an event may legitimately remain visible in more than one edition.
- Any failure (quota, tool unavailable, bad JSON) degrades to the
  deterministic briefing with a coverage warning - never a failed
  edition. One call per edition, spend recorded in the usage ledger.
"""
from __future__ import annotations

import hashlib
import os
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import is_google_news_url, squash_text  # noqa: E402
from providers import extract_json  # noqa: E402

# The primary model can be configured without giving up automatic recovery.
# Search quotas are model-specific on some Gemini plans; production recently
# returned HTTP 429 for the primary model while other configured Gemini models
# remained available. Try the explicit model first, then stable fallbacks.
_DEFAULT_GROUNDED_MODELS = (
    "gemini-3.6-flash", "gemini-3.5-flash", "gemini-2.5-flash")


def _grounded_models() -> tuple[str, ...]:
    raw_many = os.environ.get("BRIEFING_GROUNDED_MODELS", "")
    explicit = os.environ.get("BRIEFING_GROUNDED_MODEL", "")
    requested = [part.strip() for part in raw_many.split(",") if part.strip()]
    if explicit.strip():
        requested.insert(0, explicit.strip())
    ordered = requested + list(_DEFAULT_GROUNDED_MODELS)
    return tuple(dict.fromkeys(ordered))


GROUNDED_MODELS = _grounded_models()
GROUNDED_MODEL = GROUNDED_MODELS[0]  # backward-compatible public name
TIMEOUT = (10, 180)
MAX_PER_SECTION = 4
SEEN_TTL_HOURS = 72

SECTIONS = ("aviation_incidents", "taiwan_aviation",
            "international_aviation", "ground_and_maritime")

# social/video platforms never count as a briefing source
_BLOCKED_HOSTS = ("youtube.com", "youtu.be", "facebook.com", "instagram.",
                  "tiktok.", "x.com", "twitter.com", "pinterest.",
                  "threads.net", "weibo.com")
# forums are allowed, but only alongside a non-forum source
_FORUM_HOSTS = ("reddit.com", "pprune.org", "ptt.cc", "dcard.tw",
                "airliners.net/forum", "flyertalk.com")

_SEVERITIES = ("routine", "significant", "serious", "fatal")


def enabled() -> bool:
    return (os.environ.get("BRIEFING_GROUNDED", "").strip().lower()
            in ("1", "true", "yes"))


SYSTEM_PROMPT = """\
你是 SKYTICAL 的航空與交通運輸快報彙整助理。使用 google_search 搜尋本期指定的
「完整 24 小時資料窗口」，聚焦：全球航空事故與事件、台灣民航與軍用航空動態（含國防部共機動態、
華航/長榮/星宇/台灣虎航/立榮/華信）、國際航空產業（訂單/航線/政策/破產）、
台灣與全球重大鐵路/公路/海運事件。

嚴格規則：
- 只報導搜尋結果明確支持的事實；可加入來源明確支持且有助理解的近期背景，
  但必須標示實際日期，不得把舊事件寫成今日事件，不得推測原因或責任。
- 保留來源的不確定語氣（據報導/初步/調查中），不得升級確定性。
- 每一則 item 的 sourceChunks 必須列出支持該則內容的檢索結果編號
  （grounding chunk index，從 0 起算）；沒有可引用檢索結果的內容不得輸出。
- 繁體中文（台灣用語）為主，並提供英文版本。
- 事故有死亡者 severity="fatal"；重大事故 "serious"；一般飛安事件
  "significant"；其他 "routine"。military=true 僅限軍用航空相關。
- 無符合的新事件時輸出空的 items 陣列，不得編造。

輸出 JSON（無 markdown fence）：
{"items":[{"section":"aviation_incidents|taiwan_aviation|international_aviation|ground_and_maritime",
"headline_zh":"18-40字","summary_zh":"26-38字；須含主體與明確事件；完整短句優先，否則以最多兩個全形分號『；』串接可獨立閱讀的事實子句；禁止拆開人名、航空器型號或機場代碼；禁止刪節號與孤立標籤","headline_en":"...","summary_en":"10-18 words; include a named subject and clear event; use readable clauses with at most two semicolons; never split proper names, aircraft models or airport codes; no ellipsis or isolated labels",
"severity":"routine|significant|serious|fatal","taiwan":false,"military":false,
"sourceChunks":[0]}]}
"""


def _host_of(text: str) -> str:
    return str(text or "").casefold()


def _is_blocked(chunk) -> bool:
    blob = _host_of(f"{chunk.get('uri')} {chunk.get('title')}")
    return any(h in blob for h in _BLOCKED_HOSTS)


def _is_forum(chunk) -> bool:
    blob = _host_of(f"{chunk.get('uri')} {chunk.get('title')}")
    return any(h in blob for h in _FORUM_HOSTS)


def _chunks_from(data: dict) -> list[dict]:
    candidates = data.get("candidates") or []
    if not candidates:
        return []
    meta = candidates[0].get("groundingMetadata") or {}
    chunks = []
    for c in meta.get("groundingChunks") or []:
        web = (c or {}).get("web") or {}
        uri, title = str(web.get("uri") or ""), str(web.get("title") or "")
        chunks.append({"uri": uri, "title": title})
    return chunks


def _final_text(data: dict) -> str | None:
    candidates = data.get("candidates") or []
    if not candidates:
        return None
    finish = candidates[0].get("finishReason")
    if finish not in (None, "STOP"):
        return None
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts
                   if isinstance(p, dict) and not p.get("thought"))
    return text.strip() or None


def call_grounded(window) -> tuple[dict | None, SimpleNamespace | None]:
    """Grounded search with model-level quota/unavailability fallback."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return None, None
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text":
            f"本期快報資料窗口（台北時間）：{window.window_start.isoformat()} 至 "
            f"{window.window_end.isoformat()}。這是完整 24 小時窗口；請搜尋並輸出"
            "窗口內的新事件，以及由來源明確支持、仍有助理解的近期背景 JSON。"}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {
            # owner-tuned: low temperature + high thinking level so the
            # sweep stays literal and source-faithful
            "temperature": 0.2,
            "maxOutputTokens": 16384,
            "thinkingConfig": {"thinkingLevel": "high"},
        },
    }
    failures = []
    for model in GROUNDED_MODELS:
        resp = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent",
            json=payload, timeout=TIMEOUT,
            headers={"x-goog-api-key": key})
        if resp.status_code == 200:
            data = resp.json()
            meta = data.get("usageMetadata") or {}
            shim = SimpleNamespace(
                model=model, label=f"gemini:{model}+search",
                http_calls=len(failures) + 1,
                usage={"inputTokens": int(meta.get("promptTokenCount") or 0),
                       "outputTokens": (
                           int(meta.get("candidatesTokenCount") or 0)
                           + int(meta.get("thoughtsTokenCount") or 0)),
                       "usageEvents": 1 if meta else 0})
            return data, shim
        snippet = str(getattr(resp, "text", ""))[:160].replace("\n", " ")
        failures.append(f"{model}=HTTP {resp.status_code}: {snippet}")
        print(f"briefing: grounded model {model} unavailable "
              f"(HTTP {resp.status_code}); trying fallback")
        if resp.status_code not in (404, 408, 429, 500, 502, 503, 504):
            break
    raise RuntimeError("grounded models unavailable: " + " | ".join(failures))


def _seen_key(headline_zh: str) -> str:
    return hashlib.sha256(
        squash_text(headline_zh).encode("utf-8")).hexdigest()[:16]


def sanitize_items(data: dict, existing_titles: list[str],
                   seen: dict, now) -> tuple[dict, list[str]]:
    """Validated grounded items per section + warnings. Mutates `seen`."""
    warnings: list[str] = []
    out: dict = {name: [] for name in SECTIONS}
    text = _final_text(data)
    if not text:
        return out, ["grounded sweep returned no usable text"]
    try:
        parsed = extract_json(text)
    except ValueError as exc:
        return out, [f"grounded sweep JSON unusable ({exc})"]
    chunks = _chunks_from(data)
    existing_squashed = [squash_text(t) for t in existing_titles if t]
    dropped = 0
    emitted_keys = set()
    for item in (parsed.get("items") or [])[:40]:
        if not isinstance(item, dict):
            continue
        section = item.get("section")
        head_zh = str(item.get("headline_zh") or "").strip()
        sum_zh = str(item.get("summary_zh") or "").strip()
        if (section not in SECTIONS or not (8 <= len(head_zh) <= 60)
                or not (20 <= len(sum_zh) <= 400)):
            dropped += 1
            continue
        refs = item.get("sourceChunks")
        refs = [r for r in refs if isinstance(r, int)
                and 0 <= r < len(chunks)] if isinstance(refs, list) else []
        cited = [chunks[r] for r in dict.fromkeys(refs)]
        cited = [c for c in cited
                 if c["uri"] and not _is_blocked(c)
                 and not is_google_news_url(c["uri"])]
        # forums only alongside at least one non-forum source
        if cited and all(_is_forum(c) for c in cited):
            dropped += 1
            continue
        if not cited:
            dropped += 1  # no retrieved source -> no publication path
            continue
        key = _seen_key(head_zh)
        if key in emitted_keys:
            continue
        emitted_keys.add(key)
        squashed = squash_text(head_zh)
        if any(squashed in t or t in squashed
               for t in existing_squashed if len(t) >= 8):
            continue  # pipeline already covers this story
        if len(out[section]) >= MAX_PER_SECTION:
            dropped += 1
            continue
        # Kept only for backward-compatible retention/diagnostics. It no
        # longer suppresses later editions: each report is a full snapshot.
        seen[key] = (now + timedelta(hours=SEEN_TTL_HOURS)).isoformat()
        severity = item.get("severity")
        out[section].append({
            "event_id": f"gr-{key}",
            "item_type": "new",
            "previous_event_id": None,
            "origin": "grounded",
            "category": "grounded_beta",
            "headline": head_zh,
            "summary": sum_zh,
            "headline_en": str(item.get("headline_en") or "").strip(),
            "summary_en": str(item.get("summary_en") or "").strip(),
            "event_time": None,
            "source_published_at": None,
            "source_updated_at": None,
            "location": None,
            "entities": [],
            "severity": severity if severity in _SEVERITIES else "routine",
            "taiwan_priority": bool(item.get("taiwan")),
            "military": bool(item.get("military")),
            "sources": [{"name": c["title"] or c["uri"], "url": c["uri"]}
                        for c in cited[:4]],
            "risk_flags": [],
            "article_id": None,
        })
    if dropped:
        warnings.append(f"grounded sweep: {dropped} item(s) dropped by "
                        f"source-quality/limit checks")
    return out, warnings


def prune_seen(seen: dict, now) -> dict:
    from common import parse_iso

    kept = {}
    for key, expiry in (seen or {}).items():
        try:
            if parse_iso(str(expiry)) > now:
                kept[key] = expiry
        except (ValueError, TypeError):
            continue
    return kept
