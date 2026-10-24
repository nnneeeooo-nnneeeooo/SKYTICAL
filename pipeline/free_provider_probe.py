"""Free-route admission using one fixed, public, quote-verified news source.

Reports contain only route IDs, finite failure diagnostics and timestamps.
No generated text, prompts or API responses are persisted. A failed probe
never grants admission; retries observe per-route backoff across hourly runs.
"""
from __future__ import annotations

import argparse
import time
from datetime import timedelta

import requests

from common import DATA_DIR, ROOT, iso_minute, load_json, now_utc, parse_iso, save_json
from editorial_policy import is_free_provider
from providers import (NvidiaProvider, ProviderError, classify_failure,
                       safe_api_error, safe_failure_message)

HEALTH_PATH = DATA_DIR / "provider-routes.json"
FIXTURE_PATH = ROOT / "config" / "free_provider_probe.json"
PROBE_SECONDS = 180
# API signatures/prompts change independently of the model ID.
PROBE_VERSION = 2
FALLBACK_MODEL = "qwen/qwen3.5-397b-a17b"


def load_routes():
    raw = load_json(HEALTH_PATH, {})
    rows = raw.get("routes", {}) if isinstance(raw, dict) else {}
    kept = {}
    for label, row in rows.items() if isinstance(rows, dict) else []:
        if not isinstance(row, dict) or row.get("status") not in {"verified", "waiting", "unavailable"}:
            continue
        try:
            parse_iso(row["untilUtc"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("probeVersion") == PROBE_VERSION:
            kept[label] = {k: row.get(k) for k in (
                "status", "untilUtc", "checkedUtc", "failureClass", "diagnostic", "probeVersion", "schemaMode")}
    return kept


def record(label, *, passed=False, failure="provider_failure", diagnostic="", now=None, schema_mode=None):
    now = now or now_utc()
    rows = load_routes()
    unavailable = failure == "model_unavailable"
    rows[label] = {"status": "verified" if passed else "unavailable" if unavailable else "waiting",
                   "checkedUtc": iso_minute(now),
                   "untilUtc": iso_minute(now + timedelta(hours=24 if passed or unavailable else 6)),
                   "failureClass": None if passed else failure,
                   "diagnostic": None if passed else safe_failure_message(diagnostic),
                   "probeVersion": PROBE_VERSION,
                   "schemaMode": schema_mode if schema_mode in {"native", "prompt"} else None}
    save_json(HEALTH_PATH, {"schemaVersion": 1, "routes": rows})
    return rows[label]


def quarantine(provider, exc):
    kind = classify_failure(exc)
    if kind not in {"invalid_request", "model_unavailable", "rate_limit"}:
        return False
    record(provider.label, failure=kind, diagnostic=str(exc))
    return True


def catalog(provider):
    """Confirm configured IDs against the account catalog, without logging bodies."""
    import os
    if provider.name == "gemini":
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}
    elif provider.name == "nvidia":
        url = "https://integrate.api.nvidia.com/v1/models"
        headers = {"Authorization": "Bearer " + os.environ["NVIDIA_API_KEY"]}
    else:
        url, headers = "https://openrouter.ai/api/v1/models", {}
    ids, token = set(), None
    for _ in range(10):
        params = {"pageSize": 1000} if provider.name == "gemini" else {}
        if token:
            params["pageToken"] = token
        try:
            response = requests.get(url, headers=headers, params=params, timeout=(5, 20))
        except requests.RequestException as exc:
            raise ProviderError(type(exc).__name__) from exc
        if response.status_code >= 400:
            raise ProviderError(safe_api_error(response))
        data = response.json()
        for item in data.get("models" if provider.name == "gemini" else "data", []):
            if not isinstance(item, dict):
                continue
            if provider.name == "gemini" and "generateContent" not in item.get("supportedGenerationMethods", []):
                continue
            model = str(item.get("name") if provider.name == "gemini" else item.get("id") or "")
            ids.add(model.removeprefix("models/"))
        token = data.get("nextPageToken")
        if not token:
            return ids
    raise ProviderError("model catalog pagination incomplete")


def prepare_routes(providers, now, validate, *, force=False):
    candidates = list(providers)
    # This hosted NIM fallback receives exactly the same catalog and publication
    # gates as configured routes. Never add subscription/pay-per-call services.
    if any(p.name == "nvidia" and getattr(p, "requires_verification", False)
           for p in candidates) and not any(
            p.name == "nvidia" and p.model == FALLBACK_MODEL for p in candidates):
        extra = NvidiaProvider(FALLBACK_MODEL)
        index = next((i for i, p in enumerate(candidates) if p.name == "openai"), len(candidates))
        candidates.insert(index, extra)
    providers[:] = candidates  # include every attempted route in usage accounting
    fixture = load_json(FIXTURE_PATH, {})
    if not isinstance(fixture, dict) or not fixture.get("items"):
        raise ValueError("missing public provider probe fixture")
    admitted, catalogs, blocked = [], {}, {}
    for provider in candidates:
        if not is_free_provider(provider) or not getattr(provider, "requires_verification", False):
            admitted.append(provider)
            continue
        if provider.name in blocked:
            record(provider.label, failure=blocked[provider.name], diagnostic="platform cooldown", now=now)
            continue
        row = load_routes().get(provider.label)
        if not force and row and parse_iso(row["untilUtc"]) > now:
            if row["status"] == "verified":
                if provider.name == "gemini" and row.get("schemaMode") in {"native", "prompt"}:
                    provider.json_schema_mode = row["schemaMode"]
                admitted.append(provider)
            else:
                print(f"free-probe: {provider.label} waiting until {row['untilUtc']}")
            continue
        try:
            if provider.name not in catalogs:
                try:
                    catalogs[provider.name] = catalog(provider)
                except (ProviderError, ValueError, TypeError) as exc:
                    # Some services deny catalog access while allowing inference.
                    # A publication probe remains authoritative in that case.
                    catalogs[provider.name] = None
                    print(f"free-probe: {provider.name} catalog unavailable: {safe_failure_message(exc)}")
            ids = catalogs[provider.name]
            if ids is not None and provider.model not in ids:
                record(provider.label, failure="model_unavailable", diagnostic="model absent from account catalog", now=now)
                print(f"free-probe: {provider.label} unavailable in account catalog")
                continue
            draft, facts = validate(provider, fixture, tries=2,
                                    deadline=time.monotonic() + 2 * PROBE_SECONDS,
                                    max_attempt_seconds=PROBE_SECONDS)
            passed = (isinstance(draft, dict) and draft.get("status") in {"publish", "publish_brief"} and bool(facts))
            if not passed:
                record(provider.label, failure="probe_rejected", diagnostic="fixed source did not produce a publishable article", now=now)
                print(f"free-probe: {provider.label} rejected fixed source")
                continue
            record(provider.label, passed=True, now=now,
                   schema_mode=getattr(provider, "json_schema_mode", None))
            admitted.append(provider)
            print(f"free-probe: {provider.label} publication checks passed")
        except Exception as exc:
            kind = classify_failure(exc)
            if kind in {"auth", "quota"}:
                import provider_health
                provider_health.mark_failure(provider.name, kind, now)
                blocked[provider.name] = kind
            record(provider.label, failure=kind, diagnostic=str(exc), now=now)
            print(f"free-probe: {provider.label} failed: {safe_failure_message(exc)}")
    return admitted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    import write
    import usage
    from providers import build_providers
    providers = [p for p in build_providers() if is_free_provider(p)]
    try:
        admitted = prepare_routes(providers, now_utc(), write._probe_draft, force=args.force)
    finally:
        usage.record_providers(providers)
    print(f"free-probe: verified {len(admitted)} of {len(load_routes())} routes")
    if not admitted:
        print("::warning::No free route passed publication checks; news stays queued")


if __name__ == "__main__":
    main()
