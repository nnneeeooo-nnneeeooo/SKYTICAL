"""Deliver cron-scheduled workflows on time from one long-lived Actions job.

GitHub drops most ``schedule`` events for this repository, while
``workflow_dispatch`` is delivered immediately. This relay reads the cron
lines of the workflows below, dispatches each one when it is due, and hands
over to a fresh run before the job time limit. The native crons stay in place
as the fallback that restarts a broken chain.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
RELAY_WORKFLOW = "schedule-relay.yml"
RELAYED = ("hourly.yml", "briefing.yml", "radar-snapshot.yml",
           "rare-aircraft-monitor.yml")
# Workflows that branch on github.event.schedule receive the cron as an input.
PASS_SCHEDULE = frozenset({"briefing.yml"})
LIFETIME = timedelta(hours=5)
CATCH_UP = timedelta(minutes=10)
PEER_CHECK_EVERY = 5  # ticks
CRON_LINE = re.compile(r"""^\s*-\s*cron:\s*["']([^"']+)["']""", re.M)
FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field(spec: str, low: int, high: int) -> set[int]:
    values: set[int] = set()
    for part in spec.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            start, end = (int(value) for value in base.split("-", 1))
        else:
            start = int(base)
            end = high if step else start
        if not low <= start <= end <= high:
            raise ValueError(f"cron field out of range: {spec}")
        values.update(range(start, end + 1, int(step or 1)))
    return values


def cron_matches(expr: str, moment: datetime) -> bool:
    """Match a five-field numeric UTC cron expression against one minute."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"unsupported cron expression: {expr}")
    minute, hour, day, month, weekday = (
        _field(field, low, high)
        for field, (low, high) in zip(fields, FIELD_RANGES))
    if (moment.minute not in minute or moment.hour not in hour
            or moment.month not in month):
        return False
    day_ok = moment.day in day
    weekday_ok = (moment.weekday() + 1) % 7 in {value % 7 for value in weekday}
    if fields[2] != "*" and fields[4] != "*":
        return day_ok or weekday_ok
    return day_ok and weekday_ok


def load_schedules(directory: Path = WORKFLOWS_DIR) -> dict[str, list[str]]:
    schedules = {}
    for name in RELAYED:
        crons = CRON_LINE.findall((directory / name).read_text(encoding="utf-8"))
        for cron in crons:
            cron_matches(cron, datetime(2026, 1, 1, tzinfo=timezone.utc))
        if not crons:
            raise ValueError(f"{name} has no cron schedule to relay")
        schedules[name] = crons
    return schedules


def due(schedules: dict[str, list[str]], after: datetime,
        until: datetime) -> list[tuple[str, dict[str, str]]]:
    """Return one dispatch per workflow (or per cron) due in (after, until]."""
    minute = max(after, until - CATCH_UP).replace(second=0, microsecond=0)
    found: dict[tuple[str, str], dict[str, str]] = {}
    while (minute := minute + timedelta(minutes=1)) <= until:
        for name, crons in schedules.items():
            for cron in crons:
                if not cron_matches(cron, minute):
                    continue
                if name in PASS_SCHEDULE:
                    found[(name, cron)] = {"schedule": cron}
                else:
                    found[(name, "")] = {}
    return [(name, inputs) for (name, _), inputs in found.items()]


class GitHub:
    def __init__(self, repo: str, token: str, ref: str):
        self.base = f"https://api.github.com/repos/{repo}/actions"
        self.token = token
        self.ref = ref

    def _call(self, method: str, path: str, body: dict | None = None):
        request = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.token}",
                     "Accept": "application/vnd.github+json",
                     "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        return json.loads(payload) if payload else None

    def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        self._call("POST", f"/workflows/{workflow}/dispatches",
                   {"ref": self.ref, "inputs": inputs})

    def active_relay_runs(self) -> list[int]:
        runs = self._call("GET", f"/workflows/{RELAY_WORKFLOW}/runs?per_page=30")
        return [run["id"] for run in runs["workflow_runs"]
                if run["status"] != "completed"]


def _try(action, label: str, attempts: int = 3, pause=time.sleep):
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            print(f"::warning::{label} failed (attempt {attempt}): {error}")
            if attempt < attempts:
                pause(5)
    return None


def run(api, schedules: dict[str, list[str]], run_id: int, *,
        since: datetime | None = None, handoff_from: int | None = None,
        now=lambda: datetime.now(timezone.utc), sleep=time.sleep) -> str:
    """Relay until the lifetime ends; return why this run stopped."""
    def older_peers() -> set[int]:
        active = _try(api.active_relay_runs, "relay peer check", pause=sleep)
        return {peer for peer in active or []
                if peer < run_id and peer != handoff_from}

    started = now()
    if handoff_from is None and older_peers():
        print("another relay run is active; nothing to do")
        return "standby"
    last = since if since and started - CATCH_UP <= since <= started else started
    suspects: set[int] = set()
    tick = 0
    while now() - started < LIFETIME:
        current = now()
        sleep(60 - current.second - current.microsecond / 1e6 + 1)
        current = now()
        for workflow, inputs in due(schedules, last, current):
            if _try(lambda: api.dispatch(workflow, inputs) or True,
                    f"dispatch {workflow}", pause=sleep):
                print(f"{current:%FT%H:%MZ} dispatched {workflow} {inputs or ''}")
        last = current.replace(second=0, microsecond=0)
        tick += 1
        if tick % PEER_CHECK_EVERY == 0:
            peers = older_peers()
            if peers & suspects:
                print("an older relay run is still active; yielding")
                return "yielded"
            suspects = peers
    inputs = {"since": str(int(last.timestamp())), "handoff_from": str(run_id)}
    for _ in range(5):
        if _try(lambda: api.dispatch(RELAY_WORKFLOW, inputs) or True,
                "relay handoff", attempts=1):
            return "handed_off"
        sleep(10)
        active = _try(api.active_relay_runs, "relay handoff check", attempts=1)
        if any(peer > run_id for peer in active or []):
            return "handed_off"
    print("::error::relay handoff failed; the fallback cron must restart it")
    return "handoff_failed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default="",
                        help="epoch seconds already covered by the previous run")
    parser.add_argument("--handoff-from", default="",
                        help="run id of the relay run that started this one")
    args = parser.parse_args(argv)
    api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_TOKEN"],
                 os.environ.get("GITHUB_REF_NAME", "main"))
    since = (datetime.fromtimestamp(int(args.since), timezone.utc)
             if args.since.isdigit() else None)
    handoff_from = int(args.handoff_from) if args.handoff_from.isdigit() else None
    schedules = load_schedules()
    print("relaying:", json.dumps(schedules))
    result = run(api, schedules, int(os.environ["GITHUB_RUN_ID"]),
                 since=since, handoff_from=handoff_from)
    return 1 if result == "handoff_failed" else 0


if __name__ == "__main__":
    sys.exit(main())
