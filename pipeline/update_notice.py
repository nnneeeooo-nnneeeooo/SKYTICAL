"""Bilingual reader-facing updates, derived offline from the checked-in changelog.

No network, Git history or model API is required by a production build. Both
languages use the same source records explicitly marked as major.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPE = timezone(timedelta(hours=8))
SHA = re.compile(r"[0-9a-f]{40}\Z")
UI = {
    "zh": {"title": "SKYTICAL近期更新", "subtitle": "一起看看新變化", "close": "關閉更新通知", "replay": "重播翼標動畫", "stationTitle": "站長留言", "photoAlt": "neo的生活自拍", "photoCaption": "neo生活碎片", "emailLabel": "先行來信", "history": "完整更新紀錄", "continue": "繼續閱讀"},
    "en": {"title": "SKYTICAL updates", "subtitle": "Let’s see what’s new", "close": "Close site updates", "replay": "Replay wing animation", "stationTitle": "A note from neo", "photoAlt": "A selfie of neo", "photoCaption": "neo’s life lately", "emailLabel": "email me", "history": "Full changelog", "continue": "Keep reading"},
}


def compact(text, lang):
    if lang == "zh":
        text = re.sub(r"(?<=[\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60]) +| +(?=[\u2e80-\u9fff\uf900-\ufaff\uff01-\uff60])", "", text)
    return re.sub(r" {2,}", " ", text).strip()


def build_notices(raw, station, *, today=None):
    today = today or datetime.now(TPE).date()
    cutoff, end = (today - timedelta(days=14)).isoformat(), today.isoformat()
    rows, seen = [], set()
    for row in raw.get("entries", []) if isinstance(raw, dict) else []:
        if not isinstance(row, dict):
            continue
        notice = row.get("notice")
        if not isinstance(notice, dict) or notice.get("importance") != "major":
            continue
        sha, day = str(row.get("commit") or ""), str(row.get("date") or "")
        if not SHA.fullmatch(sha) or sha in seen or not cutoff <= day <= end:
            continue
        if not all(isinstance(row.get(lang), str) and row[lang].strip() for lang in UI):
            continue
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            continue
        seen.add(sha)
        rows.append(row)
    rows.sort(key=lambda row: row["date"], reverse=True)
    result = {}
    for lang, labels in UI.items():
        note = None
        if isinstance(station, dict) and station.get("enabled") is True:
            message = (station.get("messages") or {}).get(lang)
            if isinstance(message, str) and message.strip():
                email = str(station.get("contactEmail") or "")
                note = {"message": compact(message, lang), "email": email if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email) else ""}
        items = []
        for row in rows:
            copy = row[lang]
            title = re.split(r"[，；。]", copy)[0] if lang == "zh" else copy.split(". ")[0].rstrip(".")
            items.append({"date": row["date"], "title": compact(title, lang),
                          "copy": compact(copy, lang)})
        result[lang] = {"ui": labels, "station": note, "items": items}
    return result


@lru_cache(maxsize=1)
def notice_data():
    def read(name):
        try:
            return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return build_notices(read("changelog.json"), read("station-note.json"))
