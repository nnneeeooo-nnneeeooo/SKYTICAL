"""Tests for pipeline/dedupe.py.

No pytest required — run from the repo root with:

    py tests\\test_dedupe.py

Fixtures under tests/fixtures/dedupe/ use {{H-n}} / {{D-n}} placeholders
(n hours / days before now) so the 48-hour and 21-day windows never go
stale. Each test materializes the fixtures into a temp AVWIRE_DATA_DIR
and runs dedupe.py as a subprocess, never touching the real data/ dir.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "tests" / "fixtures" / "dedupe"
DEDUPE_SCRIPT = REPO / "pipeline" / "dedupe.py"

sys.path.insert(0, str(REPO / "pipeline"))
import dedupe  # noqa: E402  (unit-level access to norm_title etc.)

GROUP_ID_RE = re.compile(r"^g-\d{8}-\d{4}-(\d+)$")
_PLACEHOLDER_RE = re.compile(r"\{\{(H|D)-(\d+)\}\}")


def _stamp(**delta) -> str:
    dt = datetime.now(timezone.utc) - timedelta(**delta)
    return dt.strftime("%Y-%m-%dT%H:%MZ")


def _render(text: str) -> str:
    def sub(match: re.Match) -> str:
        unit, n = match.group(1), int(match.group(2))
        return _stamp(hours=n) if unit == "H" else _stamp(days=n)

    return _PLACEHOLDER_RE.sub(sub, text)


def _materialize_fixtures(data_dir: Path) -> None:
    for src in FIXTURES.rglob("*.json"):
        dst = data_dir / src.relative_to(FIXTURES)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(_render(src.read_text(encoding="utf-8")), encoding="utf-8")


def _run_dedupe(data_dir: Path) -> str:
    env = dict(os.environ, AVWIRE_DATA_DIR=str(data_dir))
    proc = subprocess.run(
        [sys.executable, str(DEDUPE_SCRIPT)],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, f"dedupe exited {proc.returncode}: {proc.stderr}"
    return proc.stdout.strip()


def _load_pending(data_dir: Path) -> dict:
    with open(data_dir / "pending.json", encoding="utf-8") as fh:
        return json.load(fh)


def test_norm_title_and_tiebreak() -> None:
    assert dedupe.norm_title("Hello,   WORLD!! - Reuters") == "hello world"
    assert dedupe.norm_title("A_B - C - The Aviation Herald") == "a b c"
    # A long trailing segment is content, not a source suffix.
    long_tail = "Engine shut down - crew declared emergency and diverted to Keflavik"
    assert "emergency" in dedupe.norm_title(long_tail)
    # Equal summary lengths -> SOURCES registry order (faa before reuters).
    tie = [
        {"title": "x", "summary": "same size", "sourceKey": "reuters", "source": "Reuters"},
        {"title": "y", "summary": "same size", "sourceKey": "faa", "source": "FAA"},
    ]
    assert dedupe._best_first(tie)[0]["sourceKey"] == "faa"


def test_filtering_grouping_and_ranking() -> None:
    with tempfile.TemporaryDirectory(prefix="avwire-dedupe-") as tmp:
        data_dir = Path(tmp)
        _materialize_fixtures(data_dir)
        seen_before = (data_dir / "seen.json").read_bytes()

        stdout = _run_dedupe(data_dir)
        # 14 raw (easa ok=false skipped) -> 10 fresh (dropped: seen URL,
        # seen title, stale, empty title) -> 4 groups.
        assert stdout == "dedupe: 14 raw items -> 10 fresh -> 4 groups", stdout

        # dedupe must never write seen.json.
        assert (data_dir / "seen.json").read_bytes() == seen_before

        pending = _load_pending(data_dir)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$", pending["generatedUtc"])
        groups = pending["groups"]
        assert len(groups) == 4

        for n, group in enumerate(groups, start=1):
            match = GROUP_ID_RE.match(group["id"])
            assert match and int(match.group(1)) == n, group["id"]
            for item in group["items"]:
                assert item["source"] and item["sourceKey"], item

        all_titles = [i["title"] for g in groups for i in g["items"]]
        for gone in (
            "FAA statement on winter operations",      # seen URL
            "FAA archives old advisory circular",      # stale (72 h)
            "Boeing delivers 100th 787 to Emirates!",  # seen title, 2 days ago
            "EASA phantom item that must be ignored",  # ok=false snapshot
            "   ",                                     # empty title
        ):
            assert gone not in all_titles, gone

        # Group 1: the multi-source Denver story ranks first; Reuters has
        # the longer summary so it is primary and its item comes first.
        denver = groups[0]
        assert {i["sourceKey"] for i in denver["items"]} == {"faa", "reuters"}
        assert denver["primarySource"] == "Reuters"
        assert denver["items"][0]["sourceKey"] == "reuters"
        # Raw item fields survive with the two annotations added.
        assert set(denver["items"][0]) == {
            "title", "url", "publishedUtc", "summary", "image",
            "source", "sourceKey",
        }
        assert denver["items"][0]["image"] == "https://www.reuters.com/img/denver.jpg"

        # Remaining single-source groups ranked by newest publishedUtc:
        # Airbus (H-5), NTSB (H-6), balloons (H-7).
        assert groups[1]["items"][0]["title"] == (
            "Airbus opens new A320 production line in Toulouse"
        )  # seen-title match is 30 days old -> outside the 21-day window
        assert groups[2]["items"][0]["title"].startswith("NTSB opens investigation")

        # Balloon group capped at 5, keeping the longest summaries.
        balloons = groups[3]
        assert balloons["primarySource"] == "The Aviation Herald"
        titles = [i["title"] for i in balloons["items"]]
        assert len(titles) == 5
        assert "Emergency balloon landing drill unit six" not in titles
        lengths = [len(i["summary"]) for i in balloons["items"]]
        assert lengths == sorted(lengths, reverse=True)


def test_group_cap_and_recency_order() -> None:
    titles = [
        "Quantum kettle recall expands to blue models",
        "Harbor tug crews vote on midnight shifts",
        "Desert observatory spots rogue comet fragment",
        "City council approves rooftop garden fund",
        "Vintage tram line reopens after decade",
        "Chess prodigy wins winter invitational",
        "Glacier survey drones map hidden crevasse",
        "Bakery chain debuts rye sourdough club",
        "Submarine cable repair finishes ahead early",
        "Wind farm output breaks provincial record",
        "Museum returns bronze artifacts to island",
        "Startup prints coral reef scaffolding tiles",
        "Marathon reroute avoids flooded underpass",
        "Library digitizes medieval falconry manuscripts",
        "Volcano sensors detect faint harmonic tremor",
    ]
    # Self-check: fixture titles must be pairwise dissimilar (< 0.6).
    normed = [dedupe.norm_title(t) for t in titles]
    for i in range(len(normed)):
        for j in range(i + 1, len(normed)):
            sim = dedupe._similar(normed[i], normed[j])
            assert sim < dedupe.GROUP_TITLE_SIM, (titles[i], titles[j], sim)

    now = datetime.now(timezone.utc)
    items = [
        {
            "title": title,
            "url": f"https://www.faa.gov/newsroom/story-{i}",
            "publishedUtc": (now - timedelta(minutes=10 * (i + 1))).strftime(
                "%Y-%m-%dT%H:%MZ"
            ),
            "summary": f"Summary for story {i}.",
            "image": None,
        }
        for i, title in enumerate(titles)
    ]
    with tempfile.TemporaryDirectory(prefix="avwire-dedupe-") as tmp:
        data_dir = Path(tmp)
        raw_dir = data_dir / "raw"
        raw_dir.mkdir(parents=True)
        snapshot = {
            "source": "faa",
            "fetchedUtc": _stamp(hours=0),
            "ok": True,
            "error": None,
            "items": items,
        }
        (raw_dir / "faa.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        # No seen.json at all: dedupe must cope with it missing.
        stdout = _run_dedupe(data_dir)
        assert stdout == "dedupe: 15 raw items -> 15 fresh -> 12 groups", stdout

        groups = _load_pending(data_dir)["groups"]
        assert len(groups) == dedupe.MAX_GROUPS == 12
        assert all(len(g["items"]) == 1 for g in groups)
        # Single-source groups rank purely by newest publishedUtc, so the
        # 12 newest stories are emitted in recency order.
        assert [g["items"][0]["title"] for g in groups] == titles[:12]


def test_empty_data_dir() -> None:
    with tempfile.TemporaryDirectory(prefix="avwire-dedupe-") as tmp:
        data_dir = Path(tmp)
        stdout = _run_dedupe(data_dir)
        assert stdout == "dedupe: 0 raw items -> 0 fresh -> 0 groups", stdout
        pending = _load_pending(data_dir)
        assert pending["groups"] == []


def main() -> None:
    tests = [
        test_norm_title_and_tiebreak,
        test_filtering_grouping_and_ranking,
        test_group_cap_and_recency_order,
        test_empty_data_dir,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"all {len(tests)} dedupe tests passed")


if __name__ == "__main__":
    main()
