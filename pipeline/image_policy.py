"""Shared deterministic safety rules for article image selection.

The image pipeline must prefer no image over a visually misleading one.  This
module deliberately uses only article metadata and Commons provenance; it does
not pretend that a filename is evidence of the event itself.
"""
from __future__ import annotations

import re
from html import unescape
from urllib.parse import unquote, urlsplit


_BAD_METADATA_RE = re.compile(
    r"map|logo|diagram|schematic|seal|icon|flag|emblem|coat of arms|"
    r"chart|plan\b|mairie|municipal|town hall|city hall|residential|"
    r"\bhouse\b|\bmemorial\b|statue|wreckage|debris|"
    r"Rix_mairie|Villach_10.-Oktober-Strasse_18_BKS|"
    r"China_Lake_c1955|Manassas_Airport_Terminal_Building|"
    r"Philadelphia_Skyline_seen_from_PHL_2|"
    r"Sultan_Hasanuddin_International_Airport_20251003",
    re.I,
)

# Airport lookups commonly return a terminal interior, ceiling, roof or a
# similarly named civic building.  These are not acceptable generic airport
# photos for an aviation news card.
BAD_AIRPORT_TITLE_RE = re.compile(
    r"ceiling|interior|inside|concourse|\broof\b|\bmairie\b|"
    r"municipal|town hall|city hall|residential|\bhouse\b|"
    r"\bbuilding\b|gebäude|\bmuseum\b|\bmemorial\b|statue|"
    r"\bstation\b|skyline|cityscape|panorama",
    re.I,
)

BAD_AIRLINE_INTERIOR_RE = re.compile(
    r"cabin|interior|premium[\s_-]+economy|business[\s_-]+class|"
    r"economy[\s_-]+class|first[\s_-]+class|seat(?:s)?|galley|"
    r"in[-\s]?flight|meal|lounge|flight[\s_-]+deck|cockpit|"
    r"lavatory|toilet|onboard[\s_-]+service|客艙|機艙|座椅|"
    r"豪華經濟艙|商務艙|經濟艙|機上餐飲",
    re.I,
)

BAD_AIRCRAFT_TITLE_RE = re.compile(
    r"wreckage|debris|diagram|schematic|map|logo|memorial|statue",
    re.I,
)

AIRPORT_OPERATIONS_RE = re.compile(
    r"terminal|airport (?:rebuild|expansion|barrier|fence|security|robot)|"
    r"airport closed|airport closure|check[- ]?in|queue|queue[- ]?jump|"
    r"runway|taxiway|apron|gate|"
    r"航廈|航站|櫃檯|插隊|圍欄|重建|擴建|跑道|滑行道|停機坪|登機門|"
    r"機場.*(?:設施|秩序|安全|機器人|圍欄|關閉|封閉|停用|起降)",
    re.I,
)

INCIDENT_RE = re.compile(
    r"crash|accident|fire|burn|hard[- ]landing|overrun|runway excursion|"
    r"landing|tailstrike|collision|injur|起火|失事|墜落|硬著陸|偏離跑道|"
    r"擦尾|碰撞|受傷|爆胎",
    re.I,
)

DRONE_RE = re.compile(
    r"\b(?:drone|drones|uas|uav|unmanned aerial)\b|無人機",
    re.I,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", unescape(str(value or "")))).strip()


def article_headline_text(article: dict) -> str:
    """Return only headline fields used for broad topic fallback decisions."""
    parts: list[str] = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.append(_clean(block.get("title")))
    return " ".join(part for part in parts if part)


def article_lead_text(article: dict) -> str:
    """Return title/summary plus the first body paragraph for context rules."""
    parts: list[str] = []
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.extend([
            _clean(block.get("title")),
            _clean(block.get("summary")),
        ])
        body = block.get("body") or []
        if body:
            parts.append(_clean(body[0]))
    return " ".join(part for part in parts if part)


def article_context_text(article: dict) -> str:
    """Return headline and summary context, excluding incidental body text."""
    parts = [article_headline_text(article)]
    for lang in ("zh", "en"):
        block = article.get(lang) or {}
        parts.append(_clean(block.get("summary")))
    return " ".join(part for part in parts if part)


def article_is_airport_operations(article: dict) -> bool:
    return bool(AIRPORT_OPERATIONS_RE.search(article_context_text(article)))


def article_is_cabin_story(article: dict) -> bool:
    return bool(BAD_AIRLINE_INTERIOR_RE.search(article_context_text(article)))


def article_is_incident(article: dict) -> bool:
    return bool(INCIDENT_RE.search(article_context_text(article)))


def article_is_drone_story(article: dict) -> bool:
    """Topic fallbacks are driven by the headline, not incidental body text."""
    return bool(DRONE_RE.search(article_headline_text(article)))


def image_provenance(image: dict) -> str:
    fields = [image.get(key) for key in ("matched", "subject", "url", "link")]
    text = " ".join(_clean(value) for value in fields if value)
    try:
        path = unquote(urlsplit(str(image.get("url") or "")).path)
    except ValueError:
        path = str(image.get("url") or "")
    return f"{text} {path}"


def image_is_safe_for_article(article: dict, image) -> bool:
    """Reject deterministic, visually misleading image classes.

    This is intentionally conservative.  If the metadata cannot support a
    confident match, the caller should remove the image and let the site use
    its neutral branded fallback.
    """
    if not isinstance(image, dict):
        return True
    provenance = image_provenance(image)
    if not provenance:
        return True
    matched = str(image.get("matched") or "").casefold()

    if _BAD_METADATA_RE.search(provenance):
        return False
    if matched.startswith("topic:drone") and not article_is_drone_story(article):
        return False
    if matched.startswith("airport:") and BAD_AIRPORT_TITLE_RE.search(provenance):
        return False
    if (re.search(r"\b(?:aircraft|airplane|jet)\b", matched, re.I)
            and BAD_AIRCRAFT_TITLE_RE.search(provenance)
            and not article_is_incident(article)):
        return False
    if (re.search(r"\b(?:aircraft|airplane|jet)\b", matched, re.I)
            and article_is_airport_operations(article)
            and not article_is_cabin_story(article)
            and not article_is_incident(article)):
        return False
    if (not article_is_cabin_story(article)
            and BAD_AIRLINE_INTERIOR_RE.search(provenance)
            and re.search(r"\b(?:aircraft|airline)\b", matched, re.I)):
        return False
    return True
