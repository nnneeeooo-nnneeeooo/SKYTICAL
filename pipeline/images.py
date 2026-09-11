"""images.py — attach a real, matching photo to published articles.

Runs after write.py. A captioned CNA publicity photo from the exact cited
article is checked first, including when a provisional Commons photo exists.
Source lookups have a separate six-request budget and retry failures after
six hours within the same seven-day freshness window.
For each remaining recent article without an image it tries,
in order:

  1. An event photo attached to a supported official source release.
     Taiwan CAA attachments are tied to the exact cited news item and are
     labelled as event photos.
  2. planespotters.net public photos API (no key) by aircraft
     registration found in the article — a photo of the SAME airframe
     (kind "airframe_photo"). Free with photographer credit + backlink,
     which the site renders under the image.
  3. Wikimedia Commons API (no key) with a conservative query built only
     from entities the article actually verified (airline + aircraft
     type, else airport, airline or agency). Only freely-licensed results
     (CC*/public domain) with required title tokens are accepted. Generic
     airline fallbacks additionally reject cabin/interior titles; generic
     airline/agency fallbacks also need a recent documented capture year.

The photo is embedded by URL from the origin service (no files are
committed); a match is stored on the article JSON and cached in
data/images.json. No confident match -> the article simply keeps no
image. Any network failure is logged and skipped: this stage may never
fail the pipeline, never calls a model, and never requires an API key.
Existing automatic images are revalidated inside the same seven-day article
window.  A stale or semantically unsafe match is removed before a replacement
is attempted; the neutral site fallback is preferable to a misleading photo.
"""
from __future__ import annotations

import re
import sys
from datetime import timedelta
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    ARTICLES_DIR,
    DATA_DIR,
    USER_AGENT,
    load_json,
    now_utc,
    parse_iso,
    save_json,
)
from image_policy import (  # noqa: E402
    BAD_AIRCRAFT_TITLE_RE,
    BAD_AIRLINE_INTERIOR_RE,
    BAD_AIRPORT_TITLE_RE,
    article_is_airport_operations,
    article_context_text,
    article_headline_text,
    article_is_incident,
    article_lead_text,
    image_is_safe_for_article,
    image_provenance,
)
from requests.exceptions import RequestException
from source_images import (PARSER_VERSION as SOURCE_IMAGE_PARSER_VERSION,
                           can_upgrade, lookup_source_photo, supported_source)
from image_selection import (rejection_reason, prepare_image, enforce_recent,
                             image_key, stock_usage, MAX_STOCK_REUSE)

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = DATA_DIR / "images.json"
TIMEOUT = (10, 30)
HEADERS = {"User-Agent": USER_AGENT}

# Politeness caps per run; scale within a bounded range when due no-image
# articles accumulate, then back off negative matches while they remain fresh.
BASE_LOOKUPS_PER_RUN = 6
MAX_LOOKUPS_PER_RUN = 18
LOOKUP_BACKLOG_DIVISOR = 3
FAST_RETRY_ATTEMPTS = 3
RETRY_AFTER_HOURS = 6
LONG_RETRY_AFTER_HOURS = 24
MAX_ARTICLE_AGE_DAYS = 7  # scan only the user-facing seven-day news window
GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS = 10
GENERIC_ORG_MAX_PHOTO_AGE_YEARS = 10
MAX_PROFILE_MODEL_QUERIES = 2


def _retry_after_hours(attempts: int) -> int:
    """Use short initial retries, then a daily retry until the article ages out."""
    return (RETRY_AFTER_HOURS if attempts <= FAST_RETRY_ATTEMPTS
            else LONG_RETRY_AFTER_HOURS)

PLANESPOTTERS_URL = "https://api.planespotters.net/pub/photos/reg/{reg}"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

_FREE_LICENSE_RE = re.compile(r"\b(cc[ -]|cc0|public domain|pd-)", re.I)
# never attach maps, logos, seals etc. as a news photo
_BAD_TITLE_RE = re.compile(
    r"map|logo|diagram|schematic|seal|icon|flag|emblem|coat of arms|"
    r"chart|plan\b|mairie|municipal|town hall|city hall|residential|"
    r"\bhouse\b|\bmemorial\b|statue",
    re.I)
# A generic airline story should show the carrier's aircraft exterior, not a
# cabin product. Stories with an explicit aircraft type may still use an
# interior image when the article is specifically about that cabin product.
# Kept as a module-level alias for existing tests and callers.
_BAD_AIRLINE_INTERIOR_RE = BAD_AIRLINE_INTERIOR_RE
_BAD_AIRLINE_IMAGE_RE = re.compile(
    rf"(?:{_BAD_AIRLINE_INTERIOR_RE.pattern})|"
    rf"(?:{BAD_AIRCRAFT_TITLE_RE.pattern})",
    re.I,
)
_TAG_RE = re.compile(r"<[^>]+>")
_CAA_ATTACHMENT_RE = re.compile(
    r'<a\b(?=[^>]*\bclass=["\'][^"\']*download-filebase)'
    r'(?=[^>]*\bhref=["\'](?P<href>[^"\']+))'
    r'(?=[^>]*\btitle=["\'](?P<title>[^"\']+\.(?:jpe?g|png))["\'])'
    r'[^>]*>', re.I)
_CAA_HOSTS = {"caa.gov.tw", "www.caa.gov.tw"}
# Registrations, kept deliberately conservative to avoid false hits in
# prose (e.g. plain "N95" is NOT matched): TW B-#####, US N-regs with a
# letter suffix or 4-5 digits, JA####, and common hyphenated prefixes.
_REG_RE = re.compile(
    r"\b(B-\d{4,5}|N\d{2,4}[A-Z]{1,2}|N\d{4,5}|JA\d{3,4}[A-Z]?"
    r"|(?:HL|VH|HS|9S|9V|9M|D|F|G|PH|EI|OE|VT|A6|A7|TC)-[A-Z]{3,4})\b")
_ENTITY_REG_RE = re.compile(
    r"^(?:B-\d{4,5}|N\d{2,5}[A-Z]{0,2}|JA\d{3,4}[A-Z]?|"
    r"[A-Z0-9]{1,2}-[A-Z0-9]{3,5})$", re.I)

# Location wording -> Taiwan airport photo query. Articles about island
# routes say 澎湖/金門/馬祖, never the airport's registry name, so the
# config-name match below rarely fires on its own.
_AIRPORT_ALIASES = (
    ("桃園機場", "Taoyuan International Airport", ("Taoyuan",), "桃園國際機場"),
    ("桃園國際機場", "Taoyuan International Airport", ("Taoyuan",), "桃園國際機場"),
    ("松山機場", "Taipei Songshan Airport", ("Songshan",), "臺北松山機場"),
    ("小港機場", "Kaohsiung International Airport", ("Kaohsiung",), "高雄國際機場"),
    ("高雄國際機場", "Kaohsiung International Airport", ("Kaohsiung",), "高雄國際機場"),
    ("澎湖", "Magong Airport Penghu", ("Magong",), "澎湖馬公機場"),
    ("馬公", "Magong Airport Penghu", ("Magong",), "澎湖馬公機場"),
    ("金門", "Kinmen Airport", ("Kinmen",), "金門機場"),
    ("馬祖", "Matsu Nangan Airport", ("Nangan", "Matsu"), "馬祖南竿機場"),
    ("南竿", "Matsu Nangan Airport", ("Nangan", "Matsu"), "馬祖南竿機場"),
    ("北竿", "Matsu Beigan Airport", ("Beigan", "Matsu"), "馬祖北竿機場"),
    ("花蓮機場", "Hualien Airport", ("Hualien",), "花蓮機場"),
    ("臺東機場", "Taitung Airport", ("Taitung",), "臺東機場"),
    ("台東機場", "Taitung Airport", ("Taitung",), "臺東機場"),
)

# Official-agency fallback: a story about a regulator with no aircraft/
# airport entity gets an honest agency file photo. ASCII keys match on
# word boundaries; CJK keys as substrings.
_ORG_QUERIES = (
    ("faa", "Federal Aviation Administration headquarters",
     ("Federal Aviation",), "美國聯邦航空總署（FAA）總部"),
    ("ntsb", "National Transportation Safety Board",
     ("NTSB", "National Transportation Safety"), "美國國家運輸安全委員會（NTSB）"),
    ("icao", "International Civil Aviation Organization headquarters",
     ("ICAO", "International Civil Aviation"), "國際民航組織（ICAO）總部"),
    ("iata", "International Air Transport Association",
     ("IATA",), "國際航空運輸協會（IATA）"),
    ("easa", "European Union Aviation Safety Agency",
     ("EASA",), "歐盟航空安全局（EASA）"),
    ("eurocontrol", "Eurocontrol headquarters", ("Eurocontrol",),
     "歐洲空管組織（Eurocontrol）總部"),
    ("民用航空局", "交通部民用航空局", ("民用航空局", "Civil Aeronautics"),
     "交通部民用航空局"),
)

_airlines = [
    a for a in (load_json(ROOT / "config" / "airline_icao_codes.json", {})
                .get("airlines") or [])
    if isinstance(a, dict) and a.get("airline_name_en")
]
_types = {
    str(k): str(v)
    for k, v in (load_json(ROOT / "config" / "aircraft_types.json", {})
                 .get("types") or {}).items()
}
_tw_airports = [
    a for a in (load_json(ROOT / "config" / "tw_civil_airports.json", {})
                .get("airports") or [])
    if isinstance(a, dict)
]
_visual_profile_rows = [
    row
    for row in (load_json(ROOT / "config" / "airline_visual_profiles.json", {})
                .get("profiles") or [])
    if isinstance(row, dict) and row.get("airline")
]
_visual_profiles = {
    str(name).strip().casefold(): row
    for row in _visual_profile_rows
    for name in [row.get("airline"), *(row.get("aliases") or [])]
    if str(name or "").strip()
}

_CARGO_VISUAL_RE = re.compile(
    r"貨機|貨運|航空貨運|全貨機|客改貨|\bcargo\b|\bfreight(?:er)?\b", re.I)
_REGIONAL_VISUAL_RE = re.compile(
    r"國內線|區域航線|短程航線|離島航線|\bdomestic\b|\bregional\b|\bshort[- ]haul\b",
    re.I,
)


def _article_text(article: dict) -> str:
    parts = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.append(str(block.get("title") or ""))
        parts.append(str(block.get("summary") or ""))
        parts.extend(str(p) for p in block.get("body") or [])
    for fact in article.get("facts") or []:
        if isinstance(fact, dict):
            parts.append(str(fact.get("claim") or ""))
            parts.append(str(fact.get("sourceQuote") or ""))
    ents = article.get("entities") or {}
    if isinstance(ents, dict):
        for group in ents.values():
            if isinstance(group, list):
                parts.extend(str(v) for v in group if v)
    return " ".join(parts)


def airline_visual_profile(airline: str | None) -> dict | None:
    """Return a verified profile; absence must never be filled by guessing."""
    return _visual_profiles.get(str(airline or "").casefold())


def airline_visual_role(article: dict) -> str:
    """Classify only broad roles that are safe for a generic airline photo."""
    lead = f"{article_headline_text(article)} {article_lead_text(article)}"
    if _CARGO_VISUAL_RE.search(lead):
        return "cargo"
    if _REGIONAL_VISUAL_RE.search(lead):
        return "regional"
    return "flagship"


def preferred_airline_models(article: dict, airline: str | None) -> list[str]:
    """Verified representative models for an airline-only story.

    Exact article-named models bypass this function.  A cargo story with no
    verified cargo profile deliberately returns no passenger substitute.
    """
    profile = airline_visual_profile(airline)
    if not profile:
        return []
    role = airline_visual_role(article)
    values = profile.get(role) or (
        [] if role == "cargo" else profile.get("flagship"))
    return [str(value).strip() for value in values or [] if str(value).strip()]


def profiled_airline_stock_reason(article: dict, airline: str,
                                  evidence_text: str) -> str | None:
    """Reject a generic stock photo outside the airline's verified role."""
    if find_aircraft_type(article):
        return None
    profile = airline_visual_profile(airline)
    if not profile:
        return None
    from image_selection import model_matches
    role = airline_visual_role(article)
    allowed = preferred_airline_models(article, airline)
    if role == "cargo" and not allowed:
        return "airline-cargo-profile-unavailable"
    if any(model_matches(str(model), evidence_text)
           for model in profile.get("excluded_generic") or []):
        return "nonrepresentative-airline-stock"
    if allowed and not any(model_matches(model, evidence_text)
                           for model in allowed):
        return "airline-role-mismatch"
    return None


def find_registration(article: dict) -> str | None:
    lead = article_lead_text(article)
    entities = article.get("entities") or {}
    registrations = (entities.get("registration_numbers")
                     if isinstance(entities, dict) else []) or []
    for value in registrations:
        candidate = str(value or "").strip().upper()
        if (_ENTITY_REG_RE.fullmatch(candidate)
                and re.search(
                    rf"(?<![A-Z0-9]){re.escape(candidate)}(?![A-Z0-9])",
                    lead, re.I)):
            return candidate
    match = _REG_RE.search(lead)
    return match.group(1) if match else None


def find_airline(article: dict) -> str | None:
    """Return the article's primary airline, never a background mention.

    ``entities.airlines`` is normally relevance-ordered, but some source
    drafts put a comparison carrier first.  A carrier named first in the
    headline wins; entity order is the tie-breaker.  Unknown but verified
    airline entities are retained instead of falling back to a coincidental
    dictionary match elsewhere in the article.
    """
    entities = article.get("entities") or {}
    entity_airlines = (
        entities.get("airlines") if isinstance(entities, dict) else []) or []

    def canonical(entity) -> str:
        raw = str(entity or "").strip()
        raw_low = raw.casefold()
        for airline in _airlines:
            en = str(airline.get("airline_name_en") or "").strip()
            zh = str(airline.get("airline_name_zh_tw") or "").strip()
            if (raw_low in {en.casefold(), zh.casefold()}
                    or (len(raw) >= 2 and raw_low in zh.casefold())):
                return en or zh or raw
        profile = airline_visual_profile(raw)
        if profile:
            return str(profile.get("airline") or raw)
        return raw

    def aliases(name: str) -> list[str]:
        return _airline_aliases(name)

    headline_parts = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        headline_parts.append(str(block.get("title") or ""))
    headline = " ".join(headline_parts)
    summary_parts = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        summary_parts.append(str(block.get("summary") or ""))
    summary = " ".join(summary_parts)

    ranked = []
    for index, entity in enumerate(entity_airlines):
        name = canonical(entity)
        if not name:
            continue
        positions = [
            position for value in aliases(name)
            for text, rank in ((headline, 0), (summary, 1))
            if (position := text.casefold().find(value.casefold())) >= 0
        ]
        if positions:
            # Headline order is the strongest signal, then summary order.
            title_positions = [
                headline.casefold().find(value.casefold())
                for value in aliases(name)
                if headline.casefold().find(value.casefold()) >= 0
            ]
            if title_positions:
                ranked.append((0, min(title_positions), index, name))
                continue
            summary_positions = [
                summary.casefold().find(value.casefold())
                for value in aliases(name)
                if summary.casefold().find(value.casefold()) >= 0
            ]
            ranked.append((1, min(summary_positions), index, name))
    if ranked:
        if min(ranked)[0] > 0 and find_aircraft_type({"en": {"title": headline}}):
            return None
        return min(ranked)[3]

    # No verified entity: only inspect the headline and summary.  Searching
    # the full body is how comparison carriers became false primary matches.
    for text in (headline, summary):
        ranked = []
        text_low = text.casefold()
        for index, airline in enumerate(_airlines):
            names = [str(airline.get(key) or "").strip()
                     for key in ("airline_name_en", "airline_name_zh_tw")]
            zh = names[1]
            if zh in {"星宇航空", "長榮航空", "立榮航空", "華信航空"}:
                names.append(zh[:-2])
            positions = [
                text_low.find(name.casefold())
                for name in names if name and text_low.find(name.casefold()) >= 0
            ]
            if positions:
                ranked.append((min(positions), -len(names[0]), -index,
                               names[0] or names[1]))
        if ranked:
            return min(ranked)[3]
    return None


def _aircraft_types_in_text(text: str, models=()) -> list[str]:
    """Return distinct aircraft types in textual order, preserving variants."""
    candidates = []
    for value in list(models) + list(_types.values()) + list(_types):
        value = str(value or "").strip()
        if not value or value.lower() in {"aircraft", "airplane", "unknown"}:
            continue
        hit = re.search(
            rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", text, re.I)
        if hit:
            candidates.append((hit.start(), -len(value), _types.get(value, value)))
    # Preserve the entire suffix (including MAX numbers and neo/XLR).
    for hit in re.finditer(
            r"(?<![A-Za-z0-9])(?:A\d{3}(?:-\d{3,4}|neo|XLR)?|"
            r"7\d7(?:-\d{1,3}(?:ER|F)?|\s+MAX(?:\s+\d{1,2})?)?)"
            r"(?![A-Za-z0-9])", text, re.I):
        value = hit.group()
        candidates.append((
            hit.start(), -len(value),
            ("Airbus " if value.upper().startswith("A") else "Boeing ") + value))
    found = []
    seen = set()
    for _, _, value in sorted(candidates):
        key = str(value).casefold()
        if key not in seen:
            seen.add(key)
            found.append(value)
    return found


def headline_aircraft_types(article: dict) -> list[str]:
    """Return only aircraft types explicitly present in either headline."""
    models = (article.get("entities") or {}).get("aircraft_models") or []
    return _aircraft_types_in_text(article_headline_text(article), models)


def find_aircraft_type(article: dict) -> str | None:
    """Title before summary; longest model at the same position wins."""
    models = (article.get("entities") or {}).get("aircraft_models") or []
    for text in (article_headline_text(article), article_context_text(article)):
        candidates = _aircraft_types_in_text(text, models)
        if candidates:
            return candidates[0]
    return None


def find_airport(article: dict):
    """Choose a named headline airport before a summary/background airport."""
    from image_selection import phrase
    from airport_codes import resolve_airport
    candidates = []
    for marker, query, tokens, subject in _AIRPORT_ALIASES:
        candidates.append(([marker], query, list(tokens), subject))
    for ap in _tw_airports:
        name = str(ap.get("name_en") or "")
        if name:
            candidates.append(([name, ap.get("name_zh", "")], name,
                               [name.split()[0]], ap.get("name_zh") or name))
    generic = {"airport", "international", "intl", "terminal", "airfield"}
    for value in (article.get("entities") or {}).get("airports") or []:
        name = str(value or "").strip()
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", name)
        tokens = [w for w in words if len(w) >= 4 and w.casefold() not in generic][:3]
        if not tokens and not re.search(r"[一-鿿]", name):
            continue
        aliases = [name]
        row = resolve_airport(name)
        if row:
            aliases.extend([row.get("name", ""), row.get("code", "")])
        # Distinctive name tokens help locate translated/shortened headlines;
        # the image itself still needs the entire token set or registry match.
        aliases.extend(tokens)
        candidates.append((aliases, name, tokens or [name], name))
    for text in (article_headline_text(article), article_context_text(article)):
        ranked = []
        for index, (aliases, query, tokens, subject) in enumerate(candidates):
            positions = [text.casefold().find(a.casefold()) for a in aliases if a and phrase(a, text)]
            if positions:
                ranked.append((min(positions), index, query, tokens, subject))
        if ranked:
            _, _, query, tokens, subject = min(ranked)
            return query, tokens, subject
    return None


def find_org(article: dict):
    """(commons_query, required_title_tokens, subject_zh) for an agency."""
    text = article_context_text(article)
    low = text.casefold()
    for marker, query, tokens, subject in _ORG_QUERIES:
        if re.search(r"[一-鿿]", marker):
            hit = marker in text
        else:
            hit = re.search(rf"\b{re.escape(marker)}\b", low) is not None
        if hit:
            return query, list(tokens), subject
    return None


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", unescape(value))).strip()


def _commons_photo_year(metadata: dict) -> int | None:
    """Return the documented capture year, never the later upload year."""
    value = _strip_html(str(
        (metadata.get("DateTimeOriginal") or {}).get("value") or ""))
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


def _article_year(article: dict) -> int:
    try:
        return parse_iso(str(article.get("publishedUtc"))).year
    except (TypeError, ValueError):
        return now_utc().year


def _normalized_phrase(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _image_named_airlines(image: dict) -> list[str]:
    """Return configured carrier names found in image provenance."""
    provenance = _normalized_phrase(image_provenance(image))
    found = []
    for airline in _airlines:
        en = str(airline.get("airline_name_en") or "").strip()
        zh = str(airline.get("airline_name_zh_tw") or "").strip()
        aliases = [_normalized_phrase(value) for value in (en, zh) if value]
        if any(alias and alias in provenance for alias in aliases):
            found.append(en or zh)
    return found


def _airline_aliases(name: str) -> list[str]:
    normalized = name.casefold()
    values = [name]
    for airline in _airlines:
        en = str(airline.get("airline_name_en") or "").strip()
        zh = str(airline.get("airline_name_zh_tw") or "").strip()
        if normalized in {en.casefold(), zh.casefold()}:
            values.extend((
                en, zh,
                zh[:-2] if zh in {"星宇航空", "長榮航空", "立榮航空", "華信航空"}
                else "",
            ))
            break
    profile = airline_visual_profile(name)
    if profile:
        values.extend([profile.get("airline"), *(profile.get("aliases") or [])])
    if name.endswith(" Express"):
        values.append(name.removesuffix(" Express"))
    aliases = []
    seen = set()
    for value in values:
        value = str(value or "").strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            aliases.append(value)
    return aliases


def _secondary_image_airline_allowed(article: dict,
                                     named_airlines: list[str]) -> bool:
    """Allow a secondary carrier only for explicit multi-carrier headlines."""
    entities = article.get("entities") or {}
    entity_values = (
        entities.get("airlines") if isinstance(entities, dict) else []) or []
    if not entity_values:
        return False
    headline = article_headline_text(article).casefold()
    context = article_context_text(article)
    weather_multi = re.search(
        r"typhoon|storm|weather|颱風|天氣|豪雨|航班調整|班機調整|"
        r"取消航班|航班取消",
        context,
        re.I,
    ) is not None
    for name in named_airlines:
        aliases = _airline_aliases(name)
        mentioned_in_headline = any(
            alias and alias.casefold() in headline for alias in aliases)
        if mentioned_in_headline or weather_multi:
            # Only permit the secondary image if the carrier is itself one of
            # the verified entities, not merely a dictionary match.
            for entity in entity_values:
                entity_low = str(entity or "").casefold()
                if any(
                        alias and (alias.casefold() == entity_low
                                   or entity_low in alias.casefold()
                                   or alias.casefold() in entity_low)
                        for alias in aliases):
                    return True
    return False


def existing_image_matches(article: dict, image) -> bool:
    """Shared source-evidence gate for new, cached and rendered images."""
    return rejection_reason(article, image) is None


# ── providers ────────────────────────────────────────────────────────────────

def lookup_official_source_photo(article: dict) -> dict | None:
    """Return an event photo attached to a supported official source."""
    for source in article.get("sources") or []:
        if not isinstance(source, dict):
            continue
        source_url = str(source.get("url") or "")
        try:
            if urlsplit(source_url).hostname not in _CAA_HOSTS:
                continue
        except ValueError:
            continue
        resp = requests.get(source_url, headers=HEADERS, timeout=TIMEOUT)
        if resp.status_code != 200:
            continue
        if getattr(resp, "url", source_url).rstrip("/") != source_url.rstrip("/"):
            continue
        match = _CAA_ATTACHMENT_RE.search(str(resp.text or ""))
        if not match:
            continue
        title = _strip_html(unescape(match.group("title")))
        return {
            "url": urljoin(source_url, unescape(match.group("href"))),
            "link": source_url,
            "credit": "交通部民用航空局",
            "license": None,
            "provider": "交通部民用航空局",
            "kind": "event_photo",
            "matched": str(article.get("id") or title),
            "subject": title.rsplit(".", 1)[0],
            "sourceCaption": title.rsplit(".", 1)[0],
            "photoYear": _article_year(article),
        }
    return None

def lookup_planespotters(reg: str, *, article=None) -> dict | None:
    """Photo of the exact airframe by registration; None when unavailable."""
    resp = requests.get(PLANESPOTTERS_URL.format(reg=reg),
                        headers=HEADERS, timeout=TIMEOUT)
    if resp.status_code != 200:
        return None
    photos = (resp.json() or {}).get("photos") or []
    for photo in photos:
        thumb = ((photo.get("thumbnail_large") or photo.get("thumbnail"))
                 or {}).get("src")
        link = photo.get("link")
        if not thumb or not link:
            continue
        description = " ".join(str(photo.get(key) or "").strip()
                               for key in ("airline", "aircraft", "reg"))
        description = " ".join(description.split())
        candidate = {
            "url": str(thumb),
            "link": str(link),
            "credit": str(photo.get("photographer") or "").strip() or None,
            "license": None,  # per-photographer; the backlink is the record
            "provider": "Planespotters.net",
            "kind": "airframe_photo",
            "matched": reg,
            "subject": description or f"註冊號 {reg}",
            "description": description,
        }
        if article is None or existing_image_matches(article, candidate):
            return candidate
    return None


def lookup_commons(query: str, require_tokens: list[str],
                   subject: str | None = None,
                   require_all: bool = False,
                   min_year: int | None = None,
                   prefer_recent: bool = False, prefer_landscape: bool = False,
                   required_model: str | None = None,
                   reject_title_re=None, article=None, usage=None) -> dict | None:
    """First freely-licensed Commons bitmap matching the query.

    require_tokens: title tokens used to reject unrelated search results.
    When require_all is true, every token must appear; airline-and-aircraft
    queries use this stricter mode so matching only ``A350`` can never attach
    another carrier's aircraft.
    """
    resp = requests.get(COMMONS_API, headers=HEADERS, timeout=TIMEOUT,
                        params={
                            "action": "query", "format": "json",
                            "generator": "search", "gsrnamespace": 6,
                            "gsrlimit": 20,
                            "gsrsearch": f"filetype:bitmap {query}",
                            "prop": "imageinfo",
                            "iiprop": "url|size|extmetadata",
                            "iiurlwidth": 1280,
                        })
    if resp.status_code != 200:
        return None
    pages = ((resp.json() or {}).get("query") or {}).get("pages") or {}
    tokens = [t.casefold() for t in require_tokens if t]
    candidates = []
    for page in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        title = str(page.get("title") or "")
        if _BAD_TITLE_RE.search(title):
            continue
        if reject_title_re is not None and reject_title_re.search(title):
            continue
        from image_selection import phrase
        token_hits = [phrase(t, title) for t in tokens]
        if tokens and (not all(token_hits) if require_all
                       else not any(token_hits)):
            continue
        if required_model:
            from image_selection import model_matches
            if not model_matches(required_model, title):
                continue
        for info in page.get("imageinfo") or []:
            meta = info.get("extmetadata") or {}
            license_name = _strip_html(
                str((meta.get("LicenseShortName") or {}).get("value") or ""))
            if not _FREE_LICENSE_RE.search(license_name):
                continue
            photo_year = _commons_photo_year(meta)
            if min_year is not None and (
                    photo_year is None or photo_year < min_year):
                continue
            thumb = info.get("thumburl") or info.get("url")
            if not thumb:
                continue
            artist = _strip_html(
                str((meta.get("Artist") or {}).get("value") or ""))[:80]
            candidate = {
                "url": str(thumb),
                "link": str(info.get("descriptionshorturl")
                            or info.get("descriptionurl") or thumb),
                "credit": artist or None,
                "license": license_name or None,
                "provider": "Wikimedia Commons",
                "kind": "file_photo",
                "matched": query,
                "subject": subject or None,
                "description": title.removeprefix("File:").rsplit(".", 1)[0].replace("_", " "),
                "photoYear": photo_year,
            }
            if article is not None and not existing_image_matches(article, candidate):
                continue
            count = (usage or {}).get(image_key(candidate), 0)
            if count >= MAX_STOCK_REUSE:
                continue
            if not prefer_recent and not prefer_landscape and not usage:
                return candidate
            try:
                width = int(info.get("width") or 0)
                height = int(info.get("height") or 0)
                ratio = width / height if height else 0
            except (TypeError, ValueError, ZeroDivisionError):
                width, ratio = 0, 0
            landscape = int(1.25 <= ratio <= 2.5) if prefer_landscape else 0
            resolution = min(width, 4000) if prefer_landscape else 0
            candidates.append((-count, landscape, resolution,
                               photo_year or 0 if prefer_recent else 0,
                               -int(page.get("index", 99)), candidate))
    return max(candidates, key=lambda row: row[:-1])[-1] if candidates else None


def resolve_image(article: dict, *, usage=None, diagnostics=None) -> dict | None:
    """Try independently failing providers; never relax subject constraints."""
    if article.get("articleFormat") == "roundup":
        return None
    def attempt(fn, *args, **kwargs):
        label = getattr(fn, "__name__", "provider")
        try:
            photo = fn(*args, **kwargs)
            if not photo:
                if diagnostics is not None:
                    diagnostics.append(f"{label}:no-result")
                return None
            reason = rejection_reason(article, photo)
            if not reason:
                if photo.get("kind") == "file_photo" and (usage or {}).get(image_key(photo), 0) >= MAX_STOCK_REUSE:
                    if diagnostics is not None:
                        diagnostics.append(f"{label}:stock-reuse-limit")
                    return None
                return photo
            if diagnostics is not None:
                diagnostics.append(f"{label}:{reason}")
        except (RequestException, OSError, ValueError, TypeError, KeyError) as exc:
            if diagnostics is not None:
                diagnostics.append(
                    f"{label}:lookup-error:{type(exc).__name__}")
            print(f"images: {label}: {type(exc).__name__}")
        return None
    photo = attempt(lookup_official_source_photo, article)
    if photo:
        return photo
    reg = find_registration(article)
    if reg:
        # Validate once in ``attempt`` so the precise reason is retained.
        photo = attempt(lookup_planespotters, reg)
        if photo:
            return photo
    airline, actype, airport = find_airline(article), find_aircraft_type(article), find_airport(article)
    def commons(query, tokens, **kwargs):
        return attempt(lookup_commons, query, tokens, article=article, usage=usage, **kwargs)
    photo = None
    if airport and article_is_airport_operations(article) and not (article_is_incident(article) and actype):
        query, tokens, subject = airport
        photo = commons(query, tokens, subject=subject, require_all=True, reject_title_re=BAD_AIRPORT_TITLE_RE)
    elif actype:
        query = f"{airline} {actype}" if airline else f"{actype} aircraft"
        # The shared model gate handles manufacturer subtypes (A350-941 is
        # within A350-900); an exact phrase prefilter would discard them first.
        photo = commons(query, [airline] if airline else [],
                        subject=query.removesuffix(" aircraft"), require_all=True,
                        prefer_landscape=True,
                        reject_title_re=BAD_AIRCRAFT_TITLE_RE)
    elif airline:
        profile = airline_visual_profile(airline)
        role = airline_visual_role(article)
        preferred = preferred_airline_models(article, airline)
        for representative in preferred[:MAX_PROFILE_MODEL_QUERIES]:
            photo = commons(
                f"{airline} {representative}", [airline],
                subject=f"{airline} {representative}", require_all=True,
                required_model=representative,
                min_year=_article_year(article)-GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS,
                prefer_recent=True, prefer_landscape=True,
                reject_title_re=_BAD_AIRLINE_IMAGE_RE)
            if photo:
                break
        # Unprofiled cargo carriers still receive a cargo-specific query.  A
        # profiled passenger airline with no verified cargo fleet fails closed.
        if not preferred and (role != "cargo" or not profile):
            generic_query = (f"{airline} cargo aircraft"
                             if role == "cargo"
                             else f"{airline} aircraft exterior")
            photo = commons(
                generic_query, [airline], subject=airline,
                min_year=_article_year(article)-GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS,
                prefer_recent=True, prefer_landscape=True,
                reject_title_re=_BAD_AIRLINE_IMAGE_RE)
    else:
        org = find_org(article)
        if org:
            query, tokens, subject = org
            photo = commons(query, tokens, subject=subject,
                            min_year=_article_year(article)-GENERIC_ORG_MAX_PHOTO_AGE_YEARS,
                            prefer_recent=True)
    if photo:
        return photo
    # Vetted topic candidates are subject to the identical evidence/reuse gate.
    from image_fallbacks import topic_image
    return attempt(topic_image, article, allow_airport_lookup=False)


# ── batch update ─────────────────────────────────────────────────────────────

def _recent_batches():
    cutoff = now_utc() - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    for path in sorted(ARTICLES_DIR.glob("*.json"), reverse=True):
        batch = load_json(path, None)
        if not isinstance(batch, dict):
            continue
        articles = [a for a in batch.get("articles") or []
                    if isinstance(a, dict)]
        fresh = False
        for a in articles:
            try:
                if parse_iso(str(a.get("publishedUtc"))) >= cutoff:
                    fresh = True
            except (ValueError, TypeError):
                continue
        if fresh:
            yield path, batch, articles


def _lookup_budget(articles, entries, now) -> int:
    """Scale lookups with due no-image backlog without becoming unbounded."""
    due = 0
    for article in articles:
        if article.get("articleFormat") == "roundup" or article.get("image"):
            continue
        entry = entries.get(str(article.get("id") or "")) or {}
        try:
            if (entry.get("status") == "none" and entry.get("next_retry_utc")
                    and parse_iso(entry["next_retry_utc"]) > now):
                continue
        except (TypeError, ValueError):
            pass
        due += 1
    base = min(BASE_LOOKUPS_PER_RUN, MAX_LOOKUPS_PER_RUN)
    demand = (due + LOOKUP_BACKLOG_DIVISOR - 1) // LOOKUP_BACKLOG_DIVISOR
    return min(MAX_LOOKUPS_PER_RUN, max(base, demand))


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("images: no articles yet")
        return 0
    enforce_recent()
    recent_batches = list(_recent_batches())
    usage = stock_usage([a for _, _, aa in recent_batches for a in aa])
    cache = load_json(CACHE_PATH, {})
    entries = cache.get("articles")
    if not isinstance(entries, dict):
        entries = {}
    source_entries = cache.get("sources") or {}
    cache = {"articles": entries, "sources": source_entries}
    now = now_utc()
    cutoff = now - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    lookup_budget = _lookup_budget(
        [a for _, _, aa in recent_batches for a in aa], entries, now)
    lookups = attached = source_lookups = 0

    for path, batch, articles in recent_batches:
        changed = False
        for article in articles:
            art_id = str(article.get("id") or "")
            if not art_id:
                continue
            try:
                if parse_iso(str(article.get("publishedUtc"))) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            if article.get("articleFormat") == "roundup":
                if article.pop("image", None) is not None:
                    changed = True
                entries.pop(art_id, None)
                continue
            rejection_reasons = []
            # Exact-source caption recovery outranks Commons, but a caption
            # still has to identify this article's primary visual subject.
            for candidate in (article.get("sourceImageCandidates") or []) if can_upgrade(article) else []:
                bound = dict(article, sources=candidate.get("sources") or [])
                source_image = prepare_image(bound, candidate.get("url"))
                reason = rejection_reason(bound, candidate.get("url"))
                if reason:
                    rejection_reasons.append(f"source-candidate:{reason}")
                if (source_image and not reason
                        and usage[image_key(source_image)] < MAX_STOCK_REUSE):
                    if source_image != article.get("image"):
                        article["image"] = source_image
                        article.pop("imageSelection", None)
                        usage[image_key(source_image)] += 1
                        changed = True
                    break
            # A stock fallback is provisional: RSS often omits the publisher's
            # body photo. Check the exact cited page before keeping that fallback.
            source_url = supported_source(article) if can_upgrade(article) else None
            if source_url:
                source_entry = source_entries.get(source_url) or {}
                source_image = source_entry.get("image")
                if source_image and not existing_image_matches(article, source_image):
                    source_image = None
                retry_due = True
                try:
                    retry_due = (
                        source_entry.get("parser_version")
                        != SOURCE_IMAGE_PARSER_VERSION
                        or parse_iso(source_entry["next_retry_utc"]) <= now
                    )
                except (KeyError, TypeError, ValueError):
                    pass
                if not source_image and retry_due and source_lookups < lookup_budget:
                    source_lookups += 1
                    source_reason = "no-event-photo"
                    try:
                        source_image = lookup_source_photo(article)
                    except Exception as exc:
                        source_reason = f"lookup-error:{type(exc).__name__}"
                        print(f"images: source lookup failed for {art_id}: {type(exc).__name__}")
                    if source_image:
                        source_reason = rejection_reason(article, source_image)
                        if source_reason:
                            source_image = None
                    source_entries[source_url] = {
                        "image": source_image,
                        "rejection_reason": source_reason,
                        "parser_version": SOURCE_IMAGE_PARSER_VERSION,
                        "next_retry_utc": (now + timedelta(hours=6)).isoformat(),
                    }
                    if source_reason:
                        rejection_reasons.append(f"source-photo:{source_reason}")
                if source_image and existing_image_matches(article, source_image):
                    article["image"] = source_image
                    entries[art_id] = {"status": "matched", "image": source_image,
                                       "checked_utc": now.isoformat()}
                    changed = True
                    attached += 1
                    continue
            if article.get("image"):
                if existing_image_matches(article, article["image"]):
                    continue
                print(f"images: stale airline-mismatched photo removed for "
                      f"{art_id}")
                article.pop("image", None)
                entries.pop(art_id, None)
                changed = True
            entry = entries.get(art_id) or {}
            if entry.get("status") == "none":
                try:
                    if (entry.get("next_retry_utc")
                            and parse_iso(entry["next_retry_utc"]) > now):
                        continue
                except ValueError:
                    pass
            if entry.get("status") == "matched" and entry.get("image"):
                if (existing_image_matches(article, entry["image"])
                        and usage[image_key(entry["image"])] < MAX_STOCK_REUSE):
                    article["image"] = entry["image"]
                    if entry["image"].get("kind") == "file_photo":
                        usage[image_key(entry["image"])] += 1
                    changed = True
                    attached += 1
                    continue
                entries.pop(art_id, None)
                entry = {}
            if lookups >= lookup_budget:
                continue
            lookups += 1
            try:
                image = resolve_image(article, usage=usage,
                                      diagnostics=rejection_reasons)
            except Exception as exc:  # enhancement only: never fail the run
                print(f"images: lookup failed for {art_id}: "
                      f"{type(exc).__name__}: {exc}")
                continue
            if image and existing_image_matches(article, image):
                if image.get("kind") == "file_photo":
                    usage[image_key(image)] += 1
                article.pop("imageSelection", None)
                article["image"] = image
                changed = True
                attached += 1
                entries[art_id] = {"status": "matched", "image": image,
                                   "checked_utc": now.isoformat()}
            else:
                attempts = entry.get("attempts", 0) + 1
                entries[art_id] = {
                    "status": "none", "attempts": attempts,
                    "rejection_reasons": list(dict.fromkeys(
                        rejection_reasons or ["no-suitable-image"])),
                    "checked_utc": now.isoformat(),
                    "next_retry_utc":
                        (now + timedelta(hours=_retry_after_hours(attempts)))
                        .isoformat(),
                }
        if changed:
            save_json(path, batch)

    if cache != load_json(CACHE_PATH, {}):
        save_json(CACHE_PATH, cache)
    print(f"images: budget {lookup_budget}; {lookups} stock lookup(s), "
          f"{source_lookups} source lookup(s), "
          f"{attached} article(s) got a photo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
