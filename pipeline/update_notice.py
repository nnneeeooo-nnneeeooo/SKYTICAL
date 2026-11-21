"""Bilingual reader-facing updates, derived offline from the checked-in changelog.

No network, Git history or model API is required by a production build. Both
languages use the same selected source records and grouping decisions.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from model_config import OPENAI_DEFAULT_MODEL, MODEL_DISPLAY_NAMES

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


def build_notices(raw, station, *, today=None, model=OPENAI_DEFAULT_MODEL):
    today = today or datetime.now(TPE).date()
    cutoff, end = (today - timedelta(days=14)).isoformat(), today.isoformat()
    rows, seen = [], set()
    for row in raw.get("entries", []) if isinstance(raw, dict) else []:
        if not isinstance(row, dict):
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
    grouped, consumed = [], set()
    name = MODEL_DISPLAY_NAMES.get("openai:" + model, model)
    migrations = [row for row in rows if "Luna" in row["zh"] and name in row["zh"] and any(word in row["zh"] for word in ("改用", "升級"))]
    if migrations:
        row = migrations[0]
        related = [row] + [other for other in rows if "來源不足" in other["zh"] and name in other["zh"]]
        zh = f"加入新AI模型{name.replace('GPT ', 'ChatGPT ', 1)}。"
        en = f"New AI model {name.replace('GPT ', 'ChatGPT ', 1)} joins the crew."
        if all(word in row["zh"] for word in ("撰稿", "審核", "快報")):
            zh = f"加入新AI模型{name.replace('GPT ', 'ChatGPT ', 1)}，撰稿、查證、快報一併換新。"
            en = f"New AI model {name.replace('GPT ', 'ChatGPT ', 1)} joins the crew, refreshing our writing, fact-checking and briefings."
        if len(related) > 1:
            zh += "新聞資料不夠，還會繼續找來源。"
            en += " When a story needs more evidence, it keeps looking."
        grouped.append({"date": max(item["date"] for item in related), "zh": {"title": f"AI大升級，{name}接棒！", "copy": zh}, "en": {"title": f"AI upgrade: {name} joins the crew!", "copy": en}})
        consumed.update(item["commit"] for item in related)
    topics, minor = set(), []
    for row in rows:
        if row["commit"] in consumed:
            continue
        text, importance = row["zh"], (row.get("notice") or {}).get("importance")
        if importance == "minor":
            minor.append(row)
            continue
        if row["kind"] == "feature" and "短訊彙整" in text:
            if "roundups" in topics:
                continue
            topics.add("roundups")
            count = re.search(r"最多([一二三四五六七八九十\d]+)則", text)
            if count and "每則" in text and "配圖" in text and "輪播" in text:
                number = {"一": "one", "二": "two", "三": "three", "四": "four", "五": "five", "六": "six", "七": "seven", "八": "eight", "九": "nine", "十": "ten"}.get(count[1], count[1])
                grouped.append({"date": row["date"], "zh": {"title": "短訊各有配圖，滑一下就看完", "copy": f"每期最多{count[1]}則重點，各自配圖、滑動切換，快速掌握航空大小事。"}, "en": {"title": "A picture for every brief. Just swipe.", "copy": f"Up to {number} stories per roundup, each with its own image. Swipe through for a quick aviation catch-up."}})
                continue
        if "重大航空營運事件" in text and "四十八小時" in text:
            grouped.append({"date": row["date"], "zh": {"title": "大事發生，打開首頁就看得到", "copy": "全國停飛等重大消息，優先放上首頁頭條與即時快訊，重要進展一眼掌握。"}, "en": {"title": "Big news, front and center", "copy": "Major developments, including nationwide groundings, get priority in the homepage headlines and live feed."}})
        elif importance == "major" or (row["kind"] == "feature" and "配圖" not in text):
            grouped.append({"date": row["date"], "zh": {"title": re.split(r"[，；。]", text)[0], "copy": text}, "en": {"title": row["en"].split(". ")[0].rstrip("."), "copy": row["en"]}})
        else:
            minor.append(row)
    if minor:
        evidence = "".join(row["zh"] for row in minor)
        areas = [("手機", "手機閱讀", "mobile reading"), ("搜尋", "搜尋", "search"), ("配圖|真實照片", "新聞配圖", "article images"), ("IATA|機場代碼", "機場代碼標示", "airport-code labels")]
        selected = [(zh, en) for pattern, zh, en in areas if re.search(pattern, evidence)]
        zh_copy = "、".join(zh for zh, _ in selected) + "也一起調整，細節都在完整更新紀錄。" if selected else "其他使用細節也一併調整，詳見完整更新紀錄。"
        en_copy = "We’ve also refined " + ", ".join(en for _, en in selected) + ". See the full changelog for details." if selected else "We’ve refined other everyday details, too. See the full changelog for more."
        grouped.append({"date": minor[0]["date"], "zh": {"title": "日常閱讀，也更順手", "copy": zh_copy}, "en": {"title": "The everyday details, refined", "copy": en_copy}})
    grouped.sort(key=lambda item: item["date"], reverse=True)
    result = {}
    for lang, labels in UI.items():
        note = None
        if isinstance(station, dict) and station.get("enabled") is True:
            message = (station.get("messages") or {}).get(lang)
            if isinstance(message, str) and message.strip():
                email = str(station.get("contactEmail") or "")
                note = {"message": compact(message, lang), "email": email if re.fullmatch(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", email) else ""}
        result[lang] = {"ui": labels, "station": note, "items": [{"date": item["date"], "title": compact(item[lang]["title"], lang), "copy": compact(item[lang]["copy"], lang)} for item in grouped]}
    return result


@lru_cache(maxsize=1)
def notice_data():
    def read(name):
        try:
            return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return build_notices(read("changelog.json"), read("station-note.json"))
