"""Offline checks for persisted provider cooldowns."""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import provider_health  # noqa: E402


def main() -> None:
    base = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        provider_health.HEALTH_PATH = Path(tmp) / "provider-health.json"

        until = provider_health.mark_failure("gemini", "transient", base)
        assert until == base + timedelta(hours=1)
        assert provider_health.active_platforms(base + timedelta(minutes=59)) == {
            "gemini"
        }
        assert provider_health.active_platforms(base + timedelta(hours=1, minutes=1)) == set()

        provider_health.mark_failure("nvidia", "quota", base)
        rows = provider_health.cooldown_rows(base + timedelta(hours=5))
        assert rows["nvidia"]["failureClass"] == "quota"
        assert "nvidia" not in provider_health.active_platforms(
            base + timedelta(hours=6, minutes=1)
        )

        provider_health.mark_failure("anthropic", "auth", base)
        assert "anthropic" in provider_health.active_platforms(
            base + timedelta(hours=11, minutes=59)
        )
        assert provider_health.mark_success(
            "anthropic", base + timedelta(hours=1)
        ) is True
        assert "anthropic" not in provider_health.active_platforms(
            base + timedelta(hours=1)
        )

        payload = json.loads(
            provider_health.HEALTH_PATH.read_text(encoding="utf-8")
        )
        assert payload["schemaVersion"] == 1
        assert all(
            set(row) <= {"failureClass", "cooldownUntilUtc", "updatedUtc"}
            for row in payload["platforms"].values()
        )

    print("test_provider_health: OK")


if __name__ == "__main__":
    main()
