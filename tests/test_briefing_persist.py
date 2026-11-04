"""Offline git integration tests for the daily briefing persistence step."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "pipeline" / "persist_briefing.sh"


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, check=True,
                            capture_output=True, text=True)
    return result.stdout.strip()


class PersistBriefingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="briefing-persist-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.remote = base / "remote.git"
        self.seed = base / "seed"
        self.work = base / "work"
        self.output = base / "github-output"
        git(base, "init", "--bare", "--initial-branch=main", str(self.remote))
        git(base, "clone", str(self.remote), str(self.seed))
        git(self.seed, "config", "user.name", "test")
        git(self.seed, "config", "user.email", "test@example.com")
        (self.seed / "data" / "briefings").mkdir(parents=True)
        (self.seed / "data" / "briefings" / "index.json").write_text("{}\n")
        (self.seed / "data" / "paid-budget.json").write_text("baseline\n")
        (self.seed / "data" / "usage.json").write_text("usage-0\n")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-m", "initial")
        git(self.seed, "push", "origin", "main")
        git(base, "clone", str(self.remote), str(self.work))

    def persist(self) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "GITHUB_OUTPUT": str(self.output),
               "BRIEFING_PERSIST_RETRY_DELAY": "0"}
        return subprocess.run(["bash", str(SCRIPT), "morning"], cwd=self.work,
                              env=env, text=True, capture_output=True)

    def test_dirty_budget_and_new_remote_changes_are_preserved(self) -> None:
        # Simulate the paid-budget CAS pushing a newer ledger onto main,
        # followed by a local budget refresh that leaves the tree dirty.
        (self.seed / "data" / "paid-budget.json").write_text("remote-CAS\n")
        (self.seed / "other-news.txt").write_text("new remote news\n")
        git(self.seed, "add", "-A")
        git(self.seed, "commit", "-m", "concurrent update")
        git(self.seed, "push", "origin", "main")
        (self.work / "data" / "paid-budget.json").write_text("local-unstaged\n")
        (self.work / "data" / "usage.json").write_text("usage-1\n")
        (self.work / "data" / "briefings" / "2026-11-01-morning.json").write_text(
            '{"briefing_id":"2026-11-01-morning"}\n')
        (self.work / "scratch.txt").write_text("untracked\n")
        result = self.persist()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("persisted=true", self.output.read_text())
        self.assertIn("data/paid-budget.json", result.stdout)
        self.assertEqual(git(self.seed, "show", "main:other-news.txt"), "new remote news")
        git(self.work, "fetch", "origin", "main")
        self.assertEqual(git(self.work, "show", "origin/main:data/paid-budget.json"),
                         "remote-CAS")
        self.assertEqual(git(self.work, "show", "origin/main:data/briefings/2026-11-01-morning.json"),
                         '{"briefing_id":"2026-11-01-morning"}')
        self.assertEqual(git(self.work, "show", "origin/main:data/usage.json"), "usage-1")
        self.assertEqual(git(self.work, "show", "origin/main:other-news.txt"), "new remote news")
        self.assertEqual((self.work / "data" / "paid-budget.json").read_text(),
                         "local-unstaged\n")
        self.assertEqual((self.work / "scratch.txt").read_text(), "untracked\n")

    def test_no_briefing_changes_is_no_op(self) -> None:
        before = git(self.work, "rev-parse", "HEAD")
        (self.work / "data" / "paid-budget.json").write_text("dirty-only\n")
        result = self.persist()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(git(self.work, "rev-parse", "HEAD"), before)
        self.assertEqual(self.output.read_text().strip(), "persisted=true")
        self.assertEqual((self.work / "data" / "paid-budget.json").read_text(),
                         "dirty-only\n")

    def test_push_failure_preserves_local_committed_report(self) -> None:
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        report = self.work / "data" / "briefings" / "2026-11-01-evening.json"
        report.write_text('{"briefing_id":"2026-11-01-evening"}\n')
        result = self.persist()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("briefing data could not be persisted after 3 attempts",
                      result.stdout)
        self.assertEqual(git(self.work, "show", "HEAD:data/briefings/2026-11-01-evening.json"),
                         '{"briefing_id":"2026-11-01-evening"}')
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
