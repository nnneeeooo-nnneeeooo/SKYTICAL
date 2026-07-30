Exit code: 0
Wall time: 0.3 seconds
Total output lines: 2231
Output:
"""build.py — render the AVWIRE static site from data/ JSON (see CONTRACTS.md).

Reads (all optional, degrades gracefully): data/articles/*.json, flashes.json,
incidents.json, sources.json, stats.json. Writes the site/ tree per
CONTRACTS.md: zh at /, en under /en/, one page per article ever published,
incidents / sources / methodology / changelog pages, copied assets, 404.html
and .nojekyll.
A single bad input never crashes the build: bad entries are skipped with a
one-line log to stdout and the script exits 0.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import time
import math
from datetime import timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ARTICLES_DIR,
    BASE_PATH,
    DATA_DIR,
    HOME_FEED_LIMIT,
    MAX_FLASHES,
    RAW_DIR,
    SITE_DIR,
    SITE_ORIGIN,
    SOURCES,
    STATIC_DIR,
    TEMPLATES_DIR,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    story_category,
)
from model_config import (
    DEFAULT_PROVIDER_ORDER,
    MODEL_DISPLAY_NAMES,
    MODEL_ORDER,
)

# Asia/Taipei via zoneinfo where tz data exists (Linux CI); the zone has had a
# fixed +08:00 offset with no DST since 1980, so a static fallback is exact.
try:
    from zoneinfo import ZoneInfo

    TPE = ZoneInfo("Asia/Taipei")
except Exception:  # pragma: no cover - Windows without the tzdata package
    TPE = timezone(timedelta(hours=8), "UTC+8")

_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

# ── i18n — ported verbatim from the design file (L, CATS, SEV, ST, KIND), ────
# plus the handful of production-only keys at the end of each block.
L = {
    "zh": {
        "brandZh": "航空快訊", "live": "LIVE 快訊", "updateBadge": "每小時自動更新",
        "flash": "即時快訊", "sourceStatus": "來源狀態",
        "latest": "最新新聞", "topStory": "頭條", "mainSource": "主要來源",
        "briefLabel": "短訊",
        "readMore": "閱讀全文 →", "back": "← 返回首頁",
        "heroImg": "[ 頭條照片 — 由來源圖庫自動帶入，灰階顯示 ]",
        "today": "今日全球數據", "statFlights": "目前追蹤航班", "statDelay": "全球延誤率",
        "statSerious": "本週嚴重事件", "statNotam": "生效中 NOTAM",
        "otp": "準點率排行 · 7月", "fleet": "機隊與訂單追蹤", "fleetDeliv": "2026 上半年交付",
        "fleetBacklog": "積壓訂單", "fleetOrders": "本月新訂單",
        "delays": "今日延誤熱點機場", "autoCompiled": "自動彙整",
        "refreshNote": "本文隨來源每小時更新", "sourcesBox": "資料來源 Sources",
        "genNote": "本文由自動化系統彙整生成，內容以原始來源為準",
        "genNotePunct": "。",
        "photoKind": {"airframe_photo": "同機資料照片",
                      "file_photo": "資料照片（非事件現場照片）"},
        "photoSource": "照片來源",
        "incKicker": "Incident Database", "incTitle": "事故資料庫",
        "incSub": "自動彙整全球民航事故與事件，資料來自各國調查機關與專業追報來源，每小時更新。",
        "incCountLabel": "筆紀錄",
        "incNote": "* 分級依 ICAO Annex 13：事故（Accident）、嚴重事件（Serious incident）、事件（Incident）。",
        "thDate": "日期", "thSev": "等級", "thType": "機型", "thOp": "營運人",
        "thPhase": "飛行階段", "thLoc": "地點", "thDesc": "摘要", "thStatus": "狀態", "thSrc": "來源",
        "srcKicker": "Data Sources", "srcTitle": "資料來源",
        "srcSub": "全站僅使用公開且可溯源的官方與權威資訊來源。每小時自動抓取一次，抓取狀態即時顯示於首頁側欄。",
        "srcNote": "* 所有來源皆標註於各篇文末；轉載內容僅做事實彙整，原文著作權屬原單位。",
        "thName": "來源", "thKind": "類型", "thCover": "涵蓋範圍", "thFmt": "格式",
        "thFreq": "頻率", "thLast": "最近抓取", "thState": "狀態",
        "aboutKicker": "Methodology", "aboutTitle": "方法論",
        "changeKicker": "Site Changelog", "changeTitle": "網站更新紀錄",
        "changeSub": "依 GitHub 主分支提交紀錄整理，涵蓋 AVWIRE 建站至最近一次網站功能變更。",
        "changeNotice": "每小時新聞、每日快報與航機狀態等自動資料更新不列入，避免機器提交淹沒真正的網站變更。",
        "changeCount": "筆網站變更", "changeStart": "紀錄起點",
        "changeLatest": "更新至", "changeSource": "查看完整 GitHub 提交紀錄",
        "changeCommit": "提交",
        "changeKinds": {
            "feature": "功能", "fix": "修正", "system": "系統",
            "editorial": "編輯", "design": "介面",
        },
        "footerAbout": "全自動航空新聞聚合站。GitHub Actions 每小時抓取各可信來源，自動撰寫並發布，每篇文末標註原始出處。本頁為設計原型，內容為示意樣本。",
        "footerSources": "資料來源 Data Sources",
        "footerChangelog": "網站更新紀錄",
        "nav": ["最新", "快報", "航班雷達", "事故資料庫", "來源", "方法論"],
        "cats": ["全部", "事故", "法規", "商業", "營運", "軍事"],
        "radarKicker": "Taiwan Flight Radar",
        "radarTitle": "台灣民航雷達",
        "radarSub": "公開 ADS-B 即時觀測圖，顯示台灣周邊民航機的 ICAO／IATA 航班呼號、航線、機型、高度、速度與航向。",
        "radarSearch": "搜尋 ICAO／IATA 呼號、航線、航空公司或機型",
        "radarCallsignFormat": "呼號顯示",
        "radarAirborne": "僅顯示飛行中",
        "radarRefresh": "立即更新",
        "radarLoading": "正在取得最新 ADS-B 觀測資料…",
        "radarMapLabel": "台灣周邊民航即時觀測地圖",
        "radarList": "目前航機",
        "radarNotice": "本頁不是航管雷達，資料可能延遲、缺漏或錯誤，不得用於導航、飛航操作或緊急判斷。航班呼號不一定等同旅客票面班號。",
        "radarPrivacy": "為保障安全與隱私，來源標記為軍事、PIA、LADD、緊急狀態及位置過期的資料不會顯示。",
        "radarSource": "航機位置：Airplanes.live 公開社群 ADS-B；航班代碼與航線：ADSBdb；地圖：OpenStreetMap。",
        # daily briefings
        "brKicker": "Daily Briefing", "brIndexTitle": "快報",
        "brIndexSub": "每日三次（臺北時間 07:15／15:15／23:15）的條列式全球航空與交通要聞快報，以本站已查證新聞為基礎，並由具搜尋能力的模型補充彙整（Beta）。",
        "brLatest": "最新快報", "brWindow": "資料範圍", "brCutoff": "資料截止",
        "brGenerated": "系統整理完成", "brTo": "至",
        "brEmpty": "截至本期資料截止時間，系統在本次查核的指定來源中，未發現符合收錄門檻的新事件。",
        "brPartial": "本期部分來源資料未能完整取得，內容可能不完整；來源擷取失敗不代表沒有新事件。",
        "brChecked": "📡 本期查核來源", "brWarnings": "資料覆蓋提示",
        "brUpdate": "更新", "brItems": "則",
        "brNoItems": "本期查核來源中，此分類無新增符合收錄門檻的事件通報",
        "brModeDet": "程式化組裝（未使用模型）", "brModeLlm": "模型輔助導言",
        "brBeta": "BETA", "brAiTag": "AI 搜尋",
        "brBetaNote": "Beta 功能：本快報部分條目由具搜尋能力的模型輔助彙整"
                      "（標示「AI 搜尋」者），引用連結僅取自檢索實際回傳的來源；"
                      "功能持續最佳化中，內容以各條目之原始來源為準。",
        "brSecs": ["🚨 飛安事件與緊急狀況", "🇹🇼 台灣航空動態（民航＋軍航）",
                   "🌐 國際航空產業動態", "🚄 地面與海運交通"],
        "brSevs": {"fatal": "致命", "serious": "嚴重",
                   "significant": "重要", "routine": "一般"},
        "sevs": ["全部", "事故", "嚴重事件", "事件"],
        "themeOpts": ["亮", "暗"],
        # production-only keys (not in the design dictionary)
        "siteName": "AVWIRE 航空快訊",
        "siteDesc": "全自動航空新聞聚合站：每小時抓取 FAA、ICAO、IATA、Reuters 等可信來源，自動撰寫雙語新聞並於文末標註原始出處。",
        "awaiting": "等待首次管線執行",
        "lastBuild": "最後建置",
        "aggNote": "純聚合模式：顯示來源原文標題，點擊前往原始報導",
    },
    "en": {
        "brandZh": "Aviation Wire", "live": "LIVE WIRE", "updateBadge": "Auto-updates hourly",
        "flash": "Live flash", "sourceStatus": "Source status",
        "latest": "Latest news", "topStory": "Top story", "mainSource": "Primary source",
        "briefLabel": "Brief",
        "readMore": "Read more →", "back": "← Back to front page",
        "heroImg": "[ Lead photo — pulled from source library, grayscale ]",
        "today": "Global today", "statFlights": "Flights tracked now", "statDelay": "Global delay rate",
        "statSerious": "Serious events this week", "statNotam": "Active NOTAMs",
        "otp": "On-time ranking · Jul", "fleet": "Fleet & orders", "fleetDeliv": "H1 2026 deliveries",
        "fleetBacklog": "Backlog", "fleetOrders": "New orders this month",
        "delays": "Delay hotspots today", "autoCompiled": "Auto-compiled",
        "refreshNote": "Refreshes hourly with sources", "sourcesBox": "Sources",
        "genNote": "This article was compiled automatically; the original sources prevail",
        "genNotePunct": ".",
        "photoKind": {"airframe_photo": "File photo of this airframe",
                      "file_photo": "File photo (not from this event)"},
        "photoSource": "Photo source",
        "incKicker": "Incident Database", "incTitle": "Incident database",
        "incSub": "Automatically aggregated civil-aviation accidents and incidents, from state investigators and specialist trackers. Updated hourly.",
        "incCountLabel": "records",
        "incNote": "* Classes per ICAO Annex 13: Accident, Serious incident, Incident.",
        "thDate": "Date", "thSev": "Class", "thType": "Aircraft", "thOp": "Operator",
        "thPhase": "Phase", "thLoc": "Location", "thDesc": "Summary", "thStatus": "Status", "thSrc": "Sources",
        "srcKicker": "Data Sources", "srcTitle": "Sources",
        "srcSub": "Public, traceable official and authoritative sources only. Fetched hourly; live fetch status shows on the front page rail.",
        "srcNote": "* Every article credits its sources; content is factual aggregation and copyright stays with the originators.",
        "thName": "Source", "thKind": "Kind", "thCover": "Coverage", "thFmt": "Format",
        "thFreq": "Interval", "thLast": "Last fetch", "thState": "Status",
        "aboutKicker": "Methodology", "aboutTitle": "Methodology",
        "changeKicker": "Site Changelog", "changeTitle": "Site changelog",
        "changeSub": "Compiled from the GitHub main-branch history, covering AVWIRE from its creation through the latest site change.",
        "changeNotice": "Automated hourly news, daily briefing and flight-state data commits are omitted so operational refreshes do not bury real site changes.",
        "changeCount": "site changes", "changeStart": "History starts",
        "changeLatest": "Updated through",
        "changeSource": "View the complete GitHub commit history",
        "changeCommit": "commit",
        "changeKinds": {
            "feature": "Feature", "fix": "Fix", "system": "System",
            "editorial": "Editorial", "design": "Design",
        },
        "footerAbout": "A fully automated aviation news aggregator. GitHub Actions fetches trusted sources hourly, writes and publishes automatically, and credits originals at the end of every article. Design prototype; sample content.",
        "footerSources": "Data Sources",
        "footerChangelog": "Site changelog",
        "nav": ["Latest", "Briefings", "Flight Radar", "Incident DB", "Sources",
                "Methodology"],
        "cats": ["All", "Safety", "Regulation", "Business", "Operations",
                 "Military"],
        "radarKicker": "Taiwan Flight Radar",
        "radarTitle": "Taiwan civil flight radar",
        "radarSub": "A live public ADS-B view of civil aircraft around Taiwan, with ICAO/IATA callsigns, routes, type, altitude, speed and heading.",
        "radarSearch": "Search ICAO/IATA callsign, route, airline or aircraft type",
        "radarCallsignFormat": "Callsign format",
        "radarAirborne": "Airborne only",
        "radarRefresh": "Refresh now",
        "radarLoading": "Loading the latest ADS-B observations…",
        "radarMapLabel": "Live civil-aircraft observations around Taiwan",
        "radarList": "Aircraft now",
        "radarNotice": "This is not air traffic control radar. Data may be delayed, incomplete or wrong and must not be used for navigation, flight operations or emergencies. A callsign may differ from a passenger flight number.",
        "radarPrivacy": "For safety and privacy, source-tagged military, PIA, LADD, emergency-state and stale-position records are not shown.",
        "radarSource": "Aircraft positions: Airplanes.live public community ADS-B; flight codes and routes: ADSBdb; map: OpenStreetMap.",
        # daily briefings
        "brKicker": "Daily Briefing", "brIndexTitle": "Briefings",
        "brIndexSub": "A bulleted global air and transport briefing three times daily (07:15 / 15:15 / 23:15 Taipei time), based on the site's verified articles and supplemented by a search-capable model (Beta).",
        "brLatest": "Latest briefing", "brWindow": "Data window",
        "brCutoff": "Data cutoff", "brGenerated": "Compiled", "brTo": "to",
        "brEmpty": "As of this edition's data cutoff, no new events meeting the inclusion bar were found in the sources checked for this edition.",
        "brPartial": "Some sources could not be fetched in full for this edition; coverage may be incomplete. A fetch failure does not mean no events occurred.",
        "brChecked": "📡 Sources checked", "brWarnings": "Coverage notes",
        "brUpdate": "UPDATE", "brItems": "items",
        "brNoItems": "No new events met the inclusion bar in this section "
                     "among the sources checked",
        "brModeDet": "Deterministic assembly (no model used)",
        "brModeLlm": "Model-assisted intro",
        "brBeta": "BETA", "brAiTag": "AI search",
        "brBetaNote": "Beta: some briefing entries (tagged \"AI search\") "
                      "are compiled with a search-capable model; cited "
                      "links come only from actually retrieved results. "
                      "The feature is still being optimized - the original "
                      "sources prevail.",
        "brSecs": ["🚨 Safety events & emergencies",
                   "🇹🇼 Taiwan aviation (civil + military)",
                   "🌐 International industry news",
                   "🚄 Ground & maritime transport"],
        "brSevs": {"fatal": "Fatal", "serious": "Serious",
                   "significant": "Significant", "routine": "Routine"},
        "sevs": ["All", "Accident", "Serious", "Incident"],
        "themeOpts": ["Light", "Dark"],
        # production-only keys (not in the design dictionary)
        "siteName": "AVWIRE Aviation Wire",
        "siteDesc": "A fully automated aviation news aggregator: trusted sources fetched hourly, bilingual stories written automatically, every original source credited.",
        "awaiting": "Awaiting first pipeline run",
        "lastBuild": "Last build",
        "aggNote": "Aggregation mode: original source headlines, linking to the original stories",
    },
}

CATS = {
    "safety": {"zh": "事故", "en": "Safety"},
    "reg": {"zh": "法規", "en": "Regulation"},
    "biz": {"zh": "商業", "en": "Business"},
    "ops": {"zh": "營運", "en": "Operations"},
    "mil": {"zh": "軍事", "en": "Military"},
}
SEV = {
    "acc": {"zh": "事故", "en": "Accident", "cls": "tag-accent"},
    "ser": {"zh": "嚴重事件", "en": "Serious", "cls": "tag-outline"},
    "inc": {"zh": "事件", "en": "Incident", "cls": "tag-neutral"},
}
ST = {
    "open": {"zh": "調查中", "en": "Open"},
    "closed": {"zh": "已結案", "en": "Closed"},
    "prelim": {"zh": "初報公布", "en": "Prelim out"},
}
KIND = {
    "official": {"zh": "官方機構", "en": "Official"},
    "industry": {"zh": "產業組織", "en": "Industry body"},
    "media": {"zh": "新聞媒體", "en": "News media"},
    "data": {"zh": "數據平台", "en": "Data platform"},
}
TAGCLS = {
    "safety": "tag-accent",
    "reg": "tag-neutral",
    "biz": "tag-neutral",
    "ops": "tag-neutral",
    "mil": "tag-accent-2",
}


# ── methodology page (user-authored copy, 2026-07-27) ────────────────────────
# Block types rendered by templates/about.html: p / sub / step / list / pre.

def _p(x):
    return {"t": "p", "x": x}


def _sub(x):
    return {"t": "sub", "x": x}


def _step(n, x):
    return {"t": "step", "n": n, "x": x}


def _list(*items):
    return {"t": "list", "items": list(items)}


def _pre(x):
    return {"t": "pre", "x": x}


_REPO_TREE_ZH = """avwire/
├─ .github/workflows/       # 排程與自動化工作流程
├─ pipeline/
│  ├─ fetch.py              # RSS、API 與來源擷取
│  ├─ dedupe.py             # 去重與事件合併
│  ├─ providers.py          # 多模型備援與呼叫
│  ├─ write.py              # 模型整理、引文與資料驗證
│  └─ build.py              # 網站資料產生與發布
├─ data/                    # 處理狀態與公開資料
└─ site/                    # GitHub Pages 網站"""

_REPO_TREE_EN = """avwire/
├─ .github/workflows/       # schedules & automation
├─ pipeline/
│  ├─ fetch.py              # RSS / API source fetching
│  ├─ dedupe.py             # dedup & event merging
│  ├─ providers.py          # multi-model failover & calls
│  ├─ write.py              # model compilation, quote & data checks
│  └─ build.py              # site generation & publishing
├─ data/                    # pipeline state & public data
└─ site/                    # GitHub Pages site"""

ABOUT = {
    "zh": {
        "heading": "內容產製與驗證",
        "intro": [
            "AVWIRE 是一個以可信來源、快速更新與完整溯源為核心的航空資訊平台。",
            "系統持續追蹤航空主管機關、國際組織、航空公司及可信新聞機構所發布的公開資訊，"
            "透過自動化資料管線整理事件，再由 Google Gemini、NVIDIA Nemotron 等企業級語言模型"
            "協助產生繁體中文報導。",
            "模型不是新聞來源，也不會自行憑空補充資訊。每篇內容都必須建立在系統實際取得的"
            "來源資料上，並於文末保留原始出處，方便讀者直接查證。",
        ],
        "sections": [
            {"heading": "我們的核心原則", "blocks": [
                _sub("來源先於模型"),
                _p("AVWIRE 的報導從可信…16426 tokens truncated…eturn rows


def codex_usage_rows(snapshot: dict, prices: dict):
    """Validate and price a checked-in Codex task usage snapshot.

    This dataset is separate from the site's API ledger. Cached input is a
    subset of input, and reasoning output is a subset of output, so neither is
    added a second time when calculating total tokens.
    """
    references = {
        row["model"]: row for row in gpt_family_reference_rows(prices)
    }
    rows = []
    totals = {
        "in": 0, "cached_in": 0, "uncached_in": 0, "out": 0,
        "reasoning": 0, "tokens": 0, "usd": 0.0,
    }
    raw_entries = snapshot.get("entries") if isinstance(snapshot, dict) else []
    for raw in raw_entries or []:
        if not isinstance(raw, dict):
            continue
        model = str(raw.get("model") or "").strip()
        reference = references.get(model)
        values = (
            raw.get("inputTokens"),
            raw.get("cachedInputTokens"),
            raw.get("outputTokens"),
            raw.get("reasoningOutputTokens"),
        )
        if (not reference
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value < 0 for value in values)):
            continue
        input_tokens, cached_tokens, output_tokens, reasoning_tokens = values
        if cached_tokens > input_tokens or reasoning_tokens > output_tokens:
            continue
        uncached_tokens = input_tokens - cached_tokens
        cached_rate = (reference["cached_in"]
                       if reference["cached_in"] is not None
                       else reference["in"])
        usd = (
            uncached_tokens / 1_000_000 * reference["in"]
            + cached_tokens / 1_000_000 * cached_rate
            + output_tokens / 1_000_000 * reference["out"]
        )
        row = {
            "model": model,
            "in": input_tokens,
            "cached_in": cached_tokens,
            "uncached_in": uncached_tokens,
            "out": output_tokens,
            "reasoning": reasoning_tokens,
            "tokens": input_tokens + output_tokens,
            "usd": usd,
            "source": reference["source"],
        }
        rows.append(row)
        for key in ("in", "cached_in", "uncached_in", "out",
                    "reasoning", "tokens"):
            totals[key] += row[key]
        totals["usd"] += usd
    actual = (snapshot.get("actualAdditionalApiSpendUsd")
              if isinstance(snapshot, dict) else 0)
    totals["actual_usd"] = (
        float(actual)
        if isinstance(actual, (int, float)) and not isinstance(actual, bool)
        and actual >= 0 else 0.0
    )
    return rows, totals


_CHANGELOG_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_CHANGELOG_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_CHANGELOG_KINDS = {"feature", "fix", "system", "editorial", "design"}
_CHANGELOG_REPOSITORY = "https://github.com/nnneeeooo-nnneeeooo/avwire"


def changelog_view(raw, lang: str, labels: dict) -> dict:
    """Validate checked-in changelog data and prepare date-grouped rows.

    URLs are derived from validated full commit SHAs instead of accepting
    arbitrary href values from the data file.
    """
    if not isinstance(raw, dict):
        raw = {}
    rows = []
    seen_commits = set()
    for order, item in enumerate(raw.get("entries") or []):
        if not isinstance(item, dict):
            continue
        date = str(item.get("date") or "")
        kind = str(item.get("kind") or "")
        title = str(item.get(lang) or "").strip()
        commit = item.get("commit")
        if (not _CHANGELOG_DATE_RE.fullmatch(date)
                or kind not in _CHANGELOG_KINDS or not title):
            continue
        if commit is not None:
            commit = str(commit).lower()
            if (not _CHANGELOG_COMMIT_RE.fullmatch(commit)
                    or commit in seen_commits):
                continue
            seen_commits.add(commit)
        rows.append({
            "date": date,
            "kind": kind,
            "kind_label": str(labels.get(kind) or kind),
            "title": title,
            "commit": commit,
            "short_commit": commit[:7] if commit else "",
            "url": (f"{_CHANGELOG_REPOSITORY}/commit/{commit}"
                    if commit else ""),
            "order": order,
        })
    rows.sort(key=lambda row: (row["date"], -row["order"]), reverse=True)
    groups = []
    for row in rows:
        if not groups or groups[-1]["date"] != row["date"]:
            groups.append({"date": row["date"], "entries": []})
        groups[-1]["entries"].append(row)
    history_start = str(raw.get("historyStart") or "")
    updated_through = str(raw.get("updatedThrough") or "")
    if not _CHANGELOG_DATE_RE.fullmatch(history_start):
        history_start = groups[-1]["date"] if groups else "—"
    if not _CHANGELOG_DATE_RE.fullmatch(updated_through):
        updated_through = groups[0]["date"] if groups else "—"
    return {
        "groups": groups,
        "count": len(rows),
        "history_start": history_start,
        "updated_through": updated_through,
        "repository_url": f"{_CHANGELOG_REPOSITORY}/commits/main/",
    }


def render_usage_dashboard(env, build) -> int:
    """Private dashboard at /u/<token>/ - only when the secret is set."""
    token = os.environ.get("AVWIRE_USAGE_TOKEN", "").strip()
    if not token:
        return 0
    if not _USAGE_TOKEN_RE.fullmatch(token):
        print("build: AVWIRE_USAGE_TOKEN ignored "
              "(want 16-128 chars of A-Za-z0-9_-)")
        return 0
    ledger = load_json(DATA_DIR / "usage.json", {})
    prices = load_json(Path(__file__).resolve().parent.parent
                       / "config" / "model_prices.json", {})
    codex_snapshot = load_json(Path(__file__).resolve().parent.parent
                               / "config" / "codex_usage.json", {})
    rows, totals = usage_rows(ledger, prices)
    recent = recent_run_view(ledger)
    codex_rows, codex_totals = codex_usage_rows(codex_snapshot, prices)
    try:
        rate = float(prices.get("usdToTwd") or 31.5)
    except (TypeError, ValueError):
        rate = 31.5
    daily = [{"day": d, **v}
             for d, v in sorted((ledger.get("daily") or {}).items(),
                                reverse=True)[:14]
             if isinstance(v, dict)]
    ctx = {
        "base": BASE_PATH, "favicon": FAVICON, "build": build,
        "rows": rows, "totals": totals, "daily": daily,
        "recent_runs": recent["runs"],
        "recent_models": recent["models"],
        "recent_summary": recent["summary"],
        "codex_rows": codex_rows, "codex_totals": codex_totals,
        "codex_twd": codex_totals["usd"] * rate,
        "codex_scope": str(codex_snapshot.get("scope") or "").strip(),
        "codex_updated": codex_snapshot.get("updatedUtc") or "尚無紀錄",
        "codex_tracking_since":
            codex_snapshot.get("trackingSinceUtc") or "尚未開始",
        "non_api_rows": non_api_reference_rows(prices),
        "gpt_family_rows": gpt_family_reference_rows(prices),
        "twd": totals["usd"] * rate, "rate": rate,
        "updated": ledger.get("updatedUtc") or "尚無紀錄",
        "tracking_since": ledger.get("trackingSinceUtc") or "尚未開始",
    }
    render(env, "usage.html", f"u/{token}/index.html", ctx)
    return 1


def render_manual_workbench(env, build) -> int:
    """Private drafting page at /m/<token>/; omitted when unset/invalid."""
    token = os.environ.get("AVWIRE_MANUAL_TOKEN", "").strip()
    if not token:
        return 0
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}\Z", token):
        print("build: AVWIRE_MANUAL_TOKEN ignored "
              "(want 32-128 chars of A-Za-z0-9_-)")
        return 0
    models = [{
        "id": token_id,
        "name": MODEL_DISPLAY_NAMES.get(token_id, token_id),
    } for token_id in MODEL_ORDER]
    render(env, "manual.html", f"m/{token}/index.html", {
        "base": BASE_PATH,
        "favicon": FAVICON,
        "build": build,
        "models": models,
    })
    return 1


# ── rendering ────────────────────────────────────────────────────────────────

def base_ctx(lang, page, sub, *, title, description, ticker, build, hreflang=True):
    t = L[lang]
    nav_defs = [("home", ""), ("briefings", "briefings/"),
                ("radar", "radar/"),
                ("incidents", "incidents/"),
                ("sources", "sources/"), ("about", "about/")]
    return {
        "lang": lang, "t": t, "base": BASE_PATH, "favicon": FAVICON,
        "html_lang": "zh-Hant" if lang == "zh" else "en",
        "title": title, "description": description,
        "zh_url": page_url("zh", sub), "en_url": page_url("en", sub),
        "zh_abs_url": SITE_ORIGIN + page_url("zh", sub),
        "en_abs_url": SITE_ORIGIN + page_url("en", sub),
        "self_abs_url": SITE_ORIGIN + page_url(lang, sub),
        "hreflang": hreflang,
        "home_url": page_url(lang, ""),
        "radar_url": page_url(lang, "radar/"),
        "changelog_url": page_url(lang, "changelog/"),
        "nav": [{"label": t["nav"][i], "url": page_url(lang, s), "active": page == p}
                for i, (p, s) in enumerate(nav_defs)],
        "ticker_items": ticker or [], "build": build,
        "footer_sources": FOOTER_SOURCES,
    }


def render(env, template, out_rel, ctx):
    html = env.get_template(template).render(**ctx)
    out = SITE_DIR / out_rel
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")


def main() -> int:
    t0 = time.time()
    now = now_utc()

    articles = collect_articles()
    published_ids = {a["id"] for a in articles}
    flashes = prep_flashes(load_json(DATA_DIR / "flashes.json", None),
                           published_ids)
    incidents = prep_incidents(load_json(DATA_DIR / "incidents.json", None))
    sources = merged_sources(load_json(DATA_DIR / "sources.json", []))
    stats_raw = load_json(DATA_DIR / "stats.json", {})
    briefings = collect_briefings()
    brief_rows = [r for r in (load_json(
        DATA_DIR / "briefings" / "index.json", {}).get("briefings") or [])
        if isinstance(r, dict)]
    latest_row = latest_briefing(brief_rows)
    changelog_raw = load_json(
        Path(__file__).resolve().parent.parent
        / "config" / "changelog.json", {})

    # clean output tree
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR, ignore_errors=True)
    (SITE_DIR / "assets").mkdir(parents=True, exist_ok=True)
    if STATIC_DIR.is_dir():
        for f in STATIC_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, SITE_DIR / "assets" / f.name)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    tpe_now = now.astimezone(TPE)
    build = {
        "date": tpe_now.strftime("%Y-%m-%d %a").upper(),
        "utc_hm": now.strftime("%H:%M"),
        "tpe_hm": tpe_now.strftime("%H:%M"),
        "stamp": now.strftime("%Y-%m-%d %H:%M"),
    }
    cat_keys = ["all", "safety", "reg", "biz", "ops", "mil"]
    sev_keys = ["all", "acc", "ser", "inc"]
    pages = 0
    failed = 0

    # Free no-API fallback: with no articles published yet, surface raw
    # source headlines instead of an empty page.
    agg_items = [] if articles else collect_agg_items(now)

    for lang in ("zh", "en"):
        t = L[lang]
        agg = False
        views = [art_view(a, lang) for a in articles]
        if views:
            fl = flash_view(flashes, lang)
            hero = views[0]
            feed = views[1:1 + HOME_FEED_LIMIT]
        elif agg_items:
            agg = True
            av = agg_view(agg_items, lang)
            fl = agg_flashes(av)
            hero = av[0]
            feed = av[1:1 + HOME_FEED_LIMIT]
        else:
            fl = flash_view(flashes, lang)
            hero = None
            feed = []
        # ticker items stay structured so the marquee can link each flash
        # to its story (owner request: clickable, no underline)
        ticker = [{"time": f.get("time"), "text": f.get("text"),
                   "url": f.get("url"), "hot": bool(f.get("hot")),
                   "external": bool(f.get("external"))} for f in fl]
        sv = stats_views(stats_raw, lang)

        bviews = [brief_view(b, lang, t, published_ids) for b in briefings]
        latest_brief = None
        if latest_row:
            latest_brief = next(
                (bv for bv in bviews
                 if bv["id"] == latest_row.get("briefing_id")), None)

        ctx = base_ctx(lang, "home", "", title=t["siteName"],
                       description=t["siteDesc"], ticker=ticker, build=build)
        ctx.update(hero=hero, feed=feed, flashes=fl, agg=agg,
                   source_status=source_status_view(sources, now),
                   stats=sv["tiles"], otp=sv["otp"], fleet=sv["fleet"],
                   delays=sv["delays"],
                   cat_seg=list(zip(cat_keys, t["cats"])),
                   latest_brief=latest_brief)
        render(env, "home.html", rel_path(lang, "index.html"), ctx)
        pages += 1

        for bv in bviews:
            try:
                ctx = base_ctx(lang, "briefings", f"briefings/{bv['id']}/",
                               title=f"{t['siteName']} — {bv['title']}",
                               description=f"{bv['title']} · {bv['date_label']}",
                               ticker=ticker, build=build)
                ctx["b"] = bv
                render(env, "briefing.html",
                       rel_path(lang, f"briefings/{bv['id']}/index.html"), ctx)
                pages += 1
            except Exception as exc:  # one bad briefing must not kill the build
                failed += 1
                print(f"build: briefing {bv['id']} ({lang}) failed: {exc}")

        groups: dict[str, list] = {}
        for bv in bviews:  # bviews sorted newest cutoff first -> dates desc
            groups.setdefault(bv["date_label"], []).append(bv)
        ctx = base_ctx(lang, "briefings", "briefings/",
                       title=f"{t['siteName']} — {t['brIndexTitle']}",
                       description=t["brIndexSub"], ticker=ticker, build=build)
        ctx.update(groups=[
            {"date": d, "rows": sorted(rows, key=lambda r: r["cutoff_iso"])}
            for d, rows in groups.items()])
        render(env, "briefings.html",
               rel_path(lang, "briefings/index.html"), ctx)
        pages += 1

        airline_cfg = load_json(
            Path(__file__).resolve().parent.parent
            / "config" / "airline_icao_codes.json", {})
        airline_names = {
            str(row.get("icao_code") or "").upper():
                (row.get("airline_name_zh_tw") if lang == "zh"
                 else row.get("airline_name_en"))
            for row in (airline_cfg.get("airlines") or [])
            if isinstance(row, dict) and row.get("active", True)
               and row.get("icao_code")
        }
        type_cfg = load_json(
            Path(__file__).resolve().parent.parent
            / "config" / "aircraft_types.json", {})
        aircraft_types = type_cfg.get("types") or {}
        airport_cfg = load_json(
            Path(__file__).resolve().parent.parent
            / "config" / "tw_civil_airports.json", {})
        radar_airports = [
            {
                "icao": row.get("icao"), "iata": row.get("iata"),
                "name": (row.get("name_zh") if lang == "zh"
                         else row.get("name_en")),
                "lat": row.get("lat"), "lon": row.get("lon"),
            }
            for row in (airport_cfg.get("airports") or [])
            if isinstance(row, dict) and row.get("enabled", True)
               and isinstance(row.get("lat"), (int, float))
               and isinstance(row.get("lon"), (int, float))
        ]
        ctx = base_ctx(
            lang, "radar", "radar/",
            title=f"{t['siteName']} — {t['radarTitle']}",
            description=t["radarSub"], ticker=ticker, build=build)
        ctx.update(
            airline_names=airline_names,
            aircraft_types=aircraft_types,
            radar_airports=radar_airports,
        )
        render(env, "radar.html", rel_path(lang, "radar/index.html"), ctx)
        pages += 1

        for a, v in zip(articles, views):
            try:
                ctx = base_ctx(lang, "home", f"news/{a['id']}/",
                               title=f"{t['siteName']} — {v['title']}",
                               description=v["summary"] or t["siteDesc"],
                               ticker=ticker, build=build)
                ctx["a"] = v
                render(env, "article.html",
                       rel_path(lang, f"news/{a['id']}/index.html"), ctx)
                pages += 1
            except Exception as exc:  # degrade: one bad article must not kill the build
                failed += 1
                print(f"build: article {a['id']} ({lang}) failed: {exc}")

        rows = inc_view(incidents, lang)
        ctx = base_ctx(lang, "incidents", "incidents/",
                       title=f"{t['siteName']} — {t['incTitle']}",
                       description=t["incSub"], ticker=ticker, build=build)
        ctx.update(rows=rows, count=len(rows),
                   sev_seg=list(zip(sev_keys, t["sevs"])))
        render(env, "incidents.html", rel_path(lang, "incidents/index.html"), ctx)
        pages += 1

        ctx = base_ctx(lang, "sources", "sources/",
                       title=f"{t['siteName']} — {t['srcTitle']}",
                       description=t["srcSub"], ticker=ticker, build=build)
        ctx.update(rows=sources_rows_view(sources, lang, now))
        render(env, "sources.html", rel_path(lang, "sources/index.html"), ctx)
        pages += 1

        ctx = base_ctx(lang, "about", "about/",
                       title=f"{t['siteName']} — {t['aboutTitle']}",
                       description=ABOUT[lang]["intro"][0], ticker=ticker, build=build)
        ctx.update(about=ABOUT[lang])
        render(env, "about.html", rel_path(lang, "about/index.html"), ctx)
        pages += 1

        ctx = base_ctx(
            lang, "changelog", "changelog/",
            title=f"{t['siteName']} — {t['changeTitle']}",
            description=t["changeSub"], ticker=ticker, build=build)
        ctx.update(changelog=changelog_view(
            changelog_raw, lang, t["changeKinds"]))
        render(env, "changelog.html",
               rel_path(lang, "changelog/index.html"), ctx)
        pages += 1

    pages += render_usage_dashboard(env, build)
    pages += render_manual_workbench(env, build)

    # 404 (zh chrome, bilingual body), served by GitHub Pages from the root
    ctx = base_ctx("zh", "none", "", title=f"{L['zh']['siteName']} — 404",
                   description=L["zh"]["siteDesc"], ticker="", build=build,
                   hreflang=False)
    render(env, "404.html", "404.html", ctx)
    pages += 1

    print(f"build: {len(articles)} articles, {len(flashes)} flashes, "
          f"{len(incidents)} incidents, {pages} pages, {failed} failed "
          f"-> {SITE_DIR} (base='{BASE_PATH}') in {time.time() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

