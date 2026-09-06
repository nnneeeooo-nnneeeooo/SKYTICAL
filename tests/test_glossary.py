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

GATWICK_GROUP = {"id": "gatwick", "items": [{
    "title": "London Gatwick Airport Loses All Running Water",
    "summary": "Gatwick Airport terminal services were affected.",
    "source": "Simple Flying", "url": "https://example.com/gatwick"}]}

AIRLINE_BRAND_GROUP = {"id": "brands", "items": [{
    "title": "STARLUX Airlines expands while IndiGo names a CEO",
    "summary": "STARLUX Airlines and IndiGo announced company updates.",
    "source": "AeroTime", "url": "https://example.com/brands"}]}

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
check("system prompt bans guessed and non-Taiwan proper-name renderings",
      "Never invent a phonetic rendering" in write.SYSTEM_PROMPT
      and "Hong Kong / mainland China rendering" in write.SYSTEM_PROMPT
      and "keep the complete English proper name" in write.SYSTEM_PROMPT)
check("no matches -> no glossary block",
      write.glossary_prompt_block(
          {"items": [{"title": "民航局公告離島加班機", "summary": ""}]}) == "")
gatwick_block = write.glossary_prompt_block(GATWICK_GROUP)
check("Gatwick prompt requires Taiwan rendering and bans the wrong one",
      "蓋特威克機場" in gatwick_block and "格域機場" in gatwick_block
      and "NEVER" in gatwick_block)

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

# Retaining the English name must not mask an invented Chinese translation.
for wrong in ("簡易飛行", "簡單飛行", "简易飞行", "简单飞行"):
    check(f"prompt explicitly forbids {wrong}",
          f"「{wrong}」" in block and "NEVER" in block)
    for surface in ("title", "summary", "body", "flash"):
        bad = draft("航線調整", "Route changes")
        text = f"據{wrong}（Simple Flying）報導，航線將調整。"
        if surface == "flash":
            bad["flash"]["zh"] = text
        else:
            bad["zh"][surface] = [text] if surface == "body" else text
        problem = write.glossary_problem(bad, GROUP)
        check(f"source-only brand rejects {wrong} with English in {surface}",
              problem is not None and "forbidden rendering" in problem)

sf_body = draft("航線調整", "Route changes",
                zh_body=("據 Simple Flying 報導，航線將調整。",),
                en_body=("Simple Flying reports route changes.",))
check("English-only attribution in body passes",
      write.glossary_problem(sf_body, GROUP) is None)

bad_delta = draft("Simple Flying 發布德爾塔航空空服員薪資分析",
                  "Simple Flying publishes Delta Air Lines pay analysis")
check("non-Taiwan rendering 德爾塔航空 is rejected",
      write.glossary_problem(bad_delta, GROUP) is not None)

unrelated = draft("民航局公布中秋加班機", "CAA Taiwan announces extra flights")
check("names absent from the draft's en text are not enforced",
      write.glossary_problem(unrelated, GROUP) is None)

bad_gatwick = draft("倫敦格域機場停水影響旅客服務",
                    "Gatwick Airport loses its running water")
check("Hong Kong rendering 格域機場 is rejected",
      "forbidden rendering" in
      write.glossary_problem(bad_gatwick, GATWICK_GROUP))

mixed_gatwick = draft("蓋特威克機場停水，格域機場旅客受影響",
                      "Gatwick Airport loses its running water")
check("a correct occurrence cannot hide another forbidden rendering",
      write.glossary_problem(mixed_gatwick, GATWICK_GROUP) is not None)

good_gatwick = draft("倫敦蓋特威克機場停水影響旅客服務",
                     "Gatwick Airport loses its running water")
check("Taiwan rendering 蓋特威克機場 passes",
      write.glossary_problem(good_gatwick, GATWICK_GROUP) is None)

bad_starlux = draft(
    "星達航空開通首條歐洲航線",
    "STARLUX Airlines launches its first European route")
check("coined 星達航空 is rejected",
      write.glossary_problem(bad_starlux, AIRLINE_BRAND_GROUP) is not None)

good_starlux = draft(
    "星宇航空開通首條歐洲航線",
    "STARLUX Airlines launches its first European route")
check("official 星宇航空 brand passes",
      write.glossary_problem(good_starlux, AIRLINE_BRAND_GROUP) is None)

bad_indigo = draft(
    "印地高宣布新任執行長",
    "IndiGo announces its new chief executive")
check("coined 印地高 is rejected",
      write.glossary_problem(bad_indigo, AIRLINE_BRAND_GROUP) is not None)

good_indigo = draft(
    "IndiGo（印度靛藍航空）宣布新任執行長",
    "IndiGo announces its new chief executive")
check("IndiGo with Taiwan explanatory name passes",
      write.glossary_problem(good_indigo, AIRLINE_BRAND_GROUP) is None)

english_gatwick = draft("倫敦 Gatwick Airport 停水影響旅客服務",
                        "Gatwick Airport loses its running water")
check("keeping Gatwick Airport in English passes",
      write.glossary_problem(english_gatwick, GATWICK_GROUP) is None)

omitted_en_gatwick = draft("格域機場停水影響旅客服務",
                           "London airport loses its running water")
check("source material still activates the forbidden rendering gate",
      write.glossary_problem(omitted_en_gatwick, GATWICK_GROUP) is not None)

# ── fabrication tripwire (the Delta-pay body invention, 2026-07-27) ─────────

THIN_GROUP = {"id": "g2", "items": [{
    "title": "How Much A Delta Flight Attendant Earns Before Door Close",
    "summary": "The first airline to solve a long term grievance.",
    "source": "Simple Flying", "url": "https://example.com/b"}]}

fab = draft("Simple Flying 發布達美航空空服員薪資報導",
            "Simple Flying publishes Delta Air Lines pay report")
fab["zh"]["body"] = ["文章詳細分析薪資結構，並引述公司內部文件說明實施細節。"]
check("thin material + body describing unseen article contents rejected",
      write.fabrication_problem(fab, THIN_GROUP) is not None)

ok = draft("Simple Flying 發布達美航空空服員薪資報導",
           "Simple Flying publishes Delta Air Lines pay report")
ok["zh"]["body"] = ["該報導摘要指出，達美航空成為首家解決此一長期薪資糾紛的航空公司。"]
check("supported-only body passes the tripwire",
      write.fabrication_problem(ok, THIN_GROUP) is None)

rich_group = {"id": "g3", "items": [dict(THIN_GROUP["items"][0],
                                         fulltext="long official text " * 30)]}
check("groups with full text are exempt (long bodies may describe quotes)",
      write.fabrication_problem(fab, rich_group) is None)

zh_material_group = {"id": "g4", "items": [{
    "title": "民航局引述調查報告說明事件經過", "summary": "官方說明。",
    "source": "CNA", "url": "https://example.com/c"}]}
quoted = draft("民航局引述調查報告", "CAA cites the investigation report")
quoted["zh"]["body"] = ["民航局引述調查報告說明事件經過。"]
check("phrases present in the material itself stay allowed",
      write.fabrication_problem(quoted, zh_material_group) is None)

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
