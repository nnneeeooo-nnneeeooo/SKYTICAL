"""Offline tests for pipeline/write.py (no API key, no network, no pytest).

Run from the repo root:  py tests\\test_write_offline.py   (or python3 on Linux)

The tests point the pipeline at a temporary data directory via AVWIRE_DATA_DIR
and monkeypatch write.draft_group with canned model output, so no Anthropic
API call is ever attempted.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "write"
TMP_BASE = Path(tempfile.mkdtemp(prefix="avwire-write-test-"))
DATA = TMP_BASE / "data"

# Must be set BEFORE importing common/write (common.DATA_DIR reads it at import).
os.environ["AVWIRE_DATA_DIR"] = str(DATA)
sys.path.insert(0, str(ROOT / "pipeline"))

import common  # noqa: E402
import write  # noqa: E402

NOW = common.now_utc()
OLD_STAMP = common.iso_minute(NOW - timedelta(days=30))
RECENT_STAMP = common.iso_minute(NOW - timedelta(days=3))
OLD_DATE = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
RECENT_DATE = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")

DRAFT_SAFETY = {
    "cat": "safety",
    "zh": {
        "title": "聯合航空737丹佛衝出跑道",
        "summary": "聯合航空一架737-8於丹佛降落時衝出跑道，無人受傷，NTSB已展開調查。",
        "body": ["第一段。", "第二段。"],
    },
    "en": {
        "title": "United 737 slides off Denver runway",
        "summary": "A United Airlines 737-8 slid off the runway while landing at Denver; no injuries were reported and the NTSB is investigating.",
        "body": ["First paragraph.", "Second paragraph."],
    },
    "flash": {
        "zh": "聯航737丹佛衝出跑道 無人受傷",
        "en": "United 737 slides off Denver runway; no injuries",
        "hot": True,
    },
    "incident": {
        "date": (NOW - timedelta(days=1)).strftime("%Y-%m-%d"),
        "sev": "ser",
        "aircraft": "B737-8",
        "operator": "United",
        "phase": {"zh": "降落", "en": "Landing"},
        "location": {"zh": "丹佛", "en": "Denver"},
        "desc": {"zh": "降落時衝出跑道", "en": "Runway excursion on landing"},
        "status": "open",
    },
}

DRAFT_BIZ = {
    "cat": "biz",
    "zh": {
        "title": "IATA：六月全球航空貨運需求年增8.2%",
        "summary": "IATA公布六月全球航空貨運需求較去年同期成長8.2%。",
        "body": ["第一段。", "第二段。"],
    },
    "en": {
        "title": "IATA: global air cargo demand up 8.2% in June",
        "summary": "IATA reported global air cargo demand rose 8.2% in June 2026 year on year.",
        "body": ["First paragraph.", "Second paragraph."],
    },
    "flash": {
        "zh": "IATA：六月航空貨運年增8.2%",
        "en": "IATA: June air cargo demand up 8.2%",
        "hot": False,
    },
    "incident": None,
}

_pass = 0
_fail = 0


def check(cond, label):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"FAIL: {label}")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def reset_data_dir():
    """Populate the temp data dir from the static fixtures."""
    if DATA.exists():
        shutil.rmtree(DATA)
    (DATA / "raw").mkdir(parents=True)
    (DATA / "articles").mkdir()
    shutil.copy(FIXTURES / "pending.json", DATA / "pending.json")
    shutil.copy(FIXTURES / "flashes.json", DATA / "flashes.json")
    shutil.copy(FIXTURES / "flightaware.json", DATA / "raw" / "flightaware.json")
    seen = (FIXTURES / "seen.json").read_text(encoding="utf-8")
    seen = seen.replace("__OLD__", OLD_STAMP).replace("__RECENT__", RECENT_STAMP)
    (DATA / "seen.json").write_text(seen, encoding="utf-8")
    incidents = (FIXTURES / "incidents.json").read_text(encoding="utf-8")
    incidents = incidents.replace("__OLD_DATE__", OLD_DATE)
    incidents = incidents.replace("__RECENT_DATE__", RECENT_DATE)
    (DATA / "incidents.json").write_text(incidents, encoding="utf-8")


def all_articles():
    rows = []
    for path in sorted((DATA / "articles").glob("*.json")):
        rows.extend(load(path).get("articles", []))
    return rows


def test_publish_flow():
    """Two groups publish, one is refused; every output file is checked."""
    reset_data_dir()
    # Pre-seed the current hour's batch file to prove merging works.
    hour_path = DATA / "articles" / (NOW.strftime("%Y-%m-%dT%H") + ".json")
    dummy = {"articles": [{"id": "a-existing-dummy", "publishedUtc": OLD_STAMP,
                           "cat": "ops", "primarySource": "FAA", "image": None,
                           "zh": {}, "en": {}, "sources": [{"name": "x", "url": "y"}]}]}
    hour_path.write_text(json.dumps(dummy), encoding="utf-8")

    os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"

    def fake_draft(client, group):
        if group["id"] == "g-20260726-0503-1":
            return DRAFT_SAFETY
        if group["id"] == "g-20260726-0503-2":
            return DRAFT_BIZ
        return None  # refusal path: group stays pending + unseen

    original = write.draft_group
    write.draft_group = fake_draft
    try:
        write.main()
    finally:
        write.draft_group = original

    # --- articles batch file: schema + merge -------------------------------
    articles = all_articles()
    check(len(articles) == 3, f"expected 3 articles (1 dummy + 2 new), got {len(articles)}")
    check(any(a["id"] == "a-existing-dummy" for a in articles),
          "pre-existing article kept after merge")
    new = [a for a in articles if a["id"] != "a-existing-dummy"]
    safety = next((a for a in new if a["cat"] == "safety"), None)
    biz = next((a for a in new if a["cat"] == "biz"), None)
    check(safety is not None and biz is not None, "safety + biz articles published")
    for art in new:
        check(re.fullmatch(r"a-\d{8}-\d{4}-[a-z0-9-]+", art["id"]) is not None,
              f"article id format: {art['id']}")
        check(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", art["publishedUtc"]) is not None,
              f"publishedUtc format: {art['publishedUtc']}")
        check(isinstance(art["sources"], list) and len(art["sources"]) >= 1,
              "article has at least one source")
        check(all("name" in s and "url" in s for s in art["sources"]),
              "every source has name and url")
        check(isinstance(art["zh"]["body"], list) and isinstance(art["en"]["body"], list),
              "zh/en bodies are paragraph lists")
    check(safety["id"].endswith("united-737-slides-off-denver-runway"),
          f"slug derived from en title: {safety['id']}")
    # 3 items in g-1, but two Reuters urls normalize to the same address.
    check(len(safety["sources"]) == 2,
          f"sources deduped by url, got {len(safety['sources'])}")
    check(safety["image"] == "https://img.example.com/denver-737.jpg",
          "image is first non-null item image")
    check(biz["image"] is None, "biz article image is null")
    check(safety["primarySource"] == "NTSB", "primarySource carried from group")
    check(safety["sources"][0]["name"].startswith("NTSB — "),
          "source name = display name + shortened title")

    # --- flashes: prepended with articleId, capped at MAX_FLASHES ----------
    flashes = load(DATA / "flashes.json")
    check(len(flashes) == common.MAX_FLASHES,
          f"flashes capped at {common.MAX_FLASHES}, got {len(flashes)}")
    check(flashes[0]["articleId"] == safety["id"] and flashes[0]["hot"] is True,
          "newest flash first, hot flag preserved")
    check(flashes[1]["articleId"] == biz["id"] and flashes[1]["hot"] is False,
          "second flash is the biz story")
    check(all(f["zh"] != "old flash 9" for f in flashes),
          "oldest flash dropped by the cap")

    # --- incidents: new row prepended with articleId ------------------------
    incidents = load(DATA / "incidents.json")
    check(len(incidents) == 4, f"expected 4 incidents, got {len(incidents)}")
    check(incidents[0]["aircraft"] == "B737-8" and incidents[0]["sev"] == "ser",
          "new incident row prepended")
    check(incidents[0]["articleId"] == safety["id"], "incident links to article")
    check(incidents[0]["sources"] == ["NTSB", "Reuters"],
          f"incident sources from group items, got {incidents[0]['sources']}")

    # --- seen.json: only published groups, pruned > 21 days ----------------
    seen = load(DATA / "seen.json")
    pending_fixture = load(FIXTURES / "pending.json")
    g1, g2, g3 = pending_fixture["groups"]
    for item in g1["items"] + g2["items"]:
        check(common.norm_url(item["url"]) in seen["urls"],
              f"published url recorded: {item['url']}")
    check(common.norm_url(g3["items"][0]["url"]) not in seen["urls"],
          "failed group url NOT recorded in seen.json")
    check(common.norm_url("https://recent.example.com/kept-story") in seen["urls"],
          "recent pre-existing seen url kept")
    check(common.norm_url("https://old.example.com/ancient-story") not in seen["urls"],
          "seen url older than 21 days pruned")
    title_keys = [row[0] for row in seen["titles"]]
    check("recent seen title" in title_keys, "recent seen title kept")
    check("old seen title" not in title_keys, "old seen title pruned")
    check(any("united jet slides off denver runway" in t for t in title_keys),
          "published titles recorded (normalized)")

    # --- pending.json: published groups removed, failed group kept ---------
    pending = load(DATA / "pending.json")
    ids = [g["id"] for g in pending["groups"]]
    check(ids == ["g-20260726-0503-3"], f"only failed group left pending, got {ids}")
    check(pending["generatedUtc"] == pending_fixture["generatedUtc"],
          "pending generatedUtc preserved")

    # --- stats.json ----------------------------------------------------------
    stats = load(DATA / "stats.json")
    check(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", stats["updatedUtc"]) is not None,
          "stats updatedUtc format")
    # fixture recent acc (counts) + new ser (counts); old ser + recent inc don't.
    check(stats["seriousThisWeek"] == 2,
          f"seriousThisWeek == 2, got {stats['seriousThisWeek']}")
    check(stats["flightsTracked"] == 18742 and stats["delayRate"] == 22.4
          and stats["notams"] == 1208, "FlightAware stats merged")
    print("test_publish_flow: done")


def test_group_cap_and_unique_ids():
    """Only the first 10 groups are drafted; duplicate slugs get unique ids."""
    reset_data_dir()
    for name in ("flashes.json", "incidents.json", "seen.json"):
        (DATA / name).unlink()
    groups = [
        {
            "id": f"g-cap-{i}",
            "primarySource": "FAA",
            "items": [{
                "title": f"FAA notice number {i}",
                "url": f"https://www.faa.gov/newsroom/notice-{i}",
                "publishedUtc": "2026-07-26T04:00Z",
                "summary": "s",
                "image": None,
                "source": "FAA",
                "sourceKey": "faa",
            }],
        }
        for i in range(12)
    ]
    (DATA / "pending.json").write_text(
        json.dumps({"generatedUtc": "2026-07-26T05:03Z", "groups": groups}),
        encoding="utf-8")

    os.environ["ANTHROPIC_API_KEY"] = "test-key-not-real"
    original = write.draft_group
    write.draft_group = lambda client, group: DRAFT_BIZ  # same en title every time
    try:
        write.main()
    finally:
        write.draft_group = original

    articles = all_articles()
    check(len(articles) == write.MAX_GROUPS_PER_RUN,
          f"cap: {write.MAX_GROUPS_PER_RUN} articles, got {len(articles)}")
    ids = [a["id"] for a in articles]
    check(len(set(ids)) == len(ids), "colliding slugs got unique article ids")
    pending = load(DATA / "pending.json")
    check(len(pending["groups"]) == 2,
          f"2 groups beyond the cap stay pending, got {len(pending['groups'])}")
    seen = load(DATA / "seen.json")
    check(len(seen["urls"]) == write.MAX_GROUPS_PER_RUN,
          f"seen has exactly the published urls, got {len(seen['urls'])}")
    flashes = load(DATA / "flashes.json")
    check(len(flashes) == write.MAX_GROUPS_PER_RUN, "flashes written from empty file")
    print("test_group_cap_and_unique_ids: done")


def test_no_api_key_end_to_end():
    """Without ANTHROPIC_API_KEY: exit 0, pending untouched, stats refreshed."""
    tmp2 = TMP_BASE / "nokey-data"
    (tmp2 / "raw").mkdir(parents=True)
    shutil.copy(FIXTURES / "pending.json", tmp2 / "pending.json")
    shutil.copy(FIXTURES / "flightaware.json", tmp2 / "raw" / "flightaware.json")
    pending_before = (tmp2 / "pending.json").read_bytes()

    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    env["AVWIRE_DATA_DIR"] = str(tmp2)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, str(ROOT / "pipeline" / "write.py")],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=120,
    )
    check(result.returncode == 0, f"exit code 0 without key, got {result.returncode}: "
                                  f"{result.stderr.strip()}")
    check("ANTHROPIC_API_KEY" in result.stdout, "notice printed to stdout")
    check((tmp2 / "pending.json").read_bytes() == pending_before,
          "pending.json untouched without key")
    stats = load(tmp2 / "stats.json")
    check("updatedUtc" in stats, "stats.json refreshed without key")
    check(stats["seriousThisWeek"] == 0, "seriousThisWeek 0 with no incidents.json")
    check(stats["flightsTracked"] == 18742, "FlightAware stats merged without key")
    check(not (tmp2 / "seen.json").exists(), "seen.json not created without key")
    print("test_no_api_key_end_to_end: done")


def main():
    tests = [test_publish_flow, test_group_cap_and_unique_ids,
             test_no_api_key_end_to_end]
    crashed = False
    for test in tests:
        try:
            test()
        except Exception:
            crashed = True
            print(f"ERROR in {test.__name__}:")
            traceback.print_exc()
    shutil.rmtree(TMP_BASE, ignore_errors=True)
    print(f"{_pass} checks passed, {_fail} failed")
    if _fail or crashed:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
