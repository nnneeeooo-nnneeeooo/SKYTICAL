"""Isolated live comparison using the regular SKYTICAL publication probe."""

import json
import os
import time

import requests

import free_provider_probe as probe
import write
from common import now_utc
from fulltext import extract_text
from providers import build_providers, classify_failure, safe_failure_message


def official_story(slug, publisher, title, date, url, anchor):
    response = requests.get(url, timeout=(5, 20))
    response.raise_for_status()
    lines = extract_text(response.content).splitlines()
    first = next(i for i, line in enumerate(lines) if anchor in line)
    fulltext = "\n".join(lines[first:first + 6])
    if len(fulltext) < 600:
        raise ValueError("official story body incomplete")
    return {
        "id": f"model-validation-{slug}",
        "primarySource": publisher,
        "items": [{"title": title, "source": publisher, "sourceKey": slug,
                   "url": url, "publishedUtc": date, "summary": "", "fulltext": fulltext}],
    }


def run_case(provider, fixture):
    started = time.monotonic()
    calls = provider.http_calls
    production_budget = provider.label == "cloudflare:@cf/openai/gpt-oss-120b"
    seconds = 60 if production_budget else probe.PROBE_SECONDS
    tries = 1 if production_budget else 2
    record = {"route": provider.label, "case": fixture["id"]}
    try:
        draft, facts = write._probe_draft(
            provider, fixture, tries=tries, deadline=started + tries * seconds,
            max_attempt_seconds=seconds,
        )
        record.update(outcome="passed" if draft and facts else "rejected",
                      verifiedFacts=len(facts or []))
    except Exception as exc:
        record.update(outcome=classify_failure(exc), diagnostic=safe_failure_message(exc))
    record.update(seconds=round(time.monotonic() - started, 1), calls=provider.http_calls - calls)
    print("experiment result: " + json.dumps(record, ensure_ascii=False), flush=True)


def main():
    configured = os.environ["AVWIRE_PROVIDER_ORDER"]
    only_case = os.environ.get("AVWIRE_EXPERIMENT_CASE")
    providers = build_providers()
    if len(providers) != 1 or providers[0].label != configured:
        print(f"experiment unavailable: {configured} (credential is unavailable)")
        return
    provider = providers[0]
    pace_requests = configured in {"gemini:gemma-4-31b-it", "groq:qwen/qwen3.8-27b"}
    if configured == "gemini:gemma-4-31b-it":
        provider.json_schema_mode = "prompt"  # The first run rejected native schema.
    if configured == "gemini:gemini-4-hydrogen":
        provider.reasoning_tier = "standard"  # Gemini uses medium instead of Hydrogen's default high.
        provider.json_schema_mode = "prompt"
    if configured in {"cloudflare:@cf/qwen/qwen3.8-27b", "cloudflare:@cf/openai/gpt-oss-120b"}:
        send = provider._send_payload

        def send_with_low_reasoning(payload, repair):
            return send({**payload, "reasoning_effort": "low"}, repair)

        provider._send_payload = send_with_low_reasoning
    try:
        ids = probe.catalog(provider)
    except Exception as exc:
        print(f"experiment catalog unconfirmed: {safe_failure_message(exc)}")
    else:
        if provider.model not in ids:
            print(f"experiment unavailable: {configured} (model absent from account catalog)")
            return
    if not only_case or only_case == "h140":
        run_case(provider, json.loads(probe.FIXTURE_PATH.read_text(encoding="utf-8")))
    stories = (
        ("qantas-a321xlr", "Airbus", "Qantas takes delivery of its first Airbus A321XLR",
         "2025-06-30T00:00Z", "https://www.airbus.com/en/newsroom/press-releases/2025-06-qantas-takes-delivery-of-its-first-airbus-a321xlr",
         "Australia's Qantas Airways"),
        ("starlux-a350", "Airbus", "STARLUX takes delivery of first Airbus A350-1000",
         "2026-01-06T00:00Z", "https://www.airbus.com/en/newsroom/press-releases/2026-01-starlux-takes-delivery-of-first-airbus-a350-1000",
         "STARLUX Airlines of Taiwan has taken delivery"),
    )
    for story in stories:
        if only_case and only_case != story[0]:
            continue
        try:
            fixture = official_story(*story)
        except (requests.RequestException, StopIteration, ValueError) as exc:
            print(f"experiment source unavailable: {story[0]} ({type(exc).__name__})")
        else:
            if pace_requests:
                time.sleep(65)  # These providers advertise low per-minute token ceilings.
            run_case(provider, fixture)


if __name__ == "__main__":
    main()
