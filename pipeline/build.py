"""build.py — render the SKYTICAL static site from data/ JSON (see CONTRACTS.md).

Reads (all optional, degrades gracefully): data/articles/*.json, flashes.json,
incidents.json, sources.json, stats.json. Writes the site/ tree per
CONTRACTS.md: zh at /, en under /en/, one page per article ever published,
incidents / sources / methodology / changelog pages, copied assets, 404.html
and .nojekyll.
A single bad input never crashes the build: bad entries are skipped with a
one-line log to stdout and the script exits 0.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import timedelta, timezone
from email.utils import format_datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from jinja2 import Environment, FileSystemLoader, StrictUndefined

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    ARTICLES_DIR,
    BASE_PATH,
    DATA_DIR,
    HOME_FEED_LIMIT,
    NEWS_PAGE_SIZE,
    MAX_FLASHES,
    RAW_DIR,
    SITE_DIR,
    SITE_ORIGIN,
    SOURCES,
    STATIC_DIR,
    TEMPLATES_DIR,
    is_google_news_url,
    load_json,
    norm_url,
    now_utc,
    parse_iso,
    is_transport_headline,
    story_category,
)
from model_config import (
    DEFAULT_PROVIDER_ORDER,
    MODEL_DISPLAY_NAMES,
    MODEL_ORDER,
)

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"


def static_asset_version() -> str:
    digest = hashlib.sha256()
    for name in (
        "site.css",
        "app.js",
        "search.js",
        "highlight.js",
        "skytical-logo.svg",
        "skytical-mark.svg",
        "skytical-social.png",
    ):
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:10]


ASSET_VERSION = static_asset_version()

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
        "homeLabel": "返回 SKYTICAL 首頁", "live": "LIVE 快訊", "updateBadge": "每小時自動更新",
        "flash": "即時快訊", "sourceStatus": "來源狀態",
        "latest": "最新新聞", "topStory": "頭條", "priorityLabel": "頭條",
        "mainSource": "主要來源",
        "briefLabel": "短訊", "roundupLabel": "事件彙整",
        "summaryLabel": "重點摘要",
        "readMore": "閱讀全文 →", "back": "← 返回首頁",
        "heroImg": "[ 頭條照片 — 由來源圖庫自動帶入，灰階顯示 ]",
        "today": "今日全球數據", "statFlights": "目前追蹤航班", "statDelay": "全球延誤率",
        "statUnavailable": "暫無資料",
        "statsNote": "部分即時數據目前尚未取得；已取得的項目照常顯示。",
        "statSerious": "本週嚴重事件", "statNotam": "生效中 NOTAM",
        "otp": "準點率排行 · 7月", "fleet": "機隊與訂單追蹤", "fleetDeliv": "2026 上半年交付",
        "fleetBacklog": "積壓訂單", "fleetOrders": "本月新訂單",
        "delays": "今日延誤熱點機場", "autoCompiled": "自動彙整",
        "refreshNote": "本文隨來源每小時更新", "sourcesBox": "資料來源 Sources",
        "genNote": "本文由自動化系統彙整生成，內容以原始來源為準",
        "genNotePunct": "。",
        "photoKind": {"airframe_photo": "同機資料照片",
                      "file_photo": "資料照片（非事件現場照片）",
                      "event_photo": "事件現場照片"},
        "photoSource": "照片來源",
        "incKicker": "Incident Database", "incTitle": "事故資料庫",
        "incSub": "自動彙整全球民航事故與事件，資料來自各國調查機關與專業追報來源，每小時更新。",
        "incCountLabel": "筆紀錄",
        "incWeeklySerious": "本週嚴重事件",
        "incReadEvent": "閱讀事件",
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
        "changeSub": "依 GitHub 主分支提交紀錄整理，涵蓋 SKYTICAL 建站至最近一次網站功能變更。",
        "changeNotice": "每小時新聞、每日快報與航機狀態等自動資料更新不列入，避免機器提交淹沒真正的網站變更。",
        "changeCount": "筆網站變更", "changeStart": "紀錄起點",
        "changeLatest": "更新至", "changeSource": "查看完整 GitHub 提交紀錄",
        "changeCommit": "提交",
        "changeKinds": {
            "feature": "功能", "fix": "修正", "system": "系統",
            "editorial": "編輯", "design": "介面",
        },
        "footerAbout": "SKYTICAL 是以可追溯來源為基礎的自動化航空新聞彙整服務；每篇報導附原始來源，原始報導與更正公告優先。",
        "footerSources": "資料來源 Data Sources",
        "footerChangelog": "網站更新紀錄",
        "nav": ["最新", "快報", "航班雷達", "事故資料庫", "來源", "方法論"],
        "cats": ["全部", "事故", "法規", "商業", "營運", "軍事"],
        "searchKicker": "News Search", "searchTitle": "搜尋新聞",
        "newsKicker": "News Index", "newsTitle": "全部新聞",
        "newsSub": "依發布時間排列的本站航空與運輸新聞索引。",
        "paginationLabel": "新聞分頁", "previousPage": "上一頁",
        "nextPage": "下一頁", "pageLabel": "第 {page} / {pages} 頁",
        "headerSearchPlaceholder": "搜尋班號，例如 CI100",
        "headerSearchPlaceholders": [
            "搜尋班號，例如 CI100",
            "搜尋航空公司",
            "搜尋機場或城市",
            "搜尋機型，例如 A350",
            "隨意搜尋想看的 SKYTICAL 內容",
            "今天想看什麼航空新聞？",
        ],
        "searchSub": "搜尋標題、摘要、全文、來源、日期、航班、機型與機場代碼；航空公司正式名稱與常用簡稱可互相查找。",
        "searchButton": "搜尋", "searchClear": "清除",
        "searchLoading": "正在載入新聞索引…",
        "searchPrompt": "輸入關鍵字開始搜尋全部新聞。",
        "searchCount": "找到 {count} 則新聞",
        "searchNoResults": "找不到符合「{query}」的新聞，請改用航空公司簡稱、機型、航班或機場代碼。",
        "searchError": "新聞索引暫時無法載入，請稍後重新整理頁面。",
        "radarKicker": "Taiwan Flight Radar",
        "radarTitle": "台灣民航雷達",
        "radarSub": "公開 ADS-B 即時觀測圖，顯示台灣周邊民航機的 ICAO／IATA 航班代碼、航線、機型、高度、速度與航向。",
        "radarSearch": "搜尋 ICAO／IATA 航班代碼、航線、航空公司或機型",
        "radarCallsignFormat": "代碼顯示",
        "radarAirborne": "僅顯示飛行中",
        "radarRefresh": "立即更新",
        "radarLoading": "正在取得最新 ADS-B 觀測資料…",
        "radarMapLabel": "台灣周邊民航即時觀測地圖",
        "radarList": "目前航機",
        "radarNotice": "本頁不是航管雷達，資料可能延遲、缺漏或錯誤，不得用於導航、飛航操作或緊急判斷。ICAO／IATA 航班代碼不一定等同旅客票面班號。",
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
        "sevs": ["本週嚴重事件", "全部", "事故", "嚴重事件", "事件"],
        "themeOpts": ["亮", "暗"],
        # production-only keys (not in the design dictionary)
        "siteName": "SKYTICAL",
        "siteDesc": "SKYTICAL 提供臺灣與全球航空新聞、即時航空快訊、航班與機場營運、飛安及航空產業動態，所有報導均附可追溯資料來源。",
        "articleByline": "SKYTICAL 編輯系統",
        "articleBylineLabel": "發布者",
        "publishedLabel": "發布",
        "modifiedLabel": "更新",
        "sourceTimeLabel": "來源時間",
        "metaColon": "：",
        "topicKicker": "Aviation Topics",
        "topicCount": "則相關新聞",
        "topicNavLabel": "航空新聞主題",
        "policyLink": "編輯、更正與聯絡",
        "awaiting": "等待首次管線執行",
        "lastBuild": "最後建置",
        "aggNote": "純聚合模式：顯示來源原文標題，點擊前往原始報導",
    },
    "en": {
        "homeLabel": "Back to the SKYTICAL home page", "live": "LIVE WIRE", "updateBadge": "Auto-updates hourly",
        "flash": "Live flash", "sourceStatus": "Source status",
        "latest": "Latest news", "topStory": "Top story", "priorityLabel": "TOP",
        "mainSource": "Primary source",
        "briefLabel": "Brief", "roundupLabel": "Event roundup",
        "summaryLabel": "Quick Summary",
        "readMore": "Read more →", "back": "← Back to front page",
        "heroImg": "[ Lead photo — pulled from source library, grayscale ]",
        "today": "Global today", "statFlights": "Flights tracked now", "statDelay": "Global delay rate",
        "statUnavailable": "Data unavailable",
        "statsNote": "Some live metrics are currently unavailable; available metrics are shown as reported.",
        "statSerious": "Serious events this week", "statNotam": "Active NOTAMs",
        "otp": "On-time ranking · Jul", "fleet": "Fleet & orders", "fleetDeliv": "H1 2026 deliveries",
        "fleetBacklog": "Backlog", "fleetOrders": "New orders this month",
        "delays": "Delay hotspots today", "autoCompiled": "Auto-compiled",
        "refreshNote": "Refreshes hourly with sources", "sourcesBox": "Sources",
        "genNote": "This article was compiled automatically; the original sources prevail",
        "genNotePunct": ".",
        "photoKind": {"airframe_photo": "File photo of this airframe",
                      "file_photo": "File photo (not from this event)",
                      "event_photo": "Photo from this event"},
        "photoSource": "Photo source",
        "incKicker": "Incident Database", "incTitle": "Incident database",
        "incSub": "Automatically aggregated civil-aviation accidents and incidents, from state investigators and specialist trackers. Updated hourly.",
        "incCountLabel": "records",
        "incWeeklySerious": "Serious events this week",
        "incReadEvent": "Read event",
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
        "changeSub": "Compiled from the GitHub main-branch history, covering SKYTICAL from its creation through the latest site change.",
        "changeNotice": "Automated hourly news, daily briefing and flight-state data commits are omitted so operational refreshes do not bury real site changes.",
        "changeCount": "site changes", "changeStart": "History starts",
        "changeLatest": "Updated through",
        "changeSource": "View the complete GitHub commit history",
        "changeCommit": "commit",
        "changeKinds": {
            "feature": "Feature", "fix": "Fix", "system": "System",
            "editorial": "Editorial", "design": "Design",
        },
        "footerAbout": "SKYTICAL is an automated aviation-news compilation service built on traceable sources. Every story links to its sources; original reports and corrections prevail.",
        "footerSources": "Data Sources",
        "footerChangelog": "Site changelog",
        "nav": ["Latest", "Briefings", "Flight Radar", "Incident DB", "Sources",
                 "Methodology"],
        "cats": ["All", "Safety", "Regulation", "Business", "Operations",
                 "Military"],
        "searchKicker": "News Search", "searchTitle": "Search news",
        "newsKicker": "News Index", "newsTitle": "All news",
        "newsSub": "An archive of SKYTICAL aviation and transport news, ordered by publication time.",
        "paginationLabel": "News pagination", "previousPage": "Previous",
        "nextPage": "Next", "pageLabel": "Page {page} of {pages}",
        "headerSearchPlaceholder": "Search a flight number, e.g. CI100",
        "headerSearchPlaceholders": [
            "Search a flight number, e.g. CI100",
            "Search an airline",
            "Search an airport or city",
            "Search an aircraft type, e.g. A350",
            "Explore anything on SKYTICAL",
            "What aviation news are you looking for?",
        ],
        "searchSub": "Search titles, summaries, full text, sources, dates, flights, aircraft types and airport codes. Official airline names and common short names are interchangeable.",
        "searchButton": "Search", "searchClear": "Clear",
        "searchLoading": "Loading the news index…",
        "searchPrompt": "Enter keywords to search every published story.",
        "searchCount": "{count} articles found",
        "searchNoResults": "No stories match “{query}”. Try an airline short name, aircraft type, flight or airport code.",
        "searchError": "The news index is temporarily unavailable. Please reload this page later.",
        "radarKicker": "Taiwan Flight Radar",
        "radarTitle": "Taiwan civil flight radar",
        "radarSub": "A live public ADS-B view of civil aircraft around Taiwan, with ICAO/IATA flight codes, routes, type, altitude, speed and heading.",
        "radarSearch": "Search ICAO/IATA flight code, route, airline or aircraft type",
        "radarCallsignFormat": "Code format",
        "radarAirborne": "Airborne only",
        "radarRefresh": "Refresh now",
        "radarLoading": "Loading the latest ADS-B observations…",
        "radarMapLabel": "Live civil-aircraft observations around Taiwan",
        "radarList": "Aircraft now",
        "radarNotice": "This is not air traffic control radar. Data may be delayed, incomplete or wrong and must not be used for navigation, flight operations or emergencies. ICAO/IATA flight codes may differ from a passenger flight number.",
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
        "sevs": ["This week", "All", "Accident", "Serious", "Incident"],
        "themeOpts": ["Light", "Dark"],
        # production-only keys (not in the design dictionary)
        "siteName": "SKYTICAL",
        "siteDesc": "SKYTICAL covers Taiwan and global aviation news, breaking updates, airline and airport operations, safety and the aviation industry, with traceable sources.",
        "articleByline": "SKYTICAL Editorial System",
        "articleBylineLabel": "Published by",
        "publishedLabel": "Published",
        "modifiedLabel": "Updated",
        "sourceTimeLabel": "Source time",
        "metaColon": ": ",
        "topicKicker": "Aviation Topics",
        "topicCount": "related stories",
        "topicNavLabel": "Aviation news topics",
        "policyLink": "Editorial, corrections and contact",
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

# Permanent, crawlable topic hubs.  These turn the home-page filters into
# durable landing pages for common Taiwan aviation-news search intents.
TOPICS = {
    "taiwan-aviation": {
        "cats": None,
        "terms": (
            "台灣", "臺灣", "桃園", "松山", "高雄", "臺中", "台中",
            "中華航空", "華航", "長榮航空", "星宇航空", "台灣虎航",
            "Taiwan", "Taoyuan", "Taipei", "Songshan", "Kaohsiung",
            "China Airlines", "EVA Air", "STARLUX", "Tigerair Taiwan",
            "TPE", "TSA", "KHH", "RMQ",
        ),
        "zh": {
            "label": "臺灣航空",
            "title": "臺灣航空新聞",
            "description": "彙整臺灣航空新聞、國籍航空公司、桃園與松山等機場、航班異動、飛安及民航政策的最新報導。",
            "intro": "追蹤華航、長榮、星宇、台灣虎航，以及桃園、松山、高雄等臺灣機場的重要消息與航班影響。",
        },
        "en": {
            "label": "Taiwan Aviation",
            "title": "Taiwan Aviation News",
            "description": "Latest Taiwan aviation news covering local airlines, airports, flight disruptions, safety and civil aviation policy.",
            "intro": "Coverage of Taiwan airlines and airports, including China Airlines, EVA Air, STARLUX, Tigerair Taiwan, Taoyuan, Songshan and Kaohsiung.",
        },
    },
    "flight-safety": {
        "cats": ("safety",), "terms": (),
        "zh": {"label": "飛安事件", "title": "飛安與航空事故新聞",
               "description": "全球飛安新聞、航空事故、嚴重事件、返航與緊急狀況的最新可追溯報導。",
               "intro": "整理事故調查機關、民航主管機關與可信來源發布的飛安事件及後續調查進度。"},
        "en": {"label": "Flight Safety", "title": "Flight Safety and Accident News",
               "description": "Traceable reporting on aviation safety, accidents, serious incidents, diversions and emergencies worldwide.",
               "intro": "Updates from accident investigators, civil aviation authorities and other traceable aviation sources."},
    },
    "airline-industry": {
        "cats": ("biz",), "terms": (),
        "zh": {"label": "航空產業", "title": "航空公司與航空產業新聞",
               "description": "航空公司、飛機製造商、機隊、航線、訂單與航空產業市場的最新新聞。",
               "intro": "掌握航空公司營運策略、機隊與訂單、製造商交付及全球航空市場變化。"},
        "en": {"label": "Airline Industry", "title": "Airline and Aviation Industry News",
               "description": "Latest news on airlines, aircraft manufacturers, fleets, routes, orders and the global aviation market.",
               "intro": "Airline strategy, fleet and order developments, aircraft deliveries and aviation-market updates."},
    },
    "flight-airport-operations": {
        "cats": ("ops",), "terms": (),
        "zh": {"label": "航班與機場", "title": "航班與機場營運新聞",
               "description": "航班延誤、取消、改道、機場營運、新航線與航空公司班表異動的最新新聞。",
               "intro": "追蹤航班異動、機場作業、新航線、班表及天候對航空運輸的影響。"},
        "en": {"label": "Flights and Airports", "title": "Flight and Airport Operations News",
               "description": "Latest news on flight delays, cancellations, diversions, airport operations, new routes and schedule changes.",
               "intro": "Flight disruptions, airport operations, route launches, schedule changes and weather impacts."},
    },
    "aviation-regulation": {
        "cats": ("reg",), "terms": (),
        "zh": {"label": "航空法規", "title": "航空法規與民航政策新聞",
               "description": "臺灣與國際航空法規、民航政策、適航指令、認證及主管機關公告的最新消息。",
               "intro": "彙整民航主管機關、國際組織與航空安全機構的重要規範及政策變化。"},
        "en": {"label": "Regulation", "title": "Aviation Regulation and Policy News",
               "description": "Latest aviation regulation, civil aviation policy, airworthiness, certification and authority updates.",
               "intro": "Regulatory and policy developments from civil aviation authorities, international bodies and safety agencies."},
    },
    "military-aviation": {
        "cats": ("mil",), "terms": (),
        "zh": {"label": "軍事航空", "title": "軍事航空新聞",
               "description": "臺灣與全球軍事航空、軍機動態、國防航空計畫及相關空域消息。",
               "intro": "聚焦與航空及空域直接相關的軍機、國防航空計畫與官方通報。"},
        "en": {"label": "Military Aviation", "title": "Military Aviation News",
               "description": "Taiwan and global military aviation, aircraft activity, defence aviation programs and airspace updates.",
               "intro": "Officially sourced coverage of military aircraft, defence aviation programs and relevant airspace activity."},
    },
}

EDITORIAL_POLICY = {
    "zh": {
        "kicker": "Transparency",
        "title": "編輯、更正與聯絡政策",
        "description": "SKYTICAL 的新聞來源、AI 自動化、編輯責任、更正流程與聯絡管道。",
        "intro": "SKYTICAL 是航空新聞與公開資料彙整服務。本頁說明內容如何產生、如何標註來源，以及讀者如何提出更正。",
        "sections": [
            {"title": "發布者與編輯責任", "body": [
                "本站以 SKYTICAL 名義發布內容。文章可能由自動化與 AI 輔助系統整理，並在文末揭露使用方式；模型本身不被列為新聞來源。",
                "各篇文章均保留可開啟的原始資料來源。涉及航班操作、法規、事故調查或緊急狀況時，應以主管機關、航空公司、機場或調查單位的最新公告為準。",
            ]},
            {"title": "來源與更新", "body": [
                "優先採用民航主管機關、事故調查機構、國際航空組織、航空公司與機場等可追溯來源；其他媒體內容用於補充時，同樣保留出處。",
                "文章顯示首次發布時間；內容實質更新時會保留修改時間。網站不會只為製造新鮮感而任意更改發布日期。",
            ]},
            {"title": "更正政策", "body": [
                "若標題、時間、航班、機型、地點、引述或其他事實有誤，SKYTICAL 會依可驗證來源修正、補充或撤回內容。重要變更應反映於文章內容與最後修改時間。",
                "提出更正時，請附上文章網址、需要修正的段落、建議內容及可驗證來源。",
            ]},
            {"title": "聯絡方式", "body": [
                "目前公開聯絡與更正管道為 SKYTICAL 的 GitHub Issues。請勿在公開表單提交個人資料、訂位紀錄、證件、付款資料或其他敏感內容。",
            ]},
        ],
        "contactLabel": "提出內容更正或聯絡 SKYTICAL",
    },
    "en": {
        "kicker": "Transparency",
        "title": "Editorial, Corrections and Contact Policy",
        "description": "How SKYTICAL handles sources, AI-assisted automation, editorial responsibility, corrections and reader contact.",
        "intro": "SKYTICAL is an aviation-news and public-data compilation service. This page explains how stories are produced, sourced and corrected.",
        "sections": [
            {"title": "Publisher and editorial responsibility", "body": [
                "Content is published under the SKYTICAL name. Stories may be prepared with automation and AI assistance, disclosed at the end of each article; a model is never treated as a news source.",
                "Every article retains links to its underlying sources. For flight operations, regulation, accident investigation or emergencies, the latest notice from the responsible authority, airline, airport or investigator prevails.",
            ]},
            {"title": "Sources and updates", "body": [
                "SKYTICAL prioritizes traceable civil aviation authorities, accident investigators, international aviation bodies, airlines and airports. Supplemental reporting also retains attribution.",
                "Articles show their original publication time and carry a modified time after substantive updates. Dates are not changed merely to make old material appear new.",
            ]},
            {"title": "Corrections", "body": [
                "When a headline, time, flight, aircraft type, location, quotation or other fact is wrong, SKYTICAL may correct, expand or withdraw the material using verifiable sources. Material changes should be reflected in the story and its modified time.",
                "A correction request should include the article URL, the passage at issue, the proposed correction and a verifiable source.",
            ]},
            {"title": "Contact", "body": [
                "SKYTICAL currently accepts public contact and correction requests through GitHub Issues. Do not submit personal information, booking records, identity documents, payment details or other sensitive material in a public issue.",
            ]},
        ],
        "contactLabel": "Request a correction or contact SKYTICAL",
    },
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
            "SKYTICAL 是一個以可信來源、快速更新與完整溯源為核心的航空資訊平台。",
            "系統持續追蹤航空主管機關、國際組織、航空公司及可信新聞機構所發布的公開資訊，"
            "透過自動化資料管線整理事件，再由 Anthropic Claude、OpenAI GPT、Google Gemini "
            "等主流語言模型"
            "協助產生繁體中文報導。",
            "模型不是新聞來源，也不會自行憑空補充資訊。每篇內容都必須建立在系統實際取得的"
            "來源資料上，並於文末保留原始出處，方便讀者直接查證。",
        ],
        "sections": [
            {"heading": "我們的核心原則", "blocks": [
                _sub("來源先於模型"),
                _p("SKYTICAL 的報導從可信來源開始，而不是從語言模型開始。"),
                _p("系統先取得官方公告、新聞稿、RSS、公開 API 或可信媒體報導，之後才將已取得的"
                   "資料交由模型整理。模型只能使用提供給它的來源內容，不得自行加入外部知識或"
                   "未經支持的推論。"),
                _sub("每項重要資訊皆可追溯"),
                _p("報導中的核心事實必須對應到原始資料。系統會保存來源網址、發布時間及支持"
                   "相關敘述的原文內容。"),
                _p("每篇報導文末均附有「資料來源」，讀者可直接開啟原始公告或報導進行核對。"),
                _sub("自動化不等於無限制生成"),
                _p("內容必須通過格式、來源、日期、引文及風險檢查，才能進入發布流程。"),
                _p("資料不足、來源衝突或無法驗證的內容將被拒絕發布；事故、飛安、法律及其他"
                   "高風險議題則必須通過相同且更嚴格的來源與證據檢查，通過後直接發布並保留"
                   "風險標記，不會為了維持更新數量而勉強產生報導。"),
            ]},
            {"heading": "自動化資料管線", "blocks": [
                _step("01", "來源監測"),
                _p("GitHub Actions 依排程啟動資料管線，檢查 FAA、ICAO、IATA、航空公司、"
                   "事故調查機構及其他可信來源的 RSS、公開 API 與官方網頁。"),
                _step("02", "資料清理"),
                _p("系統移除網站導覽、廣告、重複文字及無效頁面，並檢查發布時間、正文完整性與"
                   "來源有效性。"),
                _p("只有具備足夠內容且能夠追溯來源的資料，才會進入後續處理。"),
                _step("03", "去重與事件整合"),
                _p("系統透過網址正規化與標題文字相似度，避免同一篇內容被重複處理。"),
                _p("若多個來源報導同一事件，系統會先辨識共同資訊與差異，再建立單一新聞事件。"),
                _step("04", "多模型整理"),
                _p("合格資料會交由多模型備援系統處理，主要採用 Anthropic Claude、"
                   "OpenAI GPT 與 Google Gemini 等主流模型系列。"),
                _p("模型負責："),
                _list("提取來源中的核心事實",
                      "整理事件時間與發展狀態",
                      "將外語資訊轉為繁體中文",
                      "產生標題與新聞摘要",
                      "為重要敘述標記支持來源"),
                _p("若主要模型發生技術問題，系統才會切換至備援模型。模型給出的保守判定不會被"
                   "視為失敗，也不會為了取得更積極的答案而反覆詢問其他模型。"),
                _step("05", "程式化驗證"),
                _p("模型回傳的內容必須通過程式檢查，包括："),
                _list("JSON 與資料結構驗證",
                      "日期與時間一致性",
                      "原文引文逐字比對",
                      "敘述與支持來源的對應關係",
                      "重複事件檢查",
                      "風險標記與發布資格判斷"),
                _p("只有符合發布條件的內容才會進入網站。"),
                _step("06", "發布與溯源"),
                _p("通過驗證的報導會發布至 GitHub Pages，並保留："),
                _list("原始來源名稱",
                      "原始文章或公告連結",
                      "來源發布時間",
                      "本站整理時間",
                      "自動化產製標示"),
                _p("原始來源永遠優先於 SKYTICAL 的整理內容。"),
            ]},
            {"heading": "模型如何參與報導", "blocks": [
                _p("SKYTICAL 使用語言模型作為資訊整理與文字生成工具，而不是將模型視為事實來源。"),
                _p("模型只能根據系統提供的來源資料工作，不得自行搜尋網路，也不得使用未出現在"
                   "來源中的背景知識補足內容。"),
                _p("例如，來源只寫明某架飛機抵達某座機場，模型不得自行推測其屬於："),
                _list("包機任務", "備降", "調機", "維修飛行", "貨運任務", "外交活動",
                      "特殊旅客運輸"),
                _p("除非來源資料明確支持該項描述。"),
                _p("報導中使用的「證實」、「已核准」、「已交付」、「已投入營運」等字詞，"
                   "也必須與原始來源所表達的確定程度一致。"),
                _p("Beta 例外：每日三次的「快報」頁部分條目由具搜尋能力的模型"
                   "輔助彙整，此為唯一允許模型檢索的功能，並有硬性限制——"
                   "引用連結僅能來自檢索實際回傳的來源、社群與影音平台不列入、"
                   "論壇來源必須搭配其他來源。相關條目在頁面上標示「AI 搜尋」，"
                   "快報標題亦標示 BETA；一般新聞文章完全不適用此例外。"),
            ]},
            {"heading": "使用的模型與供應商", "blocks": [
                _p("SKYTICAL 採用多模型架構，以降低單一模型或單一供應商故障造成的影響。"),
                _p("對外公開的主要模型系列與供應商包括："),
                _list("Claude（Anthropic）",
                      "GPT（OpenAI）",
                      "Gemini（Google）"),
                _p("不同模型均受到相同規則約束，也必須通過相同的引文與資料驗證。更換模型不會"
                   "降低發布標準。"),
                _p("實際模型版本、技術路由與備援順序可能依可用性、品質測試與服務條件調整。"
                   "本方法論頁面僅列出大眾熟悉的主要模型家族；無論內部如何切換，來源驗證規則"
                   "與發布標準都保持一致。"),
            ]},
            {"heading": "來源選擇", "blocks": [
                _p("SKYTICAL 優先採用第一手或具有明確編輯責任的來源，例如："),
                _list("民航主管機關",
                      "航空事故調查機構",
                      "國際航空組織",
                      "機場與航空公司正式公告",
                      "飛機製造商及發動機製造商",
                      "可信新聞機構",
                      "具明確授權條件的公開資料服務"),
                _p("社群媒體貼文、轉載內容或無法確認原始出處的資訊，不會單獨作為自動發布的"
                   "重要事實依據。"),
            ]},
            {"heading": "更新頻率", "blocks": [
                _p("主要新聞資料管線原則上每小時執行一次。"),
                _p("實際發布時間可能受到以下因素影響："),
                _list("原始來源更新時間",
                      "網站或 API 暫時無法存取",
                      "資料完整性檢查",
                      "多來源去重",
                      "模型服務可用性",
                      "高風險內容覆核"),
                _p("因此，排程啟動時間不等於每小時一定會產生新文章。沒有足夠且可驗證的新資料時，"
                   "系統不會為了填補版面而生成內容。"),
            ]},
            {"heading": "透明度與開放原始碼", "blocks": [
                _p("SKYTICAL 的核心程式碼公開於 GitHub，讀者可以檢視資料擷取、去重、模型呼叫、"
                   "驗證及發布流程。"),
                _pre(_REPO_TREE_ZH),
                _p("實際目錄可能隨系統持續開發而調整，GitHub Repository 中的版本為準。"),
                _p("為保護服務安全，API 金鑰、管理員憑證及其他機密資訊不會公開於原始碼或"
                   "網站前端。"),
            ]},
            {"heading": "更正與限制", "blocks": [
                _p("自動化系統能提高更新速度與處理範圍，但無法保證完全沒有錯誤。"),
                _p("可能影響結果的因素包括："),
                _list("原始來源本身發生更正",
                      "RSS 或公開 API 資料不完整",
                      "發布時間或時區標示不一致",
                      "語言模型對內容理解有誤",
                      "多來源對同一事件的描述不同",
                      "即時資料受到覆蓋率或更新延遲影響"),
                _p("發現問題時，SKYTICAL 可更新、撤回或標記相關內容。具有權威效力的資訊，"
                   "仍應以主管機關、航空公司、機場或其他原始發布單位為準。"),
            ]},
        ],
        "disc_title": "免責聲明",
        "disclaimer": "本站提供的是航空資訊整理服務，不構成飛安操作、法律、法規遵循或投資建議。",
    },
    "en": {
        "heading": "Content production & verification",
        "intro": [
            "SKYTICAL is an aviation information platform built around trusted sources, "
            "fast updates and full traceability.",
            "The system continuously tracks public information released by civil aviation "
            "authorities, international organizations, airlines and trusted news outlets, "
            "organizes events through an automated data pipeline, and then uses "
            "widely recognized language-model families such as Anthropic Claude, "
            "OpenAI GPT and Google Gemini "
            "to help produce the Traditional Chinese and English reports.",
            "The models are not a news source and never invent information. Every article "
            "must be built on source material the system actually obtained, with the "
            "original references kept at the end so readers can verify directly.",
        ],
        "sections": [
            {"heading": "Our core principles", "blocks": [
                _sub("Sources before models"),
                _p("SKYTICAL reporting starts from trusted sources, not from a language model."),
                _p("The system first obtains official announcements, press releases, RSS "
                   "feeds, open APIs or trusted media reports, and only then hands the "
                   "collected material to a model. The model may use only the source "
                   "content given to it — no outside knowledge, no unsupported inference."),
                _sub("Every key fact is traceable"),
                _p("Core facts in a story must map back to the original material. The "
                   "system keeps the source URL, the publication time, and the original "
                   "wording that supports the key statements."),
                _p("Every article ends with a Sources box, so readers can open the "
                   "original announcement or report and check for themselves."),
                _sub("Automation is not unlimited generation"),
                _p("Content must pass format, source, date, quotation and risk checks "
                   "before it can enter the publishing flow."),
                _p("Content that is insufficient, conflicting or unverifiable is "
                   "rejected. Accident, flight-safety, legal and other high-risk stories "
                   "must pass the same, stricter source and evidence checks; passing "
                   "stories publish directly with their risk flags retained. The system "
                   "never forces out a story just to keep the update count up."),
            ]},
            {"heading": "Automated data pipeline", "blocks": [
                _step("01", "Source monitoring"),
                _p("GitHub Actions starts the pipeline on schedule, checking RSS feeds, "
                   "open APIs and official pages of the FAA, ICAO, IATA, airlines, "
                   "accident investigators and other trusted sources."),
                _step("02", "Cleaning"),
                _p("The system strips navigation, ads, duplicated text and dead pages, "
                   "and checks publication time, body completeness and source validity."),
                _p("Only material with enough substance and a traceable source moves on."),
                _step("03", "Dedup & event merging"),
                _p("URL normalization and title-text similarity keep the same piece from "
                   "being processed twice."),
                _p("When several sources cover one event, the system identifies what they "
                   "share and where they differ, then builds a single news event."),
                _step("04", "Multi-model compilation"),
                _p("Qualified material goes to a multi-model failover system built around "
                   "widely recognized model families including Anthropic Claude, "
                   "OpenAI GPT and Google Gemini."),
                _p("The models are responsible for:"),
                _list("Extracting the core facts from the sources",
                      "Organizing event timelines and development status",
                      "Rendering source information into Traditional Chinese and English",
                      "Producing the headline and summary",
                      "Tagging the supporting source for each key statement"),
                _p("The system switches to a backup model only when the primary has a "
                   "technical problem. A conservative call from a model is not treated as "
                   "a failure, and the system never re-asks other models to get a more "
                   "aggressive answer."),
                _step("05", "Programmatic validation"),
                _p("Everything a model returns must pass code-level checks, including:"),
                _list("JSON and data-structure validation",
                      "Date and time consistency",
                      "Verbatim quote matching against the source",
                      "Statement-to-source mapping",
                      "Duplicate-event checks",
                      "Risk flags and publish-eligibility rules"),
                _p("Only content that meets the publishing bar reaches the site."),
                _step("06", "Publishing & traceability"),
                _p("Validated stories are published to GitHub Pages, keeping:"),
                _list("The original source names",
                      "Links to the original articles or announcements",
                      "The source publication time",
                      "The time this site compiled the story",
                      "An automated-production label"),
                _p("The original sources always prevail over SKYTICAL's compilation."),
            ]},
            {"heading": "How models take part", "blocks": [
                _p("SKYTICAL uses language models as tools for organizing information and "
                   "generating text — never as a source of facts."),
                _p("Models work only from the source material the system provides. They "
                   "may not search the web, and may not fill gaps with background "
                   "knowledge that does not appear in the sources."),
                _p("For example, if a source only says an aircraft arrived at an airport, "
                   "the model may not speculate that the flight was:"),
                _list("A charter mission", "A diversion", "A repositioning flight",
                      "A maintenance flight", "A cargo mission", "A diplomatic movement",
                      "Special passenger transport"),
                _p("unless the sources explicitly support that description."),
                _p("Words like “confirmed”, “approved”, “delivered” or “entered service” "
                   "must match the level of certainty expressed by the original source."),
                _p("Beta exception: some entries on the thrice-daily "
                   "briefing pages are compiled with a search-capable "
                   "model - the only place model retrieval is allowed, "
                   "under hard limits: cited links must come from actually "
                   "retrieved results, social/video platforms are excluded, "
                   "and forum sources need a companion source. Such entries "
                   "are tagged \"AI search\" and the briefing carries a "
                   "BETA mark; regular articles are never covered by this "
                   "exception."),
            ]},
            {"heading": "Models and providers", "blocks": [
                _p("SKYTICAL runs a multi-model architecture to limit the impact of any "
                   "single model or vendor failing."),
                _p("The main model families and providers disclosed publicly are:"),
                _list("Claude (Anthropic)",
                      "GPT (OpenAI)",
                      "Gemini (Google)"),
                _p("Every model is bound by the same rules and must pass the same "
                   "quotation and data checks. Switching models never lowers the "
                   "publishing bar."),
                _p("Exact model versions, technical routing and fallback order may change "
                   "with availability, quality testing and service terms. The Methodology "
                   "lists only the major model families familiar to general readers; the "
                   "source-verification rules and publishing bar stay the same regardless "
                   "of internal routing."),
            ]},
            {"heading": "Source selection", "blocks": [
                _p("SKYTICAL prefers first-hand sources, or sources with clear editorial "
                   "accountability, such as:"),
                _list("Civil aviation authorities",
                      "Accident investigation agencies",
                      "International aviation organizations",
                      "Official airport and airline announcements",
                      "Airframe and engine manufacturers",
                      "Trusted news organizations",
                      "Open data services with clear licensing terms"),
                _p("Social media posts, reposts, or material whose original source cannot "
                   "be confirmed are never the sole basis for a key fact in an "
                   "automatically published story."),
            ]},
            {"heading": "Update cadence", "blocks": [
                _p("As a rule, the main news pipeline runs once every hour."),
                _p("Actual publication timing can be affected by:"),
                _list("When the original sources update",
                      "Temporary site or API outages",
                      "Data completeness checks",
                      "Cross-source deduplication",
                      "Model service availability",
                      "Human review of high-risk content"),
                _p("A scheduled run therefore does not guarantee a new article every "
                   "hour. When there is no sufficient, verifiable new material, the "
                   "system does not generate content to fill space."),
            ]},
            {"heading": "Transparency & open source", "blocks": [
                _p("SKYTICAL's core code is public on GitHub; readers can inspect the "
                   "fetching, deduplication, model calls, validation and publishing "
                   "flow."),
                _pre(_REPO_TREE_EN),
                _p("The actual layout may evolve as the system develops; the GitHub "
                   "repository is authoritative."),
                _p("To protect the service, API keys, administrative credentials and "
                   "other secrets are never published in the source code or the site "
                   "frontend."),
            ]},
            {"heading": "Corrections & limitations", "blocks": [
                _p("Automation increases speed and coverage, but cannot guarantee zero "
                   "errors."),
                _p("Factors that can affect the output include:"),
                _list("The original source issuing a correction",
                      "Incomplete RSS or open-API data",
                      "Inconsistent publication-time or timezone labeling",
                      "A language model misreading the content",
                      "Sources describing the same event differently",
                      "Coverage or update-latency limits in live data"),
                _p("When a problem is found, SKYTICAL may update, retract or flag the "
                   "content. For anything authoritative, defer to the regulator, "
                   "airline, airport or other original publisher."),
            ]},
        ],
        "disc_title": "Disclaimer",
        "disclaimer": "SKYTICAL is an aviation information compilation service. Nothing on "
                      "this site is flight-operations, legal, regulatory-compliance or "
                      "investment advice.",
    },
}

# (the design's 「　▪　」 ticker separator now lives in base.html/.ticker-sep)

# Footer source-tag order, exactly as in the design footer.
FOOTER_ORDER = ["faa", "icao", "iata", "ntsb", "easa", "eurocontrol",
                "reuters", "avherald", "flightaware", "caataiwan"]
FOOTER_SOURCES = [{"name": SOURCES[k]["name"], "url": SOURCES[k]["url"]}
                  for k in FOOTER_ORDER if k in SOURCES]

FAVICON = f"{BASE_PATH}/assets/skytical-mark.svg?v={ASSET_VERSION}"

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
NEWS_NS = "http://www.google.com/schemas/sitemap-news/0.9"
ET.register_namespace("", SITEMAP_NS)
ET.register_namespace("news", NEWS_NS)


# ── small helpers ────────────────────────────────────────────────────────────

def _bi(value, lang: str, fallback: str = "") -> str:
    """Resolve a bilingual field ({zh,en} dict or plain string)."""
    if isinstance(value, dict):
        other = "en" if lang == "zh" else "zh"
        v = value.get(lang) or value.get(other)
        return str(v) if v else fallback
    if value is None or value == "":
        return fallback
    return str(value)


def fmt_int(v) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "—"
    return f"{int(v):,}" if float(v).is_integer() else f"{v:,}"


def fmt_pct(v) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return "—"
    return f"{v:g}%"


def clock_12(dt) -> str:
    """User-facing clock time without seconds or a leading zero."""
    return dt.strftime("%I:%M %p").lstrip("0")


def timestamp_12(value, empty: str) -> str:
    """Format a stored UTC timestamp for display without leaking seconds."""
    if not value:
        return empty
    try:
        stamp = parse_iso(str(value)).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return empty
    return f"{stamp:%Y-%m-%d} {clock_12(stamp)}"


def ago(last_utc, now) -> str:
    """Relative 'ago' string vs build time: '12 min' / '3 hr' / '2 d' / '—'."""
    if not last_utc:
        return "—"
    try:
        dt = parse_iso(str(last_utc))
    except (ValueError, TypeError):
        return "—"
    mins = max(0, int((now - dt).total_seconds() // 60))
    if mins < 60:
        return f"{mins} min"
    if mins < 48 * 60:
        return f"{mins // 60} hr"
    return f"{mins // (24 * 60)} d"


def _safe_web_url(url: str) -> bool:
    """Only http(s) URLs may reach href/src attributes (feeds are untrusted)."""
    try:
        return urlsplit(url).scheme.lower() in ("http", "https")
    except ValueError:
        return False


def _public_direct_url(url: str) -> bool:
    """Only safe, direct original URLs may be shown as public sources."""
    value = str(url or "").strip()
    return bool(value) and _safe_web_url(value) and not is_google_news_url(value)


def normalize_image(raw_img):
    """Article image -> {url, link, credit, license, provider, kind} or None.

    Accepts the images.py match dict or a plain URL string (legacy).
    Only http(s) URLs survive; a credited external embed keeps its
    attribution and backlink so CC/photographer terms are honored.
    """
    if isinstance(raw_img, dict):
        url = str(raw_img.get("url") or "")
        if not url or not _safe_web_url(url):
            return None
        link = str(raw_img.get("link") or "")
        return {
            "url": url,
            "link": link if link and _safe_web_url(link) else None,
            "credit": str(raw_img.get("credit") or "") or None,
            "license": str(raw_img.get("license") or "") or None,
            "provider": str(raw_img.get("provider") or "") or None,
            "subject": str(raw_img.get("subject") or "") or None,
            "kind": (raw_img.get("kind")
                     if raw_img.get("kind") in ("airframe_photo",
                                                "file_photo",
                                                "event_photo")
                     else "file_photo"),
        }
    if raw_img:
        url = str(raw_img)
        if not _safe_web_url(url):
            return None
        return {"url": url, "link": None, "credit": None, "license": None,
                "provider": None, "subject": None, "kind": "file_photo"}
    return None


def rel_path(lang: str, sub: str) -> str:
    return ("en/" + sub) if lang == "en" else sub


def page_url(lang: str, sub: str) -> str:
    """URL for a page; sub is '' or 'incidents/' or 'news/<id>/' …"""
    return f"{BASE_PATH}/{'en/' if lang == 'en' else ''}{sub}"


def absolute_page_url(lang: str, sub: str) -> str:
    return SITE_ORIGIN + page_url(lang, sub)


def iso_timestamp(dt) -> str:
    """Stable W3C timestamp for structured data and XML sitemaps."""
    return (dt.astimezone(timezone.utc).isoformat(timespec="seconds")
            .replace("+00:00", "Z"))


# ── data loading / preparation ───────────────────────────────────────────────

# Article-footer model credit: writer id -> short public model name.
_WRITER_MODELS = (
    ("gpt-5.6-sol", "GPT-5.6 Sol"),
    ("nemotron-3-ultra", "Nemotron 3 Ultra"),
    ("nemotron-3-super", "Nemotron 3 Super"),
    ("nemotron", "Nemotron"),
    ("deepseek-v4-pro", "DeepSeek V4 Pro"),
    ("deepseek", "DeepSeek"),
    ("gemini-3.6-flash", "Gemini 3.6 Flash"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini", "Gemini"),
    ("qwen3.5", "Qwen 3.5"),
    ("qwen", "Qwen"),
    ("glm-5.2", "GLM-5.2"),
    ("glm", "GLM"),
    ("mistral-medium-3.5", "Mistral Medium 3.5"),
    ("mistral", "Mistral"),
    ("claude-opus-5", "Claude Opus 5"),
    ("claude", "Claude"),
)


def writer_model(writer, writer_models=None):
    """Public model credit, including up to five owner-supplied labels."""
    if isinstance(writer_models, list):
        labels = []
        for value in writer_models[:5]:
            clean = re.sub(r"[\x00-\x1f\x7f<>]+", " ", str(value))
            clean = re.sub(r"\s+", " ", clean).strip()[:80]
            if clean and clean not in labels:
                labels.append(clean)
        if labels:
            return "、".join(labels)
    if not isinstance(writer, str) or ":" not in writer:
        return None
    provider, model_value = writer.split(":", 1)
    if provider == "manual":
        exact = re.sub(r"[\x00-\x1f\x7f<>]+", " ", model_value)
        exact = re.sub(r"\s+", " ", exact).strip()
        return exact[:80] or None
    model_id = model_value.lower()
    for needle, model in _WRITER_MODELS:
        if needle in model_id:
            return model
    configured_name = MODEL_DISPLAY_NAMES.get(writer)
    if configured_name:
        return configured_name.removeprefix("OpenRouter · ")
    return None


def prep_article(raw):
    if not isinstance(raw, dict):
        return None
    if raw.get("archived") is True:
        return None
    art_id = raw.get("id")
    if not isinstance(art_id, str) or not _ID_RE.match(art_id.strip()):
        return None
    art_id = art_id.strip()
    try:
        publication_dt = parse_iso(str(raw.get("publishedUtc")))
    except (ValueError, TypeError):
        return None
    dt = publication_dt
    modified_dt = publication_dt
    if raw.get("updatedUtc"):
        try:
            modified_dt = max(publication_dt,
                              parse_iso(str(raw["updatedUtc"])))
        except (ValueError, TypeError):
            pass
    if raw.get("sortUtc"):
        try:
            dt = parse_iso(str(raw["sortUtc"]))
        except (ValueError, TypeError):
            # Optional manual-placement metadata must not hide a valid article.
            dt = publication_dt
    zh = raw.get("zh") if isinstance(raw.get("zh"), dict) else {}
    en = raw.get("en") if isinstance(raw.get("en"), dict) else {}
    if not (zh.get("title") or en.get("title")):
        return None

    def side(own, other):
        body = own.get("body")
        if not isinstance(body, (list, str)) or not body:
            body = other.get("body")
        if isinstance(body, str):
            body = [body]
        if not isinstance(body, list):
            body = []
        return {
            "title": str(own.get("title") or other.get("title") or ""),
            "summary": str(own.get("summary") or other.get("summary") or ""),
            "body": [str(p) for p in body if str(p).strip()],
        }

    sources = []
    for s in raw.get("sources") or []:
        if isinstance(s, dict) and s.get("url"):
            url = str(s["url"])
            if (not _safe_web_url(url) or is_google_news_url(url)):
                # Google News is a discovery aggregator, not an original
                # source URL that should be exposed or credited publicly.
                continue
            try:
                host = urlsplit(url).netloc
            except ValueError:
                host = ""
            sources.append({"n": f"{len(sources) + 1}.",
                            "name": str(s.get("name") or host or url),
                            "url": url, "host": host})
    if not sources:
        # Hard site rule: every published article must credit >=1 source.
        return None

    cat = story_category(raw.get("cat"), raw)
    raw_languages = raw.get("availableLanguages")
    available_languages = [
        lang for lang in ("zh", "en")
        if isinstance(raw_languages, list) and lang in raw_languages
    ]
    if not available_languages:
        available_languages = ["zh", "en"]
    image = normalize_image(raw.get("image"))
    # Display the SOURCE's newest publication time when the write stage
    # recorded one; the generation time (dt) is used for ordering only, so
    # a days-old official release is never presented as breaking news.
    display_dt = publication_dt
    if raw.get("sourcePublishedUtc"):
        try:
            display_dt = parse_iso(str(raw["sourcePublishedUtc"]))
        except (ValueError, TypeError):
            pass
    tpe = display_dt.astimezone(TPE)
    publication_tpe = publication_dt.astimezone(TPE)
    modified_tpe = modified_dt.astimezone(TPE)
    today_tpe = now_utc().astimezone(TPE).date()
    # Date-only source stamps (FAA/CAA give no clock time -> 00:00Z) must
    # not render as a precise-looking "08:00" TPE: show the date instead.
    date_only = (raw.get("sourcePublishedUtc")
                 and display_dt.hour == 0 and display_dt.minute == 0)
    if date_only:
        time_label = tpe.strftime("%m/%d")
        meta_ts = tpe.strftime("%Y-%m-%d")
    else:
        time_label = (clock_12(tpe) if tpe.date() == today_tpe
                      else tpe.strftime("%m/%d"))
        meta_ts = f"{tpe:%Y-%m-%d} {clock_12(tpe)} UTC+8"
    return {
        "id": art_id,
        "dt": dt,
        "published_dt": publication_dt,
        "modified_dt": modified_dt,
        "published_iso": iso_timestamp(publication_dt),
        "modified_iso": iso_timestamp(modified_dt),
        "published_meta_ts": (
            f"{publication_tpe:%Y-%m-%d} {clock_12(publication_tpe)} UTC+8"),
        "modified_meta_ts": (
            f"{modified_tpe:%Y-%m-%d} {clock_12(modified_tpe)} UTC+8"),
        "cat": cat,
        "tag_class": TAGCLS.get(cat, "tag-neutral"),
        "image": image,
        "source": str(raw.get("primarySource") or (sources[0]["name"] if sources else "—")),
        "time": time_label,
        "meta_ts": meta_ts,
        "zh": side(zh, en),
        "en": side(en, zh),
        "sources": sources,
        "writer_model": writer_model(
            raw.get("writer"), raw.get("writerModels")),
        "available_languages": available_languages,
        "article_format": (
            raw.get("articleFormat")
            if raw.get("articleFormat") in ("brief", "roundup")
            else "full"),
    }


def collect_articles():
    arts = []
    if ARTICLES_DIR.is_dir():
        for path in sorted(ARTICLES_DIR.glob("*.json")):
            data = load_json(path, None)
            rows = data.get("articles") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                print(f"build: {path.name}: no articles[] — skipped")
                continue
            for raw in rows:
                art = prep_article(raw)
                if art is None:
                    reason = ("archived article skipped"
                              if isinstance(raw, dict)
                              and raw.get("archived") is True
                              else "bad article entry skipped")
                    print(f"build: {path.name}: {reason}")
                elif not is_transport_headline(raw):
                    print(f"build: {path.name}: non-transport headline skipped")
                else:
                    arts.append(art)
    by_id = {}
    for a in arts:
        prev = by_id.get(a["id"])
        if prev is None or a["dt"] > prev["dt"]:
            by_id[a["id"]] = a
    return sorted(by_id.values(), key=lambda a: a["dt"], reverse=True)


@lru_cache(maxsize=2)
def header_search_placeholders(lang: str) -> tuple[str, ...]:
    """Load the daily LLM output, with the built-in prompts as fallback."""
    fallback = tuple(L[lang]["headerSearchPlaceholders"])
    payload = load_json(DATA_DIR / "search-prompts.json", {})
    prompts = ((payload.get("prompts") or {}).get(lang)
               if isinstance(payload, dict) else None)
    if not isinstance(prompts, list) or not 2 <= len(prompts) <= 8:
        return fallback
    cleaned = []
    for value in prompts:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text or len(text) > 96 or re.search(r"[\x00-\x1f<>]", text):
            return fallback
        cleaned.append(text)
    return tuple(cleaned) if len(set(cleaned)) == len(cleaned) else fallback


def _keyword_summary(value: str, lang: str, limit: int) -> str:
    """Turn verified text into a bounded line of complete factual clauses."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if lang == "zh":
        text = re.sub(r"^(?:根據|據)[^，]{2,30}(?:報導|資料|消息)[，,]", "", text)
        text = re.sub(r"[，。！？：—–|]+", "；", text)
        parts = [part.strip("； ") for part in text.split("；")
                 if part.strip("； ")]
        selected = []
        for part in parts[:3]:
            candidate = "；".join([*selected, part])
            if len(candidate) <= limit:
                selected.append(part)
                continue
            if not selected:
                selected.append(part[:limit].rstrip("，；、 "))
            break
        return "；".join(selected).rstrip("。； ")

    text = re.sub(r"\s*[:—–|]+\s*", "; ", text)
    words = text.split()
    return " ".join(words[:limit]).rstrip(".,;: ")


def _compact_mixed_title(value: str) -> str:
    """Remove cosmetic CJK/Latin spacing without splitting proper names."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"(?<=[一-鿿）])\s+(?=[A-Za-z0-9「（])", "", text)
    return re.sub(r"(?<=[A-Za-z0-9」）])\s+(?=[一-鿿（])", "", text)


def notification_summary(value: str, lang: str, title: str = "") -> str:
    """Return a complete two-line summary without visual ellipsis."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return text
    if lang == "zh":
        limit = 38
        if len(text) <= limit:
            return text.rstrip("。 ")
        title_text = _compact_mixed_title(title)
        if title_text and len(title_text) <= limit:
            return title_text.rstrip("。 ")
        return _keyword_summary(text, lang, limit)

    words = text.split()
    limit_words = 14
    if len(words) <= limit_words:
        return text.rstrip(". ")
    title_text = re.sub(r"\s+", " ", str(title or "")).strip()
    if title_text and len(title_text.split()) <= limit_words:
        return title_text.rstrip(". ")
    return _keyword_summary(text, lang, limit_words)


def art_view(a, lang: str):
    v = dict(a[lang])
    v["display_summary"] = notification_summary(
        v.get("summary"), lang, v.get("title"))
    v.update(
        id=a["id"], cat=a["cat"], tag_class=a["tag_class"], image=a["image"],
        cat_label=_bi(CATS.get(a["cat"]), lang, a["cat"]),
        source=a["source"], time=a["time"], meta_ts=a["meta_ts"],
        sources=a["sources"], url=page_url(lang, f"news/{a['id']}/"),
        writer_model=a["writer_model"],
        article_format=a["article_format"],
        published_iso=a["published_iso"],
        modified_iso=a["modified_iso"],
        published_meta_ts=a["published_meta_ts"],
        modified_meta_ts=a["modified_meta_ts"],
        external=False,
    )
    return v



HERO_ROTATION_SECONDS = 5 * 60
_HERO_PIN_MAX_AGE = timedelta(hours=16)
_HERO_WEATHER_RE = re.compile(
    r"(?:颱風|台風|熱帶(?:性)?(?:低氣壓|風暴)|豪大雨|豪雨|暴雨|大雨|"
    r"強降雨|雷雨|強風|暴風|寒流|寒害|大雪|降雪|冰雹|濃霧|大霧|"
    r"低能見度|沙塵暴|洪水|淹水|地震|海嘯|氣象|"
    r"typhoon|tropical storm|tropical depression|hurricane|heavy rain|"
    r"rainstorm|thunderstorm|strong winds?|gale|fog|low visibility|"
    r"snow|hail|flood|earthquake|tsunami|weather)",
    re.IGNORECASE,
)
_HERO_NATIONAL_AIRLINE_RE = re.compile(
    r"(?:國籍航空|臺灣航空|台灣航空|華航|中華航空|長榮航空|星宇航空|"
    r"台灣虎航|臺灣虎航|立榮航空|華信航空|Taiwan(?:ese)? carriers?|"
    r"China Airlines|EVA Air|STARLUX|Tigerair Taiwan|UNI Air|"
    r"Mandarin Airlines)",
    re.IGNORECASE,
)
_HERO_FLIGHT_CHANGE_RE = re.compile(
    r"(?:航班|班機|航線|飛航|取消|停飛|延後|延誤|調整|異動|加班機|"
    r"疏運|改期|轉降|停駛|flight|flights|air service|schedule|"
    r"cancel|suspend|delay|divert|rerout|extra flight|relief flight)",
    re.IGNORECASE,
)


def is_weather_airline_flight_story(article, now=None) -> bool:
    """Return True for fresh weather-driven national-airline changes.

    Only headline-level fields participate, so a secondary weather mention in
    a long article body cannot unexpectedly take over the homepage hero.
    """
    if not isinstance(article, dict):
        return False
    published = article.get("published_dt")
    if published is None:
        return False
    now = now or now_utc()
    try:
        age = now - published
    except TypeError:
        return False
    if age < timedelta(0) or age > _HERO_PIN_MAX_AGE:
        return False

    values = [article.get("source"), article.get("primarySource")]
    for lang in ("zh", "en"):
        side = article.get(lang)
        if isinstance(side, dict):
            values.extend(side.get(key) for key in ("title", "summary"))
    text = " ".join(str(value or "") for value in values)
    return bool(
        _HERO_WEATHER_RE.search(text)
        and _HERO_NATIONAL_AIRLINE_RE.search(text)
        and _HERO_FLIGHT_CHANGE_RE.search(text)
    )


def _hero_image_caption(image, lang: str) -> str:
    if not isinstance(image, dict):
        return (
            "暫無可驗證的事件或資料照片，先顯示 SKYTICAL 預設圖片。"
            if lang == "zh"
            else "No verified event or file photo is available yet; "
                 "showing the SKYTICAL default image."
        )
    parts = []
    if image.get("subject"):
        parts.append(str(image["subject"]))
    kind = str(image.get("kind") or "")
    kind_label = L[lang]["photoKind"].get(kind)
    if kind_label:
        parts.append(kind_label)
    if image.get("credit"):
        parts.append(f"© {image['credit']}")
    if image.get("license"):
        parts.append(str(image["license"]))
    if image.get("provider"):
        parts.append(str(image["provider"]))
    return " · ".join(parts)


def hero_rotation_view(view, lang: str) -> dict:
    """Return the small JSON-safe payload used by the five-minute hero swap."""
    image = view.get("image") if isinstance(view.get("image"), dict) else None
    labels = [str(view.get("cat_label") or "")]
    if view.get("article_format") == "brief":
        labels.append(L[lang]["briefLabel"])
    elif view.get("article_format") == "roundup":
        labels.append(L[lang]["roundupLabel"])
    return {
        "id": view.get("id"),
        "url": view.get("url"),
        "external": bool(view.get("external")),
        "title": view.get("title") or "",
        "summary": view.get("display_summary") or "",
        "kicker": f"{' · '.join(label for label in labels if label)}"
                  f" — {L[lang]['topStory']}",
        "time": view.get("time") or "",
        "source_meta": f"{L[lang]['mainSource']}: "
                       f"{view.get('source') or '—'}",
        "image": image,
        "image_alt": (
            str(image.get("subject") or "SKYTICAL")
            if image else "SKYTICAL"
        ),
        "image_caption": _hero_image_caption(image, lang),
    }


def normalize_search_text(value) -> str:
    """Normalize human-entered/search-index text without losing CJK words."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[^\w]+", " ", text, flags=re.UNICODE).strip()


def topic_articles(articles, slug: str):
    """Return articles belonging to a durable editorial topic hub."""
    topic = TOPICS[slug]
    cats = topic.get("cats")
    if cats:
        return [article for article in articles if article["cat"] in cats]

    terms = topic.get("terms") or ()
    matched = []
    for article in articles:
        text = " ".join([
            article["zh"]["title"], article["zh"]["summary"],
            *article["zh"]["body"], article["en"]["title"],
            article["en"]["summary"], *article["en"]["body"],
        ]).casefold()
        for term in terms:
            needle = term.casefold()
            if re.fullmatch(r"[a-z0-9 ]+", needle):
                if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                             text):
                    matched.append(article)
                    break
            elif needle in text:
                matched.append(article)
                break
    return matched


def load_search_alias_groups() -> list[tuple[str, ...]]:
    """Load bounded, duplicate-free alias groups used to expand the index."""
    path = Path(__file__).resolve().parent.parent / "config" / "search_aliases.json"
    raw = load_json(path, {})
    groups = []
    for row in (raw.get("groups") if isinstance(raw, dict) else []) or []:
        aliases = row.get("aliases") if isinstance(row, dict) else None
        if not isinstance(aliases, list):
            continue
        clean = []
        seen = set()
        for value in aliases[:20]:
            alias = re.sub(r"\s+", " ", str(value)).strip()[:80]
            norm = normalize_search_text(alias)
            if alias and norm and norm not in seen:
                clean.append(alias)
                seen.add(norm)
        if len(clean) >= 2:
            groups.append(tuple(clean))
    return groups[:200]


def _search_text_has_alias(normalized_text: str, alias: str) -> bool:
    needle = normalize_search_text(alias)
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9]+", needle):
        return re.search(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
            normalized_text,
        ) is not None
    return needle in normalized_text


def expand_search_aliases(text: str, groups=None) -> list[str]:
    """Return every alias from groups represented by at least one term."""
    normalized = normalize_search_text(text)
    matched = []
    for group in groups if groups is not None else load_search_alias_groups():
        if any(_search_text_has_alias(normalized, alias) for alias in group):
            matched.extend(group)
    return matched


def search_index_item(article, alias_groups) -> dict:
    """Build one bilingual, full-text record for the static client index.

    Titles, summaries and display metadata are already stored as structured
    fields below.  Keep only body/source text plus matched aliases in the
    opaque search field; the browser adds the structured fields while scoring.
    This removes a large amount of duplicated text from the public index.
    """
    searchable = []
    raw_searchable = [
        article["id"], article["cat"], article["source"], article["meta_ts"],
        _bi(CATS.get(article["cat"]), "zh", article["cat"]),
        _bi(CATS.get(article["cat"]), "en", article["cat"]),
    ]
    for lang in ("zh", "en"):
        raw_searchable.extend([
            article[lang]["title"], article[lang]["summary"],
            *article[lang]["body"],
        ])
    for source in article["sources"]:
        raw_searchable.extend([source["name"], source["host"]])
        searchable.extend([source["name"], source["host"]])
    for lang in ("zh", "en"):
        searchable.extend(article[lang]["body"])
    raw_search = " ".join(str(value) for value in raw_searchable if value)
    searchable.extend(expand_search_aliases(raw_search, alias_groups))
    urls = {
        lang: page_url(lang, f"news/{article['id']}/")
        for lang in article["available_languages"]
    }
    return {
        "id": article["id"],
        "title": {lang: article[lang]["title"] for lang in ("zh", "en")},
        "summary": {
            lang: article[lang]["summary"] for lang in ("zh", "en")
        },
        "category": {
            lang: _bi(CATS.get(article["cat"]), lang, article["cat"])
            for lang in ("zh", "en")
        },
        "source": article["source"],
        "date": article["meta_ts"],
        "published": article["dt"].isoformat(),
        "articleFormat": article["article_format"],
        "availableLanguages": article["available_languages"],
        "url": urls,
        "search": normalize_search_text(" ".join(
            str(value) for value in searchable if value)),
    }


def search_index_payload(articles, generated_utc) -> dict:
    alias_groups = load_search_alias_groups()
    return {
        "version": 1,
        "generatedUtc": generated_utc.isoformat(),
        "count": len(articles),
        "items": [search_index_item(article, alias_groups)
                  for article in articles],
    }


def search_aliases_payload() -> dict:
    """Publish the sanitized alias map used by article highlighting."""
    return {
        "version": 1,
        "groups": [list(group) for group in load_search_alias_groups()],
    }


def collect_agg_items(now):
    """Aggregation fallback: when no LLM-written articles exist yet, surface
    the newest raw source headlines directly (free, no-API mode)."""
    items, seen = [], set()
    cutoff = now - timedelta(hours=48)
    for key, reg in SOURCES.items():
        raw = load_json(RAW_DIR / f"{key}.json", None)
        if not isinstance(raw, dict) or not raw.get("ok"):
            continue
        for it in raw.get("items") or []:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            url = str(it.get("url") or "").strip()
            if not title or not url.startswith(("http://", "https://")):
                continue
            try:
                dt = parse_iso(str(it.get("publishedUtc")))
            except (ValueError, TypeError):
                continue
            if dt < cutoff or dt > now + timedelta(hours=2):
                continue
            k = norm_url(url)
            if k in seen:
                continue
            seen.add(k)
            image = normalize_image(it.get("image"))
            items.append({
                "dt": dt, "title": title, "url": url,
                "summary": str(it.get("summary") or "").strip(),
                "image": image,
                "source": reg["name"], "kind": reg["kind"],
                # first-seen stamps must never be shown as publish times
                "date_inferred": bool(it.get("dateInferred")),
            })
    items.sort(key=lambda i: i["dt"], reverse=True)
    return items[: HOME_FEED_LIMIT + 1]  # +1: first item becomes the hero


def _honest_time_label(dt, inferred: bool) -> str:
    """HH:MM only for today's real timestamps; m/d for older ones; a dash
    when the source never provided a publish time (inferred stamp)."""
    if inferred:
        return "—"
    tpe = dt.astimezone(TPE)
    if tpe.date() == now_utc().astimezone(TPE).date():
        return clock_12(tpe)
    return tpe.strftime("%m/%d")


def agg_view(items, lang: str):
    out = []
    for it in items:
        summary = it["summary"]
        if len(summary) > 200:
            summary = summary[:200].rstrip() + "…"
        out.append({
            "cat": "agg", "tag_class": "tag-neutral",
            "cat_label": _bi(KIND.get(it["kind"]), lang, it["kind"]),
            "title": it["title"], "summary": summary,
            "source": it["source"],
            "time": _honest_time_label(it["dt"], it.get("date_inferred", False)),
            "url": it["url"], "external": True, "image": it["image"],
        })
    return out


def agg_flashes(views):
    out = []
    for v in views[:MAX_FLASHES]:
        text = v["title"]
        if len(text) > 68:
            text = text[:68].rstrip() + "…"
        out.append({"time": v["time"], "hot": False, "pinned": False,
                    "priority": False,
                    "text": text,
                    "url": v["url"], "external": True})
    return out


def prep_flashes(raw, known_ids):
    out = []
    if not isinstance(raw, list):
        if raw is not None:
            print("build: flashes.json malformed — ignored")
        return out
    for f in raw:
        if not isinstance(f, dict):
            continue
        if f.get("archived") is True:
            continue
        try:
            dt = parse_iso(str(f.get("timeUtc")))
        except (ValueError, TypeError):
            continue
        zh = str(f.get("zh") or f.get("en") or "").strip()
        en = str(f.get("en") or f.get("zh") or "").strip()
        if not zh:
            continue
        aid = f.get("articleId")
        if isinstance(aid, str) and aid not in known_ids:
            # A hidden/archived article must not leave an orphan ticker item.
            continue
        out.append({
            "time": clock_12(dt.astimezone(TPE)),
            "hot": bool(f.get("hot")),
            "pinned": bool(f.get("pinned")),
            "zh": zh, "en": en,
            "articleId": aid if isinstance(aid, str) and aid in known_ids else None,
            "available_languages": [
                lang for lang in ("zh", "en")
                if not isinstance(f.get("availableLanguages"), list)
                or lang in f["availableLanguages"]
            ],
        })
        if len(out) >= MAX_FLASHES:
            break
    return out


def flash_view(flashes, lang: str, priority_ids=None):
    priority_ids = set(priority_ids or ())
    return [{
        "time": f["time"], "hot": f["hot"], "pinned": f["pinned"],
        "priority": f.get("articleId") in priority_ids,
        "text": f[lang],
        "url": page_url(lang, f"news/{f['articleId']}/") if f["articleId"] else None,
        "external": False,
    } for f in flashes if lang in f["available_languages"]]


def prep_incidents(raw):
    if not isinstance(raw, list):
        if raw is not None:
            print("build: incidents.json malformed — ignored")
        return []
    return [i for i in raw if isinstance(i, dict) and i.get("date")]


def _is_weekly_serious_incident(incident, cutoff) -> bool:
    if incident.get("sev") not in ("acc", "ser"):
        return False
    try:
        return parse_iso(str(incident.get("date"))) >= cutoff
    except (TypeError, ValueError):
        return False


def inc_view(incidents, lang: str, weekly_cutoff, published_ids):
    rows = []
    for i in incidents:
        date = str(i.get("date") or "")
        disp = date[5:] if re.match(r"\d{4}-\d{2}-\d{2}\Z", date) else date
        sev = i.get("sev") if isinstance(i.get("sev"), str) else ""
        srcs = i.get("sources")
        src = " · ".join(str(s) for s in srcs) if isinstance(srcs, list) else str(srcs or "")
        article_id = str(i.get("articleId") or "")
        article_url = None
        if article_id in published_ids and _ID_RE.fullmatch(article_id):
            article_url = page_url(lang, f"news/{article_id}/")
        rows.append({
            "d": disp,
            "sev_key": sev,
            "weekly_serious": _is_weekly_serious_incident(i, weekly_cutoff),
            "sev_label": _bi(SEV.get(sev), lang, sev),
            "sev_class": SEV.get(sev, {}).get("cls", "tag-neutral"),
            "ac": str(i.get("aircraft") or "—"),
            "op": _bi(i.get("operator"), lang, "—"),
            "ph": _bi(i.get("phase"), lang, "—"),
            "loc": _bi(i.get("location"), lang, "—"),
            "desc": _bi(i.get("desc"), lang, ""),
            "url": article_url,
            "st": _bi(ST.get(i.get("status")), lang, str(i.get("status") or "")),
            "src": src,
        })
    return rows


def merged_sources(raw):
    """Overlay persisted status onto sources intended for public display."""
    by_key = {}
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict) and s.get("key"):
                by_key[s["key"]] = s
    out = []
    for key, reg in SOURCES.items():
        s = by_key.get(key, {})
        # Manufacturer feeds marked private still supply candidate stories
        # to write.py.  They are deliberately absent from the homepage and
        # public Sources page; Airbus and Boeing opt in via public=true.
        if not bool(s.get("public", reg.get("public", True))):
            continue
        url = str(s.get("url") or reg["url"] or "").strip()
        if not _public_direct_url(url):
            # Discovery aggregators may remain pipeline inputs, but never
            # appear in the reader-facing source inventory.
            continue
        out.append({
            "key": key,
            "name": str(s.get("name") or reg["name"]),
            "kind": str(s.get("kind") or reg["kind"]),
            "fmt": str(s.get("fmt") or reg["fmt"]),
            "url": url,
            "cover": s.get("cover") or reg["cover"],
            "lastFetchUtc": s.get("lastFetchUtc"),
            "ok": bool(s.get("ok", False)),
        })
    return out


def source_status_view(sources, now):
    return [{"name": s["name"], "ok": s["ok"], "ago": ago(s["lastFetchUtc"], now)}
            for s in sources]


def sources_rows_view(sources, lang: str, now):
    return [{
        "name": s["name"], "url": s["url"], "fmt": s["fmt"], "ok": s["ok"],
        "kind": _bi(KIND.get(s["kind"]), lang, s["kind"]),
        "cover": _bi(s["cover"], lang),
        "last": ago(s["lastFetchUtc"], now),
    } for s in sources]


# ── daily briefings ──────────────────────────────────────────────────────────

BRIEFING_SECTIONS = ("aviation_incidents", "taiwan_aviation",
                     "international_aviation", "ground_and_maritime")
_BRIEF_EDITIONS = load_json(
    Path(__file__).resolve().parent.parent / "config"
    / "briefing_editions.json", {})
_EN_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_BRIEF_SEV_CLS = {"fatal": "tag-accent", "serious": "tag-accent",
                  "significant": "tag-outline", "routine": "tag-neutral"}


def _tpe_dt(iso):
    try:
        return parse_iso(str(iso)).astimezone(TPE)
    except (ValueError, TypeError):
        return None


def _fmt_tpe_date(dt, lang: str) -> str:
    if lang == "zh":
        return f"{dt.year} 年 {dt.month} 月 {dt.day} 日"
    return f"{_EN_MONTHS[dt.month - 1]} {dt.day}, {dt.year}"


def _fmt_tpe(iso, lang: str, time_only=False) -> str:
    dt = _tpe_dt(iso)
    if dt is None:
        return "—"
    if time_only:
        return clock_12(dt)
    return f"{_fmt_tpe_date(dt, lang)} {clock_12(dt)}"


def latest_briefing(rows):
    """Newest usable briefing by cutoff_time (never generated_at).

    failed rows are ignored, so a failed run leaves the previous
    successful edition in place.
    """
    best = None
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if r.get("status") not in ("published", "partial"):
            continue
        cut = _tpe_dt(r.get("cutoff_time"))
        if cut is None:
            continue
        if cut > now_utc().astimezone(TPE):
            continue
        if best is None or cut > best[0]:
            best = (cut, r)
    return best[1] if best else None


def collect_briefings():
    """Readable, already-closed briefings, newest cutoff first.

    The cutoff guard also keeps a stale future-dated data file from becoming
    public while a delayed scheduled run is being corrected.
    """
    index = load_json(DATA_DIR / "briefings" / "index.json", {})
    briefs = []
    for row in index.get("briefings") or []:
        if not isinstance(row, dict):
            continue
        if row.get("status") not in ("published", "partial"):
            continue
        bid = str(row.get("briefing_id") or "")
        if not bid or not _ID_RE.match(bid):
            continue
        data = load_json(DATA_DIR / "briefings" / f"{bid}.json", None)
        cutoff = _tpe_dt((data or {}).get("cutoff_time"))
        if (isinstance(data, dict)
                and data.get("status") in ("published", "partial")
                and cutoff is not None
                and cutoff <= now_utc().astimezone(TPE)):
            briefs.append(data)
    briefs.sort(key=lambda b: str(b.get("cutoff_time") or ""), reverse=True)
    return briefs


def _brief_title(b, lang: str) -> str:
    cfg = _BRIEF_EDITIONS.get(b.get("edition")) or {}
    key = "title_zh_tw" if lang == "zh" else "title_en"
    return str(cfg.get(key) or b.get("edition_label") or "SKYTICAL Briefing")


def _brief_label(b, lang: str) -> str:
    cfg = _BRIEF_EDITIONS.get(b.get("edition")) or {}
    key = "label_zh_tw" if lang == "zh" else "label_en"
    return str(cfg.get(key) or b.get("edition_label") or "")


def brief_item_view(item, lang: str, published_ids):
    zh_head = str(item.get("headline") or "").strip()
    zh_sum = str(item.get("summary") or "").strip()
    head = zh_head if lang == "zh" else (
        str(item.get("headline_en") or "").strip() or zh_head)
    summary = zh_sum if lang == "zh" else (
        str(item.get("summary_en") or "").strip() or zh_sum)
    art_id = item.get("article_id")
    url = (page_url(lang, f"news/{art_id}/")
           if art_id in published_ids else None)
    severity = str(item.get("severity") or "routine")
    marks = ""
    if severity == "fatal":
        marks += "⚠️🔴"
    elif severity in ("serious", "significant"):
        marks += "⚠️"
    if item.get("taiwan_priority"):
        marks += "🇹🇼"
    if item.get("military"):
        marks += "⚔️"
    return {
        "marks": marks,
        "grounded": item.get("origin") == "grounded",
        "headline": head, "summary": summary,
        "time": _fmt_tpe(item.get("source_published_at"), lang,
                         time_only=True),
        "severity": str(item.get("severity") or "routine"),
        "sev_cls": _BRIEF_SEV_CLS.get(item.get("severity"), "tag-neutral"),
        "update": item.get("item_type") == "update",
        "url": url,
        "sources": [
            {"name": str(s.get("name") or ""),
             "url": str(s.get("url") or "").strip()}
            for s in item.get("sources") or []
            if isinstance(s, dict) and _public_direct_url(s.get("url"))
        ],
    }


def _render_include_articles() -> bool:
    """Render-time twin of briefing._include_articles(): hourly and briefing
    workflows race on Pages deploys (last deploy wins), so both must use the
    same default.  Set BRIEFING_INCLUDE_ARTICLES=false for search-only mode."""
    return (os.environ.get("BRIEFING_INCLUDE_ARTICLES", "").strip().lower()
            not in ("0", "false", "no"))


def brief_view(b, lang: str, t, published_ids):
    sections = []
    raw_sections = b.get("sections") or {}
    include_articles = _render_include_articles()
    dropped = 0
    for i, name in enumerate(BRIEFING_SECTIONS):
        raw = [it for it in raw_sections.get(name) or []
               if isinstance(it, dict)]
        if not include_articles:
            kept = [it for it in raw if it.get("origin") == "grounded"]
            dropped += len(raw) - len(kept)
            raw = kept
        items = [brief_item_view(it, lang, published_ids) for it in raw]
        sections.append({"label": t["brSecs"][i], "items": items})
    gen_model = b.get("generation_model") or {}
    date_dt = _tpe_dt(b.get("cutoff_time"))
    # an intro written over the merged item set is stale once items are cut
    intro = str(b.get("intro_zh" if lang == "zh" else "intro_en")
                or "").strip()
    if dropped:
        intro = ""
    return {
        "id": b.get("briefing_id"),
        "title": _brief_title(b, lang),
        "label": _brief_label(b, lang),
        "date_label": _fmt_tpe_date(date_dt, lang) if date_dt else "—",
        "window_start": _fmt_tpe(b.get("window_start"), lang),
        "window_end": _fmt_tpe(b.get("window_end"), lang),
        "cutoff": _fmt_tpe(b.get("cutoff_time"), lang),
        "generated": _fmt_tpe(b.get("generated_at"), lang, time_only=True),
        "partial": b.get("status") == "partial",
        "total": sum(len(s["items"]) for s in sections),
        "sections": sections,
        "intro": intro,
        "mode_label": (t["brModeLlm"] if b.get("generation_mode")
                       == "llm_assisted" else t["brModeDet"]),
        "model_label": (f"{gen_model.get('provider')}:{gen_model.get('model')}"
                        if gen_model else ""),
        "checked": [c for c in b.get("checked_sources") or []
                    if isinstance(c, dict)],
        "warnings": [str(w) for w in b.get("warnings") or []],
        "url": page_url(lang, f"briefings/{b.get('briefing_id')}/"),
        "cutoff_iso": str(b.get("cutoff_time") or ""),
    }


def stats_views(stats, lang: str):
    if not isinstance(stats, dict):
        stats = {}
    unavailable = L[lang]["statUnavailable"]

    def metric(formatter, key):
        value = formatter(stats.get(key))
        return value if value != "—" else unavailable

    tiles = {
        "flights": metric(fmt_int, "flightsTracked"),
        "delay": metric(fmt_pct, "delayRate"),
        "serious": metric(fmt_int, "seriousThisWeek"),
        "notams": metric(fmt_int, "notams"),
    }
    optional_keys = ("flightsTracked", "delayRate", "notams")
    note = (L[lang]["statsNote"]
            if any(metric(fmt_int if key != "delayRate" else fmt_pct, key)
                   == unavailable for key in optional_keys)
            else "")
    otp = []
    raw_otp = stats.get("otp")
    if isinstance(raw_otp, list):
        for r in raw_otp:
            if not isinstance(r, dict):
                continue
            try:
                pct = float(r.get("pct"))
            except (TypeError, ValueError):
                continue
            label = r.get(lang) or r.get("airline") or r.get("name") or ""
            otp.append({
                "rank": len(otp) + 1,
                "airline": str(label),
                "code": str(r.get("code") or ""),
                "pct": f"{pct:g}",
                # bar width formula ported from the design
                "barw": f"{max(0, min(100, round((pct - 78) / 15 * 100)))}%",
            })
    fleet = None
    fr = stats.get("fleet")
    if isinstance(fr, dict):
        a, b = fr.get("airbus"), fr.get("boeing")
        if (isinstance(a, (int, float)) and not isinstance(a, bool)
                and isinstance(b, (int, float)) and not isinstance(b, bool)):
            mx = max(a, b) or 1
            ba, bb = fmt_int(fr.get("backlogAirbus")), fmt_int(fr.get("backlogBoeing"))
            fleet = {
                "bars": [
                    {"maker": "Airbus", "n": fmt_int(a),
                     "w": f"{round(a / mx * 100)}%", "color": "var(--color-accent)"},
                    {"maker": "Boeing", "n": fmt_int(b),
                     "w": f"{round(b / mx * 100)}%",
                     "color": "color-mix(in srgb,var(--color-text) 45%,transparent)"},
                ],
                "backlog": f"A {ba} · B {bb}" if "—" not in (ba, bb) else "—",
                "orders": fmt_int(fr.get("newOrders")),
            }
    delays = []
    raw_delays = stats.get("delays")
    if isinstance(raw_delays, list):
        for d in raw_delays:
            if not isinstance(d, dict) or not d.get("code"):
                continue
            try:
                pct = float(d.get("pct"))
            except (TypeError, ValueError):
                continue
            delays.append({"code": str(d["code"]),
                           "name": str(d.get(lang) or d.get("name") or ""),
                           "pct": f"{pct:g}"})
    return {"tiles": tiles, "otp": otp, "fleet": fleet, "delays": delays,
            "note": note}


# ── private usage dashboard (URL token from AVWIRE_USAGE_TOKEN secret) ──────

_USAGE_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{16,128}\Z")
_RECENT_RUN_KEEP_DAYS = 30
_RUN_TEXT_RE = re.compile(r"[\x00-\x1f\x7f]+")

_RUN_RESULT_ZH = {
    "published": "已發布",
    "manual_review": "已封存的人工審核紀錄",
    "rejected": "已拒絕",
    "refused": "已拒絕",
    "retry_pending": "待下次重試",
    "no_provider": "沒有可用 Provider",
    "skipped_no_material": "素材不足，未呼叫模型",
    "skipped_prompt_injection": "偵測到提示詞注入，未呼叫模型",
}
_ATTEMPT_OUTCOME_ZH = {
    "success": "成功", "failed": "失敗", "refused": "已拒絕",
}
_FAILURE_ZH = {
    "auth": "驗證失敗",
    "quota": "配額耗盡",
    "rate_limit": "速率限制",
    "timeout": "逾時",
    "connection": "連線失敗",
    "http_error": "HTTP 錯誤",
    "refusal": "模型拒絕",
    "truncated": "回應遭截斷",
    "invalid_json": "JSON 格式錯誤",
    "invalid_schema": "資料格式驗證失敗",
    "validation_failed": "內容驗證失敗",
    "fact_verification_failed": "事實驗證失敗",
    "evidence_binding_failed": "證據綁定失敗",
    "fabrication_check_failed": "杜撰檢查失敗",
    "glossary_check_failed": "詞彙檢查失敗",
    "prompt_injection": "提示詞注入",
    "no_material": "素材不足",
    "no_provider": "沒有可用 Provider",
    "unexpected": "未預期錯誤",
}
_STAGE_ZH = {
    "companionRetrieval": "Companion retrieval",
    "fulltextEnrichment": "Fulltext enrichment",
    "plaEnrichment": "本地脈絡補強",
    "archiveRetrieval": "Archive Context retrieval",
    "promptAssembly": "Prompt 組裝",
    "drafting": "模型撰稿",
    "validation": "Draft schema validation",
    "factVerification": "事實驗證",
    "evidenceBinding": "證據綁定",
    "glossaryCheck": "詞彙檢查",
    "fabricationCheck": "杜撰檢查",
    "articleBuild": "文章建置",
    "total": "全工作總耗時",
}


def _usage_price_for(label: str, prices: dict):
    for needle, p in (prices.get("models") or {}).items():
        if isinstance(p, dict) and needle in label:
            return p
    return None


def _configured_model_priority() -> dict:
    configured = (os.environ.get("AVWIRE_PROVIDER_ORDER")
                  or DEFAULT_PROVIDER_ORDER)
    return {
        token.strip(): index
        for index, token in enumerate(configured.split(","))
        if token.strip()
    }


def usage_rows(ledger: dict, prices: dict):
    """Per-model rows + totals with theoretical USD value at list prices."""
    rows = []
    totals = {"calls": 0, "in": 0, "out": 0, "usd": 0.0,
              "unknown": 0, "all_priced": True}
    priority = _configured_model_priority()
    models = (ledger.get("models") or {}).items()
    for label, m in sorted(
            models,
            key=lambda item: (priority.get(item[0], len(priority)), item[0])):
        if not isinstance(m, dict):
            continue
        calls = int(m.get("calls") or 0)
        tokens_in = int(m.get("inputTokens") or 0)
        tokens_out = int(m.get("outputTokens") or 0)
        unknown = int(m.get("unknownCalls") or 0)
        price = _usage_price_for(label, prices)
        usd, kind = None, ""
        if (price and isinstance(price.get("in"), (int, float))
                and isinstance(price.get("out"), (int, float))):
            usd = (tokens_in / 1e6 * price["in"]
                   + tokens_out / 1e6 * price["out"])
            kind = str(price.get("kind") or "")
        elif tokens_in or tokens_out:
            totals["all_priced"] = False
        rows.append({"label": label, "calls": calls, "in": tokens_in,
                     "out": tokens_out, "unknown": unknown,
                     "usd": usd, "kind": kind})
        totals["calls"] += calls
        totals["in"] += tokens_in
        totals["out"] += tokens_out
        totals["unknown"] += unknown
        totals["usd"] += usd or 0.0
    return rows, totals


def _run_text(value, limit=160) -> str:
    if not isinstance(value, (str, int)):
        return ""
    text = _RUN_TEXT_RE.sub(" ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"https?://\S+", "[網址已隱藏]", text,
                  flags=re.IGNORECASE)
    text = re.sub(
        r"(?i)\bauthorization\b\s*[:=]?\s*(?:bearer\s+)?\S+",
        "Authorization [已隱藏]",
        text,
    )
    text = re.sub(
        r"(?i)\b(api[-_ ]?key|token|bearer)\b"
        r"\s*[:=]?\s*\S*",
        r"\1 [已隱藏]",
        text,
    )
    return text[:max(1, min(int(limit or 160), 300))]


def _nonnegative_number(value, maximum=86_400_000):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return min(number, maximum)


def _nonnegative_int(value, maximum=1_000_000) -> int:
    number = _nonnegative_number(value, maximum)
    return int(number) if number is not None else 0


def _duration_text(value) -> str:
    ms = _nonnegative_number(value)
    if ms is None:
        return "未量測"
    if ms < 1000:
        return f"{int(round(ms))} 毫秒"
    return f"{ms / 1000:.1f} 秒"


def _model_name(label: str) -> str:
    text = _run_text(label, 160)
    if text.startswith("manual:"):
        return text.split(":", 1)[1] or "未提供模型"
    model = text.split(":", 1)[-1].split("/")[-1]
    return model.replace("-", " ").title() if model else "未知模型"


def recent_run_view(ledger: dict, now=None) -> dict:
    """Validate untrusted recentRuns and build all dashboard statistics."""
    now = now or now_utc()
    cutoff = (now - timedelta(days=_RECENT_RUN_KEEP_DAYS)).replace(
        second=0, microsecond=0)
    runs = []
    raw_rows = ledger.get("recentRuns") if isinstance(ledger, dict) else []
    for raw in raw_rows if isinstance(raw_rows, list) else []:
        if not isinstance(raw, dict):
            continue
        stamp_value = raw.get("startedUtc") or raw.get("finishedUtc")
        if not isinstance(stamp_value, str):
            continue
        try:
            stamp = parse_iso(stamp_value)
        except (TypeError, ValueError):
            continue
        if stamp < cutoff:
            continue
        result = _run_text(raw.get("result"), 40)
        if result not in _RUN_RESULT_ZH:
            continue
        attempts = []
        raw_attempts = raw.get("attempts")
        for pos, item in enumerate(
                raw_attempts if isinstance(raw_attempts, list) else [], 1):
            if not isinstance(item, dict):
                continue
            label = _run_text(item.get("label"), 160)
            outcome = _run_text(item.get("outcome"), 24)
            if not label or outcome not in _ATTEMPT_OUTCOME_ZH:
                continue
            failure = _run_text(item.get("failureClass"), 48)
            duration = _nonnegative_number(item.get("durationMs"))
            attempt = {
                "sequence": pos,
                "label": label,
                "model_name": _model_name(label),
                "outcome": outcome,
                "outcome_zh": _ATTEMPT_OUTCOME_ZH[outcome],
                "failure_class": failure,
                "failure_zh": _FAILURE_ZH.get(failure, "未預期錯誤")
                    if failure else "",
                "failure_stage": _run_text(
                    item.get("failureStage"), 48),
                "message": _run_text(item.get("failureMessage"), 180),
                "duration_ms": duration,
                "duration": _duration_text(duration),
                "http_calls": _nonnegative_int(item.get("httpCalls"), 100),
                "repair_calls":
                    _nonnegative_int(item.get("repairCalls"), 100),
                "http_duration": _duration_text(
                    _nonnegative_number(item.get("httpDurationMs"))),
                "repair_duration": _duration_text(
                    _nonnegative_number(item.get("repairDurationMs"))),
                "http_duration_measured":
                    _nonnegative_number(item.get("httpDurationMs")) is not None,
                "repair_duration_measured":
                    _nonnegative_number(
                        item.get("repairDurationMs")) is not None,
                "retry_planned": item.get("retryPlanned") is True,
                "disabled": item.get("disabledForRun") is True,
                "started_utc": _run_text(item.get("startedUtc"), 40),
            }
            attempts.append(attempt)
        for index, attempt in enumerate(attempts):
            attempt["next_model"] = (
                attempts[index + 1]["model_name"]
                if index + 1 < len(attempts) else "")
        durations_raw = raw.get("durationsMs")
        durations_raw = durations_raw if isinstance(durations_raw, dict) else {}
        stages = []
        clean_durations = {}
        for key, label in _STAGE_ZH.items():
            value = _nonnegative_number(durations_raw.get(key))
            clean_durations[key] = value
            stages.append({
                "key": key, "label": label,
                "value": value, "duration": _duration_text(value),
            })
        fallback = len({a["label"] for a in attempts}) > 1
        final_model = _run_text(raw.get("finalModel"), 160)
        resource_raw = raw.get("resourceUsage")
        resource_raw = resource_raw if isinstance(resource_raw, dict) else {}
        resource_models = []
        for item in resource_raw.get("models") or []:
            if not isinstance(item, dict):
                continue
            label = _run_text(item.get("label"), 160)
            if not label:
                continue
            resource_models.append({
                "label": label,
                "model_name": _model_name(label),
                "input_tokens": _nonnegative_int(
                    item.get("inputTokens"), 100_000_000),
                "output_tokens": _nonnegative_int(
                    item.get("outputTokens"), 100_000_000),
                "estimated": item.get("estimated") is True,
            })
            if len(resource_models) >= 50:
                break
        tpe = stamp.astimezone(TPE)
        run = {
            "stamp": stamp,
            "time_tpe": f"{tpe:%Y-%m-%d} {clock_12(tpe)} TPE",
            "time_utc": f"{stamp:%Y-%m-%d} {clock_12(stamp)} UTC",
            "workflow": _run_text(raw.get("workflow"), 32) or "unknown",
            "task_type": _run_text(raw.get("taskType"), 32) or "unknown",
            "group_id": _run_text(raw.get("groupId"), 160),
            "event_id": _run_text(raw.get("eventId"), 160),
            "source_count": _nonnegative_int(raw.get("sourceCount"), 10_000),
            "primary_source": _run_text(raw.get("primarySource"), 160),
            "result": result,
            "result_zh": _RUN_RESULT_ZH[result],
            "article_id": _run_text(raw.get("articleId"), 180),
            "final_status": _run_text(raw.get("finalStatus"), 48),
            "final_model": final_model,
            "final_model_name": _model_name(final_model)
                if final_model else "未呼叫模型",
            "fallback": fallback,
            "attempt_count": len(attempts),
            "http_calls": sum(a["http_calls"] for a in attempts),
            "repair_calls": sum(a["repair_calls"] for a in attempts),
            "durations": clean_durations,
            "stages": stages,
            "total_duration": _duration_text(clean_durations["total"]),
            "drafting_duration":
                _duration_text(clean_durations["drafting"]),
            "attempts": attempts,
            "resource_models": resource_models,
        }
        runs.append(run)
    runs.sort(key=lambda row: row["stamp"], reverse=True)
    opened = False
    for run in runs:
        notable = run["fallback"] or run["result"] in {
            "retry_pending", "no_provider", "refused"}
        run["open"] = notable and not opened
        opened = opened or run["open"]

    model_map = {}
    for run in runs:
        first_label = run["attempts"][0]["label"] if run["attempts"] else ""
        for attempt in run["attempts"]:
            row = model_map.setdefault(attempt["label"], {
                "label": attempt["label"],
                "model_name": attempt["model_name"],
                "attempts": 0, "success": 0, "failed": 0,
                "fallback": 0, "duration_total": 0.0,
                "duration_count": 0,
            })
            row["attempts"] += 1
            row["success"] += attempt["outcome"] == "success"
            row["failed"] += attempt["outcome"] == "failed"
            row["fallback"] += attempt["label"] != first_label
            if attempt["duration_ms"] is not None:
                row["duration_total"] += attempt["duration_ms"]
                row["duration_count"] += 1
    model_rows = []
    for row in model_map.values():
        row["success_rate"] = (
            row["success"] / row["attempts"] * 100 if row["attempts"] else 0)
        average = (row["duration_total"] / row["duration_count"]
                   if row["duration_count"] else None)
        row["average_duration"] = _duration_text(average)
        model_rows.append(row)
    priority = _configured_model_priority()
    model_rows.sort(
        key=lambda row: (
            priority.get(row["label"], len(priority)), row["label"]))

    totals = [run["durations"]["total"] for run in runs
              if run["durations"]["total"] is not None]
    drafting = [run["durations"]["drafting"] for run in runs
                if run["durations"]["drafting"] is not None]
    attempt_rows = [attempt for run in runs for attempt in run["attempts"]]
    failed_results = {"retry_pending", "no_provider", "refused"}
    summary = {
        "jobs": len(runs),
        "success": sum(run["result"] == "published" for run in runs),
        "failed": sum(run["result"] in failed_results for run in runs),
        "fallback": sum(run["fallback"] for run in runs),
        "fallback_rate": (
            sum(run["fallback"] for run in runs) / len(runs) * 100
            if runs else 0),
        "attempts": len(attempt_rows),
        "attempt_failures":
            sum(a["outcome"] == "failed" for a in attempt_rows),
        "average_total": _duration_text(
            sum(totals) / len(totals) if totals else None),
        "average_drafting": _duration_text(
            sum(drafting) / len(drafting) if drafting else None),
        "repairs": sum(a["repair_calls"] for a in attempt_rows),
        "timeouts": sum(a["failure_class"] == "timeout"
                        for a in attempt_rows),
    }
    return {"runs": runs, "models": model_rows, "summary": summary}


def _manual_usage_price(label: str, prices: dict):
    """Find a list-price row for provider IDs or owner-entered model names."""
    normalized = re.sub(r"[^a-z0-9]+", "", label.lower())
    if normalized.startswith("manual"):
        normalized = normalized[len("manual"):]
    candidates = []
    for key, value in (prices.get("models") or {}).items():
        if isinstance(value, dict):
            candidates.append((str(key), value))
    for value in prices.get("gptFamilyReference") or []:
        if isinstance(value, dict):
            candidates.append((str(value.get("model") or ""), value))
    for candidate, value in candidates:
        needle = re.sub(r"[^a-z0-9]+", "", candidate.lower())
        if needle and (needle in normalized or normalized in needle):
            if (isinstance(value.get("in"), (int, float))
                    and isinstance(value.get("out"), (int, float))):
                return {
                    "in": float(value["in"]),
                    "out": float(value["out"]),
                    "kind": str(value.get("kind") or "reference"),
                }
    return None


def private_manual_usage_view(recent: dict, prices: dict) -> dict:
    """Thirty-day, per-job resource accounting for the private workbench."""
    rows = []
    totals = {
        "jobs": 0, "published": 0, "in": 0, "out": 0,
        "tokens": 0, "usd": 0.0, "unpriced": 0,
    }
    for run in recent.get("runs") or []:
        if run["workflow"] not in {"manual", "manual_workbench"}:
            continue
        priced = True
        usd = 0.0
        input_tokens = 0
        output_tokens = 0
        model_names = []
        estimated = False
        for model in run["resource_models"]:
            input_tokens += model["input_tokens"]
            output_tokens += model["output_tokens"]
            estimated = estimated or model["estimated"]
            if model["model_name"] not in model_names:
                model_names.append(model["model_name"])
            price = _manual_usage_price(model["label"], prices)
            if price:
                usd += (
                    model["input_tokens"] / 1_000_000 * price["in"]
                    + model["output_tokens"] / 1_000_000 * price["out"]
                )
            elif model["input_tokens"] or model["output_tokens"]:
                priced = False
        row = {
            "time_tpe": run["time_tpe"],
            "mode": (
                "完全手動撰稿"
                if run["workflow"] == "manual_workbench" else "AI 補稿"),
            "article_id": run["article_id"],
            "group_id": run["group_id"],
            "result": run["result_zh"],
            "models": model_names or [run["final_model_name"]],
            "in": input_tokens,
            "out": output_tokens,
            "tokens": input_tokens + output_tokens,
            "estimated": estimated,
            "usd": usd if priced else None,
            "actual_usd": 0.0,
        }
        rows.append(row)
        totals["jobs"] += 1
        totals["published"] += bool(run["article_id"])
        totals["in"] += input_tokens
        totals["out"] += output_tokens
        totals["tokens"] += input_tokens + output_tokens
        totals["usd"] += usd
        totals["unpriced"] += not priced
    return {"rows": rows, "totals": totals}


def non_api_reference_rows(prices: dict):
    """Validated non-API list-price rows; never included in usage totals."""
    rows = []
    for raw in prices.get("nonApiReference") or []:
        if not isinstance(raw, dict):
            continue
        model = str(raw.get("model") or "").strip()
        purpose = str(raw.get("purpose") or "").strip()
        price_in = raw.get("in")
        cached_in = raw.get("cachedIn")
        price_out = raw.get("out")
        if (not model or not purpose
                or not isinstance(price_in, (int, float))
                or not isinstance(cached_in, (int, float))
                or not isinstance(price_out, (int, float))):
            continue
        rows.append({
            "model": model,
            "purpose": purpose,
            "in": float(price_in),
            "cached_in": float(cached_in),
            "out": float(price_out),
            "access": str(raw.get("access") or "").strip(),
            "note": str(raw.get("note") or "").strip(),
            "source": str(raw.get("source") or "").strip(),
        })
    return rows


def gpt_family_reference_rows(prices: dict):
    """Validated official GPT-family rates; never included in usage totals."""
    rows = []
    seen = set()
    for raw in prices.get("gptFamilyReference") or []:
        if not isinstance(raw, dict):
            continue
        model = str(raw.get("model") or "").strip()
        price_in = raw.get("in")
        cached_in = raw.get("cachedIn")
        price_out = raw.get("out")
        source = str(raw.get("source") or "").strip()
        parsed = urlsplit(source)
        if (not model or model in seen
                or not isinstance(price_in, (int, float))
                or (cached_in is not None
                    and not isinstance(cached_in, (int, float)))
                or not isinstance(price_out, (int, float))
                or parsed.scheme != "https"
                or parsed.hostname != "developers.openai.com"
                or not parsed.path.startswith("/api/docs/models/")):
            continue
        seen.add(model)
        rows.append({
            "model": model,
            "in": float(price_in),
            "cached_in": (float(cached_in)
                          if isinstance(cached_in, (int, float)) else None),
            "out": float(price_out),
            "source": source,
        })
    return rows


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


def copilot_usage_view(ledger: dict) -> dict:
    """Compact 30-day SKYTICAL Copilot view for the existing dashboard."""
    raw = ledger.get("copilotEvents") if isinstance(ledger, dict) else []
    rows = []
    totals = {
        "requests": 0, "blocked": 0, "rateLimited": 0, "llmCalls": 0,
        "inputTokens": 0, "outputTokens": 0, "tokens": 0,
        "costUsd": 0.0, "errors": 0, "externalSearches": 0,
    }
    for event in raw if isinstance(raw, list) else []:
        if not isinstance(event, dict):
            continue
        name = str(event.get("event") or "")
        status = str(event.get("status") or "")
        if name == "copilot_request":
            totals["requests"] += 1
        if status == "blocked" or name in {
                "off_topic", "unclear", "injection_detected"}:
            totals["blocked"] += 1
        if name == "rate_limited":
            totals["rateLimited"] += 1
        if name == "main_llm_request":
            totals["llmCalls"] += 1
            totals["inputTokens"] += int(event.get("inputTokens") or 0)
            totals["outputTokens"] += int(event.get("outputTokens") or 0)
            totals["costUsd"] += float(event.get("estimatedCostUsd") or 0)
        if event.get("externalSearchUsed") is True:
            totals["externalSearches"] += 1
        if status in {"failed", "error", "no_provider"}:
            totals["errors"] += 1
        rows.append({
            "time": timestamp_12(event.get("createdAt"), "—"),
            "event": name or "unknown",
            "status": status or "unknown",
            "model": str(event.get("model") or "—")[:160],
            "tokens": int(event.get("totalTokens") or 0),
            "cost": float(event.get("estimatedCostUsd") or 0),
            "latency": int(event.get("latencyMs") or 0),
            "sources": int(event.get("sourceCount") or 0),
            "mode": ("站內＋外部" if event.get("externalSearchUsed")
                     else "站內" if event.get("ragUsed") else "未檢索"),
        })
        if len(rows) >= 100:
            break
    totals["tokens"] = totals["inputTokens"] + totals["outputTokens"]
    totals["costUsd"] = round(totals["costUsd"], 8)
    return {"rows": rows, "totals": totals}


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
    private_manual = private_manual_usage_view(recent, prices)
    copilot = copilot_usage_view(ledger)
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
        "private_manual_rows": private_manual["rows"],
        "private_manual_totals": private_manual["totals"],
        "private_manual_twd": private_manual["totals"]["usd"] * rate,
        "copilot_rows": copilot["rows"],
        "copilot_totals": copilot["totals"],
        "codex_rows": codex_rows, "codex_totals": codex_totals,
        "codex_twd": codex_totals["usd"] * rate,
        "codex_scope": str(codex_snapshot.get("scope") or "").strip(),
        "codex_updated": timestamp_12(
            codex_snapshot.get("updatedUtc"), "尚無紀錄"),
        "codex_tracking_since":
            timestamp_12(
                codex_snapshot.get("trackingSinceUtc"), "尚未開始"),
        "non_api_rows": non_api_reference_rows(prices),
        "gpt_family_rows": gpt_family_reference_rows(prices),
        "twd": totals["usd"] * rate, "rate": rate,
        "updated": timestamp_12(
            ledger.get("updatedUtc"), "尚無紀錄"),
        "tracking_since": timestamp_12(
            ledger.get("trackingSinceUtc"), "尚未開始"),
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
        "copilot_enabled": os.environ.get(
            "SKYTICAL_COPILOT_ENABLED", "false").strip().lower()
            in {"1", "true", "yes", "on"},
    })
    return 1


# ── rendering ────────────────────────────────────────────────────────────────

def base_ctx(lang, page, sub, *, title, description, ticker, build,
             hreflang=True, alternate_languages=None):
    t = dict(L[lang])
    alternate_languages = set(alternate_languages or ("zh", "en"))
    prompts = list(header_search_placeholders(lang))
    t["headerSearchPlaceholders"] = prompts
    t["headerSearchPlaceholder"] = prompts[0]
    nav_defs = [("home", ""), ("briefings", "briefings/"),
                ("radar", "radar/"),
                ("incidents", "incidents/"),
                ("sources", "sources/"), ("about", "about/")]
    return {
        "lang": lang, "t": t, "base": BASE_PATH, "favicon": FAVICON,
        "asset_version": ASSET_VERSION,
        "html_lang": "zh-Hant-TW" if lang == "zh" else "en",
        "title": title, "description": description,
        "zh_url": page_url("zh", sub), "en_url": page_url("en", sub),
        "zh_abs_url": SITE_ORIGIN + page_url("zh", sub),
        "en_abs_url": SITE_ORIGIN + page_url("en", sub),
        "has_zh_alternate": "zh" in alternate_languages,
        "has_en_alternate": "en" in alternate_languages,
        "x_default_abs_url": SITE_ORIGIN + page_url(
            "zh" if "zh" in alternate_languages else "en", sub),
        "self_abs_url": SITE_ORIGIN + page_url(lang, sub),
        "social_image_abs_url": (
            f"{SITE_ORIGIN}{BASE_PATH}/assets/skytical-social.png?v={ASSET_VERSION}"
        ),
        "social_image_alt": "SKYTICAL — SKYLINE TO AVIATION NEWS",
        "og_type": "website",
        "structured_data": None,
        "robots_meta": "index,follow,max-image-preview:large",
        "hreflang": hreflang,
        "home_url": page_url(lang, ""),
        "news_url": page_url(lang, "news/"),
        "feed_url": page_url(lang, "feed.xml"),
        "search_url": page_url(lang, "search/"),
        "search_aliases_url": (
            f"{BASE_PATH}/search-aliases.json"
            if BASE_PATH else "/search-aliases.json"
        ),
        "radar_url": page_url(lang, "radar/"),
        "incidents_week_url": page_url(lang, "incidents/") + "?filter=week",
        "about_url": page_url(lang, "about/"),
        "policy_url": page_url(lang, "editorial-policy/"),
        "changelog_url": page_url(lang, "changelog/"),
        "topic_links": [
            {"label": topic[lang]["label"],
             "url": page_url(lang, f"topics/{slug}/")}
            for slug, topic in TOPICS.items()
        ],
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


def website_structured_data(lang: str) -> dict:
    """Homepage entities used by Google for the site name and publisher."""
    home = absolute_page_url(lang, "")
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{SITE_ORIGIN}{BASE_PATH}/#organization",
                "name": "SKYTICAL",
                "url": home,
                "logo": {
                    "@type": "ImageObject",
                    "url": (
                        f"{SITE_ORIGIN}{BASE_PATH}/assets/skytical-mark.svg"
                        f"?v={ASSET_VERSION}"
                    ),
                },
            },
            {
                "@type": "WebSite",
                "@id": f"{home}#website",
                "url": home,
                "name": "SKYTICAL",
                "alternateName": "SKYLINE TO AVIATION NEWS",
                "description": L[lang]["siteDesc"],
                "inLanguage": "zh-Hant-TW" if lang == "zh" else "en",
                "publisher": {
                    "@id": f"{SITE_ORIGIN}{BASE_PATH}/#organization",
                },
            },
        ],
    }


def article_structured_data(lang: str, article: dict) -> dict:
    """Google-supported NewsArticle fields, grounded in rendered content."""
    article_url = absolute_page_url(lang, f"news/{article['id']}/")
    publisher_id = f"{SITE_ORIGIN}{BASE_PATH}/#organization"
    schema = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "@id": f"{article_url}#article",
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": article_url,
        },
        "url": article_url,
        "headline": article["title"],
        "description": article["summary"] or L[lang]["siteDesc"],
        "datePublished": article["published_iso"],
        "dateModified": article["modified_iso"],
        "inLanguage": "zh-Hant-TW" if lang == "zh" else "en",
        "isAccessibleForFree": True,
        "articleSection": article["cat_label"],
        "author": {
            "@type": "Organization",
            "name": "SKYTICAL",
            "url": absolute_page_url(lang, "about/"),
        },
        "publisher": {
            "@type": "Organization",
            "@id": publisher_id,
            "name": "SKYTICAL",
            "url": absolute_page_url(lang, ""),
            "logo": {
                "@type": "ImageObject",
                "url": (
                    f"{SITE_ORIGIN}{BASE_PATH}/assets/skytical-mark.svg"
                    f"?v={ASSET_VERSION}"
                ),
            },
        },
    }
    if article.get("image"):
        schema["image"] = [article["image"]["url"]]
    return schema


def _write_xml(path: Path, root: ET.Element) -> None:
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True,
               short_empty_elements=True)


def _write_rss_feed(path: Path, lang: str, articles, now) -> None:
    """Write a small RSS 2.0 feed for the latest localized articles."""
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    title = ("SKYTICAL 航空新聞" if lang == "zh"
             else "SKYTICAL Aviation News")
    description = L[lang]["newsSub"]
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = absolute_page_url(lang, "news/")
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "zh-tw" if lang == "zh" else "en"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(
        now.astimezone(timezone.utc), usegmt=True)
    ET.SubElement(channel, "generator").text = "SKYTICAL static pipeline"

    localized = [article for article in articles
                 if lang in article["available_languages"]]
    for article in localized[:50]:
        item = ET.SubElement(channel, "item")
        url = absolute_page_url(lang, f"news/{article['id']}/")
        ET.SubElement(item, "title").text = article[lang]["title"]
        ET.SubElement(item, "link").text = url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = url
        ET.SubElement(item, "description").text = (
            article[lang]["summary"] or article[lang]["title"])
        ET.SubElement(item, "pubDate").text = format_datetime(
            article["published_dt"].astimezone(timezone.utc), usegmt=True)
        source_attrs = {}
        if article.get("sources") and article["sources"][0].get("url"):
            source_attrs["url"] = article["sources"][0]["url"]
        ET.SubElement(item, "source", source_attrs).text = article["source"]
    _write_xml(path, root)


def write_search_discovery_files(articles, briefings, now) -> None:
    """Write sitemaps, RSS feeds and a crawler policy for the public site."""
    urlset = ET.Element(ET.QName(SITEMAP_NS, "urlset"))
    seen = set()

    def add_url(lang: str, sub: str, modified=None) -> None:
        loc = absolute_page_url(lang, sub)
        if loc in seen:
            return
        seen.add(loc)
        node = ET.SubElement(urlset, ET.QName(SITEMAP_NS, "url"))
        ET.SubElement(node, ET.QName(SITEMAP_NS, "loc")).text = loc
        if modified is not None:
            ET.SubElement(node, ET.QName(SITEMAP_NS, "lastmod")).text = (
                iso_timestamp(modified))

    public_sections = ("", "news/", "briefings/", "radar/", "incidents/", "sources/",
                       "about/", "editorial-policy/", "changelog/")
    for lang in ("zh", "en"):
        for sub in public_sections:
            add_url(lang, sub)
        for slug in TOPICS:
            add_url(lang, f"topics/{slug}/")
        localized_count = sum(
            lang in article["available_languages"] for article in articles
        )
        page_count = max(1, math.ceil(localized_count / NEWS_PAGE_SIZE))
        for page_number in range(2, page_count + 1):
            add_url(lang, f"news/page/{page_number}/")
    for briefing in briefings:
        modified = _tpe_dt(briefing.get("generated_at")
                           or briefing.get("cutoff_time"))
        for lang in ("zh", "en"):
            add_url(lang, f"briefings/{briefing.get('briefing_id')}/",
                    modified)
    for article in articles:
        for lang in article["available_languages"]:
            add_url(lang, f"news/{article['id']}/", article["modified_dt"])
    _write_xml(SITE_DIR / "sitemap.xml", urlset)

    news_urlset = ET.Element(ET.QName(SITEMAP_NS, "urlset"))
    cutoff = now - timedelta(days=2)
    for article in articles:
        if article["published_dt"] < cutoff:
            continue
        for lang in article["available_languages"]:
            url_node = ET.SubElement(news_urlset, ET.QName(SITEMAP_NS, "url"))
            ET.SubElement(url_node, ET.QName(SITEMAP_NS, "loc")).text = (
                absolute_page_url(lang, f"news/{article['id']}/"))
            news = ET.SubElement(url_node, ET.QName(NEWS_NS, "news"))
            publication = ET.SubElement(
                news, ET.QName(NEWS_NS, "publication"))
            ET.SubElement(publication, ET.QName(NEWS_NS, "name")).text = (
                "SKYTICAL")
            ET.SubElement(publication, ET.QName(NEWS_NS, "language")).text = (
                "zh-tw" if lang == "zh" else "en")
            ET.SubElement(news, ET.QName(
                NEWS_NS, "publication_date")).text = article["published_iso"]
            ET.SubElement(news, ET.QName(
                NEWS_NS, "title")).text = article[lang]["title"]
    _write_xml(SITE_DIR / "news-sitemap.xml", news_urlset)
    _write_rss_feed(SITE_DIR / "feed.xml", "zh", articles, now)
    _write_rss_feed(SITE_DIR / "en" / "feed.xml", "en", articles, now)

    sitemap_url = f"{SITE_ORIGIN}{BASE_PATH}/sitemap.xml"
    news_sitemap_url = f"{SITE_ORIGIN}{BASE_PATH}/news-sitemap.xml"
    (SITE_DIR / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {sitemap_url}\nSitemap: {news_sitemap_url}\n",
        encoding="utf-8", newline="\n")


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
    if PUBLIC_DIR.is_dir():
        for f in PUBLIC_DIR.iterdir():
            if f.is_file():
                shutil.copy2(f, SITE_DIR / f.name)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (SITE_DIR / "search-index.json").write_text(
        json.dumps(search_index_payload(articles, now), ensure_ascii=False,
                   separators=(",", ":")),
        encoding="utf-8", newline="\n")
    (SITE_DIR / "search-aliases.json").write_text(
        json.dumps(search_aliases_payload(), ensure_ascii=False,
                   separators=(",", ":")),
        encoding="utf-8", newline="\n")

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
        "utc_hm": clock_12(now),
        "tpe_hm": clock_12(tpe_now),
        "stamp": f"{now:%Y-%m-%d} {clock_12(now)}",
    }
    cat_keys = ["all", "safety", "reg", "biz", "ops", "mil"]
    sev_keys = ["week", "all", "acc", "ser", "inc"]
    pages = 0
    failed = 0

    # Free no-API fallback: with no articles published yet, surface raw
    # source headlines instead of an empty page.
    agg_items = [] if articles else collect_agg_items(now)

    for lang in ("zh", "en"):
        t = L[lang]
        agg = False
        lang_articles = [
            a for a in articles if lang in a["available_languages"]]
        views = [art_view(a, lang) for a in lang_articles]
        pinned_articles = [
            article for article in lang_articles
            if is_weather_airline_flight_story(article, now)
        ]
        pinned_views = [art_view(article, lang)
                        for article in pinned_articles]
        priority_ids = {article["id"] for article in pinned_articles}
        hero_candidates = [hero_rotation_view(view, lang)
                           for view in pinned_views]
        if views:
            fl = flash_view(flashes, lang, priority_ids)
            hero = pinned_views[0] if pinned_views else views[0]
            pinned_ids = ({view["id"] for view in pinned_views}
                          if pinned_views else {hero["id"]})
            feed = [view for view in views if view["id"] not in pinned_ids]
            feed = feed[:HOME_FEED_LIMIT]
        elif agg_items:
            agg = True
            av = agg_view(agg_items, lang)
            fl = agg_flashes(av)
            hero = av[0]
            hero_candidates = []
            feed = av[1:1 + HOME_FEED_LIMIT]
        else:
            fl = flash_view(flashes, lang, priority_ids)
            hero = None
            hero_candidates = []
            feed = []
        # ticker items stay structured so the marquee can link each flash
        # to its story (owner request: clickable, no underline)
        ticker = [{"time": f.get("time"), "text": f.get("text"),
                   "url": f.get("url"), "hot": bool(f.get("hot")),
                   "pinned": bool(f.get("pinned")),
                   "priority": bool(f.get("priority")),
                   "external": bool(f.get("external"))} for f in fl]
        sv = stats_views(stats_raw, lang)

        bviews = [brief_view(b, lang, t, published_ids) for b in briefings]
        latest_brief = None
        if latest_row:
            latest_brief = next(
                (bv for bv in bviews
                 if bv["id"] == latest_row.get("briefing_id")), None)

        home_title = ("SKYTICAL 航空新聞｜臺灣與全球即時航空快訊"
                      if lang == "zh"
                      else "SKYTICAL Aviation News | Taiwan and Global Updates")
        ctx = base_ctx(lang, "home", "", title=home_title,
                       description=t["siteDesc"], ticker=ticker, build=build)
        ctx["structured_data"] = website_structured_data(lang)
        ctx.update(hero=hero, hero_candidates=hero_candidates,
                   feed=feed, flashes=fl, agg=agg,
                   source_status=source_status_view(sources, now),
                   stats=sv["tiles"], otp=sv["otp"], fleet=sv["fleet"],
                   delays=sv["delays"], stats_note=sv["note"],
                   cat_seg=list(zip(cat_keys, t["cats"])),
                   latest_brief=latest_brief)
        render(env, "home.html", rel_path(lang, "index.html"), ctx)
        pages += 1

        page_count = max(1, math.ceil(len(views) / NEWS_PAGE_SIZE))
        for page_number in range(1, page_count + 1):
            start = (page_number - 1) * NEWS_PAGE_SIZE
            end = start + NEWS_PAGE_SIZE
            sub = ("news/" if page_number == 1
                   else f"news/page/{page_number}/")
            previous_sub = ("news/" if page_number == 2
                            else f"news/page/{page_number - 1}/")
            next_sub = f"news/page/{page_number + 1}/"
            news_ctx = base_ctx(
                lang, "news", sub,
                title=(f"{t['newsTitle']}｜{t['siteName']}"
                       if page_number == 1 else
                       f"{t['newsTitle']} · {t['pageLabel'].format(page=page_number, pages=page_count)}｜{t['siteName']}"),
                description=t["newsSub"], ticker=ticker, build=build)
            news_ctx.update(
                articles=views[start:end], count=len(views),
                page_number=page_number, page_count=page_count,
                previous_url=(page_url(lang, previous_sub)
                              if page_number > 1 else None),
                next_url=(page_url(lang, next_sub)
                          if page_number < page_count else None),
                previous_abs_url=(absolute_page_url(lang, previous_sub)
                                  if page_number > 1 else None),
                next_abs_url=(absolute_page_url(lang, next_sub)
                              if page_number < page_count else None),
            )
            out_rel = ("news/index.html" if page_number == 1
                       else f"news/page/{page_number}/index.html")
            render(env, "news_index.html", rel_path(lang, out_rel), news_ctx)
            pages += 1

        for slug, topic in TOPICS.items():
            topic_rows = topic_articles(lang_articles, slug)
            topic_views = [art_view(article, lang) for article in topic_rows]
            copy = topic[lang]
            ctx = base_ctx(
                lang, "topics", f"topics/{slug}/",
                title=f"{copy['title']}｜{t['siteName']}",
                description=copy["description"], ticker=ticker, build=build)
            ctx.update(topic=copy, articles=topic_views, count=len(topic_views))
            render(env, "topic.html",
                   rel_path(lang, f"topics/{slug}/index.html"), ctx)
            pages += 1

        ctx = base_ctx(
            lang, "search", "search/",
            title=f"{t['siteName']} — {t['searchTitle']}",
            description=t["searchSub"], ticker=ticker, build=build)
        ctx["robots_meta"] = "noindex,follow"
        ctx["search_index_url"] = (
            f"{BASE_PATH}/search-index.json"
            if BASE_PATH else "/search-index.json")
        render(env, "search.html", rel_path(lang, "search/index.html"), ctx)
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
        airline_iata_codes = {
            str(row.get("icao_code") or "").upper():
                str(row.get("iata_code") or "").upper()
            for row in (airline_cfg.get("airlines") or [])
            if isinstance(row, dict) and row.get("active", True)
               and row.get("icao_code") and row.get("iata_code")
        }
        airline_iata_names = {
            str(row.get("iata_code") or "").upper():
                (row.get("airline_name_zh_tw") if lang == "zh"
                 else row.get("airline_name_en"))
            for row in (airline_cfg.get("airlines") or [])
            if isinstance(row, dict) and row.get("active", True)
               and row.get("iata_code")
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
            airline_iata_codes=airline_iata_codes,
            airline_iata_names=airline_iata_names,
            aircraft_types=aircraft_types,
            radar_airports=radar_airports,
        )
        render(env, "radar.html", rel_path(lang, "radar/index.html"), ctx)
        pages += 1

        for a, v in zip(lang_articles, views):
            try:
                ctx = base_ctx(lang, "home", f"news/{a['id']}/",
                               title=f"{v['title']}｜{t['siteName']}",
                               description=v["summary"] or t["siteDesc"],
                               ticker=ticker, build=build,
                               alternate_languages=a["available_languages"])
                ctx["og_type"] = "article"
                if v.get("image"):
                    ctx["social_image_abs_url"] = v["image"]["url"]
                    ctx["social_image_alt"] = (
                        v["image"].get("subject") or v["title"])
                ctx["structured_data"] = article_structured_data(lang, v)
                ctx["a"] = v
                render(env, "article.html",
                       rel_path(lang, f"news/{a['id']}/index.html"), ctx)
                pages += 1
            except Exception as exc:  # degrade: one bad article must not kill the build
                failed += 1
                print(f"build: article {a['id']} ({lang}) failed: {exc}")

        try:
            weekly_cutoff = (
                parse_iso(str(stats_raw.get("updatedUtc")))
                - timedelta(days=7)
            )
        except (TypeError, ValueError):
            weekly_cutoff = now - timedelta(days=7)
        rows = inc_view(incidents, lang, weekly_cutoff, published_ids)
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

        policy = EDITORIAL_POLICY[lang]
        ctx = base_ctx(
            lang, "policy", "editorial-policy/",
            title=f"{policy['title']}｜{t['siteName']}",
            description=policy["description"], ticker=ticker, build=build)
        ctx.update(policy=policy,
                   contact_url=("https://github.com/nnneeeooo-nnneeeooo/"
                                "avwire/issues/new"))
        render(env, "editorial-policy.html",
               rel_path(lang, "editorial-policy/index.html"), ctx)
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
    ctx["robots_meta"] = "noindex,follow"
    render(env, "404.html", "404.html", ctx)
    pages += 1

    write_search_discovery_files(articles, briefings, now)

    print(f"build: {len(articles)} articles, {len(flashes)} flashes, "
          f"{len(incidents)} incidents, {pages} pages, {failed} failed "
          f"-> {SITE_DIR} (base='{BASE_PATH}') in {time.time() - t0:.2f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
