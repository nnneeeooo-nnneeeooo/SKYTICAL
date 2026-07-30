"""Tests for pipeline/dedupe.py.

No pytest required — run from the repo root with:

    py tests\\test_dedupe.py

Fixtures under tests/fixtures/dedupe/ use {{H-n}} / {{D-n}} placeholders
(n hours / days before now) so the freshness (default 120 h) and 21-day
windows never go stale. Each test materializes the fixtures into a temp
AVWIRE_DATA_DIR and runs dedupe.py as a subprocess, never touching the
real data/ dir.
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


def _run_dedupe(data_dir: Path, extra_env: dict | None = None) -> str:
    env = dict(os.environ, AVWIRE_DATA_DIR=str(data_dir))
    env.pop("NEWS_MAX_AGE_HOURS", None)
    env.pop("AVWIRE_MAX_AGE_HOURS", None)
    if extra_env:
        env.update(extra_env)
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


def _summary_line(stdout: str) -> str:
    """First stdout line: 'dedupe: N raw items -> N fresh -> N groups'.
    (Config warnings may precede it; the stats line follows it.)"""
    for line in stdout.splitlines():
        if line.startswith("dedupe:"):
            return line
    return stdout


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
        # 15 raw (easa ok=false items are carried forward, not skipped)
        # -> 12 active items. An exact seen URL is dropped, while a new URL
        # whose headline matches a seen event remains as an update candidate.
        # -> 6 groups.
        assert _summary_line(stdout) == \
            "dedupe: 15 raw items -> 12 fresh -> 6 groups", stdout
        assert "skipped_too_old=1" in stdout, stdout
        assert "skipped_seen_url=1" in stdout, stdout
        assert "skipped_seen_title=0" in stdout, stdout
        assert "skipped_untitled=1" in stdout, stdout
        assert "window=120h" in stdout, stdout

        # dedupe must never write seen.json.
        assert (data_dir / "seen.json").read_bytes() == seen_before

        pending = _load_pending(data_dir)
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z$", pending["generatedUtc"])
        groups = pending["groups"]
        assert len(groups) == 6

        for n, group in enumerate(groups, start=1):
            match = GROUP_ID_RE.match(group["id"])
            assert match and int(match.group(1)) == n, group["id"]
            for item in group["items"]:
                assert item["source"] and item["sourceKey"], item

        all_titles = [i["title"] for g in groups for i in g["items"]]
        for gone in (
            "FAA statement on winter operations",      # seen URL
            "FAA archives old advisory circular",      # stale (130 h)
            "   ",                                     # empty title
        ):
            assert gone not in all_titles, gone
        # ok=false snapshots are carried forward by fetch.py — items survive.
        assert "EASA carried-forward item survives source flap" in all_titles

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

        # Remaining single-source groups ranked by newest publishedUtc. The
        # Boeing URL is new, so its seen-title match becomes an article update.
        assert groups[1]["items"][0]["sourceKey"] == "easa"
        assert groups[2]["items"][0]["title"] == \
            "Boeing delivers 100th 787 to Emirates!"
        assert groups[2]["updateCandidate"] is True
        assert groups[3]["items"][0]["title"] == (
            "Airbus opens new A320 production line in Toulouse"
        )  # seen-title match is 30 days old -> outside the 21-day window
        assert groups[4]["items"][0]["title"].startswith("NTSB opens investigation")

        # Balloon group fits the six-item current-source cap.
        balloons = groups[5]
        assert balloons["primarySource"] == "The Aviation Herald"
        titles = [i["title"] for i in balloons["items"]]
        assert len(titles) == 6
        lengths = [len(i["summary"]) for i in balloons["items"]]
        assert lengths == sorted(lengths, reverse=True)


def test_structured_event_matching() -> None:
    """Different editorial wording still joins on entity/model/action anchors."""
    aerotime = {
        "title": "ANA orders eight additional Embraer E190-E2 aircraft",
        "summary": "ANA expanded its E190-E2 commitment by eight aircraft.",
    }
    agn = {
        "title": "ANA boosts E190-E2 order with eight more aircraft",
        "summary": "Embraer and ANA announced the expanded aircraft order.",
    }
    unrelated = {
        "title": "ANA introduces a new cabin on Boeing 787 aircraft",
        "summary": "The airline unveiled redesigned cabin interiors.",
    }
    assert dedupe.same_event(aerotime, agn)
    assert not dedupe.same_event(aerotime, unrelated)


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
        assert _summary_line(stdout) == \
            "dedupe: 15 raw items -> 15 fresh -> 12 groups", stdout

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
        assert _summary_line(stdout) == \
            "dedupe: 0 raw items -> 0 fresh -> 0 groups", stdout
        pending = _load_pending(data_dir)
        assert pending["groups"] == []


def _write_snapshot(data_dir: Path, key: str, items: list) -> None:
    raw_dir = data_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{key}.json").write_text(
        json.dumps({"source": key, "fetchedUtc": _stamp(hours=0), "ok": True,
                    "error": None, "items": items}, ensure_ascii=False),
        encoding="utf-8")


def _mk_item(title: str, url: str, hours_ago: float, summary: str) -> dict:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {"title": title, "url": url,
            "publishedUtc": dt.strftime("%Y-%m-%dT%H:%MZ"),
            "summary": summary, "image": None}


def test_freshness_window_and_future_guard() -> None:
    """120h default window (env-tunable, validated) + future-date guard."""
    body = "A perfectly usable summary sentence with plenty of real text."
    items = [
        _mk_item("Future item within clock skew", "https://www.faa.gov/n/f2",
                 -2, body),            # +2h -> tolerated
        _mk_item("Future item beyond clock skew", "https://www.faa.gov/n/f8",
                 -8, body),            # +8h -> source clock error, dropped
        _mk_item("Hundred hour old official notice", "https://www.faa.gov/n/o1",
                 100, body),           # kept by the 120h default
        _mk_item("Ancient item far outside window", "https://www.faa.gov/n/o2",
                 130, body),           # dropped
    ]
    with tempfile.TemporaryDirectory(prefix="avwire-dedupe-") as tmp:
        data_dir = Path(tmp)
        _write_snapshot(data_dir, "faa", items)

        stdout = _run_dedupe(data_dir)
        assert _summary_line(stdout) == \
            "dedupe: 4 raw items -> 2 fresh -> 2 groups", stdout
        assert "skipped_future_date=1" in stdout, stdout
        assert "skipped_too_old=1" in stdout, stdout
        titles = [g["items"][0]["title"]
                  for g in _load_pending(data_dir)["groups"]]
        assert "Future item within clock skew" in titles
        assert "Hundred hour old official notice" in titles

        # Narrower window via env: the 100h item now falls out too.
        stdout = _run_dedupe(data_dir, {"NEWS_MAX_AGE_HOURS": "72"})
        assert _summary_line(stdout) == \
            "dedupe: 4 raw items -> 1 fresh -> 1 groups", stdout
        assert "window=72h" in stdout, stdout

        # Invalid values fall back to the safe default with a warning.
        for bad in ("abc", "12", "999"):
            stdout = _run_dedupe(data_dir, {"NEWS_MAX_AGE_HOURS": bad})
            assert "config: NEWS_MAX_AGE_HOURS" in stdout, (bad, stdout)
            assert "window=120h" in stdout, (bad, stdout)


def test_material_groups_rank_first() -> None:
    """Title-only groups - even multi-source ones - must not crowd real
    stories out of the cap."""
    body = "A real summary carrying enough evidence text for the model."
    faa_items = [
        _mk_item("Newest but title only headline item",
                 "https://www.faa.gov/n/thin", 1, ""),
        _mk_item("Older official notice with a full summary",
                 "https://www.faa.gov/n/full", 30, body),
        _mk_item("Summary that just repeats its own headline",
                 "https://www.faa.gov/n/echo", 2,
                 "Summary that just repeats its own headline"),
    ]
    # Same headline via a Google-News-fed source: forms a MULTI-source
    # group that still has zero summary material (their summaries are
    # blanked at fetch time).
    reuters_items = [
        _mk_item("Newest but title only headline item",
                 "https://www.reuters.com/n/thin", 1, ""),
    ]
    with tempfile.TemporaryDirectory(prefix="avwire-dedupe-") as tmp:
        data_dir = Path(tmp)
        _write_snapshot(data_dir, "faa", faa_items)
        _write_snapshot(data_dir, "reuters", reuters_items)
        stdout = _run_dedupe(data_dir)
        assert _summary_line(stdout) == \
            "dedupe: 4 raw items -> 4 fresh -> 3 groups", stdout
        groups = _load_pending(data_dir)["groups"]
        assert groups[0]["items"][0]["title"] == \
            "Older official notice with a full summary", groups
        assert len(groups[1]["items"]) == 2, \
            "multi-source thin group ranks below the material story"
        assert "groups_with_material=1/3" in stdout, stdout


def main() -> None:
    tests = [
        test_norm_title_and_tiebreak,
        test_structured_event_matching,
        test_filtering_grouping_and_ranking,
        test_group_cap_and_recency_order,
        test_empty_data_dir,
        test_freshness_window_and_future_guard,
        test_material_groups_rank_first,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"all {len(tests)} dedupe tests passed")


if __name__ == "__main__":
    main()
