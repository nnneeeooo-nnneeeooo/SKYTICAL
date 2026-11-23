"""Offline tests for the schedule relay: cron matching, due slots and handoff."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import schedule_relay as relay  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"


def utc(hour, minute, second=0, day=23):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=timezone.utc)


class Clock:
    def __init__(self, start):
        self.now = start

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


class FakeApi:
    def __init__(self, clock, active=(), fail_dispatches=0):
        self.clock = clock
        self.active = list(active)
        self.fail_dispatches = fail_dispatches
        self.dispatched = []

    def dispatch(self, workflow, inputs):
        if self.fail_dispatches:
            self.fail_dispatches -= 1
            raise OSError("network down")
        self.dispatched.append((self.clock.now, workflow, dict(inputs)))

    def active_relay_runs(self):
        return list(self.active)


def test_cron_matching_covers_the_syntax_used_by_the_workflows():
    assert relay.cron_matches("45 * * * *", utc(3, 45))
    assert not relay.cron_matches("45 * * * *", utc(3, 44))
    assert relay.cron_matches("5,35 * * * *", utc(0, 35))
    assert relay.cron_matches("*/10 * * * *", utc(9, 50))
    assert not relay.cron_matches("*/10 * * * *", utc(9, 55))
    assert relay.cron_matches("0 */4 * * *", utc(8, 0))
    assert not relay.cron_matches("0 */4 * * *", utc(9, 0))
    assert relay.cron_matches("15 23 * * 1-5", utc(23, 15))  # Monday
    assert not relay.cron_matches("15 23 * * 0,6", utc(23, 15))
    assert relay.cron_matches("0 0 * * 7", utc(0, 0, day=22))  # Sunday as 7


def test_every_relayed_workflow_has_crons_and_accepts_dispatch():
    schedules = relay.load_schedules()
    assert schedules["hourly.yml"] == ["45 * * * *"]
    assert set(schedules) == set(relay.RELAYED)
    for name in relay.RELAYED:
        assert "workflow_dispatch:" in (WORKFLOWS / name).read_text(encoding="utf-8")


def test_due_fires_each_slot_once_and_bounds_catch_up():
    schedules = {"hourly.yml": ["45 * * * *"],
                 "briefing.yml": ["15 23 * * *", "5,35 * * * *"],
                 "rare-aircraft-monitor.yml": ["*/5 * * * *"]}
    assert relay.due(schedules, utc(3, 44), utc(3, 45, 1)) == [
        ("hourly.yml", {}), ("rare-aircraft-monitor.yml", {})]
    assert relay.due(schedules, utc(3, 45), utc(3, 46, 1)) == []
    assert relay.due(schedules, utc(23, 14), utc(23, 15, 1)) == [
        ("briefing.yml", {"schedule": "15 23 * * *"}),
        ("rare-aircraft-monitor.yml", {})]
    # A stalled runner catches up at most ten minutes, one dispatch per workflow.
    stalled = relay.due(schedules, utc(1, 0), utc(3, 46))
    assert stalled == [("rare-aircraft-monitor.yml", {}), ("hourly.yml", {})]


def test_run_dispatches_on_time_and_hands_off_without_a_gap():
    clock = Clock(utc(3, 40, 20))
    api = FakeApi(clock)
    result = relay.run(api, {"hourly.yml": ["45 * * * *"]}, 100,
                       now=clock, sleep=clock.sleep)
    assert result == "handed_off"
    hourly = [moment for moment, name, _ in api.dispatched if name == "hourly.yml"]
    assert [(moment.hour, moment.minute) for moment in hourly] == [
        (3, 45), (4, 45), (5, 45), (6, 45), (7, 45)]
    moment, name, inputs = api.dispatched[-1]
    assert name == relay.RELAY_WORKFLOW
    assert inputs["handoff_from"] == "100"
    covered = datetime.fromtimestamp(int(inputs["since"]), timezone.utc)
    assert covered == moment.replace(second=0, microsecond=0)

    # The successor starts after a minute boundary and still fires that slot.
    clock = Clock(utc(8, 45, 20))
    api = FakeApi(clock, active=[100])
    relay.run(api, {"hourly.yml": ["45 * * * *"]}, 105, since=utc(8, 44),
              handoff_from=100, now=clock, sleep=clock.sleep)
    assert api.dispatched[0][1:] == ("hourly.yml", {})
    assert api.dispatched[0][0] < utc(8, 47)


def test_fallback_start_stands_by_and_duplicate_chain_yields():
    clock = Clock(utc(3, 40))
    api = FakeApi(clock, active=[90, 100])
    assert relay.run(api, {"hourly.yml": ["* * * * *"]}, 100,
                     now=clock, sleep=clock.sleep) == "standby"
    assert api.dispatched == []

    api = FakeApi(clock, active=[90, 95, 100])
    assert relay.run(api, {"hourly.yml": ["45 * * * *"]}, 100, handoff_from=90,
                     now=clock, sleep=clock.sleep) == "yielded"
    assert clock.now < utc(3, 52)


def test_failed_dispatch_is_retried_and_handoff_failure_is_reported():
    clock = Clock(utc(3, 44, 30))
    api = FakeApi(clock, fail_dispatches=2)
    relay.run(api, {"hourly.yml": ["45 * * * *"]}, 100, now=clock, sleep=clock.sleep)
    assert api.dispatched[0][1] == "hourly.yml"

    # An outage longer than the inline retries delivers the slot late, once.
    clock = Clock(utc(3, 44, 30))
    api = FakeApi(clock, fail_dispatches=7)
    relay.run(api, {"hourly.yml": ["45 * * * *"]}, 100, now=clock, sleep=clock.sleep)
    first, second = api.dispatched[:2]
    assert first[1] == "hourly.yml" and utc(3, 46) < first[0] < utc(3, 55)
    assert (second[0].hour, second[0].minute) == (4, 45)

    clock = Clock(utc(3, 44, 30))
    api = FakeApi(clock, fail_dispatches=10 ** 6)
    assert relay.run(api, {"hourly.yml": ["45 * * * *"]}, 100,
                     now=clock, sleep=clock.sleep) == "handoff_failed"


def test_workflow_contracts():
    text = (WORKFLOWS / relay.RELAY_WORKFLOW).read_text(encoding="utf-8")
    assert "actions: write" in text
    assert "if: github.ref == 'refs/heads/main'" in text
    assert "python3 -u pipeline/schedule_relay.py" in text
    assert relay.LIFETIME < timedelta(minutes=330) < timedelta(hours=6)
    assert "timeout-minutes: 330" in text
    briefing = (WORKFLOWS / "briefing.yml").read_text(encoding="utf-8")
    assert "SCHEDULE: ${{ github.event.schedule || inputs.schedule }}" in briefing
    assert '[ "$EVENT_NAME" = "workflow_dispatch" ] && [ -z "$SCHEDULE" ]' in briefing
