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

# GitHub Pages project sites live under /<repo>/ — override with env for
# user/organization pages or local preview (set AVWIRE_BASE_PATH="").
BASE_PATH = os.environ.get("AVWIRE_BASE_PATH", "/avwire").rstrip("/")

# Absolute origin for hreflang/canonical links (search engines require
# fully-qualified URLs there).
SITE_ORIGIN = (os.environ.get("AVWIRE_SITE_ORIGIN")
               or "https://nnneeeooo-nnneeeooo.github.io").rstrip("/")

USER_AGENT = (
    "AVWIREBot/1.0 (automated aviation news aggregator; "
    "+https://github.com/avwire) requests"
)

# Keep at most this many entries per source per fetch, and this many flashes.
MAX_ITEMS_PER_SOURCE = 25
MAX_FLASHES = 10
# Articles shown on the home page feed.
HOME_FEED_LIMIT = 30


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

# Master source registry. `key` is the stable identifier used for
# data/raw/<key>.json. `fmt` is what we display on the sources page.
# `endpoint` is what fetch.py actually requests; `kind`:
#   official | industry | media | data
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
    "flightaware": {
        "name": "FlightAware",
        "kind": "data",
        "fmt": "API",
        "url": "https://flightaware.com",
        "endpoint": "https://aeroapi.flightaware.com/aeroapi",
        "type": "api",  # optional; used only when AEROAPI_KEY is set
        "cover": {
            "zh": "航班追蹤與延誤數據",
            "en": "Flight tracking & delay data",
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
        "keywords": [
            "航空", "民航", "航班", "機場", "航線", "華航", "中華航空",
            "長榮航", "星宇", "台灣虎航", "臺灣虎航", "立榮", "華信",
            "空軍", "軍機", "共機", "中共機艦", "國軍", "國防部",
            "無人機", "直升機", "戰機", "台鐵", "臺鐵", "高鐵", "捷運",
            "航港", "港務", "小三通", "船班",
        ],
        "cover": {
            "zh": "中央社 — 航空、軍航與交通相關報導",
            "en": "CNA Taiwan — aviation, military air & transport",
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
        "cover": {
            "zh": "國防部/軍聞社 — 共機動態與軍事新聞",
            "en": "Taiwan MND — PLA activity & military news",
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

CATEGORIES = ("safety", "reg", "biz", "ops", "mil")

# Military takes precedence over the other editorial categories.  Keep the
# terms deliberately specific: generic aviation-security language such as
# "counter-drone" or "defence against interference" must not turn a civil FAA
# story into military news.
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


def is_military_story(*records) -> bool:
    """Return True when article/draft/group material is explicitly military.

    The accepted records are JSON-shaped pipeline objects.  Serialising them
    keeps this guard compatible with published articles, pending groups and
    review drafts without maintaining three subtly different field walkers.
    """
    try:
        text = json.dumps(records, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = " ".join(str(record) for record in records)
    return (any(term in text for term in _MILITARY_ZH_TERMS)
            or _MILITARY_EN_RE.search(text) is not None)


def story_category(category, *records) -> str:
    """Return the canonical category, with explicit military material first."""
    if is_military_story(*records):
        return "mil"
    return category if category in CATEGORIES else "ops"


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


def slugify(text: str, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "story"
