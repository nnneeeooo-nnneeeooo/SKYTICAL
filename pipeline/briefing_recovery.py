"""Bounded overdue recovery for the fixed daily briefing editions.

This module uses only persisted briefing JSON and the public index to decide
whether paid generation is needed. It runs at most three overdue editions per
invocation and keeps each edition's configured date window unchanged.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import briefing  # noqa: E402

GRACE = timedelta(minutes=30)
MAX_PER_RUN = 3
EDITIONS = ("morning", "afternoon", "evening")


def recovery_targets(now: datetime) -> list[tuple[str, date]]:
    """Return up to three overdue editions from yesterday and today."""
    local = now.astimezone(briefing.TPE)
    today = local.date()
    candidates: list[tuple[datetime, str, date]] = []
    for target_date in (today - timedelta(days=1), today):
        for edition in EDITIONS:
            window = briefing.get_briefing_window(edition, target_date)
            due_at = window.scheduled_time + GRACE
            if local >= due_at:
                candidates.append((window.scheduled_time, edition, target_date))
    # Prefer the newest due edition. A repeatedly failing older day must not
    # consume all three generation slots before today's reports are reached.
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [(edition, target_date)
            for _, edition, target_date in candidates]


def _index_data() -> dict:
    data = briefing.load_json(briefing.INDEX_PATH, {})
    if isinstance(data, dict) and isinstance(data.get("briefings"), list):
        return data
    # A missing or malformed index can be reconstructed from valid persisted
    # reports. Preserve failed rows when the index itself was readable.
    rows = []
    try:
        files = briefing.BRIEFINGS_DIR.glob("*.json")
        for path in files:
            if path.name in ("index.json", "event_index.json"):
                continue
            report = briefing.load_json(path, None)
            if not isinstance(report, dict):
                continue
            report_id = report.get("briefing_id")
            if briefing.complete_briefing(path, str(report_id)):
                rows.append(_row(report))
    except OSError:
        pass
    return {"briefings": rows}


def _row(report: dict) -> dict:
    return {key: report[key] for key in (
        "briefing_id", "date", "edition", "status", "cutoff_time",
        "generated_at", "item_count")}


def ensure_index(report: dict) -> bool:
    """Make a valid report visible in index.json; return whether it changed."""
    try:
        before_bytes = briefing.INDEX_PATH.read_bytes()
    except OSError:
        before_bytes = None
    before = briefing.load_json(briefing.INDEX_PATH, None)
    if not (isinstance(before, dict)
            and isinstance(before.get("briefings"), list)):
        briefing.save_json(briefing.INDEX_PATH, _index_data())
    data = briefing.load_json(briefing.INDEX_PATH, {"briefings": []})
    expected = _row(report)
    existing = next((row for row in data.get("briefings", [])
                     if isinstance(row, dict)
                     and row.get("briefing_id") == expected["briefing_id"]), None)
    if existing == expected:
        try:
            return briefing.INDEX_PATH.read_bytes() != before_bytes
        except OSError:
            return True
    briefing.upsert_index_row(expected)
    try:
        return briefing.INDEX_PATH.read_bytes() != before_bytes
    except OSError:
        return True


def complete_on_disk(edition: str, target_date: date) -> dict | None:
    identifier = f"{target_date.isoformat()}-{edition}"
    path = briefing.BRIEFINGS_DIR / f"{identifier}.json"
    report = briefing.complete_briefing(path, identifier)
    if not report:
        return None
    if (report.get("edition") != edition
            or report.get("date") != target_date.isoformat()):
        return None
    return report


def _set_output(publish: bool, failed: bool) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"publish={'true' if publish else 'false'}\n")
            stream.write(f"failed={'true' if failed else 'false'}\n")


def process(targets: list[tuple[str, date]], *, generate: bool = True) -> tuple[bool, bool]:
    """Process targets independently; return (publish, any_failed)."""
    publish = False
    failed = False
    generated = 0
    for edition, target_date in targets:
        identifier = f"{target_date.isoformat()}-{edition}"
        complete = complete_on_disk(edition, target_date)
        if complete:
            repaired = ensure_index(complete)
            publish = publish or repaired
            print(f"briefing recovery: {identifier} complete; "
                  f"index_repaired={str(repaired).lower()}")
            continue
        if not generate:
            continue
        if generated >= MAX_PER_RUN:
            print(f"briefing recovery: generation cap reached; deferred {identifier}")
            continue
        generated += 1
        print(f"briefing recovery: generating {identifier}")
        try:
            briefing.run_edition(edition, target_date, skip_existing=True)
        except Exception as exc:
            briefing.record_failure(edition, target_date,
                                    f"{type(exc).__name__}: {exc}")
            print(f"::error::briefing recovery failed {identifier}: "
                  f"{type(exc).__name__}: {str(exc)[:300]}")
            failed = True
            continue
        report = complete_on_disk(edition, target_date)
        if not report:
            print(f"::error::briefing recovery produced no complete report for {identifier}")
            failed = True
            continue
        ensure_index(report)
        publish = True
        print(f"briefing recovery: {identifier} persisted and indexed "
              f"status={report['status']}")
    return publish, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recover", action="store_true",
                      help="recover up to three overdue editions")
    mode.add_argument("--edition", choices=EDITIONS,
                      help="process one normal scheduled or manual edition")
    parser.add_argument("--date", help="Taipei report date YYYY-MM-DD")
    parser.add_argument("--cron", help="resolve the edition date from a scheduled UTC cron")
    args = parser.parse_args(argv)
    now = briefing.now_utc()
    if args.recover:
        targets = recovery_targets(now)
    else:
        if args.cron and briefing.CRON_TO_EDITION.get(args.cron.strip()) != args.edition:
            print("briefing recovery: --cron does not map to --edition")
            return 2
        try:
            target_date = (date.fromisoformat(args.date) if args.date else
                           briefing.scheduled_taipei_date(args.edition, now)
                           if args.cron else
                           now.astimezone(briefing.TPE).date())
        except ValueError:
            print("briefing recovery: invalid --date; expected YYYY-MM-DD")
            return 2
        targets = [(args.edition, target_date)]
    publish, failed = process(targets)
    _set_output(publish, failed)
    print(f"briefing recovery: publish={str(publish).lower()} "
          f"failed={str(failed).lower()} targets={len(targets)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
