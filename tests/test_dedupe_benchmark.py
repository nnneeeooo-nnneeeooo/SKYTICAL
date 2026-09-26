from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "benchmarks" / "dedupe_benchmark.py"
DATASET = ROOT / "benchmarks" / "dedupe_pairs.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("dedupe_benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_dedupe_dataset_is_balanced_and_unique():
    rows = json.loads(DATASET.read_text(encoding="utf-8"))
    assert len(rows) == 30
    assert sum(int(row["label"]) for row in rows) == 15
    assert len({row["id"] for row in rows}) == len(rows)
    assert all(row["a"].strip() and row["b"].strip() for row in rows)


def test_metrics_counts_and_rates():
    module = _load_module()
    result = module.metrics([1, 1, 0, 0], [1, 0, 1, 0])
    assert result.tp == 1
    assert result.fp == 1
    assert result.tn == 1
    assert result.fn == 1
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5
    assert result.accuracy == 0.5


def test_threshold_grid_is_stable():
    module = _load_module()
    grid = module.threshold_grid()
    assert grid[0] == 0.5
    assert grid[-1] == 0.9
    assert len(grid) == 17
