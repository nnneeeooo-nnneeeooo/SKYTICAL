"""Tests for the proper-noun glossary enforcement in write.py (offline).

No pytest required — run from the repo root:

    py tests\\test_glossary.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-glossary-")

sys.path.insert(0, str(REPO / "pipeline"))
import write  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


def draft(zh_title, en_title, zh_body=("內文。",), en_body=("Body.",)):
    return {
        "zh": {"title": zh_title, "summary": zh_title, "body": list(zh_body)},
        "en": {"title": en_title, "summary": en_title, "body": list(en_body)},
        "flash": {"zh": zh_title[:20], "en": en_title[:40], "hot": False},
    }


GROUP = {"id": "g1", "items": [{
    "title": "Boeing 737 MAX 7 nears FAA approval for Southwest Airlines",
    "summary": "Simple Flying reports the final certification steps.",
    "source": "Simple Flying", "url": "https://example.com/a"}]}

# ── matching + prompt injection ──────────────────────────────────────────────

pairs, keeps = write.glossary_matches(
    "Southwest Airlines and Simple Flying and Airbus", include_soft=True)
check("glossary matches translate pairs and keep-names",
      ("Southwest Airlines", "西南航空") in pairs
      and ("Airbus", "空中巴士") in pairs and "Simple Flying" in keeps)
hard_pairs, _ = write.glossary_matches("Airbus and Boeing and Reuters")
check("manufacturers/agencies are soft (prompt-only, never draft-gating)",
      hard_pairs == [])

block = write.glossary_prompt_block(GROUP)
check("prompt block lists the mandatory renderings",
      "西南航空" in block and "Simple Flying" in block
      and "MANDATORY NAME GLOSSARY" in block)
check("prompt block appears inside the group prompt",
      "MANDATORY NAME GLOSSARY" in write.group_prompt(GROUP))
check("no matches -> no glossary block",
      write.glossary_prompt_block(
          {"items": [{"title": "民航局公告離島加班機", "summary": ""}]}) == "")

# ── the machine gate (the two real failures from 2026-07-27) ────────────────

bad_sw = draft("南威航空737 MAX 7即將獲FAA批准",
               "Boeing 737 MAX 7 nears FAA approval for Southwest Airlines")
check("coined 南威航空 is rejected",
      write.glossary_problem(bad_sw, GROUP) is not None
      and "西南航空" in write.glossary_problem(bad_sw, GROUP))

good_sw = draft("西南航空737 MAX 7即將獲FAA批准",
                "Boeing 737 MAX 7 nears FAA approval for Southwest Airlines")
check("canonical 西南航空 passes", write.glossary_problem(good_sw, GROUP) is None)

kept_en = draft("Southwest Airlines 737 MAX 7 即將獲FAA批准",
                "Boeing 737 MAX 7 nears FAA approval for Southwest Airlines")
check("keeping the English name verbatim also passes",
      write.glossary_problem(kept_en, GROUP) is None)

bad_sf = draft("簡單飛行發布達美空服員薪資分析",
               "Simple Flying publishes Delta flight attendant pay analysis")
check("coined 簡單飛行 is rejected (brand must stay English)",
      write.glossary_problem(bad_sf, GROUP) is not None)

good_sf = draft("Simple Flying 發布達美航空空服員薪資分析",
                "Simple Flying publishes Delta Air Lines pay analysis")
check("verbatim Simple Flying + 達美航空 passes",
      write.glossary_problem(good_sf, GROUP) is None)

bad_delta = draft("Simple Flying 發布德爾塔航空空服員薪資分析",
                  "Simple Flying publishes Delta Air Lines pay analysis")
check("non-Taiwan rendering 德爾塔航空 is rejected",
      write.glossary_problem(bad_delta, GROUP) is not None)

unrelated = draft("民航局公布中秋加班機", "CAA Taiwan announces extra flights")
check("names absent from the draft's en text are not enforced",
      write.glossary_problem(unrelated, GROUP) is None)

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
