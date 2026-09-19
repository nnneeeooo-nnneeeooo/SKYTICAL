"""Regression coverage for SKYTICAL_* environment-name migration."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PIPELINE = REPO / "pipeline"


def _probe(code: str, env: dict[str, str]) -> str:
    clean = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("AVWIRE_", "SKYTICAL_"))
    }
    clean.update(env)
    result = subprocess.run(
        [sys.executable, "-B", "-c",
         "import sys; sys.path.insert(0, " + repr(str(PIPELINE)) + "); " + code],
        cwd=REPO, env=clean, capture_output=True, text=True, timeout=20,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout.strip()


class EnvironmentMigrationTests(unittest.TestCase):
    def test_skytical_data_dir_wins_over_legacy_alias(self):
        with tempfile.TemporaryDirectory() as new_dir, tempfile.TemporaryDirectory() as old_dir:
            out = _probe(
                "import common; print(common.DATA_DIR)",
                {"SKYTICAL_DATA_DIR": new_dir, "AVWIRE_DATA_DIR": old_dir},
            )
            self.assertEqual(Path(out), Path(new_dir))

    def test_legacy_data_dir_still_works_when_new_name_is_absent(self):
        with tempfile.TemporaryDirectory() as old_dir:
            out = _probe(
                "import common; print(common.DATA_DIR)",
                {"AVWIRE_DATA_DIR": old_dir},
            )
            self.assertEqual(Path(out), Path(old_dir))

    def test_skytical_model_wins_over_legacy_model(self):
        out = _probe(
            "import providers; print(providers.AnthropicProvider().model)",
            {"SKYTICAL_MODEL": "new-model", "AVWIRE_MODEL": "old-model"},
        )
        self.assertEqual(out, "new-model")

    def test_legacy_model_still_works_when_new_name_is_absent(self):
        out = _probe(
            "import providers; print(providers.AnthropicProvider().model)",
            {"AVWIRE_MODEL": "old-model"},
        )
        self.assertEqual(out, "old-model")


if __name__ == "__main__":
    unittest.main(verbosity=2)
