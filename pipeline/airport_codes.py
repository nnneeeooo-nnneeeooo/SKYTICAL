"""airport_codes.py — enforce one IATA code on each named airport.

Owner editorial rule: whenever an article names an airport that has an IATA
three-letter location code, the first mention must carry that code in
parentheses in both Traditional Chinese and English. This is deliberately a
code-level publishing rule, not a request for the writer model to remember or
invent airport codes.

The resolver uses the bundled ``airportsdata`` package (no runtime network
request), SKYTICAL's reviewed Taiwan-airport configuration, and a small
reviewed alias table for genuinely ambiguous/common source names. Exact or
uniquely resolvable names are accepted; ambiguous names are never guessed.
The stage is idempotent and may safely run before every site build, including
against already-published recent articles.
"""
from __future__ import annotations

import re
import sys
import unicodedata
from collections import defaultdict
from datetime import timedelta
from functools import lru_cache
from pathlib import Path

import airportsdata

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTICLES_DIR, load_json, now_utc, parse_iso, save_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_ARTICLE_AGE_DAYS = 30

_GENERIC_WORDS = {
    "airport", "airports", "international", "intl", "regional", "municipal",
    "aerodrome", "airfield", "terminal", "aeroporto", "aeropuerto",
    "aéroport", "flughafen",
}
_ZH_AIRPORT_RE = re.compile(
    r"[\u3400-\u9fffA-Za-z0-9·．・\-]{2,36}?(?:國際)?機場"
)
_EN_GENERIC_AIRPORT_RE = re.compile(
    r"\b[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ0-9'’.-]*(?:\s+"
    r"[A-ZÀ-ÖØ-Þa-zà-öø-ÿ0-9'’.-]+){0,7}\s+Airport\b",
    re.I,
)
_GENERIC_ZH = {
    "當地機場", "主要機場", "相關機場", "國際機場", "一座機場", "多座機場",
    "該座機場", "這座機場",
}
_MILITARY_BASE_RE = re.compile(
    r"\b(?:air force|air national guard|air base|air station|"
    r"military base|radar site|afb)\b|空軍基地|軍事基地|雷達站",
    re.I,
)
_AIRPORT_IDENTITY_RE = re.compile(
    r"\b(?:airport|airports)\b|機場",
    re.I,
)


def _console_safe(value: object) -> str:
    """Render diagnostics even when Windows stdout uses a narrow code page."""
    text = str(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="backslashreplace").decode(encoding)
    except (LookupError, UnicodeError):
        return text.encode("ascii", errors="backslashreplace").decode("ascii")


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _name_core(value: str) -> str:
    words = [word for word in _norm(value).split() if word not in _GENERIC_WORDS]
    return " ".join(words)


def _add_alias(index: dict[str, set[str]], alias: str, code: str) -> None:
    key = _norm(alias)
    if len(key) >= 3:
        index[key].add(code)


@lru_cache(maxsize=1)
def _registry() -> tuple[dict[str, dict], dict[str, set[str]], dict[str, dict]]:
    """Return (IATA rows, normalized alias -> codes, Taiwan rows by code)."""
    rows = {
        str(code).upper(): dict(row)
        for code, row in airportsdata.load("IATA").items()
        if re.fullmatch(r"[A-Z]{3}", str(code).upper())
    }
    aliases: dict[str, set[str]] = defaultdict(set)

    for code, row in rows.items():
        name = str(row.get("name") or "").strip()
        city = str(row.get("city") or "").strip()
        icao = str(row.get("icao") or "").strip().upper()
        if name:
            _add_alias(aliases, name, code)
            core = _name_core(name)
            if len(core) >= 4:
                _add_alias(aliases, core, code)
        if city:
            # City-only aliases are intentionally not added. "London" or
            # "Tokyo" can refer to several airports. The explicit "X Airport"
            # form is accepted only when it resolves uniquely after indexing.
            _add_alias(aliases, f"{city} Airport", code)
            _add_alias(aliases, f"{city} International Airport", code)
        if icao:
            _add_alias(aliases, icao, code)

    tw_rows: dict[str, dict] = {}
    cfg = load_json(ROOT / "config" / "tw_civil_airports.json", {})
    for row in cfg.get("airports") or []:
        if not isinstance(row, dict):
            continue
        code = str(row.get("iata") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            continue
        tw_rows[code] = dict(row)
        for key in ("name_zh", "name_en", "icao"):
            value = str(row.get(key) or "").strip()
            if value:
                _add_alias(aliases, value, code)

    return rows, aliases, tw_rows


@lru_cache(maxsize=1)
def _reviewed_aliases() -> dict[str, str]:
    cfg = load_json(ROOT / "config" / "airport_iata_aliases.json", {})
    out = {}
    for alias, code in (cfg.get("aliases") or {}).items():
        normalized = _norm(str(alias))
        code = str(code or "").strip().upper()
        if normalized and re.fullmatch(r"[A-Z]{3}", code):
            out[normalized] = code
    return out


@lru_cache(maxsize=32)
def _reviewed_alias_values(code: str) -> tuple[str, ...]:
    """Return every reviewed display alias for one IATA code."""
    cfg = load_json(ROOT / "config" / "airport_iata_aliases.json", {})
    target = str(code or "").strip().upper()
    names = []
    for alias, alias_code in (cfg.get("aliases") or {}).items():
        if str(alias_code or "").strip().upper() != target:
            continue
        value = str(alias or "").strip()
        if value:
            names.append(value)
    return tuple(names)


@lru_cache(maxsize=32)
def _reviewed_alias_names(code: str) -> tuple[str, ...]:
    """Return reviewed Traditional Chinese aliases for one IATA code."""
    return tuple(value for value in _reviewed_alias_values(code)
                 if re.search(r"[\u3400-\u9fff]", value))


def _strip_iata_annotation(value: str) -> str:
    """Remove a trailing parenthesized or bare IATA token from an entity."""
    text = str(value or "").strip()
    text = re.sub(r"\s*[（(]\s*[A-Z]{3}\s*[)）]\s*$", "", text)
    text = re.sub(r"\s+\b[A-Z]{3}\b\s*$", "", text)
    return text.strip()


def _row_for_code(code: str, rows: dict[str, dict], tw_rows: dict[str, dict]):
    code = str(code or "").strip().upper()
    if code not in rows and code not in tw_rows:
        return None
    row = dict(rows.get(code) or {})
    row.update(tw_rows.get(code) or {})
    row["code"] = code
    return row


def resolve_airport(entity: str) -> dict | None:
    """Resolve a verified airport entity without fuzzy guessing."""
    rows, aliases, tw_rows = _registry()
    raw = str(entity or "").strip()
    if not raw:
        return None

    # Resolve the textual identity before trusting an embedded code.  Source
    # metadata has previously paired a correct airport name with another
    # airport's code (for example Philadelphia International Airport (PNE)).
    # The name is the authoritative part when it resolves uniquely.
    identity = _strip_iata_annotation(raw)
    reviewed_code = _reviewed_aliases().get(_norm(identity))
    if reviewed_code:
        row = _row_for_code(reviewed_code, rows, tw_rows)
        if row:
            return row
        # Reviewed aliases may intentionally cover a retired or newly named
        # airport that is not present in the bundled airportsdata release.
        return {"code": reviewed_code, "name": identity,
                "name_en": identity}

    tokens = re.findall(r"\b[A-Z]{3}\b", raw)
    if _norm(identity) == _norm(raw) and len(tokens) == 1:
        return _row_for_code(tokens[0], rows, tw_rows)
    # The registry's name-core index intentionally supports full names such
    # as "San Francisco International Airport", but that core must not turn
    # a city-only entity into an airport identity.
    if not (_AIRPORT_IDENTITY_RE.search(identity)
            or re.search(r"[機場]", identity)):
        return None

    candidates = aliases.get(_norm(identity), set())
    if len(candidates) == 1:
        return _row_for_code(next(iter(candidates)), rows, tw_rows)

    # An exact code, or an otherwise unresolved entity carrying an explicit
    # code, remains usable as a last resort.  This branch is deliberately
    # after name resolution so a bad annotation cannot override a known name.
    for token in tokens:
        row = _row_for_code(token, rows, tw_rows)
        if row:
            return row
    return None


def _looks_like_airport_entity(name: str) -> bool:
    """Decide whether an unresolved entity merits an editorial warning.

    City-only mentions and named military installations are common entity
    extraction noise.  They are not treated as missing civilian IATA codes
    unless the value explicitly identifies an airport or carries a code.
    """
    text = str(name or "").strip()
    if not text:
        return False
    if re.search(r"\b[A-Z]{3}\b", text):
        return True
    if _MILITARY_BASE_RE.search(text):
        return bool(_AIRPORT_IDENTITY_RE.search(text))
    return bool(_AIRPORT_IDENTITY_RE.search(text)
                or re.search(r"[機場]", text))


def _slots(article: dict, lang: str):
    block = article.get(lang)
    if not isinstance(block, dict):
        return []
    # The article page renders title + body.  Summaries are index/search
    # metadata and must not consume the first-mention code invisibly.
    out = [("title", None, str(block.get("title") or ""))]
    for index, paragraph in enumerate(block.get("body") or []):
        out.append(("body", index, str(paragraph or "")))
    return out


def _set_slot(article: dict, lang: str, key: str, index: int | None,
              value: str) -> None:
    if key == "body":
        article[lang]["body"][int(index)] = value
    else:
        article[lang][key] = value


def _airport_patterns(entity: str, row: dict) -> list[re.Pattern]:
    values = []
    entity_value = _strip_iata_annotation(str(entity or "").strip())
    for value in (entity_value, row.get("name_en"), row.get("name"),
                  *_reviewed_alias_values(str(row.get("code") or ""))):
        value = _strip_iata_annotation(str(value or "").strip())
        # An ICAO/IATA-only entity is metadata, not the visible airport
        # identity.  Matching it first would place TPE after "ICAO code
        # RCTP" instead of after the airport name.
        if value == entity_value and re.fullmatch(r"[A-Z]{3,4}", value):
            continue
        if value and value not in values:
            values.append(value)
    patterns = []
    for value in values:
        variants = {value}
        # Accept normal source punctuation variants such as
        # London-Gatwick/London Gatwick and Leipzig/Halle/Leipzig-Halle,
        # without broadening a named airport into every airport in that city.
        spaced = re.sub(r"\s*[-–—/]\s*", " ", value)
        if spaced:
            variants.add(spaced)
        for variant in variants:
            patterns.append(re.compile(re.escape(variant), re.I))
    return patterns


def _find_en_match(article: dict, entity: str, row: dict):
    patterns = _airport_patterns(entity, row)
    for key, index, text in _slots(article, "en"):
        hits = []
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                hits.append(match)
        if hits:
            match = min(hits, key=lambda m: (m.start(), -len(m.group(0))))
            return key, index, match.start(), match.end()
    return None


def _zh_candidates(text: str):
    matches = []
    for match in _ZH_AIRPORT_RE.finditer(text):
        if match.group(0) not in _GENERIC_ZH:
            matches.append(match)
    return matches


def _find_zh_identity_match(text: str, entity: str, row: dict):
    """Find a reviewed airport identity in a translated visible slot."""
    values = []
    for value in (entity, row.get("name_zh"), row.get("name_en"),
                  row.get("name"), *_reviewed_alias_values(
                      str(row.get("code") or ""))):
        value = _strip_iata_annotation(str(value or "").strip())
        if (value and not re.fullmatch(r"[A-Z]{3,4}", value)
                and value not in values):
            values.append(value)

    patterns = []
    for value in values:
        patterns.append(re.compile(re.escape(value)))
        if not value.endswith("機場"):
            patterns.append(re.compile(re.escape(value + "機場")))
    hits = []
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            hits.append(match)
    if not hits:
        return None
    return min(hits, key=lambda match: (match.start(), -len(match.group(0))))


def _insert_code(text: str, start: int, end: int, code: str, lang: str) -> str:
    tail = text[end:]
    if lang == "zh":
        # Chinese copy often places the English airport name in a second
        # parenthetical immediately after the Chinese name. Merge the IATA
        # code into that existing bilingual parenthetical instead of creating
        # adjacent or nested parentheses.
        bilingual_existing = re.match(
            r"(?P<space>\s*)[（(]\s*(?P<old>[A-Z]{3})\s*[；;]\s*"
            r"(?P<content>[^()（）]*[A-Za-z][^()（）]*)[)）]",
            tail,
        )
        if bilingual_existing:
            content = bilingual_existing.group("content").strip()
            leading = bilingual_existing.group("space")
            if bilingual_existing.group("old") == code:
                return text
            return (text[:end] + leading + f"（{code}；{content}）"
                    + tail[bilingual_existing.end():])
        bilingual_after_code = re.match(
            r"(?P<space>\s*)[（(]\s*(?P<old>[A-Z]{3})\s*[)）]"
            r"\s*[（(](?P<content>[^()（）]*[A-Za-z][^()（）]*)[)）]",
            tail,
        )
        if bilingual_after_code:
            content = bilingual_after_code.group("content").strip()
            if not re.fullmatch(r"[A-Z]{3}", content):
                return (text[:end] + f"（{code}；{content}）"
                        + tail[bilingual_after_code.end():])
        bilingual_nested = re.match(
            r"(?P<space>\s*)[（(](?P<content>[^()（）]*[A-Za-z][^()（）]*)"
            r"[（(]\s*(?P<old>[A-Z]{3})\s*[)）]\s*[)）]",
            tail,
        )
        if bilingual_nested:
            content = bilingual_nested.group("content").strip()
            if not re.fullmatch(r"[A-Z]{3}", content):
                return (text[:end] + f"（{code}；{content}）"
                        + tail[bilingual_nested.end():])
        bilingual_plain = re.match(
            r"(?P<space>\s*)[（(](?P<content>[^()（）]*[A-Za-z][^()（）]*)[)）]",
            tail,
        )
        if bilingual_plain:
            content = bilingual_plain.group("content").strip()
            if (not re.fullmatch(r"[A-Z]{3}", content)
                    and not re.search(r"\b(?:IATA|ICAO)\b", content, re.I)):
                return (text[:end] + f"（{code}；{content}）"
                        + tail[bilingual_plain.end():])
    nested = re.match(
        r"(?P<space>\s*)[（(]\s*(?P<outer>[A-Z]{3})\s*"
        r"[（(]\s*(?P=outer)\s*[)）]\s*[)）]",
        tail,
    )
    if nested:
        leading = nested.group("space")
        replacement = (leading + f"（{code}）" if lang == "zh"
                       else (leading or " ") + f"({code})")
        return text[:end] + replacement + tail[nested.end():]
    immediate = re.match(
        r"(?P<space>\s*)(?:[（(]\s*[A-Z]{3}\s*[)）])"
        r"(?:\s*[（(]\s*[A-Z]{3}\s*[)）])*",
        tail,
    )
    if immediate:
        codes = re.findall(r"[（(]\s*([A-Z]{3})\s*[)）]",
                           immediate.group(0))
        if len(codes) == 1 and codes[0] == code:
            return text
        leading = immediate.group("space")
        replacement = (leading + f"（{code}）" if lang == "zh"
                       else (leading or " ") + f"({code})")
        return text[:end] + replacement + tail[immediate.end():]
    token = f"（{code}）" if lang == "zh" else f" ({code})"
    return text[:end] + token + text[end:]


def _code_annotation_pattern(code: str) -> re.Pattern:
    return re.compile(
        rf"(?P<leading>\s*)[（(]\s*{re.escape(code)}\s*"
        r"(?:(?:[；;])\s*(?P<content>[^()（）]*))?[)）]"
    )


def _first_identity_anchor(article: dict, lang: str, entity: str,
                           row: dict):
    if lang == "en":
        return _find_en_match(article, entity, row)
    for key, index, text in _slots(article, "zh"):
        match = _find_zh_identity_match(text, entity, row)
        if match:
            return key, index, match.start(), match.end()
    return None


def _dedupe_code(article: dict, lang: str, code: str, entity: str,
                 row: dict) -> None:
    """Keep a code only when it annotates the first resolved identity."""
    pattern = _code_annotation_pattern(code)
    anchor = _first_identity_anchor(article, lang, entity, row)
    if not anchor:
        # Code-only entities such as route endpoints may already be correctly
        # annotated in the copy even though no full airport name is present.
        # Without an identity anchor there is no safe basis for deleting any
        # existing annotation.
        return
    target = None
    key, index, _start, end = anchor
    text = _slot_text(article, lang, key, index)
    immediate = pattern.match(text[end:])
    if immediate:
        target = (key, index, end + immediate.start())

    for key, index, text in _slots(article, lang):
        def repl(match):
            if target == (key, index, match.start()):
                return match.group(0)
            content = match.group("content")
            if content is not None:
                return f"（{content.strip()}）"
            return ""

        cleaned = pattern.sub(repl, text)
        if cleaned != text:
            _set_slot(article, lang, key, index, cleaned)


def _clean_punctuation_spacing(text: str) -> str:
    """Remove source-copy spaces left immediately before punctuation."""
    return re.sub(r"[ \t]+([,.;:!?，。；：！？])", r"\1", text)


def _visible_has_code(article: dict, lang: str, code: str) -> bool:
    pattern = _code_annotation_pattern(code)
    return any(pattern.search(text) for _key, _index, text in
               _slots(article, lang))


def enforce_article(article: dict) -> tuple[bool, list[str]]:
    """Add first-mention IATA codes; return (changed, unresolved entities)."""
    entities = article.get("entities") or {}
    airports = entities.get("airports") if isinstance(entities, dict) else []
    if not isinstance(airports, list) or not airports:
        return False, []

    resolved = []
    unresolved = []
    seen_codes = set()
    for entity in airports:
        name = str(entity or "").strip()
        row = resolve_airport(name)
        if not row:
            if name and _looks_like_airport_entity(name):
                unresolved.append(name)
            continue
        code = str(row["code"])
        if code in seen_codes:
            continue
        seen_codes.add(code)
        resolved.append({"entity": name, "row": row, "code": code})

    if not resolved:
        return False, unresolved

    changed = False
    en_locations = {}
    by_slot: dict[tuple[str, int | None], list[tuple[int, int, str]]] = defaultdict(list)
    for item in resolved:
        loc = _find_en_match(article, item["entity"], item["row"])
        if loc:
            key, index, start, end = loc
            en_locations[item["code"]] = (key, index, start, end)
            by_slot[(key, index)].append((start, end, item["code"]))

    # English: exact/official airport identity decides the code placement.
    for (key, index), matches in by_slot.items():
        text = next(value for k, i, value in _slots(article, "en")
                    if k == key and i == index)
        for start, end, code in sorted(matches, reverse=True):
            new_text = _insert_code(text, start, end, code, "en")
            changed |= new_text != text
            text = new_text
        cleaned = _clean_punctuation_spacing(text)
        changed |= cleaned != text
        text = cleaned
        _set_slot(article, "en", key, index, text)

    # Chinese: pair airport mentions with resolved English mentions in the
    # equivalent title/summary/paragraph. This avoids asking a transliteration
    # heuristic to invent an airport identity.
    zh_done = set()

    # First honor a reviewed Chinese identity wherever it appears. Doing
    # this before English-slot pairing is important when the Chinese title
    # mentions an airport before the corresponding English body paragraph.
    for item in resolved:
        code = item["code"]
        for key, index, text in _slots(article, "zh"):
            match = _find_zh_identity_match(
                text, item["entity"], item["row"])
            if not match:
                continue
            new_text = _insert_code(text, match.start(), match.end(), code, "zh")
            cleaned = _clean_punctuation_spacing(new_text)
            changed |= cleaned != text
            _set_slot(article, "zh", key, index, cleaned)
            zh_done.add(code)
            break

    for slot, matches in by_slot.items():
        key, index = slot
        zh_slot = next((value for k, i, value in _slots(article, "zh")
                        if k == key and i == index), None)
        if zh_slot is None:
            continue
        candidates = _zh_candidates(zh_slot)
        ordered = sorted(
            (row for row in matches if row[2] not in zh_done),
            key=lambda row: row[0],
        )
        if not ordered:
            continue
        if len(ordered) == 1 and len(candidates) == 1:
            pairs = [(candidates[0], ordered[0][2])]
        else:
            continue

        text = zh_slot
        for match, code in sorted(
                pairs, key=lambda pair: pair[0].start(), reverse=True):
            new_text = _insert_code(text, match.start(), match.end(), code, "zh")
            changed |= new_text != text
            text = new_text
            zh_done.add(code)
        cleaned = _clean_punctuation_spacing(text)
        changed |= cleaned != text
        text = cleaned
        _set_slot(article, "zh", key, index, text)

    # Single-airport fallback for bilingual wording that is not structurally
    # aligned. A lone resolved airport cannot be confused with another code.
    if len(resolved) == 1:
        item = resolved[0]
        code = item["code"]
        if code not in en_locations and not _visible_has_code(article, "en", code):
            for key, index, text in _slots(article, "en"):
                match = _EN_GENERIC_AIRPORT_RE.search(text)
                if match:
                    new_text = _insert_code(text, match.start(), match.end(), code, "en")
                    changed |= new_text != text
                    _set_slot(article, "en", key, index, new_text)
                    break
        if code not in zh_done and not _visible_has_code(article, "zh", code):
            zh_name = str(item["row"].get("name_zh") or "").strip()
            placed = False
            if zh_name:
                for key, index, text in _slots(article, "zh"):
                    pos = text.find(zh_name)
                    if pos >= 0:
                        end = pos + len(zh_name)
                        new_text = _insert_code(text, pos, end, code, "zh")
                        changed |= new_text != text
                        _set_slot(article, "zh", key, index, new_text)
                        placed = True
                        break
            if not placed:
                for key, index, text in _slots(article, "zh"):
                    match = _find_zh_identity_match(
                        text, item["entity"], item["row"])
                    if match:
                        new_text = _insert_code(
                            text, match.start(), match.end(), code, "zh")
                        changed |= new_text != text
                        _set_slot(article, "zh", key, index, new_text)
                        placed = True
                        break
            if not placed:
                for key, index, text in _slots(article, "zh"):
                    candidates = _zh_candidates(text)
                    if len(candidates) == 1:
                        match = candidates[0]
                        new_text = _insert_code(text, match.start(), match.end(), code, "zh")
                        changed |= new_text != text
                        _set_slot(article, "zh", key, index, new_text)
                        break

    for item in resolved:
        for lang in ("zh", "en"):
            before = "\n".join(value for _k, _i, value in _slots(article, lang))
            _dedupe_code(article, lang, item["code"], item["entity"],
                         item["row"])
            after = "\n".join(value for _k, _i, value in _slots(article, lang))
            changed |= before != after

    return changed, unresolved


def _slot_text(article: dict, lang: str, key: str, index: int | None) -> str:
    return next(
        (value for k, i, value in _slots(article, lang)
         if k == key and i == index),
        "",
    )


def _has_immediate_code(text: str, end: int, code: str) -> bool:
    match = re.match(
        r"\s*[（(]\s*([A-Z]{3})\s*(?:[；;][^()（）]*)?[)）]",
        text[end:],
    )
    return bool(match and match.group(1) == code)


def _code_precedes(article: dict, lang: str, key: str,
                   index: int | None, start: int, code: str,
                   entity: str, row: dict) -> bool:
    """Return whether an earlier visible identity already carries the code."""
    slots = _slots(article, lang)
    current = next(
        (position for position, (slot_key, slot_index, _text)
         in enumerate(slots) if slot_key == key and slot_index == index),
        None,
    )
    if current is None:
        return False
    annotation = _code_annotation_pattern(code)
    for position, slot_key, slot_index, text in (
            (position, *slot) for position, slot in enumerate(slots)):
        if position > current:
            break
        limit = start if position == current else len(text)
        if lang == "en":
            identity_patterns = _airport_patterns(entity, row)
            matches = [match for pattern in identity_patterns
                       for match in pattern.finditer(text[:limit])]
            if any(_has_immediate_code(text, match.end(), code)
                   for match in matches):
                return True
        else:
            match = _find_zh_identity_match(text[:limit], entity, row)
            if match and annotation.match(text[match.end():]):
                return True
    return False


def validate_article(article: dict) -> list[str]:
    """Return resolved airport mentions still missing their visible code.

    Only title/body slots rendered by ``templates/article.html`` are checked.
    An entity that is not actually present in a visible translation is not a
    violation; the extractor may have retained background metadata.
    """
    entities = article.get("entities") or {}
    airports = entities.get("airports") if isinstance(entities, dict) else []
    if not isinstance(airports, list):
        return []

    resolved = []
    seen_codes = set()
    for entity in airports:
        name = str(entity or "").strip()
        row = resolve_airport(name)
        if not row or row["code"] in seen_codes:
            continue
        seen_codes.add(row["code"])
        resolved.append({"entity": name, "row": row, "code": row["code"]})

    violations = []
    reported = set()

    def report(item, lang: str, key: str, index: int | None) -> None:
        marker = (item["code"], lang, key, index)
        if marker in reported:
            return
        reported.add(marker)
        violations.append(
            f"{item['entity']} ({item['code']}) in {lang}:{key}"
        )

    en_by_slot: dict[tuple[str, int | None], list[tuple[int, int, dict]]] = defaultdict(list)
    direct_zh_codes = set()
    for item in resolved:
        en_loc = _find_en_match(article, item["entity"], item["row"])
        if en_loc:
            key, index, start, end = en_loc
            en_by_slot[(key, index)].append((start, end, item))
            text = _slot_text(article, "en", key, index)
            if (not _has_immediate_code(text, end, item["code"])
                    and not _code_precedes(
                        article, "en", key, index, start, item["code"],
                        item["entity"], item["row"])):
                report(item, "en", key, index)

        for key, index, text in _slots(article, "zh"):
            match = _find_zh_identity_match(
                text, item["entity"], item["row"])
            if not match:
                continue
            direct_zh_codes.add(item["code"])
            if (not _has_immediate_code(text, match.end(), item["code"])
                    and not _code_precedes(
                        article, "zh", key, index, match.start(),
                        item["code"], item["entity"], item["row"])):
                report(item, "zh", key, index)
            break

    # For translated airport names without a reviewed Chinese alias, pair the
    # Chinese airport mentions with the English mentions in the same visible
    # slot, using their document order.
    for (key, index), matches in en_by_slot.items():
        zh_text = _slot_text(article, "zh", key, index)
        candidates = _zh_candidates(zh_text)
        if len(matches) > 1 or len(candidates) != len(matches):
            continue
        for candidate, (_start, _end, item) in zip(
                candidates, sorted(matches, key=lambda row: row[0])):
            if item["code"] in direct_zh_codes:
                continue
            if (not _has_immediate_code(zh_text, candidate.end(), item["code"])
                    and not _code_precedes(
                        article, "zh", key, index, candidate.start(),
                        item["code"], item["entity"], item["row"])):
                report(item, "zh", key, index)

    return violations


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("airport_codes: no articles yet")
        return 0

    cutoff = now_utc() - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    updated = 0
    unresolved_total = 0
    violation_total = 0
    for path in sorted(ARTICLES_DIR.glob("*.json"), reverse=True):
        batch = load_json(path, None)
        if not isinstance(batch, dict):
            continue
        changed = False
        for article in batch.get("articles") or []:
            if not isinstance(article, dict):
                continue
            try:
                if parse_iso(str(article.get("publishedUtc"))) < cutoff:
                    continue
            except (TypeError, ValueError):
                continue
            article_changed, unresolved = enforce_article(article)
            if unresolved:
                unresolved_total += len(unresolved)
                print(
                    _console_safe(
                        "airport_codes: no unique IATA match for "
                        + ", ".join(unresolved)
                        + f" in {article.get('id') or path.name}"
                    )
                )
            violations = validate_article(article)
            if violations:
                violation_total += len(violations)
                print(
                    _console_safe(
                        "airport_codes: visible first-mention code violation: "
                        + "; ".join(violations)
                        + f" in {article.get('id') or path.name}"
                    )
                )
            if article_changed:
                changed = True
                updated += 1
        if changed:
            save_json(path, batch)

    print(
        f"airport_codes: {updated} article(s) updated; "
        f"{unresolved_total} unresolved airport entit{'y' if unresolved_total == 1 else 'ies'}; "
        f"{violation_total} visible placement violation(s)"
    )
    return 1 if violation_total else 0


if __name__ == "__main__":
    raise SystemExit(main())
