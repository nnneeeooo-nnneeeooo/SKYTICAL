"""build.py — render the AVWIRE static site from data/ JSON (see CONTRACTS.md).

Reads (all optional, degrades gracefully): data/articles/*.json, flashes.json,
incidents.json, sources.json, stats.json. Writes the site/ tree per
CONTRACTS.md: zh at /, en under /en/, one page per article ever published,
incidents / sources / about pages, copied assets, 404.html and .nojekyll.
A single bad input never crashes the build: bad entries are skipped with a
one-line log to stdout and the script exits 0.
"""
from __future__ import annotations

import re
import shutil
import sys
import time
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
        "readMore": "閱讀全文 →", "back": "← 返回首頁",
        "heroImg": "[ 頭條照片 — 由來源圖庫自動帶入，灰階顯示 ]",
        "today": "今日全球數據", "statFlights": "目前追蹤航班", "statDelay": "全球延誤率",
        "statSerious": "本週嚴重事件", "statNotam": "生效中 NOTAM",
        "otp": "準點率排行 · 7月", "fleet": "機隊與訂單追蹤", "fleetDeliv": "2026 上半年交付",
        "fleetBacklog": "積壓訂單", "fleetOrders": "本月新訂單",
        "delays": "今日延誤熱點機場", "autoCompiled": "自動彙整",
        "refreshNote": "本文隨來源每小時更新", "sourcesBox": "資料來源 Sources",
        "genNote": "本文由自動化系統彙整生成，內容以原始來源為準。",
        "incKicker": "Incident Database", "incTitle": "事故資料庫",
        "incSub": "自動彙整全球民航事故與事件，資料來自各國調查機關與專業追報來源，每小時更新。",
        "incCountLabel": "筆紀錄",
        "incNote": "* 分級依 ICAO Annex 13：事故（Accident）、嚴重事件（Serious incident）、事件（Incident）。",
        "thDate": "日期", "thSev": "等級", "thType": "機型", "thOp": "營運人",
        "thPhase": "飛行階段", "thLoc": "地點", "thDesc": "摘要", "thStatus": "狀態", "thSrc": "來源",
        "srcKicker": "Data Sources", "srcTitle": "資料來源",
        "srcSub": "全站僅使用免費公開來源。每小時整點抓取一次，抓取狀態即時顯示於首頁側欄。",
        "srcNote": "* 所有來源皆標註於各篇文末；轉載內容僅做事實彙整，原文著作權屬原單位。",
        "thName": "來源", "thKind": "類型", "thCover": "涵蓋範圍", "thFmt": "格式",
        "thFreq": "頻率", "thLast": "最近抓取", "thState": "狀態",
        "aboutKicker": "Methodology", "aboutTitle": "方法論", "aboutPipeTitle": "自動化資料管線",
        "aboutAttrTitle": "撰稿與來源歸屬", "aboutSchedTitle": "更新排程",
        "aboutRepoTitle": "開放原始碼", "aboutDiscTitle": "免責聲明",
        "aboutWhat": "AVWIRE 是全自動航空新聞聚合站：程式每小時抓取 FAA、ICAO、IATA、路透社等可信來源，自動撰寫新聞稿，並在每篇文末完整標註原始出處。無人工編輯介入，原始來源永遠優先。",
        "aboutAttr": "每篇報導由語言模型根據多個原始來源撰寫：僅彙整來源中的事實，不加入未經來源支持的推論；同一事件的多來源會先去重合併。文末「資料來源」列出所有引用連結。",
        "aboutSched": "GitHub Actions 於每小時整點觸發（cron: 0 * * * *），僅使用免費公開介面：RSS、公開 API 與網頁。單次更新流程約 3–5 分鐘，完成後發布至 GitHub Pages。",
        "aboutRepo": "全站程式碼開源，repo 結構如下。歡迎檢視程式碼、回報問題或自行部署一份。",
        "aboutDisc": "本站內容為自動生成，可能存在錯誤或遺漏，不構成飛安、法遵或投資建議。任何權威資訊請以官方原始來源為準。",
        "footerAbout": "全自動航空新聞聚合站。GitHub Actions 每小時抓取各可信來源，自動撰寫並發布，每篇文末標註原始出處。本頁為設計原型，內容為示意樣本。",
        "footerSources": "資料來源 Data Sources",
        "nav": ["最新", "事故資料庫", "來源", "方法論"],
        "cats": ["全部", "事故", "法規", "商業", "營運"],
        "sevs": ["全部", "事故", "嚴重事件", "事件"],
        "themeOpts": ["亮", "暗"],
        "pipeSteps": [
            "GitHub Actions 每小時整點觸發工作流程",
            "抓取 FAA / ICAO / IATA / Reuters 等 RSS 與公開 API",
            "相似度去重、跨來源合併，語言模型撰寫新聞稿",
            "發布至 GitHub Pages，文末自動附上原始來源連結",
        ],
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
        "readMore": "Read more →", "back": "← Back to front page",
        "heroImg": "[ Lead photo — pulled from source library, grayscale ]",
        "today": "Global today", "statFlights": "Flights tracked now", "statDelay": "Global delay rate",
        "statSerious": "Serious events this week", "statNotam": "Active NOTAMs",
        "otp": "On-time ranking · Jul", "fleet": "Fleet & orders", "fleetDeliv": "H1 2026 deliveries",
        "fleetBacklog": "Backlog", "fleetOrders": "New orders this month",
        "delays": "Delay hotspots today", "autoCompiled": "Auto-compiled",
        "refreshNote": "Refreshes hourly with sources", "sourcesBox": "Sources",
        "genNote": "This article was compiled automatically; the original sources prevail.",
        "incKicker": "Incident Database", "incTitle": "Incident database",
        "incSub": "Automatically aggregated civil-aviation accidents and incidents, from state investigators and specialist trackers. Updated hourly.",
        "incCountLabel": "records",
        "incNote": "* Classes per ICAO Annex 13: Accident, Serious incident, Incident.",
        "thDate": "Date", "thSev": "Class", "thType": "Aircraft", "thOp": "Operator",
        "thPhase": "Phase", "thLoc": "Location", "thDesc": "Summary", "thStatus": "Status", "thSrc": "Sources",
        "srcKicker": "Data Sources", "srcTitle": "Sources",
        "srcSub": "Free, public sources only. Fetched at the top of every hour; live fetch status shows on the front page rail.",
        "srcNote": "* Every article credits its sources; content is factual aggregation and copyright stays with the originators.",
        "thName": "Source", "thKind": "Kind", "thCover": "Coverage", "thFmt": "Format",
        "thFreq": "Interval", "thLast": "Last fetch", "thState": "Status",
        "aboutKicker": "Methodology", "aboutTitle": "Methodology", "aboutPipeTitle": "Automated pipeline",
        "aboutAttrTitle": "Writing & attribution", "aboutSchedTitle": "Schedule",
        "aboutRepoTitle": "Open source", "aboutDiscTitle": "Disclaimer",
        "aboutWhat": "AVWIRE is a fully automated aviation news aggregator: every hour it fetches trusted sources such as FAA, ICAO, IATA and Reuters, writes the stories automatically, and credits every original source at the end of each article. No human editing; sources always prevail.",
        "aboutAttr": "Each story is written by a language model from multiple original sources: it aggregates facts only, adds no unsupported inference, and merges duplicate coverage of the same event. The Sources box lists every reference used.",
        "aboutSched": "GitHub Actions triggers at the top of every hour (cron: 0 * * * *), using free public interfaces only: RSS, open APIs and web pages. A full run takes 3–5 minutes and publishes to GitHub Pages.",
        "aboutRepo": "The whole site is open source; the repo layout is below. Inspect the code, file issues, or deploy your own copy.",
        "aboutDisc": "Content is machine-generated and may contain errors or omissions. It is not flight-safety, compliance or investment advice; defer to official sources.",
        "footerAbout": "A fully automated aviation news aggregator. GitHub Actions fetches trusted sources hourly, writes and publishes automatically, and credits originals at the end of every article. Design prototype; sample content.",
        "footerSources": "Data Sources",
        "nav": ["Latest", "Incident DB", "Sources", "Methodology"],
        "cats": ["All", "Safety", "Regulation", "Business", "Operations"],
        "sevs": ["All", "Accident", "Serious", "Incident"],
        "themeOpts": ["Light", "Dark"],
        "pipeSteps": [
            "GitHub Actions triggers the workflow at the top of every hour",
            "Fetch RSS and open APIs from FAA / ICAO / IATA / Reuters and more",
            "De-duplicate, merge across sources, and draft stories with a language model",
            "Publish to GitHub Pages with original source links appended to every article",
        ],
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
TAGCLS = {"safety": "tag-accent", "reg": "tag-neutral", "biz": "tag-neutral", "ops": "tag-neutral"}

TICKER_SEP = "　▪　"  # 「　▪　」 per the design

# Footer source-tag order, exactly as in the design footer.
FOOTER_ORDER = ["faa", "icao", "iata", "ntsb", "easa", "eurocontrol",
                "reuters", "avherald", "flightaware", "caataiwan"]
FOOTER_SOURCES = [{"name": SOURCES[k]["name"], "url": SOURCES[k]["url"]}
                  for k in FOOTER_ORDER if k in SOURCES]

# Favicon: the design's __bundler_thumbnail SVG as a data: URI.
_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">'
    '<rect width="120" height="120" fill="#ec3013"/>'
    '<text x="60" y="72" font-family="Archivo,sans-serif" font-weight="800" '
    'font-size="34" fill="#f3f2f2" text-anchor="middle">AW</text></svg>'
)
FAVICON = "data:image/svg+xml," + quote(_FAVICON_SVG)


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


def rel_path(lang: str, sub: str) -> str:
    return ("en/" + sub) if lang == "en" else sub


def page_url(lang: str, sub: str) -> str:
    """URL for a page; sub is '' or 'incidents/' or 'news/<id>/' …"""
    return f"{BASE_PATH}/{'en/' if lang == 'en' else ''}{sub}"


# ── data loading / preparation ───────────────────────────────────────────────

def prep_article(raw):
    if not isinstance(raw, dict):
        return None
    art_id = raw.get("id")
    if not isinstance(art_id, str) or not _ID_RE.match(art_id.strip()):
        return None
    art_id = art_id.strip()
    try:
        dt = parse_iso(str(raw.get("publishedUtc")))
    except (ValueError, TypeError):
        return None
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
            if not _safe_web_url(url):  # feed-derived: block javascript: etc.
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

    cat = raw.get("cat") if isinstance(raw.get("cat"), str) else "ops"
    image = str(raw["image"]) if raw.get("image") else None
    if image and not _safe_web_url(image):
        image = None
    # Display the SOURCE's newest publication time when the write stage
    # recorded one; the generation time (dt) is used for ordering only, so
    # a days-old official release is never presented as breaking news.
    display_dt = dt
    if raw.get("sourcePublishedUtc"):
        try:
            display_dt = parse_iso(str(raw["sourcePublishedUtc"]))
        except (ValueError, TypeError):
            pass
    tpe = display_dt.astimezone(TPE)
    today_tpe = now_utc().astimezone(TPE).date()
    # Date-only source stamps (FAA/CAA give no clock time -> 00:00Z) must
    # not render as a precise-looking "08:00" TPE: show the date instead.
    date_only = (raw.get("sourcePublishedUtc")
                 and display_dt.hour == 0 and display_dt.minute == 0)
    if date_only:
        time_label = tpe.strftime("%m/%d")
        meta_ts = tpe.strftime("%Y-%m-%d")
    else:
        time_label = (tpe.strftime("%H:%M") if tpe.date() == today_tpe
                      else tpe.strftime("%m/%d"))
        meta_ts = tpe.strftime("%Y-%m-%d %H:%M") + " UTC+8"
    return {
        "id": art_id,
        "dt": dt,
        "cat": cat,
        "tag_class": TAGCLS.get(cat, "tag-neutral"),
        "image": image,
        "source": str(raw.get("primarySource") or (sources[0]["name"] if sources else "—")),
        "time": time_label,
        "meta_ts": meta_ts,
        "zh": side(zh, en),
        "en": side(en, zh),
        "sources": sources,
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
                    print(f"build: {path.name}: bad article entry skipped")
                else:
                    arts.append(art)
    by_id = {}
    for a in arts:
        prev = by_id.get(a["id"])
        if prev is None or a["dt"] > prev["dt"]:
            by_id[a["id"]] = a
    return sorted(by_id.values(), key=lambda a: a["dt"], reverse=True)


def art_view(a, lang: str):
    v = dict(a[lang])
    v.update(
        id=a["id"], cat=a["cat"], tag_class=a["tag_class"], image=a["image"],
        cat_label=_bi(CATS.get(a["cat"]), lang, a["cat"]),
        source=a["source"], time=a["time"], meta_ts=a["meta_ts"],
        sources=a["sources"], url=page_url(lang, f"news/{a['id']}/"),
        external=False,
    )
    return v


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
            image = str(it["image"]) if it.get("image") else None
            if image and not _safe_web_url(image):
                image = None
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
        return tpe.strftime("%H:%M")
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
        out.append({"time": v["time"], "hot": False, "text": text,
                    "url": v["url"], "external": True})
    return out


def prep_flashes(raw, known_ids):
    out = []
    if not isinstance(raw, list):
        if raw is not None:
            print("build: flashes.json malformed — ignored")
        return out
    for f in raw[:MAX_FLASHES]:
        if not isinstance(f, dict):
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
        out.append({
            "time": dt.astimezone(TPE).strftime("%H:%M"),
            "hot": bool(f.get("hot")),
            "zh": zh, "en": en,
            "articleId": aid if isinstance(aid, str) and aid in known_ids else None,
        })
    return out


def flash_view(flashes, lang: str):
    return [{
        "time": f["time"], "hot": f["hot"], "text": f[lang],
        "url": page_url(lang, f"news/{f['articleId']}/") if f["articleId"] else None,
        "external": False,
    } for f in flashes]


def prep_incidents(raw):
    if not isinstance(raw, list):
        if raw is not None:
            print("build: incidents.json malformed — ignored")
        return []
    return [i for i in raw if isinstance(i, dict) and i.get("date")]


def inc_view(incidents, lang: str):
    rows = []
    for i in incidents:
        date = str(i.get("date") or "")
        disp = date[5:] if re.match(r"\d{4}-\d{2}-\d{2}\Z", date) else date
        sev = i.get("sev") if isinstance(i.get("sev"), str) else ""
        srcs = i.get("sources")
        src = " · ".join(str(s) for s in srcs) if isinstance(srcs, list) else str(srcs or "")
        rows.append({
            "d": disp,
            "sev_key": sev,
            "sev_label": _bi(SEV.get(sev), lang, sev),
            "sev_class": SEV.get(sev, {}).get("cls", "tag-neutral"),
            "ac": str(i.get("aircraft") or "—"),
            "op": _bi(i.get("operator"), lang, "—"),
            "ph": _bi(i.get("phase"), lang, "—"),
            "loc": _bi(i.get("location"), lang, "—"),
            "desc": _bi(i.get("desc"), lang, ""),
            "st": _bi(ST.get(i.get("status")), lang, str(i.get("status") or "")),
            "src": src,
        })
    return rows


def merged_sources(raw):
    """Overlay data/sources.json onto the registry so all sources always show."""
    by_key = {}
    if isinstance(raw, list):
        for s in raw:
            if isinstance(s, dict) and s.get("key"):
                by_key[s["key"]] = s
    out = []
    for key, reg in SOURCES.items():
        s = by_key.get(key, {})
        out.append({
            "key": key,
            "name": str(s.get("name") or reg["name"]),
            "kind": str(s.get("kind") or reg["kind"]),
            "fmt": str(s.get("fmt") or reg["fmt"]),
            "url": str(s.get("url") or reg["url"]),
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


def stats_views(stats, lang: str):
    if not isinstance(stats, dict):
        stats = {}
    tiles = {
        "flights": fmt_int(stats.get("flightsTracked")),
        "delay": fmt_pct(stats.get("delayRate")),
        "serious": fmt_int(stats.get("seriousThisWeek")),
        "notams": fmt_int(stats.get("notams")),
    }
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
    return {"tiles": tiles, "otp": otp, "fleet": fleet, "delays": delays}


# ── rendering ────────────────────────────────────────────────────────────────

def base_ctx(lang, page, sub, *, title, description, ticker, build, hreflang=True):
    t = L[lang]
    nav_defs = [("home", ""), ("incidents", "incidents/"),
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
        "nav": [{"label": t["nav"][i], "url": page_url(lang, s), "active": page == p}
                for i, (p, s) in enumerate(nav_defs)],
        "ticker_line": ticker, "build": build,
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
    flashes = prep_flashes(load_json(DATA_DIR / "flashes.json", None),
                           {a["id"] for a in articles})
    incidents = prep_incidents(load_json(DATA_DIR / "incidents.json", None))
    sources = merged_sources(load_json(DATA_DIR / "sources.json", []))
    stats_raw = load_json(DATA_DIR / "stats.json", {})

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
    cat_keys = ["all", "safety", "reg", "biz", "ops"]
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
        ticker = TICKER_SEP.join(f"{f['time']}  {f['text']}" for f in fl)
        sv = stats_views(stats_raw, lang)

        ctx = base_ctx(lang, "home", "", title=t["siteName"],
                       description=t["siteDesc"], ticker=ticker, build=build)
        ctx.update(hero=hero, feed=feed, flashes=fl, agg=agg,
                   source_status=source_status_view(sources, now),
                   stats=sv["tiles"], otp=sv["otp"], fleet=sv["fleet"],
                   delays=sv["delays"],
                   cat_seg=list(zip(cat_keys, t["cats"])))
        render(env, "home.html", rel_path(lang, "index.html"), ctx)
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
                       description=t["aboutWhat"], ticker=ticker, build=build)
        ctx.update(pipe_steps=[{"n": f"0{i + 1}", "text": s}
                               for i, s in enumerate(t["pipeSteps"])])
        render(env, "about.html", rel_path(lang, "about/index.html"), ctx)
        pages += 1

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
