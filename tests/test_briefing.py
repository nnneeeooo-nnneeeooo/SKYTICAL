"""Tests for pipeline/briefing.py (thrice-daily transport briefing).

No pytest required — run from the repo root:

    py tests\\test_briefing.py

Everything runs offline against a temp AVWIRE_DATA_DIR with fixture
articles; model providers are replaced by a fake module that counts
calls, so no real RSS, API, NVIDIA or Gemini endpoint is ever touched.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-briefing-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)
# The selection/dedup/update machinery below is exercised with the merged
# mode on; production default is the pure bulletin (owner 2026-07-27).
os.environ["BRIEFING_INCLUDE_ARTICLES"] = "true"

sys.path.insert(0, str(REPO / "pipeline"))
import briefing  # noqa: E402
from briefing import (  # noqa: E402
    CRON_TO_EDITION,
    TPE,
    event_fingerprint,
    get_briefing_window,
    scheduled_taipei_date,
)

CHECKS = 0
FAILED = 0


def check(name: str, cond) -> None:
    global CHECKS, FAILED
    CHECKS += 1
    if cond:
        print(f"PASS {name}")
    else:
        FAILED += 1
        print(f"FAIL {name}")


# ── fixtures ─────────────────────────────────────────────────────────────────

def reset() -> None:
    for sub in ("articles", "briefings"):
        shutil.rmtree(TMP / sub, ignore_errors=True)
    for f in ("sources.json", "review.json"):
        try:
            (TMP / f).unlink()
        except FileNotFoundError:
            pass


def tpe(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TPE)


def utc_stamp(dt) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def make_article(art_id, title, src_dt, *, cat="ops", orgs=("CAA Taiwan",),
                 locs=("臺灣",), claims=("fact one", "fact two"),
                 urls=("https://example.gov/a",), summary="摘要內容"):
    return {
        "id": art_id,
        "publishedUtc": utc_stamp(src_dt),
        "sourcePublishedUtc": utc_stamp(src_dt),
        "cat": cat,
        "primarySource": "Test",
        "image": None,
        "zh": {"title": title, "summary": summary, "body": [summary]},
        "en": {"title": f"EN {title}", "summary": "en summary",
               "body": ["en body"]},
        "sources": [{"name": "Test source", "url": u} for u in urls],
        "writer": "nvidia:test-model",
        "facts": [{"factId": f"F{i+1}", "claim": c, "sourceQuote": c}
                  for i, c in enumerate(claims)],
        "riskFlags": [],
        "eventStatus": "confirmed",
        "entities": {"organizations": list(orgs), "locations": list(locs),
                     "event_dates": []},
    }


def write_articles(articles, fname="batch.json") -> None:
    path = TMP / "articles" / fname
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"articles": articles}, ensure_ascii=False),
                    encoding="utf-8")


def write_sources(ok=True) -> None:
    (TMP / "sources.json").write_text(json.dumps([
        {"name": "FAA", "ok": ok, "lastFetchUtc": "2026-07-27T00:00Z"},
        {"name": "CAA Taiwan", "ok": True,
         "lastFetchUtc": "2026-07-27T00:00Z"},
    ]), encoding="utf-8")


def load_brief(briefing_id):
    return json.loads((TMP / "briefings" / f"{briefing_id}.json")
                      .read_text(encoding="utf-8"))


def load_index():
    return json.loads((TMP / "briefings" / "index.json")
                      .read_text(encoding="utf-8"))


def all_items(brief):
    return [it for sec in brief["sections"].values() for it in sec]


class FakeProvider:
    calls = 0

    def __init__(self, name="fake", model="fake-model", result=None,
                 error=None):
        self.name, self.model = name, model
        self.label = f"{name}:{model}"
        self._result, self._error = result, error

    def available(self):
        return True

    def draft(self, system_prompt, user_prompt, schema):
        FakeProvider.calls += 1
        if self._error:
            raise self._error
        return self._result


def install_fake_providers(providers):
    fake = types.ModuleType("providers")
    fake.build_providers = lambda: list(providers)
    sys.modules["providers"] = fake


# ── 1-6: fixed half-open windows ────────────────────────────────────────────

D = date(2026, 7, 27)
morning = get_briefing_window("morning", D)
afternoon = get_briefing_window("afternoon", D)
evening = get_briefing_window("evening", D)

check("morning window is prev-day 23:00 -> 07:00 TPE",
      morning.window_start == tpe(2026, 7, 26, 23)
      and morning.window_end == tpe(2026, 7, 27, 7))
check("afternoon window is 07:00 -> 15:00 TPE",
      afternoon.window_start == tpe(2026, 7, 27, 7)
      and afternoon.window_end == tpe(2026, 7, 27, 15))
check("evening window is 15:00 -> 23:00 TPE",
      evening.window_start == tpe(2026, 7, 27, 15)
      and evening.window_end == tpe(2026, 7, 27, 23))
check("windows are timezone-aware (+08:00)",
      morning.window_start.utcoffset() == timedelta(hours=8)
      and morning.cutoff_time.tzinfo is not None)
check("07:00:00 belongs to afternoon, not morning",
      not morning.contains(tpe(2026, 7, 27, 7))
      and afternoon.contains(tpe(2026, 7, 27, 7)))
check("15:00:00 belongs to evening, not afternoon",
      not afternoon.contains(tpe(2026, 7, 27, 15))
      and evening.contains(tpe(2026, 7, 27, 15)))
check("23:00:00 belongs to next-day morning, not evening",
      not evening.contains(tpe(2026, 7, 27, 23))
      and get_briefing_window("morning", date(2026, 7, 28))
      .contains(tpe(2026, 7, 27, 23)))
check("boundary compare works across timezones (UTC input)",
      afternoon.contains(datetime(2026, 7, 26, 23, 0,
                                  tzinfo=timezone.utc)))

# 7: a delayed run cannot move the window — it is a pure function of
# (edition, taipei_date), and the id is stable too.
w1 = get_briefing_window("morning", D)
w2 = get_briefing_window("morning", D)
check("window derived from edition+date only (delay-proof)",
      w1 == w2 and w1.briefing_id == "2026-07-27-morning")

# 8: UTC runner -> correct Taipei date at the scheduled instants.
check("23:15 UTC previous day maps to Taipei morning date",
      datetime(2026, 7, 26, 23, 15, tzinfo=timezone.utc)
      .astimezone(TPE).date() == D)
check("07:15 UTC maps to Taipei afternoon date",
      datetime(2026, 7, 27, 7, 15, tzinfo=timezone.utc)
      .astimezone(TPE).date() == D)
check("delayed evening cron after Taipei midnight keeps previous date",
      scheduled_taipei_date(
          "evening", datetime(2026, 7, 28, 16, 51,
                              tzinfo=timezone.utc)) == date(2026, 7, 28))

# 9: cron -> edition mapping, cross-checked against config and workflow.
check("cron mapping matches spec",
      CRON_TO_EDITION == {"15 23 * * *": "morning",
                          "15 7 * * *": "afternoon",
                          "15 15 * * *": "evening"})
_editions_cfg = json.loads((REPO / "config" / "briefing_editions.json")
                           .read_text(encoding="utf-8"))
check("config cron_utc agrees with CRON_TO_EDITION",
      {cfg["cron_utc"]: name for name, cfg in _editions_cfg.items()}
      == CRON_TO_EDITION)
_wf = (REPO / ".github" / "workflows" / "briefing.yml").read_text(
    encoding="utf-8")
check("workflow declares exactly the three edition crons",
      all(f'cron: "{c}"' in _wf for c in CRON_TO_EDITION)
      and _wf.count("- cron:") == 3)
check("workflow maps each schedule string explicitly",
      all(re.search(re.escape(f'"{c}")') + r'\s+echo "edition=' + e + '"',
                    _wf)
          for c, e in CRON_TO_EDITION.items()))
check("workflow supports dispatch edition+date inputs",
      "workflow_dispatch" in _wf and "edition:" in _wf and "date:" in _wf
      and "concurrency" in _wf)
check("scheduled workflow passes cron so delayed date is resolved centrally",
      'python pipeline/briefing.py --cron "${{ steps.ed.outputs.cron }}"'
      in _wf)

# 11: no now-minus-24h briefing logic anywhere in the module.
_src = (REPO / "pipeline" / "briefing.py").read_text(encoding="utf-8")
check("no 24-hour rolling-window logic in briefing.py",
      "hours=24" not in _src
      and re.search(r"now\w*\(\)\s*-\s*timedelta", _src) is None)

# ── 10: CLI dispatch (edition + date, and cron form) ─────────────────────────

reset()
write_sources(ok=True)
art_morning = make_article("a-m1", "晨間事件A", tpe(2026, 7, 27, 6, 30))
write_articles([art_morning])
check("main --edition/--date runs", briefing.main(
    ["--edition", "morning", "--date", "2026-07-27"]) == 0)
bm = load_brief("2026-07-27-morning")
check("briefing schema basics", bm["content_type"]
      == "daily_transport_briefing" and bm["edition"] == "morning"
      and bm["timezone"] == "Asia/Taipei"
      and bm["window_start"] == "2026-07-26T23:00:00+08:00"
      and bm["window_end"] == "2026-07-27T07:00:00+08:00"
      and bm["cutoff_time"] == bm["window_end"])
check("morning picked the 06:30 article",
      bm["item_count"] == 1 and all_items(bm)[0]["item_type"] == "new")
check("deterministic mode with no model recorded",
      bm["generation_mode"] == "deterministic"
      and bm["generation_model"] is None)
check("main --cron maps to edition", briefing.main(
    ["--cron", "15 7 * * *", "--date", "2026-07-27"]) == 0
    and (TMP / "briefings" / "2026-07-27-afternoon.json").exists())

# ── 12-14: only the published article store feeds briefings ─────────────────

reset()
write_sources(ok=True)
(TMP / "review.json").write_text(json.dumps({"pending": [{
    "id": "r1", "status": "manual_review",
    "zh": {"title": "覆核中的墜機事件", "summary": "不得出現"},
}]}, ensure_ascii=False), encoding="utf-8")
write_articles([make_article("a-pub", "已發布事件", tpe(2026, 7, 27, 6))])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
_txt = json.dumps(bm, ensure_ascii=False)
check("pending manual_review items never appear",
      "覆核中的墜機事件" not in _txt and bm["item_count"] == 1)
check("selection reads only data/articles (rejects can't exist there)",
      all_items(bm)[0]["article_id"] == "a-pub")
check("items carry >=1 source and verified zh headline+summary",
      all_items(bm)[0]["sources"] and all_items(bm)[0]["headline"])

# incomplete article (no source URL) is skipped, not published
reset()
write_sources(ok=True)
bad = make_article("a-bad", "無來源事件", tpe(2026, 7, 27, 6), urls=())
write_articles([bad, make_article("a-ok", "有來源事件",
                                  tpe(2026, 7, 27, 5))])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("article without source URL is skipped with a warning",
      bm["item_count"] == 1
      and any("a-bad" in w for w in bm["warnings"]))

# ── 15-18: cross-edition dedup, updates, id stability ────────────────────────

reset()
write_sources(ok=True)
base_kw = dict(cat="safety", orgs=("Delta Air Lines",), locs=("高雄小港",),
               claims=("Delta A350 landed at Kaohsiung",))
write_articles([make_article("a-ev1", "達美A350抵達小港",
                             tpe(2026, 7, 27, 6, 10), **base_kw)],
               "m.json")
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
ev_id = all_items(load_brief("2026-07-27-morning"))[0]["event_id"]

# afternoon: same facts, retitled, reprinted on a new URL -> not an update
write_articles([make_article("a-ev2", "換個標題的同一事件",
                             tpe(2026, 7, 27, 8, 5),
                             urls=("https://other-site.example/copy",),
                             **base_kw)], "a.json")
briefing.main(["--edition", "afternoon", "--date", "2026-07-27"])
ba = load_brief("2026-07-27-afternoon")
check("same event without new facts never repeats in a later edition",
      ba["item_count"] == 0)

# evening: same event with a genuinely new fact -> update item
write_articles([make_article(
    "a-ev3", "達美A350小港起飛離場", tpe(2026, 7, 27, 16, 40),
    cat="safety", orgs=("Delta Air Lines",), locs=("高雄小港",),
    claims=("Delta A350 landed at Kaohsiung",
            "Aircraft departed Kaohsiung on July 27"),
    urls=("https://example.gov/followup",))], "e.json")
briefing.main(["--edition", "evening", "--date", "2026-07-27"])
be = load_brief("2026-07-27-evening")
up = all_items(be)[0] if all_items(be) else {}
check("substantive new fact surfaces as an update item",
      be["item_count"] == 1 and up.get("item_type") == "update")
check("update binds to the original event id and lists new info",
      up.get("previous_event_id") == ev_id
      and up.get("new_information")
      == ["Aircraft departed Kaohsiung on July 27"])
check("event_id ignores edition, headline and article id",
      up.get("event_id") == ev_id)
a1 = make_article("x1", "標題甲", tpe(2026, 7, 27, 6), **base_kw)
a2 = make_article("x2", "完全不同的標題乙", tpe(2026, 7, 27, 6), **base_kw)
check("fingerprint is identical for retitled duplicates",
      event_fingerprint(a1, "aviation_incidents")
      == event_fingerprint(a2, "aviation_incidents"))
_fp_core = _src.split("core = {")[1].split("return hashlib")[0]
check("fingerprint core hashes no edition/headline/generated_at/position",
      all(bad not in _fp_core for bad in
          ("edition", "headline", "generated_at", "briefing_id", "title")))

# safety article classified into incidents with severity ordering
check("safety article lands in aviation_incidents",
      len(be["sections"]["aviation_incidents"]) == 1)

# ── 19-22: model-call discipline ─────────────────────────────────────────────

# zero candidates -> zero calls even with the intro flag on
reset()
write_sources(ok=True)
write_articles([])
FakeProvider.calls = 0
install_fake_providers([FakeProvider(
    result={"introZh": "十" * 30, "introEn": "e" * 30})])
os.environ["BRIEFING_LLM_INTRO"] = "true"
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
check("empty edition performs zero model calls", FakeProvider.calls == 0)
b_empty = load_brief("2026-07-27-morning")
check("empty edition is deterministic with empty sections",
      b_empty["generation_mode"] == "deterministic"
      and b_empty["item_count"] == 0
      and all(v == [] for v in b_empty["sections"].values()))

# items with verified summaries -> no per-item rewriting; intro is one batch
reset()
write_sources(ok=True)
write_articles([make_article(f"a-{i}", f"事件{i}",
                             tpe(2026, 7, 27, 5, i),
                             orgs=(f"Org{i}",), locs=(f"City{i}",),
                             claims=(f"claim {i}",),
                             urls=(f"https://example.gov/{i}",))
                for i in range(4)])
FakeProvider.calls = 0
install_fake_providers([FakeProvider(
    result={"introZh": "本" * 30, "introEn": "e" * 30})])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("4 items cost at most one batch call", FakeProvider.calls == 1)
check("llm_assisted mode records the real provider+model",
      bm["generation_mode"] == "llm_assisted"
      and bm["generation_model"] == {"provider": "fake",
                                     "model": "fake-model"}
      and bm["intro_zh"] == "本" * 30)
check("item headlines/summaries reused verbatim (no rewriting)",
      sorted(it["headline"] for it in all_items(bm))
      == [f"事件{i}" for i in range(4)])

# model failure -> deterministic fallback, edition never fails
reset()
write_sources(ok=True)
write_articles([make_article("a-f", "事件F", tpe(2026, 7, 27, 6))])
FakeProvider.calls = 0
install_fake_providers([FakeProvider(error=RuntimeError("boom")),
                        FakeProvider(error=RuntimeError("boom2"))])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("failed batch call is capped at BRIEFING_EXTRA_LLM_CALLS_MAX=1",
      FakeProvider.calls == 1)
check("model failure falls back to deterministic, edition still published",
      bm["status"] in ("published", "partial")
      and bm["generation_mode"] == "deterministic"
      and bm["item_count"] == 1)
del os.environ["BRIEFING_LLM_INTRO"]

# ── 23-24: empty copy vs source failure ──────────────────────────────────────

_build_src = (REPO / "pipeline" / "build.py").read_text(encoding="utf-8")
check("conservative empty-edition copy is the specified sentence",
      "截至本期資料截止時間，系統在本次查核的指定來源中，未發現符合收錄門檻的新事件。"
      in _build_src)
check("no 'nothing happened worldwide' style claims in templates",
      "全球沒有" not in _build_src and "均無異常" not in _build_src)

reset()
write_sources(ok=False)  # FAA failing
write_articles([])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("source fetch failure -> partial with a coverage warning, "
      "never 'no events'",
      bm["status"] == "partial"
      and any("coverage gap" in w for w in bm["warnings"])
      and any(not c["ok"] for c in bm["checked_sources"]))

# ── 25: failed runs never clobber a successful edition ───────────────────────

reset()
write_sources(ok=True)
write_articles([make_article("a-keep", "既有事件", tpe(2026, 7, 27, 8))])
briefing.main(["--edition", "afternoon", "--date", "2026-07-27"])
good = load_brief("2026-07-27-afternoon")
_orig_loader = briefing.load_published_articles
briefing.load_published_articles = lambda: (_ for _ in ()).throw(
    RuntimeError("disk gone"))
check("crashing re-run exits 0 (deploy of old content still possible)",
      briefing.main(["--edition", "afternoon", "--date", "2026-07-27"]) == 0)
briefing.load_published_articles = _orig_loader
check("briefing file survives the crash untouched",
      load_brief("2026-07-27-afternoon") == good)
check("index keeps the successful status for that edition",
      [r["status"] for r in load_index()["briefings"]
       if r["briefing_id"] == "2026-07-27-afternoon"] == ["published"])

briefing.load_published_articles = lambda: (_ for _ in ()).throw(
    RuntimeError("still broken"))
briefing.main(["--edition", "evening", "--date", "2026-07-27"])
briefing.load_published_articles = _orig_loader
check("a failed edition is recorded as failed without a briefing file",
      [r["status"] for r in load_index()["briefings"]
       if r["briefing_id"] == "2026-07-27-evening"] == ["failed"]
      and not (TMP / "briefings" / "2026-07-27-evening.json").exists())

# ── 26: homepage picks the latest by cutoff_time, skipping failed ────────────

import build  # noqa: E402

rows = [
    {"briefing_id": "2026-07-27-morning", "status": "published",
     "cutoff_time": "2026-07-27T07:00:00+08:00",
     "generated_at": "2026-07-27T23:59:00+08:00"},  # late regen: irrelevant
    {"briefing_id": "2026-07-27-afternoon", "status": "partial",
     "cutoff_time": "2026-07-27T15:00:00+08:00",
     "generated_at": "2026-07-27T15:18:00+08:00"},
    {"briefing_id": "2026-07-27-evening", "status": "failed",
     "cutoff_time": "2026-07-27T23:00:00+08:00",
     "generated_at": "2026-07-27T23:18:00+08:00"},
]
latest = build.latest_briefing(rows)
check("latest briefing = max cutoff_time among published/partial",
      latest["briefing_id"] == "2026-07-27-afternoon")
check("failed never becomes the latest briefing",
      build.latest_briefing([rows[2]]) is None)

# ── 27-29: no secrets, no Perplexity, no paid APIs ───────────────────────────

reset()
write_sources(ok=True)
write_articles([make_article("a-s", "事件S", tpe(2026, 7, 27, 6))])
os.environ["NVIDIA_API_KEY"] = "nvapi-TESTFAKEKEY1234567890"
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
del os.environ["NVIDIA_API_KEY"]
_out = (TMP / "briefings" / "2026-07-27-morning.json").read_text(
    encoding="utf-8")
check("briefing output contains no secrets or reasoning traces",
      "nvapi-" not in _out and "reasoning_content" not in _out
      and "<think>" not in _out)

_repo_hits = []
for path in REPO.rglob("*"):
    if (path.suffix not in (".py", ".yml", ".yaml", ".json", ".md", ".txt")
            or ".git" in path.parts or "tests" in path.parts
            or "site" in path.parts):
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for marker in ("PERPLEXITY_API_KEY", "api.perplexity.ai",
                   "NEWSAPI", "SERPAPI", "TAVILY_API", "EXA_API",
                   "customsearch.googleapis"):
        if marker in text:
            _repo_hits.append(f"{path.name}:{marker}")
check("repo adds no Perplexity/paid-search keys or endpoints",
      _repo_hits == [])
_req = (REPO / "requirements.txt").read_text(encoding="utf-8").lower()
check("requirements.txt adds no paid news/search dependency",
      all(m not in _req for m in ("newsapi", "bing", "serpapi", "tavily",
                                  "exa", "perplexity")))

# ── section classification for the expanded source mix ──────────────────────

def _art_text(text):
    a = make_article("a-cls", text, tpe(2026, 7, 27, 6))
    a["entities"]["locations"] = []
    a["zh"]["summary"] = text
    return a


check("小三通/船班 stories classify as ground_and_maritime",
      briefing.classify_section(_art_text("小三通航線多航次停航")) ==
      "ground_and_maritime")
check("台鐵 stories classify as ground_and_maritime",
      briefing.classify_section(_art_text("台鐵區間車出軌無人受傷")) ==
      "ground_and_maritime")
check("共機動態 stories are taiwan_aviation with the military flag",
      briefing.classify_section(_art_text("國防部公布中共軍機臺海周邊動態"))
      == "taiwan_aviation"
      and briefing._has_marker(
          briefing._text_blob(_art_text("中共軍機臺海周邊動態")),
          briefing._MILITARY_MARKERS))

import build as _b  # noqa: E402

_mil_item = {"headline": "共機動態", "summary": "s", "severity": "routine",
             "taiwan_priority": True, "military": True, "item_type": "new",
             "sources": [], "article_id": None,
             "source_published_at": "2026-07-27T00:00:00+08:00"}
_marks_mil = _b.brief_item_view(_mil_item, "zh", set())["marks"]
check("briefing item view renders taiwan+military marks",
      "⚔" in _marks_mil and "\U0001f1f9\U0001f1fc" in _marks_mil
      and "⚠" not in _marks_mil)
_fatal_item = dict(_mil_item, severity="fatal", taiwan_priority=False,
                   military=False)
_marks_fatal = _b.brief_item_view(_fatal_item, "zh", set())["marks"]
check("fatal items render warning+red marks",
      "⚠" in _marks_fatal and "\U0001f534" in _marks_fatal)

# ── verified-article fallback production default ─────────────────────────────

reset()
write_sources(ok=True)
write_articles([make_article("a-bul", "正式新聞作為快報回退",
                             tpe(2026, 7, 27, 6))])
del os.environ["BRIEFING_INCLUDE_ARTICLES"]
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("default mode includes verified site articles as fallback",
      bm["item_count"] == 1)

# render-time gate: hourly builds race briefing builds on Pages deploys, so
# build.py must use the same include-by-default policy.
_stale_item = {"headline": "殘留的正式新聞", "summary": "s",
               "severity": "routine", "item_type": "new", "sources": [],
               "article_id": None,
               "source_published_at": "2026-07-27T00:00:00+08:00"}
_stale = {
    "briefing_id": "2026-07-27-morning", "edition": "morning",
    "status": "published", "cutoff_time": "2026-07-27T07:00:00+08:00",
    "sections": {
        "aviation_incidents": [_stale_item,
                               dict(_stale_item, headline="AI搜尋條目",
                                    origin="grounded")],
        "taiwan_aviation": [dict(_stale_item, headline="另一則殘留")],
    },
    "intro_zh": "為合併版寫的導言",
}
os.environ.pop("BRIEFING_INCLUDE_ARTICLES", None)
_bv = _b.brief_view(_stale, "zh", _b.L["zh"], set())
check("render gate includes verified articles by default",
      _bv["total"] == 3 and _bv["intro"] == "為合併版寫的導言")
os.environ["BRIEFING_INCLUDE_ARTICLES"] = "false"
_bv2 = _b.brief_view(_stale, "zh", _b.L["zh"], set())
os.environ["BRIEFING_INCLUDE_ARTICLES"] = "true"
check("render gate: explicit false restores search-only mode",
      _bv2["total"] == 1
      and all(it["grounded"]
              for s in _bv2["sections"] for it in s["items"])
      and _bv2["intro"] == "")

# ── delayed cron, future-window guard and grounded fallback ──────────────────

reset()
write_sources(ok=True)
write_articles([make_article("a-delay", "跨午夜仍屬前日晚報",
                             tpe(2026, 7, 27, 20))])
_real_now_utc = briefing.now_utc
briefing.now_utc = lambda: datetime(2026, 7, 27, 16, 51,
                                   tzinfo=timezone.utc)
briefing.main(["--cron", "15 15 * * *"])
briefing.now_utc = _real_now_utc
check("delayed evening cron writes previous Taipei date",
      load_brief("2026-07-27-evening")["item_count"] == 1
      and not (TMP / "briefings" / "2026-07-28-evening.json").exists())

reset()
write_sources(ok=True)
briefing.now_utc = lambda: datetime(2026, 7, 27, 9, 0,
                                   tzinfo=timezone.utc)
briefing.main(["--edition", "evening", "--date", "2026-07-27"])
briefing.now_utc = _real_now_utc
check("future/incomplete window is failed without a published JSON",
      not (TMP / "briefings" / "2026-07-27-evening.json").exists()
      and [r["status"] for r in load_index()["briefings"]
           if r["briefing_id"] == "2026-07-27-evening"] == ["failed"])

reset()
write_sources(ok=True)
write_articles([make_article("a-fallback", "搜尋失敗仍有正式新聞",
                             tpe(2026, 7, 27, 6))])
import grounded as _grounded  # noqa: E402
_real_enabled = _grounded.enabled
_real_call_grounded = _grounded.call_grounded
_grounded.enabled = lambda: True
_grounded.call_grounded = lambda window: (_ for _ in ()).throw(
    RuntimeError("simulated search outage"))
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
_grounded.enabled = _real_enabled
_grounded.call_grounded = _real_call_grounded
bm = load_brief("2026-07-27-morning")
check("grounded outage keeps article fallback and marks edition partial",
      bm["status"] == "partial"
      and bm["item_count"] == 1
      and any("AI 搜尋服務暫時不穩定" in w for w in bm["warnings"]))

# ── caps ─────────────────────────────────────────────────────────────────────

reset()
write_sources(ok=True)
write_articles([make_article(f"a-cap{i}", f"容量測試{i}",
                             tpe(2026, 7, 27, 3, i),
                             orgs=(f"CapOrg{i}",), locs=(f"CapCity{i}",),
                             claims=(f"cap claim {i}",),
                             urls=(f"https://example.gov/cap{i}",))
                for i in range(9)])
briefing.main(["--edition", "morning", "--date", "2026-07-27"])
bm = load_brief("2026-07-27-morning")
check("per-section cap (6) enforced with an explicit warning",
      bm["item_count"] == 6
      and any("dropped by" in w for w in bm["warnings"]))

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
