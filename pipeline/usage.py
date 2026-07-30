"""usage.py — cumulative LLM API usage ledger (data/usage.json).

Providers accumulate per-call token usage in memory (providers.py reads
it straight from each API response); write.py and briefing.py flush it
here exactly once per run. The ledger stores lifetime totals per model
label plus a rolling daily series, and build.py renders it on a private
dashboard page whose URL contains a secret token (AVWIRE_USAGE_TOKEN).

Numbers are usage accounting only - no keys, no prompts, no article
content ever lands in this file. Calls made before this ledger existed
are backfilled as `unknownCalls` (call counts recovered from CI logs;
their token spend is unrecoverable).
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA_DIR,
    iso_minute,
    load_json,
    now_utc,
    parse_iso,
    save_json,
)

USAGE_PATH = DATA_DIR / "usage.json"
DAILY_KEEP_DAYS = 120
RECENT_RUN_KEEP_DAYS = 30
RECENT_RUN_MAX = 1000
_RUN_STAGES = (
    "companionRetrieval", "fulltextEnrichment", "plaEnrichment",
    "archiveRetrieval", "promptAssembly", "drafting", "validation",
    "factVerification", "evidenceBinding", "glossaryCheck",
    "fabricationCheck", "articleBuild", "total",
)


def _short_text(value, limit: int) -> str | None:
    if not isinstance(value, (str, int)):
        return None
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"https?://\S+", "[URL removed]", text,
                  flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\bauthorization\b\s*[:=]?\s*(?:bearer\s+)?\S+",
        "Authorization [redacted]",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[-_ ]?key|token|bearer)\b\s*[:=]?\s*\S*",
        r"\1 [redacted]",
        text,
    )
    return text[:limit] or None


def _safe_count(value, maximum=1_000_000) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, min(int(value or 0), maximum))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_duration(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if number < 0 or number != number or number == float("inf"):
        return None
    return min(round(number), 86_400_000)


def _sanitize_resource_usage(value) -> dict:
    """Keep only token accounting metadata for one private workbench job."""
    value = value if isinstance(value, dict) else {}
    models = []
    for raw in value.get("models") or []:
        if not isinstance(raw, dict):
            continue
        label = _short_text(raw.get("label"), 160)
        if not label:
            continue
        models.append({
            "label": label,
            "inputTokens": _safe_count(
                raw.get("inputTokens"), 100_000_000),
            "outputTokens": _safe_count(
                raw.get("outputTokens"), 100_000_000),
            "estimated": raw.get("estimated") is True,
        })
        if len(models) >= 50:
            break
    return {
        "actualUsd": 0.0,
        "models": models,
    }


def _sanitize_recent_run(row: dict) -> dict | None:
    """Whitelist the detail schema so content/secrets cannot be persisted."""
    if not isinstance(row, dict):
        return None
    started = _short_text(row.get("startedUtc"), 40)
    finished = _short_text(row.get("finishedUtc"), 40)
    if _recent_run_time({"startedUtc": started, "finishedUtc": finished}) \
            is None:
        return None
    raw_durations = row.get("durationsMs")
    raw_durations = raw_durations if isinstance(raw_durations, dict) else {}
    durations = {
        key: _safe_duration(raw_durations.get(key))
        for key in _RUN_STAGES
        if key in raw_durations
    }
    attempts = []
    raw_attempts = row.get("attempts")
    for item in (raw_attempts if isinstance(raw_attempts, list) else [])[:50]:
        if not isinstance(item, dict):
            continue
        label = _short_text(item.get("label"), 160)
        outcome = _short_text(item.get("outcome"), 24)
        if not label or outcome not in ("success", "failed", "refused"):
            continue
        attempts.append({
            "sequence": len(attempts) + 1,
            "provider": _short_text(item.get("provider"), 40),
            "model": _short_text(item.get("model"), 160),
            "label": label,
            "startedUtc": _short_text(item.get("startedUtc"), 40),
            "durationMs": _safe_duration(item.get("durationMs")),
            "httpCalls": _safe_count(item.get("httpCalls"), 100),
            "repairCalls": _safe_count(item.get("repairCalls"), 100),
            "httpDurationMs": _safe_duration(item.get("httpDurationMs")),
            "repairDurationMs":
                _safe_duration(item.get("repairDurationMs")),
            "outcome": outcome,
            "failureClass": _short_text(item.get("failureClass"), 48),
            "failureStage": _short_text(item.get("failureStage"), 48),
            "failureMessage": _short_text(item.get("failureMessage"), 180),
            "retryPlanned": item.get("retryPlanned") is True,
            "disabledForRun": item.get("disabledForRun") is True,
        })
    return {
        "startedUtc": started,
        "finishedUtc": finished,
        "workflow": _short_text(row.get("workflow"), 32) or "unknown",
        "taskType": _short_text(row.get("taskType"), 32) or "unknown",
        "groupId": _short_text(row.get("groupId"), 160),
        "eventId": _short_text(row.get("eventId"), 160),
        "sourceCount": _safe_count(row.get("sourceCount"), 10_000),
        "primarySource": _short_text(row.get("primarySource"), 160),
        "result": _short_text(row.get("result"), 40),
        "articleId": _short_text(row.get("articleId"), 180),
        "finalStatus": _short_text(row.get("finalStatus"), 48),
        "finalModel": _short_text(row.get("finalModel"), 160),
        "fallbackUsed": row.get("fallbackUsed") is True,
        "attemptCount": len(attempts),
        "httpCallCount": sum(item["httpCalls"] for item in attempts),
        "repairCallCount": sum(item["repairCalls"] for item in attempts),
        "durationsMs": durations,
        "attempts": attempts,
        "resourceUsage": _sanitize_resource_usage(
            row.get("resourceUsage")),
    }


def _recent_run_time(row: dict):
    """Return the retention timestamp for a minimally valid run row."""
    if not isinstance(row, dict):
        return None
    value = row.get("startedUtc") or row.get("finishedUtc")
    if not isinstance(value, str):
        return None
    try:
        return parse_iso(value)
    except (TypeError, ValueError):
        return None


def _prune_recent_runs(rows, now=None) -> list[dict]:
    """Keep valid run dictionaries inside the inclusive 30-day window."""
    now = now or now_utc()
    cutoff = (now - timedelta(days=RECENT_RUN_KEEP_DAYS)).replace(
        second=0, microsecond=0)
    kept = []
    for row in rows if isinstance(rows, list) else []:
        sanitized = _sanitize_recent_run(row)
        stamp = _recent_run_time(sanitized) if sanitized else None
        if stamp is None or stamp < cutoff:
            continue
        kept.append((stamp, sanitized))
    kept.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in kept[:RECENT_RUN_MAX]]


def load_ledger() -> dict:
    raw = load_json(USAGE_PATH, {})
    if not isinstance(raw, dict):
        raw = {}
    models = raw.get("models")
    daily = raw.get("daily")
    return {
        "updatedUtc": raw.get("updatedUtc"),
        "trackingSinceUtc": raw.get("trackingSinceUtc"),
        "models": models if isinstance(models, dict) else {},
        "daily": daily if isinstance(daily, dict) else {},
        "recentRuns": _prune_recent_runs(raw.get("recentRuns")),
    }


def _stamp_ledger(ledger: dict, now) -> None:
    ledger["recentRuns"] = _prune_recent_runs(
        ledger.get("recentRuns"), now)
    ledger["updatedUtc"] = iso_minute(now)
    ledger.setdefault("trackingSinceUtc", iso_minute(now))
    if not ledger["trackingSinceUtc"]:
        ledger["trackingSinceUtc"] = iso_minute(now)


def record_run(run: dict) -> None:
    """Append one model-work record without ever failing the news pipeline."""
    try:
        sanitized = _sanitize_recent_run(run)
        if sanitized is None:
            print("usage: recent run ignored (missing valid timestamp)")
            return
        ledger = load_ledger()
        ledger["recentRuns"].append(sanitized)
        _stamp_ledger(ledger, now_utc())
        save_json(USAGE_PATH, ledger)
        print("usage: recorded recent model run")
    except Exception as exc:  # ledger diagnostics must not stop publishing
        print(f"usage: recent run update failed ({type(exc).__name__})")


def record_providers(providers) -> None:
    """Merge this run's provider spend into the ledger. Call ONCE per run
    per provider set - the counters live on the provider objects."""
    rows = []
    for p in providers or []:
        calls = int(getattr(p, "http_calls", 0) or 0)
        if calls <= 0:
            continue
        u = getattr(p, "usage", None) or {}
        rows.append((str(getattr(p, "label", "?")), calls,
                     int(u.get("inputTokens") or 0),
                     int(u.get("outputTokens") or 0),
                     int(u.get("usageEvents") or 0)))
    if not rows:
        return
    ledger = load_ledger()
    now = now_utc()
    day = now.strftime("%Y-%m-%d")
    for label, calls, tokens_in, tokens_out, events in rows:
        m = ledger["models"].setdefault(label, {
            "calls": 0, "inputTokens": 0, "outputTokens": 0,
            "unknownCalls": 0})
        m["calls"] = int(m.get("calls") or 0) + calls
        m["inputTokens"] = int(m.get("inputTokens") or 0) + tokens_in
        m["outputTokens"] = int(m.get("outputTokens") or 0) + tokens_out
        m["unknownCalls"] = (int(m.get("unknownCalls") or 0)
                             + max(0, calls - events))
        d = ledger["daily"].setdefault(day, {
            "calls": 0, "inputTokens": 0, "outputTokens": 0})
        d["calls"] += calls
        d["inputTokens"] += tokens_in
        d["outputTokens"] += tokens_out
    cutoff = (now - timedelta(days=DAILY_KEEP_DAYS)).strftime("%Y-%m-%d")
    ledger["daily"] = {k: v for k, v in sorted(ledger["daily"].items())
                       if k >= cutoff}
    _stamp_ledger(ledger, now)
    save_json(USAGE_PATH, ledger)
    total_calls = sum(r[1] for r in rows)
    print(f"usage: recorded {total_calls} call(s) across {len(rows)} "
          f"provider(s)")
