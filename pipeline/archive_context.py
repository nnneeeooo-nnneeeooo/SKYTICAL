"""Deterministic retrieval of verified historical context for AVWIRE.

The archive is the already-published ``data/articles/*.json`` collection.
This module never calls a network service, embedding model or LLM.  It
qualifies old articles, extracts reproducible identifiers from source text,
scores explicit relationships, and returns a small evidence-only context.

The caller may give the returned object to a model, but only
``selected_events`` belongs in the prompt.  ``excluded_candidates`` is kept
for tests and operational diagnostics and must never be exposed as evidence.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from common import ARTICLES_DIR, is_transport_story, parse_iso, squash_text

ARCHIVE_CONTEXT_VERSION = 1
MAX_ARCHIVE_EVENTS = 3
MAX_ARCHIVE_FACTS = 12
MAX_ARCHIVE_PROMPT_CHARS = 12000

_INJECTION_RE = re.compile(
    r"(?:ignore|disregard|override|forget)\s+(?:all\s+)?(?:previous|prior|"
    r"above|system|developer)\s+(?:instructions?|prompts?|messages?)|"
    r"(?:system|developer)\s+(?:prompt|message)|"
    r"(?:reveal|print|return|exfiltrate|leak)\s+(?:the\s+)?(?:secret|"
    r"credentials?|api[-_\s]?keys?|system\s+prompt|private\s+data)|"
    r"(?:act|pretend|role[-\s]?play)\s+as\s+(?:the\s+)?(?:system|developer|"
    r"administrator)|"
    r"output\s+(?:exactly|only)\s+|"
    r"<\s*/?\s*(?:script|iframe|system|developer)\b|"
    r"javascript\s*:|data\s*:\s*text/html",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]{0,500}>")
_SPACE_RE = re.compile(r"\s+")
_ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_REGISTRATION_RE = re.compile(
    r"\b(?:"
    r"[A-Z]{1,2}-[A-Z0-9]{3,5}|"
    r"N\d{1,5}[A-Z]{0,2}|"
    r"JA\d{3,4}[A-Z]?|"
    r"9M-[A-Z]{3}|"
    r"VH-[A-Z]{3}|"
    r"F-[A-Z]{4}|G-[A-Z]{4}|D-[A-Z]{4}"
    r")\b",
    re.IGNORECASE,
)
_MSN_RE = re.compile(
    r"\b(?:MSN|M\/S\/N|manufacturer\s+serial\s+number|serial\s+number|"
    r"製造序號|序號)\s*[:#：]?\s*([A-Z0-9][A-Z0-9-]{1,19})\b",
    re.IGNORECASE,
)
_FLIGHT_MARKED_RE = re.compile(
    r"(?:flight|flight\s+number|test\s+flight|航班|班機)\s*[:#：]?\s*"
    r"([A-Z]{2,3}\s?\d{1,4}[A-Z]?)\b|"
    r"(?:test\s+callsign|callsign|試飛呼號|呼號)\s*[:#：]?\s*"
    r"([A-Z]{3,8})\b",
    re.IGNORECASE,
)
_FLIGHT_COMPACT_RE = re.compile(r"\b([A-Z]{2,3}\d{1,4}[A-Z]?)\b")
_MODEL_RE = re.compile(
    r"\b(?:Airbus\s+|Boeing\s+|Embraer\s+|Bombardier\s+|COMAC\s+|ATR\s+)?"
    r"(?:A3\d{2}(?:-\d{3,4})?(?:ULR)?|B?7[2378]7(?:-\d{1,3})?|777X|"
    r"7[34]7(?:-\d{1,3})?|E1[789]5-E2|E\d{3}|C9(?:09|19)|"
    r"ARJ21|ATR\s?\d{2}(?:-\d{3})?|F-\d{1,2}[A-Z]?|C-\d{1,3})\b",
    re.IGNORECASE,
)
_ROUTE_DASH_RE = re.compile(
    r"\b([A-Z]{3,4})\s*(?:-|–|—|→|↔|/)\s*([A-Z]{3,4})\b")
_ROUTE_WORD_RE = re.compile(
    r"\b(?:from\s+)?([A-Z]{3,4})\s+(?:to|toward|towards)\s+"
    r"([A-Z]{3,4})\b",
    re.IGNORECASE,
)
_PROGRAMME_RE = re.compile(
    r"\b(?:Project|Programme|Program|Operation|Initiative)\s+"
    r"[A-Z0-9][A-Za-z0-9-]*(?:\s+[A-Z0-9][A-Za-z0-9-]*){0,4}\b|"
    r"[\u3400-\u9fffA-Za-z0-9·-]{2,24}(?:計畫|專案|方案|行動)",
)
_OFFICIAL_ID_RE = re.compile(
    r"\b(?:NOTAM|AD|EAD|SFAR|NPRM|Docket|Case|Investigation|Report|"
    r"Directive|Regulation|Order|Notice|Bulletin)"
    r"\s*(?:No\.?|Number|ID|#|編號|案號)?\s*[:：#-]?\s*"
    r"([A-Z0-9][A-Z0-9./-]{2,30})\b|"
    r"(?:案號|公告編號|命令編號|法規編號|指令編號|調查編號|"
    r"訂單編號|合約編號|交易編號)\s*[:：#]?\s*"
    r"([A-Z0-9][A-Z0-9./-]{2,30})",
    re.IGNORECASE,
)
_AIRPORT_CODE_RE = re.compile(
    r"(?:airport|機場|aerodrome)\s*(?:code|代碼)?\s*[:：()]?\s*"
    r"\b([A-Z]{3,4})\b",
    re.IGNORECASE,
)
_EVENT_TITLE_RE = re.compile(
    r"\b(?:announc(?:e|es|ed)|launch(?:es|ed)?|resume[sd]?|suspend(?:s|ed)?|"
    r"cancel(?:s|led)?|return(?:s|ed)?|arriv(?:e|es|ed|al)|depart(?:s|ed|ure)|"
    r"deliver(?:s|ed|y)|order(?:s|ed)?|approv(?:e|es|ed|al)|issue[sd]?|"
    r"release[sd]?|publish(?:es|ed)?|report(?:s|ed)?|test(?:s|ed|ing)?|"
    r"land(?:s|ed|ing)?|take[ -]?off|open(?:s|ed|ing)?|close[sd]?|"
    r"extend(?:s|ed)?|delay(?:s|ed)?|amend(?:s|ed)?|withdraw(?:s|n)?|"
    r"公布|宣布|啟航|首航|復航|停飛|停航|增班|減班|返回|返航|抵達|"
    r"起飛|降落|交付|訂購|核准|發布|公告|修正|延後|撤回|啟用|關閉|"
    r"調查|報告|部署|演訓|測試|試飛)\b",
    re.IGNORECASE,
)

_PLANNED_TERMS = (
    "plan", "planned", "plans to", "proposal", "proposed", "draft",
    "consultation", "considering", "expects", "scheduled", "order",
    "announced", "計畫", "規劃", "提案", "草案", "諮詢", "預計", "訂購",
    "宣布",
)
_COMPLETED_TERMS = (
    "delivered", "delivery", "entered service", "effective", "final rule",
    "final report", "inaugural", "first flight", "launched", "resumed",
    "returned", "arrived", "completed", "交付", "生效", "最終規定",
    "最終報告", "首航", "復航", "返回", "抵達", "完成",
)
_INVESTIGATION_TERMS = (
    "investigation", "investigating", "preliminary report", "final report",
    "hearing", "調查", "初步報告", "最終報告", "聽證",
)
_REGULATORY_TERMS = (
    "regulation", "directive", "rule", "consultation", "nprm", "effective",
    "amended", "withdrawn", "法規", "規定", "指令", "草案", "諮詢",
    "生效", "修正", "撤回",
)
_ORDER_TERMS = (
    "order", "contract", "option", "delivery", "fleet", "訂單", "合約",
    "選擇權", "交付", "機隊",
)
_ROUTE_TERMS = (
    "route", "service", "flight", "inaugural", "resume", "suspend",
    "航線", "航班", "首航", "復航", "停飛", "增班",
)
_MILITARY_TERMS = (
    "air force", "navy", "army", "squadron", "wing", "base", "deployment",
    "exercise", "空軍", "海軍", "陸軍", "部隊", "聯隊", "基地", "部署", "演訓",
)


def contains_prompt_injection(value) -> bool:
    """Return True for common instruction/role/data-exfiltration attacks."""
    if isinstance(value, dict):
        return any(contains_prompt_injection(k)
                   or contains_prompt_injection(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(contains_prompt_injection(v) for v in value)
    return bool(_INJECTION_RE.search(html.unescape(str(value or ""))))


def source_has_prompt_injection(group: dict) -> bool:
    """Code-level fail-closed check for current source material."""
    return contains_prompt_injection({
        "id": group.get("id"),
        "primarySource": group.get("primarySource"),
        "items": group.get("items") or [],
    })


def _plain(value) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(str(value or "")))
    text = _TAG_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _key(value) -> str:
    return squash_text(_plain(value))


def _safe_url(value) -> str | None:
    """Normalize an HTTP(S) URL without treating query text as instructions."""
    raw = _plain(value)
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme.lower() not in ("http", "https"):
        return None
    if not parsed.hostname or parsed.username or parsed.password:
        return None
    query = urlencode(parse_qsl(parsed.query, keep_blank_values=True),
                      doseq=True)
    clean = urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(),
                        parsed.path or "/", query, ""))
    if contains_prompt_injection(clean):
        return None
    return clean


def _record_text(record: dict) -> str:
    parts: list[str] = []
    if isinstance(record.get("items"), list):
        for item in record["items"]:
            if not isinstance(item, dict):
                continue
            parts.extend(str(item.get(k) or "")
                         for k in ("title", "summary", "fulltext", "source"))
    for lang in ("zh", "en"):
        block = record.get(lang) or {}
        if isinstance(block, dict):
            parts.extend([str(block.get("title") or ""),
                          str(block.get("summary") or "")])
    for fact in record.get("facts") or []:
        if isinstance(fact, dict):
            parts.extend([str(fact.get("claim") or ""),
                          str(fact.get("sourceQuote") or "")])
    entities = record.get("entities") or {}
    if isinstance(entities, dict):
        for values in entities.values():
            if isinstance(values, list):
                parts.extend(str(v) for v in values if v)
    return _plain(" ".join(parts))


def _matches(pattern: re.Pattern, text: str) -> set[str]:
    out = set()
    for match in pattern.finditer(text):
        groups = [g for g in match.groups() if g] or [match.group(0)]
        for value in groups:
            clean = _plain(value).upper()
            if clean:
                out.add(clean)
    return out


def _aircraft_model_keys(text: str) -> set[str]:
    """Return literal models plus safe, explicit programme-family aliases.

    A published source can call the 777X programme ``777X`` while a current
    certification update names a specific 777-8 or 777-9 variant.  They are
    not interchangeable aircraft facts, but they are a deterministic
    relationship anchor for retrieving programme background.  Keep the
    literal values too: the drafting prompt still receives only source quotes.
    """
    models = _matches(_MODEL_RE, text)
    for model in tuple(models):
        compact = re.sub(r"^BOEING\s+", "", model)
        if compact == "777X" or re.fullmatch(r"777-(?:8|9)", compact):
            models.add("BOEING 777X FAMILY")
    return models


def _routes(text: str) -> set[tuple[str, str]]:
    values = set()
    for pattern in (_ROUTE_DASH_RE, _ROUTE_WORD_RE):
        for a, b in pattern.findall(text):
            if a != b:
                values.add(tuple(sorted((a.upper(), b.upper()))))
    return values


def _programmes(text: str) -> set[str]:
    """Keep exact matches plus stable leading programme-name n-grams."""
    values = set()
    for match in _PROGRAMME_RE.finditer(text):
        raw = _plain(match.group(0))
        values.add(_key(raw))
        words = raw.split()
        if words and words[0].casefold() in {
                "project", "programme", "program", "operation",
                "initiative"}:
            for end in range(2, len(words) + 1):
                values.add(_key(" ".join(words[:end])))
    return values


def _status_terms(text: str) -> set[str]:
    low = text.casefold()

    def has_any(terms) -> bool:
        for term in terms:
            needle = term.casefold()
            if needle.isascii() and re.fullmatch(r"[a-z ]+", needle):
                if re.search(rf"(?<![a-z]){re.escape(needle)}(?![a-z])", low):
                    return True
            elif needle in low:
                return True
        return False

    terms = set()
    if has_any(_PLANNED_TERMS):
        terms.add("planned")
    if has_any(_COMPLETED_TERMS):
        terms.add("completed")
    if has_any(_INVESTIGATION_TERMS):
        terms.add("investigation")
    if has_any(_REGULATORY_TERMS):
        terms.add("regulatory")
    if has_any(_ORDER_TERMS):
        terms.add("order")
    if has_any(_ROUTE_TERMS):
        terms.add("route")
    if has_any(_MILITARY_TERMS):
        terms.add("military")
    return terms


def extract_entity_keys(record: dict) -> dict[str, object]:
    """Extract deterministic metadata keys from a story group or article."""
    text = _record_text(record)
    compact_flights = _matches(_FLIGHT_COMPACT_RE, text)
    # Common aircraft models and years look like compact flight numbers.
    compact_flights = {
        value for value in compact_flights
        if not _MODEL_RE.fullmatch(value)
        and not re.fullmatch(r"(?:A|B)\d{3,4}", value)
    }
    routes = _routes(text)
    airports = _matches(_AIRPORT_CODE_RE, text)
    for route in routes:
        airports.update(route)
    entities = record.get("entities") or {}
    named: dict[str, set[str]] = {}
    if isinstance(entities, dict):
        for key, values in entities.items():
            if isinstance(values, list):
                named[key] = {_key(v) for v in values
                              if len(_plain(v)) >= 2}
    dates = set(_ISO_DATE_RE.findall(text))
    for item in record.get("items") or []:
        if isinstance(item, dict):
            dates.update(_ISO_DATE_RE.findall(
                str(item.get("publishedUtc") or "")))
    for field in ("sourcePublishedUtc", "publishedUtc"):
        dates.update(_ISO_DATE_RE.findall(str(record.get(field) or "")))
    return {
        "text": text,
        "registrations": _matches(_REGISTRATION_RE, text),
        "msns": _matches(_MSN_RE, text),
        "flight_numbers": (_matches(_FLIGHT_MARKED_RE, text)
                           | compact_flights),
        "official_ids": {
            value for value in _matches(_OFFICIAL_ID_RE, text)
            if any(char.isdigit() for char in value)
        },
        "aircraft_models": _aircraft_model_keys(text),
        "programmes": _programmes(text),
        "airport_codes": airports,
        "routes": routes,
        "dates": dates,
        "statuses": _status_terms(text),
        "named": named,
    }


def has_identifiable_new_event(group: dict) -> bool:
    """A short source may be drafted only when its own text states an event."""
    if source_has_prompt_injection(group):
        return False
    for item in group.get("items") or []:
        if not isinstance(item, dict):
            continue
        summary = _plain(item.get("summary"))
        fulltext = _plain(item.get("fulltext"))
        title = _plain(item.get("title"))
        if summary or len(fulltext) >= 80:
            return True
        if len(title) >= 20 and _EVENT_TITLE_RE.search(title):
            return True
    return False


def _parse_date(value) -> datetime | None:
    try:
        return parse_iso(str(value))
    except (TypeError, ValueError):
        match = _ISO_DATE_RE.search(str(value or ""))
        if not match:
            return None
        try:
            return datetime.fromisoformat(match.group(1)).replace(
                tzinfo=timezone.utc)
        except ValueError:
            return None


def _event_date(article: dict) -> tuple[str | None, datetime | None]:
    entities = article.get("entities") or {}
    values = entities.get("event_dates") if isinstance(entities, dict) else []
    for value in values or []:
        parsed = _parse_date(value)
        if parsed:
            return parsed.date().isoformat(), parsed
    for field in ("sourcePublishedUtc", "publishedUtc"):
        parsed = _parse_date(article.get(field))
        if parsed:
            return parsed.date().isoformat(), parsed
    return None, None


def _current_date(group: dict) -> datetime | None:
    dates = []
    for item in group.get("items") or []:
        if not isinstance(item, dict) or item.get("dateInferred"):
            continue
        parsed = _parse_date(item.get("publishedUtc"))
        if parsed:
            dates.append(parsed)
    return max(dates) if dates else None


def _article_sources(article: dict) -> list[dict]:
    sources, seen = [], set()
    for source in article.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = _safe_url(source.get("url"))
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append({"name": _plain(source.get("name")) or "?",
                        "url": url})
    return sources


def _qualified_facts(article: dict, sources: list[dict]) -> list[dict]:
    facts = []
    for fact in article.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        claim = _plain(fact.get("claim"))
        quote = str(fact.get("sourceQuote") or "").strip()
        url = _safe_url(fact.get("sourceUrl"))
        if not url and len(sources) == 1:
            # Backward compatibility: a single-source old article has an
            # unambiguous fact-to-source mapping even before sourceUrl existed.
            url = sources[0]["url"]
        if not claim or len(_key(quote)) < 8 or not url:
            continue
        source_name = next(
            (s["name"] for s in sources if s["url"] == url),
            sources[0]["name"] if len(sources) == 1 else "?",
        )
        facts.append({"claim": claim, "source_quote": quote,
                      "source_url": url, "source_name": source_name})
    return facts


def _candidate(article: dict) -> tuple[dict | None, str | None]:
    event_id = _plain(article.get("id"))
    if not event_id:
        return None, "missing event id"
    status = article.get("status")
    if status is not None and status not in ("publish", "publish_brief"):
        return None, "not verified"
    if not is_transport_story(article):
        return None, "outside aviation/transport scope"
    if contains_prompt_injection({
            "zh": article.get("zh"), "en": article.get("en"),
            "facts": article.get("facts"), "entities": article.get("entities"),
            "sources": article.get("sources")}):
        return None, "prompt injection"
    if "conflicting_information" in (article.get("riskFlags") or []):
        return None, "conflict"
    sources = _article_sources(article)
    if not sources:
        return None, "missing source URL"
    date_text, date_dt = _event_date(article)
    if not date_text or not date_dt:
        return None, "missing event/publication date"
    facts = _qualified_facts(article, sources)
    if not facts:
        if not article.get("facts"):
            return None, "no quote"
        if len(sources) > 1:
            return None, "no fact-level source URL"
        return None, "no quote"
    return {
        "event_id": event_id,
        "event_date": date_text,
        "_event_dt": date_dt,
        "source_name": facts[0]["source_name"],
        "source_url": facts[0]["source_url"],
        "facts": facts,
        "_article": article,
        "_keys": extract_entity_keys(article),
    }, None


def _named_matches(current_text: str, candidate_keys: dict) -> dict[str, set[str]]:
    current = _key(current_text)
    matches = {}
    for key, values in (candidate_keys.get("named") or {}).items():
        # Models, airports, dates and unique identifiers have their own
        # independent matchers.  Counting them again as a "named core entity"
        # would incorrectly turn a model-only or airport-only match into Tier 2.
        if key in {
            "aircraft_models", "airports", "locations", "flight_numbers",
            "registration_numbers", "event_dates",
        }:
            continue
        matched = {value for value in values
                   if len(value) >= 3 and value in current}
        if matched:
            matches[key] = matched
    return matches


def _days_between(current_dt: datetime | None,
                  archive_dt: datetime) -> int | None:
    if current_dt is None:
        return None
    return (current_dt.date() - archive_dt.date()).days


def _progression_type(old_status: set[str], new_status: set[str],
                      blob: str) -> str | None:
    if "investigation" in old_status and "investigation" in new_status:
        return "investigation_progression"
    if "regulatory" in old_status and "regulatory" in new_status:
        return "regulatory_progression"
    if "order" in old_status and "completed" in new_status:
        return "delivery_followup"
    if "route" in old_status and "planned" in old_status \
            and "completed" in new_status:
        return "same_route"
    if "planned" in old_status and "completed" in new_status:
        if any(term in blob.casefold() for term in _ORDER_TERMS):
            return "delivery_followup"
        if any(term in blob.casefold() for term in _REGULATORY_TERMS):
            return "regulatory_progression"
        return "other"
    return None


def _conflict_reason(current: dict, old: dict, shared_unique: set[str],
                     days: int | None) -> str | None:
    if not shared_unique or days not in (0, None):
        return None
    current_routes = current.get("routes") or set()
    old_routes = old.get("routes") or set()
    # On the same event date, the same flight/notice tied to two wholly
    # different airport pairs is unsafe.  On different dates it may be a
    # legitimate previous leg or schedule update.
    if current_routes and old_routes and not (current_routes & old_routes):
        return "conflict: same identifier/date but incompatible route"
    current_dates = current.get("dates") or set()
    old_dates = old.get("dates") or set()
    if len(current_dates) == 1 and len(old_dates) == 1 \
            and current_dates != old_dates and days == 0:
        return "conflict: same identifier but incompatible event date"
    return None


def _relationship(current: dict, candidate: dict,
                  current_dt: datetime | None) -> tuple[dict | None, str | None]:
    old = candidate["_keys"]
    days = _days_between(current_dt, candidate["_event_dt"])
    if days is not None and days < 0:
        return None, "expired: archive event is newer than source"
    if days is not None and days > 3650:
        return None, "expired: outside ten-year relationship window"
    if candidate["_article"].get("eventStatus") == "planned" \
            and days is not None and days > 730:
        return None, "expired time-sensitive claim"

    evidence: list[str] = []
    unique_types = (
        ("registrations", "same registration"),
        ("msns", "same MSN"),
        ("flight_numbers", "same flight number/test callsign"),
        ("official_ids", "same official identifier"),
    )
    shared_by_type = {}
    for key, label in unique_types:
        shared = set(current.get(key) or set()) & set(old.get(key) or set())
        if shared:
            shared_by_type[key] = shared
            evidence.extend(f"{label}: {value}" for value in sorted(shared))
    shared_unique = set().union(*shared_by_type.values()) \
        if shared_by_type else set()
    conflict = _conflict_reason(current, old, shared_unique, days)
    if conflict:
        return None, conflict

    current_routes = set(current.get("routes") or set())
    old_routes = set(old.get("routes") or set())
    shared_routes = current_routes & old_routes
    named = _named_matches(str(current.get("text") or ""), old)
    named_values = set().union(*named.values()) if named else set()
    shared_models = (set(current.get("aircraft_models") or set())
                     & set(old.get("aircraft_models") or set()))
    shared_programmes = (set(current.get("programmes") or set())
                         & set(old.get("programmes") or set()))
    shared_airports = (set(current.get("airport_codes") or set())
                       & set(old.get("airport_codes") or set()))
    current_status = set(current.get("statuses") or set())
    old_status = set(old.get("statuses") or set())
    progression = _progression_type(
        old_status, current_status,
        f"{current.get('text', '')} {old.get('text', '')}",
    )

    relationship_type = "other"
    tier = None
    if shared_unique:
        tier = 1
        if "official_ids" in shared_by_type and progression in (
                "investigation_progression", "regulatory_progression",
                "delivery_followup"):
            relationship_type = progression
        elif "registrations" in shared_by_type or "msns" in shared_by_type:
            relationship_type = (
                "previous_leg"
                if current_routes and old_routes and not shared_routes
                else "same_aircraft"
            )
        elif "official_ids" in shared_by_type:
            relationship_type = progression or (
                "regulatory_progression"
                if "regulatory" in current_status | old_status
                else "investigation_progression"
                if "investigation" in current_status | old_status
                else "other"
            )
        elif shared_routes:
            relationship_type = "same_route"
        else:
            relationship_type = progression or "other"
    else:
        if shared_routes:
            evidence.append("same route: " + ", ".join(
                "-".join(route) for route in sorted(shared_routes)))
        if shared_models:
            evidence.append("same aircraft model: "
                            + ", ".join(sorted(shared_models)))
        if shared_programmes:
            evidence.append("same formal programme: "
                            + ", ".join(sorted(shared_programmes)))
        if named_values:
            evidence.append("same named core entity: "
                            + ", ".join(sorted(named_values)))
        if shared_airports:
            evidence.append("same airport code(s): "
                            + ", ".join(sorted(shared_airports)))
        if days is not None:
            evidence.append(f"archive predates source by {days} day(s)")

        core_count = len(named_values)
        conditions = sum(bool(value) for value in (
            shared_routes, shared_models, shared_programmes,
            len(shared_airports) >= 2, progression,
            days is not None and 0 <= days <= 730,
        ))
        independent_anchor = (
            bool(shared_routes) or bool(shared_models)
            or len(shared_airports) >= 2 or bool(progression)
            or core_count >= 2
        )
        if core_count >= 1 and conditions >= 2 and independent_anchor:
            tier = 2
            relationship_type = progression or (
                "same_route" if shared_routes else
                "programme_background"
            )
        elif progression and core_count >= 1 and (
                shared_programmes or shared_models or shared_routes):
            tier = 3
            relationship_type = progression
        elif days is not None and 0 <= days <= 730 and (
                (shared_programmes and core_count >= 1
                 and (shared_models or shared_routes or core_count >= 2))
                or (shared_models and any(
                    key in named for key in ("airlines", "organizations")))):
            tier = 4
            relationship_type = "programme_background"

    if tier is None:
        return None, "weak relationship"
    if days is None and tier > 1:
        return None, "missing compatible time relationship"

    base = {1: 100, 2: 80, 3: 60, 4: 40}[tier]
    score = base + min(9, len(evidence) * 2)
    if days is not None:
        score += 5 if days <= 30 else 3 if days <= 180 else 0
    result = {
        "relationship_type": relationship_type,
        "relationship_evidence": evidence,
        "relationship_tier": tier,
        "confidence_score": min(score, 115),
        "confidence_reason": (
            f"tier {tier}; {len(evidence)} deterministic evidence item(s)"
            + (f"; {days} day(s) apart" if days is not None else "")
        ),
    }
    return result, None


def load_archive_articles(articles_dir: Path = ARTICLES_DIR) -> list[dict]:
    """Read published article batches; malformed files fail closed."""
    articles = []
    if not articles_dir.is_dir():
        return articles
    for path in sorted(articles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = data.get("articles") if isinstance(data, dict) else None
        if isinstance(rows, list):
            articles.extend(row for row in rows if isinstance(row, dict))
    return articles


def retrieve_archive_context(group: dict, articles_dir: Path = ARTICLES_DIR,
                             articles: list[dict] | None = None) -> dict:
    """Return qualified, ranked historical evidence for one source group."""
    result = {
        "archive_context_version": ARCHIVE_CONTEXT_VERSION,
        "retrieval_status": "none",
        "selected_events": [],
        "excluded_candidates": [],
    }
    if source_has_prompt_injection(group):
        result["retrieval_status"] = "insufficient"
        result["excluded_candidates"].append({
            "event_id": None,
            "reason": "current source contains prompt injection",
        })
        return result

    current = extract_entity_keys(group)
    current_dt = _current_date(group)
    current_urls = {
        url for url in (
            _safe_url(item.get("url"))
            for item in group.get("items") or []
            if isinstance(item, dict)
        ) if url
    }
    ranked = []
    conflicts = False
    for raw in articles if articles is not None else load_archive_articles(
            articles_dir):
        event_id = _plain(raw.get("id")) or None
        candidate, reason = _candidate(raw)
        if reason:
            result["excluded_candidates"].append({
                "event_id": event_id, "reason": reason})
            continue
        if current_urls & {
                fact["source_url"] for fact in candidate["facts"]}:
            result["excluded_candidates"].append({
                "event_id": event_id,
                "reason": "duplicate current source URL",
            })
            continue
        relation, reason = _relationship(current, candidate, current_dt)
        if reason:
            if reason.startswith("conflict"):
                conflicts = True
            result["excluded_candidates"].append({
                "event_id": event_id, "reason": reason})
            continue
        selected = {
            "event_id": candidate["event_id"],
            **relation,
            "event_date": candidate["event_date"],
            "source_name": candidate["source_name"],
            "source_url": candidate["source_url"],
            "facts": candidate["facts"],
        }
        ranked.append(selected)

    ranked.sort(key=lambda row: (
        row["relationship_tier"], -row["confidence_score"],
        row["event_date"], row["event_id"]))
    fact_count = 0
    prompt_chars = 0
    for event in ranked:
        if len(result["selected_events"]) >= MAX_ARCHIVE_EVENTS:
            result["excluded_candidates"].append({
                "event_id": event["event_id"], "reason": "event limit"})
            continue
        kept_facts = []
        for fact in event["facts"]:
            size = sum(len(str(v)) for v in fact.values())
            if fact_count >= MAX_ARCHIVE_FACTS \
                    or prompt_chars + size > MAX_ARCHIVE_PROMPT_CHARS:
                break
            kept_facts.append(fact)
            fact_count += 1
            prompt_chars += size
        if not kept_facts:
            result["excluded_candidates"].append({
                "event_id": event["event_id"], "reason": "fact/token limit"})
            continue
        result["selected_events"].append({**event, "facts": kept_facts})

    if result["selected_events"]:
        result["retrieval_status"] = "found"
    elif conflicts:
        result["retrieval_status"] = "conflict"
    elif result["excluded_candidates"]:
        result["retrieval_status"] = "insufficient"
    return result


def archive_fact_index(context: dict | None) -> dict[tuple[str, str], dict]:
    """Index only facts selected by the deterministic retriever."""
    index = {}
    for event in (context or {}).get("selected_events") or []:
        event_id = str(event.get("event_id") or "")
        for fact in event.get("facts") or []:
            quote = squash_text(fact.get("source_quote"))
            if event_id and len(quote) >= 8:
                index[(event_id, quote)] = {
                    "event_id": event_id,
                    "claim": str(fact.get("claim") or ""),
                    "source_quote": str(fact.get("source_quote") or ""),
                    "source_url": str(fact.get("source_url") or ""),
                    "source_name": str(fact.get("source_name")
                                       or event.get("source_name") or "?"),
                }
    return index


def find_archive_fact(context: dict | None, event_id: str,
                      source_quote: str) -> dict | None:
    """Find one selected archive fact containing the model's verbatim quote."""
    quote = squash_text(source_quote)
    if not event_id or len(quote) < 8:
        return None
    for (candidate_id, archived_quote), fact in archive_fact_index(
            context).items():
        if candidate_id == event_id and quote in archived_quote:
            return fact
    return None


def stable_context_id(context: dict) -> str:
    """Short audit identifier for selected context (not a security token)."""
    payload = json.dumps(context.get("selected_events") or [],
                         ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
