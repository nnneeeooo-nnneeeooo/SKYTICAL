"""Discoverable, process-isolated briefing regression tests.

The original 68 checks are preserved in _briefing_legacy.py and execute in a
fresh interpreter. Importing this module performs no pipeline work and does
not mutate environment variables, sys.path, or production data.
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
LEGACY = Path(__file__).with_name("_briefing_legacy.py")
EXPECTED_CHECKS = 68

_WORKER = r"""
import ast
import runpy
import socket
import sys
import urllib.request
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
import requests

path = Path(sys.argv[1])
mode = sys.argv[2]
if mode not in {"run", "fail", "network"}:
    raise ValueError("unknown briefing-test worker mode")

with ExitStack() as stack:
    for target in (
        "socket.socket.connect",
        "socket.socket.connect_ex",
        "socket.create_connection",
        "requests.sessions.Session.request",
        "urllib.request.urlopen",
        "httpx.Client.send",
        "httpx.AsyncClient.send",
    ):
        stack.enter_context(
            patch(target, side_effect=AssertionError("live network is forbidden"))
        )
    if mode == "network":
        probes = (
            lambda: requests.get("https://example.invalid"),
            lambda: urllib.request.urlopen("https://example.invalid"),
            lambda: httpx.get("https://example.invalid"),
            lambda: socket.create_connection(("example.invalid", 443)),
        )
        for probe in probes:
            try:
                probe()
            except AssertionError as exc:
                if str(exc) != "live network is forbidden":
                    raise
            else:
                raise AssertionError("network guard did not reject a request")
        print("4 network probes blocked")
    elif mode == "fail":
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = sorted(
            (node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "check"),
            key=lambda node: node.lineno,
        )
        calls[0].args[0] = ast.Constant(
            "intentional briefing isolation regression failure")
        calls[0].args[1] = ast.Constant(False)
        ast.fix_missing_locations(tree)
        exec(compile(tree, str(path), "exec"), {
            "__name__": "__main__", "__file__": str(path), "__package__": None,
        })
    else:
        runpy.run_path(str(path), run_name="__main__")
"""


def _run_legacy(mode: str = "run"):
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("AVWIRE_", "SKYTICAL_", "API_1_", "PYTHON"))
        and not key.endswith(("_API_KEY", "_TOKEN"))
    }
    with tempfile.TemporaryDirectory(prefix="skytical-briefing-test-") as directory:
        root = Path(directory)
        env.update(
            TMPDIR=str(root), TMP=str(root), TEMP=str(root),
            PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0",
            PYTHONIOENCODING="utf-8",
        )
        result = subprocess.run(
            [sys.executable, "-B", "-c", _WORKER, str(LEGACY), mode],
            cwd=REPO, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=90, check=False,
        )
    return result, root


class BriefingIsolationTests(unittest.TestCase):
    def _assert_success(self, result):
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        match = re.search(r"^(\d+) checks passed, 0 failed$", output, re.MULTILINE)
        self.assertIsNotNone(match, output)
        self.assertEqual(int(match.group(1)), EXPECTED_CHECKS, output)

    def test_all_original_checks_pass_in_isolated_process(self):
        result, directory = _run_legacy()
        self._assert_success(result)
        self.assertFalse(directory.exists())

    def test_failure_propagates_to_test_runner(self):
        result, directory = _run_legacy("fail")
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 1, output)
        self.assertIn("FAIL intentional briefing isolation regression failure", output)
        self.assertIn("67/68 passed, 1 FAILED", output)
        self.assertFalse(directory.exists())

    def test_parent_environment_and_search_path_are_unchanged(self):
        environment, search_path = dict(os.environ), list(sys.path)
        result, directory = _run_legacy()
        self._assert_success(result)
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual(sys.path, search_path)
        self.assertFalse(directory.exists())

    def test_import_has_no_side_effects(self):
        spec = importlib.util.spec_from_file_location("_briefing_import_probe", __file__)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        environment, search_path = dict(os.environ), list(sys.path)
        output = io.StringIO()
        with ExitStack() as stack:
            for target in ("tempfile.mkdtemp", "tempfile.TemporaryDirectory",
                           "subprocess.run"):
                stack.enter_context(patch(
                    target, side_effect=AssertionError("work performed on import")))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(output))
            spec.loader.exec_module(module)
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(dict(os.environ), environment)
        self.assertEqual(sys.path, search_path)

    def test_network_guard_blocks_live_requests(self):
        result, directory = _run_legacy("network")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("4 network probes blocked", result.stdout)
        self.assertFalse(directory.exists())

    def test_legacy_script_keeps_original_contract(self):
        source = LEGACY.read_text(encoding="utf-8")
        self.assertIn("morning window is prev-day 07:00", source)
        self.assertIn("per-section cap (6) enforced", source)
        self.assertIn("sys.exit(1 if FAILED else 0)", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
