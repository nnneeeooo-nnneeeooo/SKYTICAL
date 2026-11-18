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
    record = {"route": provider.label, "case": fixture["id"]}
    try:
        draft, facts = write._probe_draft(
            provider, fixture, tries=2, deadline=started + 2 * probe.PROBE_SECONDS,
            max_attempt_seconds=probe.PROBE_SECONDS,
        )
        record.update(outcome="passed" if draft and facts else "rejected",
                      verifiedFacts=len(facts or []))
    except Exception as exc:
        record.update(outcome=classify_failure(exc), diagnostic=safe_failure_message(exc))
    record.update(seconds=round(time.monotonic() - started, 1), calls=provider.http_calls - calls)
    print("experiment result: " + json.dumps(record, ensure_ascii=False), flush=True)


def main():
    configured = os.environ["AVWIRE_PROVIDER_ORDER"]
    providers = build_providers()
    if len(providers) != 1 or providers[0].label != configured:
        print(f"experiment unavailable: {configured} (credential is unavailable)")
        return
    provider = providers[0]
    gemma_with_token_limit = configured == "gemini:gemma-4-31b-it"
    if gemma_with_token_limit:
        provider.json_schema_mode = "prompt"  # The first run rejected native schema.
    if configured == "gemini:gemini-4-hydrogen":
        provider.reasoning_tier = "standard"  # Gemini uses medium instead of Hydrogen's default high.
        provider.json_schema_mode = "prompt"
    try:
        ids = probe.catalog(provider)
    except Exception as exc:
        print(f"experiment catalog unconfirmed: {safe_failure_message(exc)}")
    else:
        if provider.model not in ids:
            print(f"experiment unavailable: {configured} (model absent from account catalog)")
            return
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
        try:
            fixture = official_story(*story)
        except (requests.RequestException, StopIteration, ValueError) as exc:
            print(f"experiment source unavailable: {story[0]} ({type(exc).__name__})")
        else:
            if gemma_with_token_limit:
                time.sleep(65)  # Google lists a 16K input-token/minute limit for this project.
            run_case(provider, fixture)


if __name__ == "__main__":
    main()
