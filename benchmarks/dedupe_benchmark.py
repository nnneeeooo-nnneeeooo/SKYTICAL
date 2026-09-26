#!/usr/bin/env python3
"""Benchmark deterministic SKYTICAL event matching against multilingual embeddings.

This tool is benchmark-only. It never changes production thresholds and never
runs inside the hourly news pipeline. It evaluates a labelled pair set using:
1. pipeline.dedupe.same_event
2. Sentence Transformers cosine similarity across a threshold sweep
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import dedupe  # noqa: E402

DEFAULT_DATASET = ROOT / "benchmarks" / "dedupe_pairs.json"
DEFAULT_OUTPUT = ROOT / "benchmark-results" / "dedupe"
DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@dataclass
class Metrics:
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float
    recall: float
    f1: float
    accuracy: float


def metrics(labels: list[int], predictions: list[int]) -> Metrics:
    tp = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 1)
    fp = sum(1 for y, p in zip(labels, predictions) if y == 0 and p == 1)
    tn = sum(1 for y, p in zip(labels, predictions) if y == 0 and p == 0)
    fn = sum(1 for y, p in zip(labels, predictions) if y == 1 and p == 0)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    accuracy = (tp + tn) / len(labels) if labels else 0.0
    return Metrics(
        tp, fp, tn, fn,
        round(precision, 4),
        round(recall, 4),
        round(f1, 4),
        round(accuracy, 4),
    )


def current_predictions(rows: list[dict]) -> tuple[list[int], float]:
    started = time.perf_counter()
    out = []
    for row in rows:
        a = {"title": row["a"], "summary": ""}
        b = {"title": row["b"], "summary": ""}
        out.append(1 if dedupe.same_event(a, b) else 0)
    elapsed = (time.perf_counter() - started) * 1000
    return out, elapsed


def cosine(a, b) -> float:
    dot = sum(float(x) * float(y) for x, y in zip(a, b))
    aa = math.sqrt(sum(float(x) * float(x) for x in a))
    bb = math.sqrt(sum(float(y) * float(y) for y in b))
    return dot / (aa * bb) if aa and bb else 0.0


def embedding_scores(rows: list[dict], model_name: str) -> tuple[list[float], float]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name)
    texts = []
    for row in rows:
        texts.extend([row["a"], row["b"]])
    started = time.perf_counter()
    vectors = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    elapsed = (time.perf_counter() - started) * 1000
    scores = []
    for i in range(0, len(vectors), 2):
        scores.append(float(vectors[i] @ vectors[i + 1]))
    return scores, elapsed


def threshold_grid() -> list[float]:
    return [round(0.50 + i * 0.025, 3) for i in range(17)]


def best_threshold(labels: list[int], scores: list[float]) -> tuple[float, Metrics]:
    ranked = []
    for threshold in threshold_grid():
        preds = [1 if score >= threshold else 0 for score in scores]
        m = metrics(labels, preds)
        ranked.append((m.f1, m.accuracy, -threshold, threshold, m))
    ranked.sort(reverse=True)
    _, _, _, threshold, m = ranked[0]
    return threshold, m


def markdown(payload: dict) -> str:
    current = payload["current"]
    semantic = payload["semantic"]
    lines = [
        "# SKYTICAL Dedupe Benchmark",
        "",
        f"Pairs: {payload['pairs']} "
        f"({payload['positivePairs']} same-event / {payload['negativePairs']} different-event)",
        "",
        "## Summary",
        "",
        "| Method | Precision | Recall | F1 | Accuracy | Runtime |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Current deterministic | {current['metrics']['precision']:.4f} | "
        f"{current['metrics']['recall']:.4f} | {current['metrics']['f1']:.4f} | "
        f"{current['metrics']['accuracy']:.4f} | {current['elapsedMs']:.2f} ms |",
        f"| Multilingual embeddings @ {semantic['bestThreshold']:.3f} | "
        f"{semantic['metrics']['precision']:.4f} | {semantic['metrics']['recall']:.4f} | "
        f"{semantic['metrics']['f1']:.4f} | {semantic['metrics']['accuracy']:.4f} | "
        f"{semantic['elapsedMs']:.2f} ms* |",
        "",
        "*Embedding runtime excludes model download/load and measures encoding only.",
        "",
        "## Decision gate",
        "",
        "Do not replace production matching from this benchmark alone. A semantic "
        "candidate is worth a production experiment only if it improves F1 on a "
        "larger labelled holdout set without materially increasing false positives, "
        "and if CPU runtime/dependency size remain acceptable for GitHub Actions.",
        "",
        "## Misclassified pairs",
        "",
    ]
    for row in payload["rows"]:
        misses = []
        if row["currentPrediction"] != row["label"]:
            misses.append("current")
        if row["semanticPrediction"] != row["label"]:
            misses.append("semantic")
        if misses:
            lines.append(
                f"- **{row['id']}** ({'/'.join(misses)}): "
                f"`{row['a']}` ↔ `{row['b']}` "
                f"(label={row['label']}, cosine={row['cosine']:.4f})"
            )
    if not any(
        row["currentPrediction"] != row["label"]
        or row["semanticPrediction"] != row["label"]
        for row in payload["rows"]
    ):
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    rows = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        print("dataset must be a non-empty JSON list", file=sys.stderr)
        return 2

    labels = [int(row["label"]) for row in rows]
    current, current_ms = current_predictions(rows)
    scores, semantic_ms = embedding_scores(rows, args.model)
    threshold, semantic_metrics = best_threshold(labels, scores)
    semantic = [1 if score >= threshold else 0 for score in scores]

    payload_rows = []
    for row, cp, sp, score in zip(rows, current, semantic, scores):
        payload_rows.append({
            **row,
            "currentPrediction": cp,
            "semanticPrediction": sp,
            "cosine": round(score, 6),
        })

    payload = {
        "pairs": len(rows),
        "positivePairs": sum(labels),
        "negativePairs": len(labels) - sum(labels),
        "model": args.model,
        "current": {
            "metrics": asdict(metrics(labels, current)),
            "elapsedMs": round(current_ms, 2),
        },
        "semantic": {
            "bestThreshold": threshold,
            "metrics": asdict(semantic_metrics),
            "elapsedMs": round(semantic_ms, 2),
        },
        "rows": payload_rows,
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "summary.md").write_text(
        markdown(payload),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
