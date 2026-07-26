"""pla_series.py — PLA-activity time series + comparison context (擴寫).

Owner direction (2026-07-27): recurring statistical stories (the daily
國防部共機艦動態) should read like a real writer's work - today's numbers
COMPARED against history - without ever letting the model "remember"
numbers on its own. The pipeline therefore:

1. deterministically extracts the day's counts (共機 N 架次 / 共艦 M 艘 /
   公務船 K 艘 / 中線 note) from the source material with regexes - no
   model in the loop - and records them in data/pla_activity.json;
2. renders the history (previous day, 7/30-day averages, 30-day peak,
   same day last month) as an extra <SOURCE> item labeled 「AVWIRE 資料庫」,
   so every comparison the model writes is quote-verifiable against
   material it was actually shown, exactly like any other claim.

The model is told to attribute comparisons to 本站統計紀錄 and may use
only the numbers shown; with too little history the block says so and the
article simply stays a factual daily report.
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    DATA_DIR,
    load_json,
    parse_iso,
    save_json,
)

SERIES_PATH = DATA_DIR / "pla_activity.json"
KEEP_DAYS = 400
DB_SOURCE_NAME = "AVWIRE 資料庫"

# Both phrasing orders appear in the wild:
# 「偵獲中共軍機4架次、軍艦7艘及公務船3艘」 (noun first)
# 「偵獲7艘共艦、3艘公務船及4架次共機」   (number first)
# number-first patterns are tried FIRST: in 「7艘共艦、3艘公務船」 the
# noun-first pattern would leap across the 頓號 and steal 公務船's count.
_PATTERNS = {
    "aircraft": (re.compile(r"(\d+)\s*架次(?:之)?(?:中共軍機|共機|軍機)"),
                 re.compile(r"(?:中共軍機|共機|軍機)\D{0,4}(\d+)\s*架次")),
    "ships": (re.compile(r"(\d+)\s*艘(?:中共)?(?:共艦|軍艦)"),
              re.compile(r"(?:中共軍艦|共艦|軍艦)\D{0,4}(\d+)\s*艘")),
    "official": (re.compile(r"(\d+)\s*艘公務船"),
                 re.compile(r"公務船\D{0,4}(\d+)\s*艘")),
}


def extract_stats(text: str):
    """Day counts from official wording, or None when it isn't a PLA
    activity report (needs at least aircraft AND ships)."""
    text = str(text or "")
    out = {}
    for key, patterns in _PATTERNS.items():
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                out[key] = int(match.group(1))
                break
    if "aircraft" not in out or "ships" not in out:
        return None
    if re.search(r"[無未]\D{0,10}逾越", text):
        out["medianNote"] = "未逾越海峽中線"
    elif "逾越" in text and "中線" in text:
        out["medianNote"] = "有逾越中線相關敘述"
    return out


def _load() -> dict:
    raw = load_json(SERIES_PATH, {})
    days = raw.get("days")
    return {"days": days if isinstance(days, dict) else {}}


def record(day_iso: str, stats: dict) -> bool:
    """Idempotently store one day's counts; True when the file changed."""
    series = _load()
    entry = {k: stats[k] for k in ("aircraft", "ships", "official",
                                   "medianNote") if k in stats}
    if series["days"].get(day_iso) == entry:
        return False
    series["days"][day_iso] = entry
    if len(series["days"]) > KEEP_DAYS:
        for key in sorted(series["days"])[:-KEEP_DAYS]:
            del series["days"][key]
    save_json(SERIES_PATH, series)
    return True


def _avg(values):
    return round(sum(values) / len(values), 1) if values else None


def context_block(day_iso: str) -> str:
    """zh statistics lines from OUR records, excluding the current day."""
    series = _load()
    try:
        today = date.fromisoformat(day_iso)
    except ValueError:
        return ""
    rows = []
    for key, entry in series["days"].items():
        if key >= day_iso:
            continue
        try:
            rows.append((date.fromisoformat(key), entry))
        except ValueError:
            continue
    rows.sort()
    lines = ["以下為本站資料庫（AVWIRE 依國防部歷日公開統計自行記錄）之歷史數據，"
             "僅供比較，引用時請標明為本站統計紀錄："]
    if not rows:
        lines.append(f"資料庫自 {day_iso} 起開始記錄，尚無更早的歷史數據可供比較。")
        return "\n".join(lines)
    prev_day, prev = rows[-1]
    lines.append(
        f"前一次紀錄（{prev_day.month} 月 {prev_day.day} 日）：共機 "
        f"{prev.get('aircraft', '—')} 架次、共艦 {prev.get('ships', '—')} 艘、"
        f"公務船 {prev.get('official', '—')} 艘")
    for window in (7, 30):
        recent = [e for d, e in rows if d >= today - timedelta(days=window)]
        aircraft = _avg([e["aircraft"] for e in recent if "aircraft" in e])
        ships = _avg([e["ships"] for e in recent if "ships" in e])
        if aircraft is not None and len(recent) >= 2:
            lines.append(f"近 {window} 日（共 {len(recent)} 筆紀錄）平均：共機 "
                         f"{aircraft} 架次/日、共艦 {ships} 艘/日")
    month = [(d, e) for d, e in rows
             if d >= today - timedelta(days=30) and "aircraft" in e]
    if month:
        peak_day, peak = max(month, key=lambda pair: pair[1]["aircraft"])
        lines.append(f"近 30 日單日最高：共機 {peak['aircraft']} 架次"
                     f"（{peak_day.month} 月 {peak_day.day} 日）")
    last_month = today - timedelta(days=30)
    lm = series["days"].get(last_month.isoformat())
    if lm:
        lines.append(f"上月同期（{last_month.month} 月 {last_month.day} 日）："
                     f"共機 {lm.get('aircraft', '—')} 架次、共艦 "
                     f"{lm.get('ships', '—')} 艘")
    return "\n".join(lines)


def _group_text(group: dict) -> str:
    return " ".join(
        f"{item.get('title') or ''} {item.get('summary') or ''} "
        f"{item.get('fulltext') or ''}"
        for item in group.get("items") or [])


def _group_day(group: dict, now) -> str:
    for item in group.get("items") or []:
        raw = item.get("publishedUtc")
        if raw:
            try:
                return parse_iso(str(raw)).date().isoformat()
            except ValueError:
                continue
    return now.date().isoformat()


def enrich_groups(groups: list, now) -> int:
    """Record stats + attach the database context item to PLA groups."""
    enriched = 0
    for group in groups or []:
        items = group.get("items") or []
        if any(item.get("dbContext") for item in items):
            continue
        stats = extract_stats(_group_text(group))
        if stats is None:
            continue
        day_iso = _group_day(group, now)
        record(day_iso, stats)
        block = context_block(day_iso)
        if not block:
            continue
        items.append({
            "title": "本站資料庫 — 共機艦動態歷史統計",
            "summary": block,
            "source": DB_SOURCE_NAME,
            "dbContext": True,
        })
        group["items"] = items
        enriched += 1
        print(f"pla_series: group {group.get('id')} enriched with database "
              f"context ({day_iso}: {stats.get('aircraft')}架次/"
              f"{stats.get('ships')}艘)")
    return enriched
