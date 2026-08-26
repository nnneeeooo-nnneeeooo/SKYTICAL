"""Shared helpers and configuration for the AVWIRE pipeline.

Every pipeline stage (fetch -> dedupe -> write -> build) imports from here.
Data contracts between stages are documented in pipeline/CONTRACTS.md.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
# AVWIRE_DATA_DIR lets tests point the pipeline at fixture data.
DATA_DIR = Path(os.environ.get("AVWIRE_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
ARTICLES_DIR = DATA_DIR / "articles"
SITE_DIR = ROOT / "site"
TEMPLATES_DIR = ROOT / "templates"
STATIC_DIR = ROOT / "static"

# The production site is served from the root of the SKYTICAL custom domain.
# Override this for a project-site preview that needs a repository subpath.
BASE_PATH = os.environ.get("AVWIRE_BASE_PATH", "").rstrip("/")

# Absolute origin for hreflang/canonical links (search engines require
# fully-qualified URLs there).
SITE_ORIGIN = (os.environ.get("AVWIRE_SITE_ORIGIN")
               or "https://skytical.tech").rstrip("/")

USER_AGENT = (
    "AVWIREBot/1.0 (automated aviation news aggregator; "
    "+https://github.com/avwire) requests"
)

# Keep at most this many entries per source per fetch, and this many flashes.
MAX_ITEMS_PER_SOURCE = 25
MAX_FLASHES = 10
# Articles shown on the home page feed.
HOME_FEED_LIMIT = 30
# Articles shown on each static news-index page.  Pagination keeps the index
# crawlable without making the first screen carry the entire archive.
NEWS_PAGE_SIZE = 100


def _parse_max_age(value, default: int = 120,
                   low: int = 24, high: int = 336) -> int:
    """Validate the freshness-window setting (hours).

    Non-integers fall back to the default with a warning; values outside
    [low, high] are treated as configuration errors and also fall back, so
    a bad setting can never admit unbounded-age news.
    """
    if value in (None, ""):
        return default
    try:
        hours = int(str(value).strip())
    except (TypeError, ValueError):
        print(f"config: NEWS_MAX_AGE_HOURS={value!r} is not an integer; "
              f"using {default}")
        return default
    if not low <= hours <= high:
        print(f"config: NEWS_MAX_AGE_HOURS={hours} outside [{low}, {high}]; "
              f"using {default}")
        return default
    return hours


# Freshness window for the dedupe stage. Official sources go quiet on
# weekends, so the default reaches back 5 days; seen.json's 21-day memory
# still prevents any story from running twice. Single source of truth -
# do not read the env var anywhere else. (AVWIRE_MAX_AGE_HOURS is the
# deprecated alias.)
NEWS_MAX_AGE_HOURS = _parse_max_age(
    os.environ.get("NEWS_MAX_AGE_HOURS")
    or os.environ.get("AVWIRE_MAX_AGE_HOURS"))

# Items stamped this far in the future are treated as source clock/parse
# errors and dropped before any AI call; smaller offsets are tolerated as
# timezone skew.
FUTURE_SKEW_HOURS = 6

# --- source-material completeness (editorial spec section 2) -------------
# An item contributes usable evidence only when its summary adds real text
# beyond the headline; a group needs at least one such item to be worth an
# LLM call. Single source of truth for dedupe.py and write.py.
MIN_EFFECTIVE_SUMMARY_CHARS = 25
# CJK text is roughly twice as information-dense: a 15-character Chinese
# sentence is a complete evidential statement.
MIN_EFFECTIVE_SUMMARY_CHARS_CJK = 12

_SQUASH_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s]|_")
_CJK_RE = re.compile(r"[぀-ヿ一-鿿]")


def squash_text(text) -> str:
    """Whitespace-collapsed, case-folded text for verbatim comparisons."""
    return _SQUASH_RE.sub(" ", str(text or "")).strip().casefold()


def _comparable(text: str) -> str:
    """Squashed text with punctuation removed, so a summary that re-quotes
    the headline with CJK punctuation variants still counts as an echo."""
    return _SQUASH_RE.sub(" ", _PUNCT_RE.sub(" ", text)).strip()


def item_has_material(item: dict) -> bool:
    if not isinstance(item, dict):
        return False
    summary = _comparable(squash_text(item.get("summary")))
    if not summary:
        return False
    title = _comparable(squash_text(item.get("title")))
    if title and title in summary:
        # A summary that merely repeats the headline is not evidence.
        summary = summary.replace(title, "", 1)
    effective = summary.strip()
    threshold = (MIN_EFFECTIVE_SUMMARY_CHARS_CJK
                 if _CJK_RE.search(effective)
                 else MIN_EFFECTIVE_SUMMARY_CHARS)
    return len(effective) >= threshold


def group_has_material(group: dict) -> bool:
    return any(item_has_material(item)
               for item in (group.get("items") or []))


# Broad Taiwan feeds use one shared allowlist so a new category cannot drift
# away from the established aviation/transport coverage gate.
TAIWAN_TRANSPORT_KEYWORDS = (
    "航空", "民航", "飛安", "航班", "航機", "飛機", "客機",
    "貨機", "小型機", "機場", "航線", "空域", "空管", "跑道",
    "墜機", "迫降", "轉降", "起飛", "降落", "華航", "中華航空",
    "長榮航", "星宇", "台灣虎航", "臺灣虎航", "立榮", "華信",
    "空軍", "軍機", "共機", "中共機艦", "共艦", "軍艦", "軍港",
    "無人機", "直升機", "戰機", "轟炸機", "台鐵", "臺鐵",
    "高鐵", "捷運", "航港", "港務", "小三通", "船班",
)

TAIWAN_AIRLINE_KEYWORDS = (
    "國籍航空", "中華航空", "華航", "長榮航空", "長榮航",
    "星宇航空", "星宇", "台灣虎航", "臺灣虎航", "立榮航空", "立榮",
    "華信航空", "華信",
)

# Master source registry. `key` is the stable identifier used for
# data/raw/<key>.json. `fmt` is what we display on the sources page.
# `endpoint` is what fetch.py actually requests; `kind`:
#   official | industry | media | data
# `public` defaults to true.  Hidden manufacturer feeds still enter the
# editorial pipeline, but build.py and briefing.py omit them from public
# source-status displays.
SOURCES: dict[str, dict] = {
    "faa": {
        "name": "FAA",
        "kind": "official",
        "fmt": "HTML",
        "url": "https://www.faa.gov",
        "endpoint": "https://www.faa.gov/newsroom/press_releases",
        "type": "html",
        "cover": {
            "zh": "美國聯邦航空總署 — 新聞、AD、法規",
            "en": "US regulator — news, ADs, rules",
        },
    },
    "ntsb": {
        "name": "NTSB",
        "kind": "official",
        "fmt": "RSS",
        "url": "https://www.ntsb.gov",
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=site:ntsb.gov%20when:7d&hl=en-US&gl=US&ceid=US:en"
        ),
        "type": "rss",
        "cover": {
            "zh": "美國運輸安全委員會 — 事故調查",
            "en": "US accident investigator",
        },
    },
    "icao": {
        "name": "ICAO",
        "kind": "official",
        "fmt": "HTML",
        "url": "https://www.icao.int",
        "endpoint": "https://www.icao.int/news",
        "type": "html",
        "cover": {
            "zh": "國際民航組織 — 標準與環境",
            "en": "UN body — standards & environment",
        },
    },
    "iata": {
        "name": "IATA",
        "kind": "industry",
        "fmt": "RSS",
        "url": "https://www.iata.org",
        "endpoint": "https://www.iata.org/api/rss/pressrelease",
        "type": "rss",
        "cover": {
            "zh": "產業數據與政策",
            "en": "Industry data & policy",
        },
    },
    "easa": {
        "name": "EASA",
        "kind": "official",
        "fmt": "RSS",
        "url": "https://www.easa.europa.eu",
        "endpoint": "https://www.easa.europa.eu/en/newsroom-and-events/news/feed.xml",
        "type": "rss",
        "cover": {
            "zh": "歐盟航空安全局 — AD 與安全公告",
            "en": "EU safety agency — ADs & bulletins",
        },
    },
    "eurocontrol": {
        "name": "Eurocontrol",
        "kind": "official",
        "fmt": "HTML",
        "url": "https://www.eurocontrol.int",
        "endpoint": "https://www.eurocontrol.int/newsroom",
        "type": "html",
        "cover": {
            "zh": "歐洲空管網路狀態",
            "en": "European network operations",
        },
    },
    "reuters": {
        "name": "Reuters",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://www.reuters.com",
        # Reuters has no public RSS; per spec use a Google News RSS query.
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=(aerospace%20OR%20airline%20OR%20aviation)%20site:reuters.com%20when:2d"
            "&hl=en-US&gl=US&ceid=US:en"
        ),
        "type": "rss",
        "cover": {
            "zh": "路透社航太與國防版",
            "en": "Reuters aerospace & defense",
        },
    },
    "avherald": {
        "name": "The Aviation Herald",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://avherald.com",
        # avherald robots.txt disallows all non-search bots; use Google News
        # RSS headlines instead of crawling the site directly.
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=site:avherald.com%20when:3d&hl=en-US&gl=US&ceid=US:en"
        ),
        "type": "rss",
        "cover": {
            "zh": "全球事故事件專業追報",
            "en": "Global incident tracking",
        },
    },
    "aerospaceglobalnews": {
        "name": "Aerospace Global News",
        "kind": "media",
        "fmt": "HTML",
        "url": "https://aerospaceglobalnews.com/",
        "endpoint": "https://aerospaceglobalnews.com/latest-news/",
        "type": "html",
        "cover": {
            "zh": "全球航太、民航、國防、太空與技術新聞",
            "en": "Global aerospace, air transport, defence, space & technology news",
        },
    },
    "flightaware": {
        "name": "FlightAware",
        "kind": "data",
        "fmt": "API",
        "url": "https://flightaware.com",
        "endpoint": "https://aeroapi.flightaware.com/aeroapi",
        "type": "api",  # optional; used only when AEROAPI_KEY is set
        "cover": {
            "zh": "全球航班延誤與取消統計",
            "en": "Worldwide flight delay & cancellation statistics",
        },
    },
    "caataiwan": {
        "name": "CAA Taiwan",
        "kind": "official",
        "fmt": "RSS",
        "url": "https://www.caa.gov.tw",
        "endpoint": "https://www.caa.gov.tw/RssNewsContent.aspx?a=165&ngid=1&lang=1",
        "type": "rss",
        "cover": {
            "zh": "交通部民航局 — 航班異動與公告",
            "en": "Taiwan CAA notices",
        },
    },
    "evaair": {
        "name": "長榮航空 EVA Air",
        "kind": "official",
        "fmt": "RSS",
        "url": "https://www.evaair.com/zh-tw/about-eva-air/news/",
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=(site:evaair.com%2Fzh-tw%2Fabout-eva-air%2Fnews%2Fnews-releases"
            "%20OR%20site:evaair.com%2Fen-global%2Fabout-eva-air%2Fnews%2F"
            "news-releases)%20when:7d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        # EVA Air returns HTTP 403 to GitHub Actions. Google News is used only
        # as a headline/link index for pages on EVA Air's official domain.
        "type": "rss",
        "cover": {
            "zh": "長榮航空官方新聞稿索引 — 航線、機隊與營運動態",
            "en": "EVA Air official release index — network, fleet & operations",
        },
    },
    "simpleflying": {
        "name": "Simple Flying",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://simpleflying.com",
        "endpoint": "https://simpleflying.com/feed/",
        "type": "rss",
        "cover": {
            "zh": "全球航空新聞與產業分析",
            "en": "Global aviation news & analysis",
        },
    },
    "aerotime": {
        "name": "AeroTime",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://www.aerotime.aero",
        "endpoint": "https://www.aerotime.aero/feed",
        "type": "rss",
        "cover": {
            "zh": "全球航空新聞、產業動態與分析",
            "en": "Global aviation news, industry updates & analysis",
        },
    },
    "cnataiwan": {
        "name": "中央社 CNA",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://www.cna.com.tw",
        # official CNA feed (broad politics wire); the keyword filter below
        # keeps only aviation / military-aviation / transport items so the
        # editorial stage never burns model calls on unrelated politics
        "endpoint": "https://feeds.feedburner.com/rsscna/politics",
        "type": "rss",
        "keywords": list(TAIWAN_TRANSPORT_KEYWORDS),
        "scope_filter": True,
        "cover": {
            "zh": "中央社 — 航空、軍航與交通相關報導",
            "en": "CNA Taiwan — aviation, military air & transport",
        },
    },
    "cnataiwanfinance": {
        "name": "中央社 CNA 產經證券",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://www.cna.com.tw/list/aie.aspx",
        "endpoint": "https://feeds.feedburner.com/rsscna/finance",
        "type": "rss",
        "keywords": list(TAIWAN_TRANSPORT_KEYWORDS),
        "scope_filter": True,
        "cover": {
            "zh": "中央社產經證券 — 國籍航空、航太與交通產業",
            "en": "CNA business — Taiwan airlines, aerospace & transport",
        },
    },
    "cnataiwanairlines": {
        "name": "中央社 CNA 國籍航空",
        "kind": "media",
        "fmt": "XML",
        "url": "https://www.cna.com.tw",
        # CNA's category feeds expose only their latest entries, while this
        # publisher-declared Google News sitemap retains the recent article
        # URLs, titles and dates. CNA explicitly advertises the sitemap in
        # robots.txt; article full text still follows the existing robots and
        # allowlist policy.
        "endpoint": "https://www.cna.com.tw/GoogleNewsSitemap_fromRemote_cfp.xml",
        "type": "html",
        "parser": "xml",
        "keywords": list(TAIWAN_AIRLINE_KEYWORDS),
        "scope_filter": True,
        "cover": {
            "zh": "中央社七日國籍航空索引 — 航線、機隊與營運動態",
            "en": "CNA seven-day Taiwan-airline index — network, fleet & operations",
        },
    },
    "mndnews": {
        "name": "國防部・軍聞社",
        "kind": "official",
        "fmt": "RSS",
        "url": "https://www.mnd.gov.tw",
        # MND blocks direct RSS pulls (403); Google News headlines proxy the
        # official releases (共機動態 etc.); CNA items usually join the same
        # story group and provide the quotable material
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=site:mna.mnd.gov.tw%20OR%20site:mnd.gov.tw%20when:2d"
            "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "type": "rss",
        "scope_filter": True,
        "cover": {
            "zh": "國防部/軍聞社 — 軍事航空、機艦與運輸動態",
            "en": "Taiwan MND — military aviation, vessels & transport",
        },
    },
    "twtransport": {
        "name": "臺灣交通要聞",
        "kind": "media",
        "fmt": "RSS",
        "url": "https://news.google.com",
        "endpoint": (
            "https://news.google.com/rss/search?"
            "q=(台鐵%20OR%20高鐵%20OR%20捷運%20OR%20航港局%20OR%20小三通)"
            "%20(事故%20OR%20停駛%20OR%20停航%20OR%20出軌%20OR%20恢復)"
            "%20when:1d&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
        ),
        "type": "rss",
        "cover": {
            "zh": "台鐵/高鐵/捷運/海運重大營運與事故報導",
            "en": "Taiwan rail / metro / maritime major events",
        },
    },
}


def _load_manufacturer_source_catalog() -> dict:
    """Load the checked-in, no-secret manufacturer discovery registry.

    Malformed entries fail closed: a broken optional feed must not prevent
    the established source registry from loading or make an arbitrary URL
    reachable by fetch.py.
    """
    path = ROOT / "config" / "manufacturer_sources.json"
    try:
        with open(path, encoding="utf-8") as fh:
            catalog = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        print(f"config: manufacturer sources unavailable ({exc})")
        return {"schemaVersion": 1, "feeds": [], "socialAccounts": []}
    if not isinstance(catalog, dict):
        print("config: manufacturer sources must be an object")
        return {"schemaVersion": 1, "feeds": [], "socialAccounts": []}
    return catalog


MANUFACTURER_SOURCE_CATALOG = _load_manufacturer_source_catalog()
_SOURCE_REQUIRED = {"key", "name", "kind", "fmt", "url", "endpoint",
                    "type", "cover"}
for _manufacturer_source in MANUFACTURER_SOURCE_CATALOG.get("feeds") or []:
    if not isinstance(_manufacturer_source, dict):
        print("config: ignored non-object manufacturer feed")
        continue
    _manufacturer_key = str(_manufacturer_source.get("key") or "").strip()
    _manufacturer_urls = (
        str(_manufacturer_source.get("url") or ""),
        str(_manufacturer_source.get("endpoint") or ""),
    )
    if (not _manufacturer_key
            or not _SOURCE_REQUIRED.issubset(_manufacturer_source)
            or _manufacturer_source.get("type") not in {"rss", "html"}
            or any(urlsplit(url).scheme != "https"
                   or not urlsplit(url).netloc
                   for url in _manufacturer_urls)
            or _manufacturer_key in SOURCES):
        print(f"config: ignored invalid/duplicate manufacturer feed "
              f"{_manufacturer_key!r}")
        continue
    SOURCES[_manufacturer_key] = _manufacturer_source


CATEGORIES = ("safety", "reg", "biz", "ops", "mil")

# Site-wide subject gate.  A military label does not by itself make a story
# relevant to an aviation and transport publication: the material must still
# contain a concrete aviation, airspace, maritime, rail or road-transport
# subject.  Keep these terms specific enough that generic politics/defence
# stories (budgets, speeches, presidential inspections, land exercises) fail.
_TRANSPORT_ZH_TERMS = (
    # civil and military aviation
    "航空", "民航", "飛安", "航班", "航機", "飛機", "小型機", "客機",
    "貨機", "機場", "航線", "飛航", "空域", "空管", "航管", "塔台",
    "跑道", "起飛", "降落", "墜機", "空難", "迫降", "轉降", "客艙",
    "空服員", "機師", "飛行員", "直升機", "無人機", "戰機", "軍機",
    "共機", "轟炸機",
    "機艦", "航太", "波音", "空中巴士", "華航", "中華航空", "長榮航",
    "星宇", "台灣虎航", "臺灣虎航", "立榮", "華信",
    # maritime transport and military vessels
    "共艦", "軍艦", "軍港", "航空母艦", "航母", "艦艇", "船班", "船舶",
    "客輪", "貨輪", "渡輪", "郵輪", "海運", "航運", "航港", "港務",
    "港口", "碼頭", "小三通", "停航", "擱淺", "沉船",
    # rail and road transport
    "台鐵", "臺鐵", "高鐵", "捷運", "鐵路", "列車", "火車", "軌道",
    "出軌", "停駛", "客運", "公車", "巴士", "高速公路", "道路運輸",
    "交通事故",
)
_TRANSPORT_EN_RE = re.compile(
    r"\b(?:"
    r"aviation|aerospace|airlines?|airports?|aircraft|airplanes?|aeroplanes?|"
    r"faa|ntsb|icao|iata|easa|eurocontrol|"
    r"air\s+cargo|airspace|air\s+traffic|flights?|runways?|pilots?|"
    r"cabin\s+crew|flight\s+attendants?|boeing|airbus|e-?vtol|ads-?b|"
    r"drones?|helicopters?|fighter\s+(?:jets?|aircraft)|bombers?|"
    r"warships?|naval\s+(?:vessels?|base|port)|aircraft\s+carriers?|"
    r"shipping|maritime|ports?|harbou?rs?|ferr(?:y|ies)|cruise\s+ships?|"
    r"cargo\s+ships?|passenger\s+ships?|vessels?|"
    r"railways?|railroads?|trains?|metros?|subways?|high-?speed\s+rail|"
    r"buses?|coaches|highways?|road\s+transport|transportation"
    r")\b",
    re.IGNORECASE,
)
_TRANSPORT_HEADLINE_ZH_TERMS = (
    "豪華經濟艙", "商務艙", "機組員", "紅箭", "火箭", "探空", "地滑翔機",
    "航艦", "無人載具", "教練機", "開航", "航展", "登機門", "候機廳",
    "指揮控制", "發動機", "原型機", "史基浦", "達美", "墨航",
)
_TRANSPORT_HEADLINE_EN_RE = re.compile(
    r"\b(?:air\s+force|airshow|air\s+show|aircrew|red\s+arrows?|"
    r"seaglider|schiphol|farnborough|gulfstream|cessna|lockheed|"
    r"recaro|collins|delta|rafale|fighter|prototype|rocket|missile|"
    r"air\s+base|airbase)\b",
    re.IGNORECASE,
)
_AIRCRAFT_MODEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]{1,4}-?\d{2,4}[A-Z0-9]*(?:-\d+)?|"
    r"Il-\d{2,4}(?:-\d+)?|"
    r"R\d|JASSM|EPACS)\b"
)
_MILITARY_REPLICA_ZH_RE = re.compile(
    r"(?:建造|打造|興建|搭建|建).{0,24}(?:模型|複製品)"
    r"|(?:模型|複製品).{0,32}(?:國防預算|敵情|威脅|情報)"
)
_MILITARY_REPLICA_EN_RE = re.compile(
    r"\b(?:scale models?|replicas?|mock-?ups?)\b.{0,100}\b(?:"
    r"presidential|government|military|warships?|fighter jets?|"
    r"naval base|defen[cs]e budget)\b",
    re.IGNORECASE,
)


def _string_values(value):
    """Yield JSON-shaped string values without field names.

    Ignoring dictionary keys matters here: an empty ``aircraft_models`` field
    must not make an otherwise political article look aviation-related.
    """
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_values(child)
    elif isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _string_values(child)


def is_transport_story(*records) -> bool:
    """True only for concrete aviation or transport subject matter."""
    text = " ".join(
        part for record in records for part in _string_values(record)
    )
    # Replicas and training mock-ups are not real aircraft/vessel/transport
    # operations.  Without this veto, incidental mentions such as "fighter
    # jet models" or "naval-base model" can defeat the subject gate.
    if (_MILITARY_REPLICA_ZH_RE.search(text)
            or _MILITARY_REPLICA_EN_RE.search(text)):
        return False
    return (any(term in text for term in _TRANSPORT_ZH_TERMS)
            or _TRANSPORT_EN_RE.search(text) is not None)


def _headline_values(value):
    """Yield only title fields from RSS items or stored bilingual articles."""
    if isinstance(value, str):
        yield value
        return
    if not isinstance(value, dict):
        return
    title = value.get("title")
    if isinstance(title, str):
        yield title
    for lang in ("zh", "en"):
        block = value.get(lang)
        if isinstance(block, dict) and isinstance(block.get("title"), str):
            yield block["title"]


def is_transport_headline(*records) -> bool:
    """True when a story's headline itself names a transport subject.

    Summaries and body paragraphs often mention an airline only as a partner,
    advertiser or piece of background context.  Broad feeds therefore need a
    title-level gate in addition to the wider source-material gate.
    """
    headline = " ".join(
        title for record in records for title in _headline_values(record)
    )
    if not headline.strip():
        return False
    if (_MILITARY_REPLICA_ZH_RE.search(headline)
            or _MILITARY_REPLICA_EN_RE.search(headline)):
        return False
    return (is_transport_story({"title": headline})
            or any(term in headline for term in _TRANSPORT_HEADLINE_ZH_TERMS)
            or _TRANSPORT_HEADLINE_EN_RE.search(headline) is not None
            or _AIRCRAFT_MODEL_RE.search(headline) is not None)


_TAIWAN_AIRLINE_ZH_TERMS = TAIWAN_AIRLINE_KEYWORDS
_TAIWAN_AIRLINE_EN_RE = re.compile(
    r"\b(?:china airlines|eva air|starlux(?: airlines?)?|"
    r"tigerair taiwan|uni air|mandarin airlines)\b",
    re.IGNORECASE,
)


def is_taiwan_airline_story(*records) -> bool:
    """Whether source material concerns a Taiwan-based national carrier.

    This is an editorial priority signal only. Freshness, deduplication,
    source completeness and safety review continue to apply downstream.
    """
    text = " ".join(
        part for record in records for part in _string_values(record)
    )
    return (any(term in text for term in _TAIWAN_AIRLINE_ZH_TERMS)
            or _TAIWAN_AIRLINE_EN_RE.search(text) is not None)


# Military takes precedence over the other editorial categories when it is
# part of the story's editorial focus.  Keep the terms deliberately specific:
# generic aviation-security language such as "counter-drone" or "defence
# against interference" must not turn a civil FAA story into military news.
_MILITARY_ZH_TERMS = (
    "國防部",
    "國軍",
    "共軍",
    "共機",
    "共艦",
    "解放軍",
    "軍聞社",
    "漢光",
    "軍事",
    "軍機",
    "軍艦",
    "戰機",
    "轟炸機",
    "空軍",
    "海軍",
    "陸軍",
    "國防預算",
    "中科院",
    "聯合防禦操演",
    "戰略預備隊",
)
_MILITARY_EN_RE = re.compile(
    r"\b(?:"
    r"military|armed forces|people(?:'|’)?s liberation army|pla|"
    r"air force|navy|warships?|fighter jets?|fighter aircraft|bombers?|"
    r"taiwan mnd|mndnews|mnd\.gov\.tw|"
    r"(?:ministry|department) of (?:national )?defen[cs]e|"
    r"defen[cs]e (?:ministry|minister|budget)|pentagon|"
    r"han kuang|joint defen[cs]e exercise|strategic reserve|ncsist"
    r")\b",
    re.IGNORECASE,
)

_BUSINESS_FOCUS_RE = re.compile(
    r"(?:"
    r"財報|季報|業績|營收|收入|淨利|獲利|虧損|每股|現金流|"
    r"積壓訂單|交付量|民航機交付|商用飛機交付|"
    r"\b(?:financial results?|quarterly results?|earnings|revenue|"
    r"net income|profit|loss per share|cash flow|commercial deliveries|"
    r"commercial aircraft deliveries|commercial airplanes? deliveries|"
    r"backlog)\b"
    r")",
    re.IGNORECASE,
)

_CLASSIFICATION_TEXT_FIELDS = (
    "title",
    "summary",
    "flash",
    "primarySource",
    "sourceKey",
)


def _classification_values(value, fields=_CLASSIFICATION_TEXT_FIELDS):
    """Yield only fields that describe a story's primary editorial focus.

    Body paragraphs, facts, source quotes and entity lists deliberately do
    not participate.  They commonly contain secondary business segments or
    contextual organisations and previously caused mixed civil/defence
    company reports to be forced into the military category.
    """
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for field in fields:
            child = value.get(field)
            if isinstance(child, str):
                yield child
            elif isinstance(child, dict):
                yield from _classification_values(child, fields)
        for locale in ("zh", "en"):
            child = value.get(locale)
            if isinstance(child, str):
                yield child
            elif isinstance(child, dict):
                yield from _classification_values(child, fields)
        for item in value.get("items") or []:
            yield from _classification_values(item, fields)
        return
    if isinstance(value, (list, tuple, set)):
        for child in value:
            yield from _classification_values(child, fields)


def _classification_text(records, fields=_CLASSIFICATION_TEXT_FIELDS) -> str:
    return " ".join(
        text for record in records
        for text in _classification_values(record, fields)
        if text
    )


def _matches_military(text: str) -> bool:
    return (any(term in text for term in _MILITARY_ZH_TERMS)
            or _MILITARY_EN_RE.search(text) is not None)


def is_military_story(*records) -> bool:
    """Return True when the headline-level editorial focus is military."""
    return _matches_military(_classification_text(records))


def story_category(category, *records) -> str:
    """Return the canonical category after checking the editorial focus.

    A model-selected military category is corrected to business when the
    headline is unambiguously a financial/commercial-results story and the
    headline itself has no military subject.  This narrow correction avoids
    treating a diversified manufacturer's secondary defence segment as the
    primary topic while preserving genuine military procurement reporting.
    """
    normalized = category if category in CATEGORIES else "ops"
    title_text = _classification_text(records, ("title",))
    if (normalized == "mil"
            and _BUSINESS_FOCUS_RE.search(title_text)
            and not _matches_military(title_text)):
        return "biz"
    if is_military_story(*records):
        return "mil"
    return normalized


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_minute(dt: datetime) -> str:
    """Format per spec: 2026-07-26T05:47Z (minute precision, Z suffix)."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse_iso(value: str) -> datetime:
    """Parse timestamps produced by iso_minute() or full ISO-8601 strings."""
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_cid|mc_eid|ref$|cmpid)")


def norm_url(url: str) -> str:
    """Normalize a URL for dedupe: lowercase host, drop tracking params,
    fragments and trailing slashes."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not _TRACKING_PARAMS.match(k.lower())
    ]
    return urlunsplit(
        (
            parts.scheme.lower() or "https",
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(query),
            "",
        )
    )


def is_google_news_url(url: str) -> bool:
    """Return whether ``url`` is a Google News aggregator link.

    Google News is useful as a discovery feed, but its redirect/app-shell URL
    is not an original article URL that can be credited to readers.
    """
    try:
        host = (urlsplit(str(url).strip()).hostname or "").casefold()
    except ValueError:
        return False
    return host == "news.google.com" or host.endswith(".news.google.com")


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "story"
