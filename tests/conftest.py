"""Run legacy script suites and pytest modules in separate Python processes.

Several script suites replace provider modules and set AVWIRE_DATA_DIR before
importing the pipeline. Sharing those imports can point another suite at live
data or a deleted fixture directory. Isolation also lets pytest run script-only
checks instead of silently collecting zero tests from them.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys

import pytest


class IsolatedSuite(pytest.File):
    def collect(self):
        tree = ast.parse(self.path.read_text(encoding="utf-8"))
        has_tests = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            or isinstance(node, ast.ClassDef) and any(
                isinstance(child, ast.FunctionDef) and child.name.startswith("test")
                for child in node.body)
            for node in tree.body)
        script = any(isinstance(node, ast.If) and "__name__" in ast.unparse(node.test)
                     for node in tree.body)
        if has_tests:
            yield IsolatedCheck.from_parent(self, name="pytest", mode="pytest")
        if script or not has_tests:
            yield IsolatedCheck.from_parent(self, name="script", mode="script")


class IsolatedCheck(pytest.Item):
    def __init__(self, *, mode, **kwargs):
        super().__init__(**kwargs)
        self.mode = mode

    def reportinfo(self):
        return self.path, 0, f"{self.path.name}::{self.mode}"

    def repr_failure(self, excinfo):
        return f"{self.path.name} ({self.mode})\n{excinfo.value}"

    def runtest(self):
        root = self.path.parents[1]
        env = dict(os.environ, SKYTICAL_PYTEST_CHILD="1", PYTHONUTF8="1")
        args = [sys.executable]
        if self.mode == "pytest":
            args += ["-m", "pytest", "-q", "-p", "no:cacheprovider"]
        args.append(str(self.path))
        result = subprocess.run(args, cwd=root, env=env, capture_output=True,
                                encoding="utf-8", errors="replace", timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr


def pytest_pycollect_makemodule(module_path, parent):
    if os.environ.get("SKYTICAL_PYTEST_CHILD") != "1":
        return IsolatedSuite.from_parent(parent, path=module_path)
