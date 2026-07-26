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
import providers  # noqa: E402
import write  # noqa: E402

NOW = common.now_utc()
OLD_STAMP = common.iso_minute(NOW - timedelta(days=30))
RECENT_STAMP = common.iso_minute(NOW - timedelta(days=3))
OLD_DATE = (NOW - timedelta(days=30)).strftime("%Y-%m-%d")
RECENT_DATE = (NOW - timedelta(days=2)).strftime("%Y-%m-%d")

_EMPTY_ENTITIES = {key: [] for key in write.ENTITY_KEYS}

DRAFT_SAFETY = {
    # v2 editorial rules: aviation safety events are NEVER auto-published;
    # they go to data/review.json for human approval.
    "status": "manual_review",
    "decisionReason": "航空安全事件，調查進行中，須人工覆核",
    "facts": [
        {"factId": "F1",
         "claim": "NTSB 已對丹佛 737 衝出跑道事件展開調查",
         "sourceQuote": "NTSB said it is investigating a runway excursion"},
        {"factId": "F2",
         "claim": "無人受傷",
         "sourceQuote": "No injuries were reported."},
    ],
    "headlineSupportedBy": ["F1"],
    "summarySupportedBy": ["F1", "F2"],
    "entities": {**_EMPTY_ENTITIES,
                 "organizations": ["NTSB"],
                 "airlines": ["United Airlines"],
                 "aircraft_models": ["Boeing 737-8"],
                 "airports": ["Denver International Airport"]},
    "eventStatus": "under_investigation",
    "riskFlags": ["accident_or_serious_incident", "investigation"],
    "requiresHumanReview": True,
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
    "status": "publish",
    "decisionReason": "",
    "facts": [
        {"factId": "F1",
         "claim": "六月全球航空貨運需求年增 8.2%",
         "sourceQuote": "rose 8.2% in June 2026"},
    ],
    "headlineSupportedBy": ["F1"],
    "summarySupportedBy": ["F1"],
    "entities": {**_EMPTY_ENTITIES,
                 "organizations": ["International Air Transport Association"]},
    "eventStatus": "confirmed",
    "riskFlags": [],
    "requiresHumanReview": False,
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
    """Biz publishes; safety queues for review; approval publishes it."""
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

    # --- run 1: only the biz article publishes -----------------------------
    articles = all_articles()
    check(len(articles) == 2, f"expected 2 articles (dummy + biz), got {len(articles)}")
    check(any(a["id"] == "a-existing-dummy" for a in articles),
          "pre-existing article kept after merge")
    biz = next((a for a in articles if a.get("cat") == "biz"), None)
    check(biz is not None, "biz article published")
    check(re.fullmatch(r"a-\d{8}-\d{4}-[a-z0-9-]+", biz["id"]) is not None,
          f"article id format: {biz['id']}")
    check(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", biz["publishedUtc"]) is not None,
          f"publishedUtc format: {biz['publishedUtc']}")
    check(isinstance(biz["sources"], list) and len(biz["sources"]) >= 1
          and all("name" in s and "url" in s for s in biz["sources"]),
          "article credits its sources")
    check(isinstance(biz["zh"]["body"], list) and isinstance(biz["en"]["body"], list),
          "zh/en bodies are paragraph lists")
    check(biz["image"] is None, "biz article image is null")
    check(biz.get("writer", "").startswith("anthropic:"),
          "writer provenance recorded")
    check(len(biz.get("facts", [])) == 1, "verified fact stored on article")
    check(biz.get("riskFlags") == [], "publish requires empty risk flags")
    check(biz.get("eventStatus") == "confirmed", "eventStatus stored")
    check(biz.get("entities", {}).get("organizations")
          == ["International Air Transport Association"], "entities stored")

    # --- the safety story sits in the review queue, not on the site --------
    review = load(DATA / "review.json")
    check(len(review) == 1, f"safety story queued for review, got {len(review)}")
    entry = review[0]
    check(entry["id"] == "g-20260726-0503-1", f"queued group id: {entry['id']}")
    check(entry["approve"] is False, "queued entries await human approval")
    check(entry["writer"].startswith("anthropic:"), "queue records the writer")
    check(len(entry["facts"]) == 2, "verified facts stored with the entry")
    check(entry["riskFlags"] == ["accident_or_serious_incident", "investigation"],
          f"risk flags on queue entry, got {entry['riskFlags']}")
    check(entry["draft"]["zh"]["title"] == DRAFT_SAFETY["zh"]["title"],
          "full draft preserved for the human editor")

    # --- flashes: only the biz flash prepended -----------------------------
    flashes = load(DATA / "flashes.json")
    check(len(flashes) == common.MAX_FLASHES,
          f"flashes at cap {common.MAX_FLASHES}, got {len(flashes)}")
    check(flashes[0]["articleId"] == biz["id"] and flashes[0]["hot"] is False,
          "newest flash is the biz story")
    check(any(f["zh"] == "old flash 9" for f in flashes),
          "no flash dropped yet (cap not exceeded)")

    # --- incidents: untouched until approval --------------------------------
    incidents = load(DATA / "incidents.json")
    check(len(incidents) == 3, f"no incident row before approval, got {len(incidents)}")

    # --- seen.json: published AND queued groups are consumed ----------------
    seen = load(DATA / "seen.json")
    pending_fixture = load(FIXTURES / "pending.json")
    g1, g2, g3 = pending_fixture["groups"]
    for item in g1["items"] + g2["items"]:
        check(common.norm_url(item["url"]) in seen["urls"],
              f"published/queued url recorded: {item['url']}")
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
          "queued titles recorded (normalized)")

    # --- pending.json: published + queued removed, failed group kept -------
    pending = load(DATA / "pending.json")
    ids = [g["id"] for g in pending["groups"]]
    check(ids == ["g-20260726-0503-3"], f"only failed group left pending, got {ids}")
    check(pending["generatedUtc"] == pending_fixture["generatedUtc"],
          "pending generatedUtc preserved")

    # --- stats.json ----------------------------------------------------------
    stats = load(DATA / "stats.json")
    check(re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z", stats["updatedUtc"]) is not None,
          "stats updatedUtc format")
    check(stats["seriousThisWeek"] == 1,
          f"only the fixture acc counts before approval, got {stats['seriousThisWeek']}")
    check(stats["flightsTracked"] == 18742 and stats["delayRate"] == 22.4
          and stats["notams"] == 1208, "FlightAware stats merged")

    # --- run 2: a human flips approve -> the safety story publishes --------
    review[0]["approve"] = True
    (DATA / "review.json").write_text(
        json.dumps(review, ensure_ascii=False), encoding="utf-8")
    original = write.draft_group
    write.draft_group = lambda client, group: None  # nothing new this run
    try:
        write.main()
    finally:
        write.draft_group = original

    articles = all_articles()
    safety = next((a for a in articles if a.get("cat") == "safety"), None)
    check(len(articles) == 3, f"approved article published, got {len(articles)}")
    check(safety is not None, "safety article on site after approval")
    check(safety["id"].endswith("united-737-slides-off-denver-runway"),
          f"slug derived from en title: {safety['id']}")
    # 3 items in g-1, but two Reuters urls normalize to the same address.
    check(len(safety["sources"]) == 2,
          f"sources deduped by url, got {len(safety['sources'])}")
    check(safety["image"] == "https://img.example.com/denver-737.jpg",
          "image is first non-null item image")
    check(safety["primarySource"] == "NTSB", "primarySource carried from group")
    check(safety["sources"][0]["name"].startswith("NTSB — "),
          "source name = display name + shortened title")
    check(safety.get("riskFlags") == ["accident_or_serious_incident",
                                      "investigation"],
          "risk flags carried onto the published article")
    check(len(safety.get("facts", [])) == 2, "verified facts carried over")
    check(load(DATA / "review.json") == [], "review queue emptied after approval")
    flashes = load(DATA / "flashes.json")
    check(flashes[0]["articleId"] == safety["id"] and flashes[0]["hot"] is True,
          "approved flash prepended, hot flag preserved")
    check(all(f["zh"] != "old flash 9" for f in flashes),
          "oldest flash dropped by the cap")
    incidents = load(DATA / "incidents.json")
    check(len(incidents) == 4 and incidents[0]["aircraft"] == "B737-8"
          and incidents[0]["sev"] == "ser", "incident row added on approval")
    check(incidents[0]["articleId"] == safety["id"], "incident links to article")
    check(incidents[0]["sources"] == ["NTSB", "Reuters"],
          f"incident sources from group items, got {incidents[0]['sources']}")
    stats = load(DATA / "stats.json")
    check(stats["seriousThisWeek"] == 2,
          f"approved ser incident counted, got {stats['seriousThisWeek']}")
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
    # Same en title every time; the quote must match THESE groups' titles.
    cap_draft = json.loads(json.dumps(DRAFT_BIZ))
    cap_draft["facts"] = [{"factId": "F1", "claim": "FAA 發布多則通知",
                           "sourceQuote": "FAA notice number"}]
    original = write.draft_group
    write.draft_group = lambda client, group: cap_draft
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
    for key in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "NVIDIA_API_KEY"):
        env.pop(key, None)
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


class FakeProvider:
    """Scripted provider: each draft() call pops the next scripted step.

    A step is an Exception instance (raised), a dict / None (returned).
    The final step repeats forever. `calls` counts every invocation.
    """

    def __init__(self, name, script):
        self.name = name
        self.label = f"{name}:fake"
        self.script = list(script)
        self.calls = 0

    def available(self):
        return True

    def draft(self, system_prompt, user_prompt, schema):
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def test_extract_json_and_validate_draft():
    ej = providers.extract_json
    check(ej('{"a": 1}') == {"a": 1}, "plain JSON object parses")
    check(ej('```json\n{"a": 1}\n```') == {"a": 1}, "fenced JSON parses")
    check(ej('<think>reasoning...</think>{"a": 1}') == {"a": 1},
          "reasoning block stripped")
    check(ej('Here is the story:\n{"a": {"b": 2}}\nHope this helps!')
          == {"a": {"b": 2}}, "surrounding prose stripped")
    for bad in ("no json here", "[1, 2, 3]", ""):
        try:
            ej(bad)
            check(False, f"extract_json({bad!r}) should raise")
        except ValueError:
            check(True, "bad input raises ValueError")

    check(write.validate_draft(DRAFT_SAFETY) is None, "safety draft validates")
    check(write.validate_draft(DRAFT_BIZ) is None, "biz draft validates")
    check(write.validate_draft("nope") is not None, "non-dict rejected")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    del broken["status"]
    check("status" in (write.validate_draft(broken) or ""),
          "missing status rejected")
    reject_draft = {"status": "reject",
                    "decisionReason": "not enough evidence"}
    check(write.validate_draft(reject_draft) is None,
          "reject draft valid without content fields")
    check(write.validate_draft(DRAFT_SAFETY) is None,
          "manual_review draft validates with full content")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["facts"] = []
    check("facts" in (write.validate_draft(broken) or ""),
          "publish with empty facts rejected")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["flash"]["hot"] = "false"
    check("hot" in (write.validate_draft(broken) or ""),
          "string flash.hot rejected (bool('false') is True)")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["riskFlags"] = ["none"]
    check("riskFlags" in (write.validate_draft(broken) or ""),
          "v2 forbids the 'none' flag (empty array instead)")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["headlineSupportedBy"] = ["F9"]
    check("headlineSupportedBy" in (write.validate_draft(broken) or ""),
          "supported-by must reference existing factId values")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["eventStatus"] = "finalized"
    check("eventStatus" in (write.validate_draft(broken) or ""),
          "unknown eventStatus rejected")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["cat"] = "sports"
    check("cat" in (write.validate_draft(broken) or ""), "bad cat rejected")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    del broken["zh"]["title"]
    check("zh.title" in (write.validate_draft(broken) or ""),
          "missing zh title rejected")
    broken = json.loads(json.dumps(DRAFT_BIZ))
    broken["en"]["body"] = []
    check("en.body" in (write.validate_draft(broken) or ""),
          "empty body rejected")
    broken = json.loads(json.dumps(DRAFT_SAFETY))
    broken["incident"]["sev"] = "catastrophic"
    check("incident.sev" in (write.validate_draft(broken) or ""),
          "bad incident sev rejected")
    broken = json.loads(json.dumps(DRAFT_SAFETY))
    broken["incident"]["date"] = "26 July 2026"
    check("incident.date" in (write.validate_draft(broken) or ""),
          "non-ISO incident date rejected")
    print("test_extract_json_and_validate_draft: done")


def test_provider_failover():
    """Primary dies on quota -> fallback writes; invalid draft falls through."""
    reset_data_dir()
    primary = FakeProvider("gemini", [providers.ProviderQuotaError("HTTP 429")])
    bad_draft = json.loads(json.dumps(DRAFT_BIZ))
    bad_draft["cat"] = "not-a-cat"  # fails validation -> next provider
    middle = FakeProvider("nvidia", [bad_draft])
    backup = FakeProvider("anthropic", [DRAFT_SAFETY, DRAFT_BIZ, None])

    original = write.build_providers
    write.build_providers = lambda: [primary, middle, backup]
    try:
        write.main()
    finally:
        write.build_providers = original

    articles = all_articles()
    check(len(articles) == 1, f"biz published via fallback, got {len(articles)}")
    check(articles[0].get("writer") == "anthropic:fake",
          "article records the provider that actually wrote it")
    review = load(DATA / "review.json")
    check(len(review) == 1 and review[0]["writer"] == "anthropic:fake",
          "safety draft queued for review via fallback provider")
    check(primary.calls == 1,
          f"dead primary is never called again, got {primary.calls} calls")
    check(middle.calls == 3 and backup.calls == 3,
          "surviving providers tried once per group")
    pending = load(DATA / "pending.json")
    ids = [g["id"] for g in pending["groups"]]
    check(ids == ["g-20260726-0503-3"],
          f"refused group stays pending, got {ids}")
    print("test_provider_failover: done")


def test_model_chain_and_routing_policy():
    """name:model order tokens; platform-level death; primary retry-once."""
    # --- order tokens: same platform may appear with different models -----
    saved = {k: os.environ.get(k) for k in (
        "AVWIRE_PROVIDER_ORDER", "NVIDIA_API_KEY", "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY")}
    os.environ["AVWIRE_PROVIDER_ORDER"] = (
        "nvidia:nvidia/nemotron-3-ultra-550b-a55b, "
        "nvidia:nvidia/nemotron-3-super-120b-a12b, "
        "gemini:gemini-3-flash-preview, bogus, nvidia")
    os.environ["NVIDIA_API_KEY"] = "test-key-not-real"
    os.environ["GEMINI_API_KEY"] = "test-key-not-real"
    os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        labels = [p.label for p in providers.build_providers()]
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check(labels == ["nvidia:nvidia/nemotron-3-ultra-550b-a55b",
                     "nvidia:nvidia/nemotron-3-super-120b-a12b",
                     "gemini:gemini-3-flash-preview",
                     "nvidia:deepseek-ai/deepseek-v3.1"],
          f"order tokens honored in order, got {labels}")

    # --- platform auth death skips same-platform fallback models ----------
    reset_data_dir()
    ultra = FakeProvider("nvidia", [providers.ProviderAuthError("HTTP 401")])
    superp = FakeProvider("nvidia", [DRAFT_BIZ])
    gem = FakeProvider("gemini", [DRAFT_BIZ])

    original = write.build_providers
    write.build_providers = lambda: [ultra, superp, gem]
    try:
        write.main()
    finally:
        write.build_providers = original

    check(ultra.calls == 1 and superp.calls == 0,
          f"account failure skips same-platform models "
          f"(ultra {ultra.calls}, super {superp.calls})")
    articles = all_articles()
    check(len(articles) == 1 and articles[0]["writer"] == "gemini:fake",
          "cross-platform fallback wrote the publishable article")

    # --- primary model retries ONCE on a validation failure ----------------
    reset_data_dir()
    pending_fixture = load(FIXTURES / "pending.json")
    only_biz = {**pending_fixture, "groups": [pending_fixture["groups"][1]]}
    (DATA / "pending.json").write_text(
        json.dumps(only_biz, ensure_ascii=False), encoding="utf-8")
    bad = json.loads(json.dumps(DRAFT_BIZ))
    bad["cat"] = "not-a-cat"
    prim = FakeProvider("gemini", [bad, DRAFT_BIZ])

    original = write.build_providers
    write.build_providers = lambda: [prim]
    try:
        write.main()
    finally:
        write.build_providers = original

    check(prim.calls == 2, f"primary retried exactly once, got {prim.calls}")
    articles = all_articles()
    check(len(articles) == 1 and articles[0]["writer"] == "gemini:fake",
          "retry produced the published article")
    print("test_model_chain_and_routing_policy: done")


def test_editorial_gate():
    """Model reject skips the group; fabricated quotes are dropped/blocking."""
    reset_data_dir()
    reject_draft = {"status": "reject",
                    "decisionReason": "insufficient verifiable evidence"}
    fabricated = json.loads(json.dumps(DRAFT_BIZ))
    fabricated["facts"] = [{"factId": "F1", "claim": "完全捏造的主張",
                            "sourceQuote": "this text appears nowhere"}]
    partial = json.loads(json.dumps(DRAFT_BIZ))
    partial["facts"] = [
        {"factId": "F1", "claim": "FAA 就鬧事乘客執法發布聲明",
         "sourceQuote": "enforcement actions against unruly passengers"},
        {"factId": "F2", "claim": "捏造的引文會被丟棄",
         "sourceQuote": "quote fabricated by the model"},
    ]
    # g1 -> editorial reject; g2 -> all quotes fabricated; g3 -> one good.
    solo = FakeProvider("gemini", [reject_draft, fabricated, partial])

    original = write.build_providers
    write.build_providers = lambda: [solo]
    try:
        write.main()
    finally:
        write.build_providers = original

    articles = all_articles()
    check(len(articles) == 1,
          f"only the quote-backed group publishes, got {len(articles)}")
    # 4 calls: g1 reject, g2 fabricated + one primary retry, g3 publish.
    check(solo.calls == 4, f"expected 4 calls incl. retry, got {solo.calls}")
    facts = articles[0].get("facts", [])
    check(len(facts) == 1 and "unruly passengers" in facts[0]["sourceQuote"],
          f"fabricated fact dropped, verified fact kept: {facts}")
    pending = load(DATA / "pending.json")
    ids = [g["id"] for g in pending["groups"]]
    check(ids == ["g-20260726-0503-1", "g-20260726-0503-2"],
          f"rejected + unverifiable groups stay pending, got {ids}")
    seen = load(DATA / "seen.json")
    pending_fixture = load(FIXTURES / "pending.json")
    check(common.norm_url(pending_fixture["groups"][0]["items"][0]["url"])
          not in seen["urls"], "rejected group NOT marked seen")
    print("test_editorial_gate: done")


def test_all_providers_auth_dead():
    """Every provider failing auth -> SystemExit(1), nothing published."""
    reset_data_dir()
    pending_before = (DATA / "pending.json").read_bytes()
    a = FakeProvider("gemini", [providers.ProviderAuthError("HTTP 401")])
    b = FakeProvider("nvidia", [providers.ProviderAuthError("HTTP 403")])

    original = write.build_providers
    write.build_providers = lambda: [a, b]
    exited = None
    try:
        write.main()
    except SystemExit as exc:
        exited = exc.code
    finally:
        write.build_providers = original

    check(exited == 1, f"SystemExit(1) when all providers fail auth, got {exited}")
    check(not list((DATA / "articles").glob("*.json")),
          "no articles when every provider is auth-dead")
    check((DATA / "pending.json").read_bytes() == pending_before,
          "pending.json untouched when nothing published")
    stats = load(DATA / "stats.json")
    check("updatedUtc" in stats, "stats refreshed even on auth failure")
    print("test_all_providers_auth_dead: done")


def main():
    tests = [test_publish_flow, test_group_cap_and_unique_ids,
             test_extract_json_and_validate_draft, test_provider_failover,
             test_model_chain_and_routing_policy, test_editorial_gate,
             test_all_providers_auth_dead, test_no_api_key_end_to_end]
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
