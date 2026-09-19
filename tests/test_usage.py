"""Discoverable, process-isolated tests for API usage and its dashboard.

Run with either ``python tests/test_usage.py`` or
``python -m pytest -q tests/test_usage.py``.

The original 46 checks are preserved verbatim in _usage_legacy.py. They
run in a fresh Python process, never while pytest imports this module.
The parent owns and cleans the entire temporary tree, including on failure.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
LEGACY = Path(__file__).with_name("_usage_legacy.py")
EXPECTED_CHECKS = 46

_WORKER = r'''
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
    raise ValueError("unknown usage-test worker mode")
with ExitStack() as stack:
    for target in (
        "socket.socket.connect", "socket.socket.connect_ex",
        "socket.create_connection", "requests.sessions.Session.request",
        "urllib.request.urlopen", "httpx.Client.send", "httpx.AsyncClient.send",
    ):
        stack.enter_context(patch(
            target, side_effect=AssertionError("live network is forbidden")))
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
        # Inject one false check in memory only. The unchanged legacy exit
        # code must reach unittest/pytest, rather than being silently ignored.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        calls = sorted((node for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "check"), key=lambda node: node.lineno)
        calls[0].args[0] = ast.Constant("intentional isolation regression failure")
        calls[0].args[1] = ast.Constant(False)
        ast.fix_missing_locations(tree)
        exec(compile(tree, str(path), "exec"), {
            "__name__": "__main__", "__file__": str(path), "__package__": None,
        })
    else:
        runpy.run_path(str(path), run_name="__main__")
'''


def _run_legacy(mode: str = "run") -> tuple[subprocess.CompletedProcess[str], Path]:
    # Do not pass inherited provider credentials or dashboard configuration
    # to a test worker. The legacy checks set their own fake API keys.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("AVWIRE_", "SKYTICAL_", "API_1_", "PYTHON"))
           and not key.endswith(("_API_KEY", "_TOKEN"))}
    with tempfile.TemporaryDirectory(prefix="skytical-usage-test-") as directory:
        root = Path(directory)
        env.update(TMPDIR=str(root), TMP=str(root), TEMP=str(root),
                   PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0",
                   PYTHONIOENCODING="utf-8")
        result = subprocess.run(
            [sys.executable, "-B", "-c", _WORKER, str(LEGACY), mode],
            cwd=REPO, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60, check=False,
        )
    return result, root


def _output_snapshot() -> dict[str, tuple[str, str]]:
    """Include ignored/untracked files, empty directories, and symlinks."""
    result = {}
    for name in ("data", "site"):
        root = REPO / name
        paths = [root]
        if root.is_dir() and not root.is_symlink():
            paths.extend(sorted(root.rglob("*")))
        for path in paths:
            key = str(path.relative_to(REPO))
            if path.is_symlink():
                result[key] = ("symlink", os.readlink(path))
            elif path.is_file():
                result[key] = ("file", hashlib.sha256(path.read_bytes()).hexdigest())
            elif path.is_dir():
                result[key] = ("directory", "")
            else:
                result[key] = ("missing", "")
    return result


class UsageIsolationTests(unittest.TestCase):
    def setUp(self):
        before = _output_snapshot()
        self.addCleanup(lambda: self.assertEqual(
            _output_snapshot(), before, "production data/site changed"))

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

    def test_original_check_count_is_preserved(self):
        tree = ast.parse(LEGACY.read_text(encoding="utf-8"))
        count = sum(isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "check" for node in ast.walk(tree))
        self.assertEqual(count, EXPECTED_CHECKS)

    def test_cached_modules_and_parent_environment_are_unchanged(self):
        # A child interpreter must not reuse any parent's cached DATA_DIR,
        # USAGE_PATH, output directory, provider mock, or test credentials.
        with tempfile.TemporaryDirectory(prefix="skytical-usage-parent-") as name:
            stale = Path(name)
        sentinels = {}
        for name in ("common", "usage", "build", "providers"):
            module = types.ModuleType(name)
            module.DATA_DIR = stale
            module.USAGE_PATH = stale / "usage.json"
            module.SITE_DIR = stale / "site"
            module.requests = object()
            sentinels[name] = module
        with patch.dict(sys.modules, sentinels), patch.dict(os.environ, {
            "AVWIRE_DATA_DIR": str(stale),
            "AVWIRE_USAGE_TOKEN": "parent-test-token-not-for-worker",
            "NVIDIA_API_KEY": "parent-fake-key", "GEMINI_API_KEY": "parent-fake-key",
        }):
            environment = dict(os.environ)
            search_path = list(sys.path)
            attributes = {key: dict(vars(value)) for key, value in sentinels.items()}
            result, directory = _run_legacy()
            self._assert_success(result)
            self.assertEqual(dict(os.environ), environment)
            self.assertEqual(sys.path, search_path)
            for name, module in sentinels.items():
                self.assertIs(sys.modules[name], module)
                self.assertEqual(vars(module), attributes[name])
            self.assertFalse(stale.exists())
            self.assertFalse(directory.exists())

    def test_failed_check_propagates_and_temporary_files_are_removed(self):
        result, directory = _run_legacy("fail")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("FAIL intentional isolation regression failure", result.stdout)
        self.assertIn("45/46 passed, 1 FAILED", result.stdout)
        self.assertFalse(directory.exists())

    def test_import_has_no_environment_filesystem_or_execution_side_effects(self):
        spec = importlib.util.spec_from_file_location("_usage_import_probe", __file__)
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

    def test_timeout_also_cleans_the_temporary_directory(self):
        directories = []

        def timeout(*args, **kwargs):
            root = Path(kwargs["env"]["TMPDIR"])
            directories.append(root)
            (root / "partial-output.txt").write_text("fixture", encoding="utf-8")
            raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

        with patch.object(subprocess, "run", side_effect=timeout):
            with self.assertRaises(subprocess.TimeoutExpired):
                _run_legacy()
        self.assertEqual(len(directories), 1)
        self.assertFalse(directories[0].exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
