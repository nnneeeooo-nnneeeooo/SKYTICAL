"""Offline tests for overdue briefing recovery and Actions contracts."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMP = Path(tempfile.mkdtemp(prefix="briefing-recovery-"))
os.environ["AVWIRE_DATA_DIR"] = str(TEMP)
sys.path.insert(0, str(ROOT / "pipeline"))
import briefing  # noqa: E402
import briefing_recovery as recovery  # noqa: E402

briefing.BRIEFINGS_DIR = TEMP / "briefings"
briefing.INDEX_PATH = briefing.BRIEFINGS_DIR / "index.json"
briefing.EVENT_INDEX_PATH = briefing.BRIEFINGS_DIR / "event_index.json"


def check(name: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(name)
    print(f"PASS {name}")


def reset() -> None:
    import shutil
    shutil.rmtree(briefing.BRIEFINGS_DIR, ignore_errors=True)
    briefing.BRIEFINGS_DIR.mkdir(parents=True)


def valid_report(edition: str, day: date) -> dict:
    window = briefing.get_briefing_window(edition, day)
    return {
        "briefing_id": window.briefing_id,
        "date": day.isoformat(),
        "edition": edition,
        "status": "published",
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "cutoff_time": window.cutoff_time.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "item_count": 0,
        "sections": {name: [] for name in briefing.SECTIONS},
        "checked_sources": [],
        "warnings": [],
    }


def put_report(edition: str, day: date, report: dict | None = None) -> Path:
    path = briefing.BRIEFINGS_DIR / f"{day.isoformat()}-{edition}.json"
    path.write_text(json.dumps(report or valid_report(edition, day)), encoding="utf-8")
    return path


def indexed_rows() -> list[dict]:
    data = briefing.load_json(briefing.INDEX_PATH, {})
    return data.get("briefings", []) if isinstance(data, dict) else []


today = date(2026, 10, 5)

# Existing complete editions skip all generation and repair only a missing index.
reset()
put_report("morning", today)
calls = []
old_run = briefing.run_edition
briefing.run_edition = lambda *a, **k: calls.append((a, k))
publish, failed = recovery.process([("morning", today)])
check("complete JSON with missing index is repaired without model generation",
      publish and not failed and not calls
      and indexed_rows()[0]["status"] == "published")

for status in ("published", "partial"):
    reset()
    report = valid_report("morning", today)
    report["status"] = status
    put_report("morning", today, report)
    briefing.save_json(briefing.INDEX_PATH, {"briefings": [recovery._row(report)]})
    calls.clear()
    publish, failed = recovery.process([("morning", today)])
    check(f"indexed {status} report skips generation and build",
          not publish and not failed and not calls)

reset()
put_report("morning", today)
old_now = briefing.now_utc
old_sources = briefing.checked_sources_snapshot
briefing.now_utc = lambda: datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
briefing.checked_sources_snapshot = lambda: (_ for _ in ()).throw(
    AssertionError("complete report must exit before source/model work"))
result = old_run("morning", today, skip_existing=True)
briefing.now_utc = old_now
briefing.checked_sources_snapshot = old_sources
check("run_edition skip guard avoids downstream generation work", result == 0)

# A malformed index is rebuilt and counts as publishable state change.
reset()
put_report("afternoon", today)
briefing.INDEX_PATH.write_text("{broken", encoding="utf-8")
publish, failed = recovery.process([("afternoon", today)])
check("bad index repair marks publish true and performs no generation",
      publish and not failed and indexed_rows()[0]["edition"] == "afternoon")

# A failed index row or invalid report cannot pass the persisted-state guard.
reset()
put_report("morning", today, {"briefing_id": f"{today}-morning",
                              "status": "failed"})
briefing.INDEX_PATH.write_text(json.dumps({"briefings": [{
    "briefing_id": f"{today}-morning", "status": "failed"}]}), encoding="utf-8")
generated = []
def generate(edition, target_date, *, skip_existing=False):
    generated.append((edition, target_date, skip_existing))
    put_report(edition, target_date)
briefing.run_edition = generate
publish, failed = recovery.process([("morning", today)])
check("failed or incomplete edition regenerates and is verified on disk",
      publish and not failed and len(generated) == 1
      and generated[0][2] and indexed_rows()[0]["status"] == "published")

# Candidates are scanned across both dates; only generation attempts use quota.
reset()
yesterday = date(2026, 10, 4)
for edition in ("morning", "afternoon", "evening"):
    put_report(edition, yesterday)
targets = recovery.recovery_targets(
    datetime(2026, 10, 5, 23, 46, tzinfo=briefing.TPE))
check("overdue scan includes today after yesterday's three editions are complete",
      ("morning", today) in targets and len(targets) == 6)
midnight_targets = recovery.recovery_targets(
    datetime(2026, 10, 5, 0, 10, tzinfo=briefing.TPE))
check("cross-midnight recovery checks yesterday's evening report date",
      ("evening", yesterday) in midnight_targets
      and all(target_date != today for _, target_date in midnight_targets))
early = recovery.recovery_targets(
    datetime(2026, 10, 5, 6, 0, tzinfo=briefing.TPE))
check("recovery never includes a future same-day edition",
      all(target_date != today for _, target_date in early))

reset()
attempted = []
def write_target(edition, target_date, *, skip_existing=False):
    attempted.append((edition, target_date))
    put_report(edition, target_date)
briefing.run_edition = write_target
targets = recovery.recovery_targets(
    datetime(2026, 10, 5, 23, 46, tzinfo=briefing.TPE))
publish, failed = recovery.process(targets)
check("one recovery invocation generates no more than three reports",
      publish and not failed and len(attempted) == recovery.MAX_PER_RUN
      and all(target_date == today for _, target_date in attempted))

# Failed candidates do not stop later edition attempts and cannot look successful.
reset()
attempted.clear()
def fail_first(edition, target_date, *, skip_existing=False):
    attempted.append((edition, target_date))
    if len(attempted) == 1:
        raise RuntimeError("fixture failure")
    put_report(edition, target_date)
briefing.run_edition = fail_first
publish, failed = recovery.process(targets[:2])
check("a failed edition is reported while the next candidate still succeeds",
      failed and publish and len(attempted) == 2
      and any(row.get("status") == "failed" for row in indexed_rows()))

# Fixed due time, 30-minute grace and midnight date resolution.
not_due = recovery.recovery_targets(
    datetime(2026, 10, 5, 23, 44, tzinfo=briefing.TPE))
due = recovery.recovery_targets(
    datetime(2026, 10, 5, 23, 46, tzinfo=briefing.TPE))
check("recovery waits for scheduled time plus 30-minute grace",
      ("evening", today) not in not_due and ("evening", today) in due)
orig_now = briefing.now_utc
orig_process = recovery.process
resolved = []
briefing.now_utc = lambda: datetime(2026, 10, 4, 16, 10, tzinfo=timezone.utc)
recovery.process = lambda rows: (resolved.extend(rows) or (False, False))
recovery.main(["--edition", "evening", "--cron", "15 15 * * *"])
briefing.now_utc = orig_now
recovery.process = orig_process
check("delayed evening cron at 00:10 keeps previous Taipei report date",
      resolved == [("evening", yesterday)])

# Workflow contract: original schedule retained and refresh/skip/persistence guards exist.
workflow = (ROOT / ".github" / "workflows" / "briefing.yml").read_text(encoding="utf-8")
check("workflow retains daily editions and enables half-hour recovery",
      all(f'cron: "{cron}"' in workflow for cron in
          ("15 23 * * *", "15 7 * * *", "15 15 * * *", "5,35 * * * *")))
check("workflow refreshes main after concurrency and skips empty builds",
      "git reset --hard origin/main" in workflow
      and "steps.run_briefing.outputs.publish == 'true'" in workflow
      and "run_briefing.outcome == 'failure'" in workflow
      and "needs.briefing.outputs.persisted == 'true'" in workflow)

briefing.run_edition = old_run
print("All briefing recovery tests passed.")
