"""images.py — attach a real, matching photo to published articles.

Runs after write.py. For each recent article without an image it tries,
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
     airline/agency fallbacks also need a recent documented capture year.

The photo is embedded by URL from the origin service (no files are
committed); a match is stored on the article JSON and cached in
data/images.json. No confident match -> the article simply keeps no
image. Any network failure is logged and skipped: this stage may never
fail the pipeline, never calls a model, and never requires an API key.
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

ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = DATA_DIR / "images.json"
TIMEOUT = (10, 30)
HEADERS = {"User-Agent": USER_AGENT}

# Politeness caps per run; articles are few and the cache is permanent.
MAX_LOOKUPS_PER_RUN = 6
MAX_ATTEMPTS = 3          # per article before we stop retrying "none"
RETRY_AFTER_HOURS = 6
MAX_ARTICLE_AGE_DAYS = 14  # never backfill ancient batches
GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS = 10
GENERIC_ORG_MAX_PHOTO_AGE_YEARS = 10

PLANESPOTTERS_URL = "https://api.planespotters.net/pub/photos/reg/{reg}"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

_FREE_LICENSE_RE = re.compile(r"\b(cc[ -]|cc0|public domain|pd-)", re.I)
# never attach maps, logos, seals etc. as a news photo
_BAD_TITLE_RE = re.compile(
    r"map|logo|diagram|seal|icon|flag|emblem|coat of arms|chart|plan\b",
    re.I)
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
    r"|(?:HL|VH|HS|9V|9M|D|F|G|PH|EI|OE|VT|A6|A7|TC)-[A-Z]{3,4})\b")

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


def find_registration(article: dict) -> str | None:
    match = _REG_RE.search(_article_text(article))
    return match.group(1) if match else None


def find_airline(article: dict) -> str | None:
    """Return the article's primary airline, never a background mention.

    The drafting contract orders ``entities.airlines`` by relevance.  Use
    that order before scanning prose so a route story about STARLUX does not
    select China Airlines merely because the comparison carrier appears in
    the body, and an IndiGo executive story does not select a former employer.
    """
    text = _article_text(article)
    low = text.casefold()
    entities = article.get("entities") or {}
    entity_airlines = (
        entities.get("airlines") if isinstance(entities, dict) else []) or []
    for entity in entity_airlines:
        entity_low = str(entity or "").casefold()
        for airline in _airlines:
            en = str(airline.get("airline_name_en") or "")
            zh = str(airline.get("airline_name_zh_tw") or "")
            if entity_low and entity_low in (en.casefold(), zh.casefold()):
                return en or zh
    lead_parts = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        lead_parts.extend([
            str(block.get("title") or ""),
            str(block.get("summary") or ""),
            str((block.get("body") or [""])[0]),
        ])
    lead = " ".join(lead_parts)
    lead_low = lead.casefold()
    ranked = []
    for index, airline in enumerate(_airlines):
        en = str(airline.get("airline_name_en") or "")
        zh = str(airline.get("airline_name_zh_tw") or "")
        score = 0
        positions = []
        if en:
            score += lead_low.count(en.casefold()) * 10
            score += low.count(en.casefold())
            position = lead_low.find(en.casefold())
            if position >= 0:
                positions.append(position)
        if zh:
            score += lead.count(zh) * 10
            score += text.count(zh)
            position = lead.find(zh)
            if position >= 0:
                positions.append(position)
        if score:
            first_position = min(positions) if positions else len(lead)
            ranked.append((score, -first_position, -index, en or zh))
    return max(ranked)[3] if ranked else None


def find_aircraft_type(article: dict) -> str | None:
    """Display name for a type the article mentions.

    Accepts the full name ("Airbus A350-900"), the bare model
    ("A350-900"), the ICAO code ("A359"), or the family ("A350") — the
    family match returns the family-level name so the photo query never
    claims a sub-variant the article did not verify.
    """
    text = _article_text(article)
    low = text.casefold()
    for code, name in _types.items():
        maker = name.split()[0]
        bare = name.split()[-1]
        if name.casefold() in low or (len(bare) >= 4
                                      and bare.casefold() in low):
            return name
        if len(code) >= 4 and re.search(rf"\b{re.escape(code)}\b", text):
            return name
        family = bare.split("-")[0]
        if (len(family) >= 4 and family.casefold() != bare.casefold()
                and re.search(rf"\b{re.escape(family)}\b", text, re.I)):
            return f"{maker} {family}"
    return None


def find_airport(article: dict):
    """(commons_query, required_title_tokens, subject_zh) for an airport."""
    text = _article_text(article)
    low = text.casefold()
    for marker, query, tokens, subject in _AIRPORT_ALIASES:
        if marker in text:
            return query, list(tokens), subject
    for ap in _tw_airports:
        for key in ("name_zh", "name_en"):
            val = str(ap.get(key) or "")
            if val and (val in text or val.casefold() in low):
                name = str(ap.get("name_en") or val)
                return name, [name.split()[0]], str(ap.get("name_zh") or name)
    return None


def find_org(article: dict):
    """(commons_query, required_title_tokens, subject_zh) for an agency."""
    text = _article_text(article)
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


def existing_image_matches(article: dict, image) -> bool:
    """Whether an existing automatic image still fits revised article facts.

    Only Commons images produced by this pipeline carry ``matched`` or
    ``subject`` provenance and are eligible for replacement.  Legacy/manual
    images and other providers remain owner-controlled.  Exact-registration
    matches win; otherwise a newly identified primary airline must appear in
    the stored match provenance so a generic aircraft photo from another
    carrier cannot survive an article correction.
    """
    if not isinstance(image, dict):
        return True
    if (image.get("provider") != "Wikimedia Commons"
            or image.get("kind") != "file_photo"):
        return True
    provenance = " ".join(str(image.get(key) or "") for key in (
        "matched", "subject", "url", "link"))
    if not str(image.get("matched") or image.get("subject") or "").strip():
        return True
    normalized = re.sub(r"[^a-z0-9]+", " ", provenance.casefold()).strip()
    reg = find_registration(article)
    if reg:
        normalized_reg = re.sub(r"[^a-z0-9]+", " ", reg.casefold()).strip()
        if normalized_reg and normalized_reg in normalized:
            return True
    org = find_org(article)
    if org:
        query, _tokens, _subject = org
        if str(image.get("matched") or "").casefold() == query.casefold():
            try:
                photo_year = int(image.get("photoYear"))
            except (TypeError, ValueError):
                return False
            return photo_year >= (
                _article_year(article) - GENERIC_ORG_MAX_PHOTO_AGE_YEARS)
    airline = find_airline(article)
    if not airline:
        return True
    normalized_airline = re.sub(
        r"[^a-z0-9]+", " ", airline.casefold()).strip()
    generic_match = re.sub(
        r"[^a-z0-9]+", " ",
        str(image.get("matched") or "").casefold()).strip()
    if generic_match == f"{normalized_airline} aircraft":
        try:
            photo_year = int(image.get("photoYear"))
        except (TypeError, ValueError):
            return False
        return photo_year >= (
            _article_year(article) - GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS)
    return bool(normalized_airline and normalized_airline in normalized)


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
            "photoYear": _article_year(article),
        }
    return None

def lookup_planespotters(reg: str) -> dict | None:
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
        return {
            "url": str(thumb),
            "link": str(link),
            "credit": str(photo.get("photographer") or "").strip() or None,
            "license": None,  # per-photographer; the backlink is the record
            "provider": "Planespotters.net",
            "kind": "airframe_photo",
            "matched": reg,
            "subject": f"註冊號 {reg}",
        }
    return None


def lookup_commons(query: str, require_tokens: list[str],
                   subject: str | None = None,
                   require_all: bool = False,
                   min_year: int | None = None,
                   prefer_recent: bool = False) -> dict | None:
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
                            "iiprop": "url|extmetadata",
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
        token_hits = [t in title.casefold() for t in tokens]
        if tokens and (not all(token_hits) if require_all
                       else not any(token_hits)):
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
                "photoYear": photo_year,
            }
            if not prefer_recent:
                return candidate
            candidates.append((photo_year or 0,
                               -int(page.get("index", 99)), candidate))
    return max(candidates, key=lambda row: row[:2])[2] if candidates else None


def resolve_image(article: dict) -> dict | None:
    """Best honest match for one article, or None. Network errors bubble."""
    if article.get("articleFormat") == "roundup":
        # A single airline, aircraft or place photo would misrepresent a
        # briefing made of unrelated events.  Use the site's neutral fallback.
        return None
    source_photo = lookup_official_source_photo(article)
    if source_photo:
        return source_photo
    reg = find_registration(article)
    if reg:
        photo = lookup_planespotters(reg)
        if photo:
            return photo
    airline = find_airline(article)
    actype = find_aircraft_type(article)
    airport = find_airport(article)
    if airline and actype:
        # family token ("A350") so Commons titles with any sub-variant match
        type_token = actype.split()[-1].split("-")[0]
        return lookup_commons(
            f'{airline} {actype}', [type_token, airline],
            subject=f"{airline} {actype}", require_all=True)
    if actype:
        type_token = actype.split()[-1].split("-")[0]
        return lookup_commons(f'{actype} aircraft', [type_token],
                              subject=actype)
    if airline:
        min_year = (
            _article_year(article) - GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS)
        return lookup_commons(
            f'{airline} aircraft', [airline], subject=airline,
            min_year=min_year, prefer_recent=True)
    if airport:
        query, tokens, subject = airport
        return lookup_commons(query, tokens, subject=subject)
    org = find_org(article)
    if org:
        query, tokens, subject = org
        min_year = _article_year(article) - GENERIC_ORG_MAX_PHOTO_AGE_YEARS
        return lookup_commons(query, tokens, subject=subject,
                              min_year=min_year, prefer_recent=True)
    return None  # nothing visual verified in this article -> no image


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


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("images: no articles yet")
        return 0
    cache = load_json(CACHE_PATH, {})
    entries = cache.get("articles")
    if not isinstance(entries, dict):
        entries = {}
    cache = {"articles": entries}
    now = now_utc()
    lookups = attached = 0

    for path, batch, articles in _recent_batches():
        changed = False
        for article in articles:
            art_id = str(article.get("id") or "")
            if not art_id:
                continue
            if article.get("articleFormat") == "roundup":
                if article.pop("image", None) is not None:
                    changed = True
                entries.pop(art_id, None)
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
                if entry.get("attempts", 0) >= MAX_ATTEMPTS:
                    continue
                try:
                    if (entry.get("next_retry_utc")
                            and parse_iso(entry["next_retry_utc"]) > now):
                        continue
                except ValueError:
                    pass
            if entry.get("status") == "matched" and entry.get("image"):
                if existing_image_matches(article, entry["image"]):
                    article["image"] = entry["image"]
                    changed = True
                    attached += 1
                    continue
                entries.pop(art_id, None)
                entry = {}
            if lookups >= MAX_LOOKUPS_PER_RUN:
                continue
            lookups += 1
            try:
                image = resolve_image(article)
            except Exception as exc:  # enhancement only: never fail the run
                print(f"images: lookup failed for {art_id}: "
                      f"{type(exc).__name__}: {exc}")
                continue
            if image:
                article["image"] = image
                changed = True
                attached += 1
                entries[art_id] = {"status": "matched", "image": image,
                                   "checked_utc": now.isoformat()}
            else:
                attempts = entry.get("attempts", 0) + 1
                entries[art_id] = {
                    "status": "none", "attempts": attempts,
                    "checked_utc": now.isoformat(),
                    "next_retry_utc":
                        (now + timedelta(hours=RETRY_AFTER_HOURS))
                        .isoformat(),
                }
        if changed:
            save_json(path, batch)

    if cache != load_json(CACHE_PATH, {}):
        save_json(CACHE_PATH, cache)
    print(f"images: {lookups} lookup(s), {attached} article(s) got a photo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
