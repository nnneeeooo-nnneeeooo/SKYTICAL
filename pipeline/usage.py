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

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA_DIR,
    iso_minute,
    load_json,
    now_utc,
    save_json,
)

USAGE_PATH = DATA_DIR / "usage.json"
DAILY_KEEP_DAYS = 120


def load_ledger() -> dict:
    raw = load_json(USAGE_PATH, {})
    models = raw.get("models")
    daily = raw.get("daily")
    return {
        "updatedUtc": raw.get("updatedUtc"),
        "trackingSinceUtc": raw.get("trackingSinceUtc"),
        "models": models if isinstance(models, dict) else {},
        "daily": daily if isinstance(daily, dict) else {},
    }


def _provider_usage_rows(
    providers,
) -> list[tuple[str, int, int, int, int]]:
    """Snapshot non-idle provider counters for one ledger flush."""
    rows: list[tuple[str, int, int, int, int]] = []
    for provider in providers or []:
        calls = int(getattr(provider, "http_calls", 0) or 0)
        if calls <= 0:
            continue
        counters = getattr(provider, "usage", None) or {}
        rows.append((
            str(getattr(provider, "label", "?")),
            calls,
            int(counters.get("inputTokens") or 0),
            int(counters.get("outputTokens") or 0),
            int(counters.get("usageEvents") or 0),
        ))
    return rows


def record_providers(providers) -> None:
    """Merge this run's provider spend into the ledger. Call ONCE per run
    per provider set - the counters live on the provider objects."""
    rows = _provider_usage_rows(providers)
    if not rows:
        return
    ledger = load_ledger()
    now = now_utc()
    stamp = iso_minute(now)
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
    ledger["updatedUtc"] = stamp
    ledger["trackingSinceUtc"] = ledger.get("trackingSinceUtc") or stamp
    save_json(USAGE_PATH, ledger)
    total_calls = sum(r[1] for r in rows)
    print(f"usage: recorded {total_calls} call(s) across {len(rows)} "
          f"provider(s)")
