"""Tests for pipeline/pla_series.py (共機艦動態 comparison context).

No pytest required — run from the repo root:

    py tests\\test_pla.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-pla-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)

sys.path.insert(0, str(REPO / "pipeline"))
import pla_series  # noqa: E402
import write  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


CNA_TEXT = ("國防部今天發布共機艦動態，統計自昨天上午6時起至今天上午6時止。"
            "偵獲7艘共艦、3艘公務船及4架次共機，持續在台海周邊活動。"
            "期間並無共機逾越台灣海峽中線。")
MND_TEXT = "偵獲中共軍機12架次、軍艦9艘及公務船2艘，其中5架次逾越海峽中線。"

# ── extraction (both real-world word orders) ────────────────────────────────

s1 = pla_series.extract_stats(CNA_TEXT)
check("number-first CNA wording extracts 4/7/3 + no-crossing note",
      s1 == {"aircraft": 4, "ships": 7, "official": 3,
             "medianNote": "未逾越海峽中線"})
s2 = pla_series.extract_stats(MND_TEXT)
check("noun-first MND wording extracts 12/9/2 + crossing note",
      s2 and s2["aircraft"] == 12 and s2["ships"] == 9
      and s2["official"] == 2 and s2["medianNote"] == "有逾越中線相關敘述")
check("non-PLA text returns None",
      pla_series.extract_stats("民航局公布中秋加班機 1340 架次") is None)

# ── series persistence ───────────────────────────────────────────────────────

check("first record writes", pla_series.record("2026-07-27", s1) is True)
check("identical record is idempotent",
      pla_series.record("2026-07-27", s1) is False)

# seed a month of history for the context block
for i, (day, n_air, n_ship) in enumerate([
        ("2026-06-27", 20, 8), ("2026-07-20", 6, 5), ("2026-07-21", 9, 6),
        ("2026-07-22", 30, 12), ("2026-07-23", 8, 7), ("2026-07-24", 10, 6),
        ("2026-07-25", 7, 5), ("2026-07-26", 5, 7)]):
    pla_series.record(day, {"aircraft": n_air, "ships": n_ship,
                            "official": 3})

block = pla_series.context_block("2026-07-27")
check("context cites the previous record",
      "前一次紀錄（7 月 26 日）" in block and "共機 5 架次" in block)
check("context carries 7-day and 30-day averages",
      "近 7 日" in block and "近 30 日" in block)
check("context names the 30-day peak with its date",
      "共機 30 架次（7 月 22 日）" in block)
check("context includes same-day-last-month when recorded",
      "上月同期（6 月 27 日）" in block and "共機 20 架次" in block)
check("context excludes the current day from history",
      "7 月 27 日）" not in block.replace("上月同期", ""))
check("empty history says so instead of inventing",
      "尚無更早" in pla_series.context_block("2020-01-01"))

# ── group enrichment + quote verifiability ──────────────────────────────────

NOW = datetime(2026, 7, 27, 0, 30, tzinfo=timezone.utc)
group = {"id": "g1", "items": [{
    "title": "國防部公布共機艦動態", "summary": CNA_TEXT,
    "url": "https://www.cna.com.tw/x", "source": "CNA",
    "publishedUtc": "2026-07-27T00:10Z"}]}
n = pla_series.enrich_groups([group], NOW)
check("PLA group gains the database context item",
      n == 1 and group["items"][-1]["source"] == "AVWIRE 資料庫"
      and "近 30 日" in group["items"][-1]["summary"])
check("re-enrichment is skipped",
      pla_series.enrich_groups([group], NOW) == 0)
check("non-PLA groups untouched",
      pla_series.enrich_groups([{"id": "g2", "items": [{
          "title": "航線新聞", "summary": "航空公司開新航線"}]}], NOW) == 0)

quote_line = "近 30 日單日最高：共機 30 架次（7 月 22 日）"
draft = {"facts": [{"factId": "F1", "claim": "30-day peak was 30 sorties",
                    "sourceQuote": quote_line}]}
check("comparison claims quoting the database block machine-verify",
      len(write.verify_facts(draft, group, "test")) == 1)
check("database item is never a footer source (no url)",
      write.build_sources(group["items"]) and all(
          "AVWIRE" not in s["name"]
          for s in write.build_sources(group["items"])))

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
