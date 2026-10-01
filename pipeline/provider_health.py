"""Persistent provider-platform cooldowns for SKYTICAL drafting.

The writer already has a run-local circuit breaker. This module persists only
platform-level infrastructure failures that are unlikely to recover within the
next hourly run, so a known-bad free provider is not hammered every hour.

No prompts, source text, API keys or raw exception messages are stored here.
"""
from __future__ import annotations

from datetime import timedelta

from common import DATA_DIR, iso_minute, load_json, now_utc, parse_iso, save_json

HEALTH_PATH = DATA_DIR / "provider-health.json"
SCHEMA_VERSION = 1
COOLDOWNS = {
    "transient": timedelta(hours=1),
    "quota": timedelta(hours=6),
    "auth": timedelta(hours=12),
}


def _load(now=None) -> dict:
    now = now or now_utc()
    payload = load_json(HEALTH_PATH, {})
    rows = payload.get("platforms") if isinstance(payload, dict) else None
    if not isinstance(rows, dict):
        rows = {}
    active = {}
    for name, row in rows.items():
        if not isinstance(row, dict):
            continue
        try:
            until = parse_iso(str(row.get("cooldownUntilUtc") or ""))
        except (TypeError, ValueError):
            continue
        if until <= now:
            continue
        failure_class = str(row.get("failureClass") or "")
        if failure_class not in COOLDOWNS:
            continue
        active[str(name)] = {
            "failureClass": failure_class,
            "cooldownUntilUtc": iso_minute(until),
            "updatedUtc": str(row.get("updatedUtc") or ""),
        }
    return {"schemaVersion": SCHEMA_VERSION, "platforms": active}


def _save(payload: dict) -> None:
    save_json(HEALTH_PATH, payload)


def active_platforms(now=None) -> set[str]:
    """Return provider platform names still inside a persisted cooldown."""
    return set(_load(now)["platforms"])


def cooldown_rows(now=None) -> dict:
    """Return sanitized active cooldown metadata for diagnostics."""
    return dict(_load(now)["platforms"])


def mark_failure(platform: str, failure_class: str, now=None):
    """Persist a platform cooldown and return its expiry timestamp."""
    platform = str(platform or "").strip()
    if not platform:
        return None
    kind = failure_class if failure_class in COOLDOWNS else "transient"
    now = now or now_utc()
    until = now + COOLDOWNS[kind]
    payload = _load(now)
    payload["platforms"][platform] = {
        "failureClass": kind,
        "cooldownUntilUtc": iso_minute(until),
        "updatedUtc": iso_minute(now),
    }
    _save(payload)
    return until


def mark_success(platform: str, now=None) -> bool:
    """Clear a platform cooldown after a completed provider response."""
    platform = str(platform or "").strip()
    if not platform:
        return False
    payload = _load(now)
    if platform not in payload["platforms"]:
        return False
    del payload["platforms"][platform]
    _save(payload)
    return True
