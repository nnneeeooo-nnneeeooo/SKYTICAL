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
def _reviewed_alias_names(code: str) -> tuple[str, ...]:
    """Return reviewed Traditional Chinese aliases for one IATA code."""
    cfg = load_json(ROOT / "config" / "airport_iata_aliases.json", {})
    target = str(code or "").strip().upper()
    names = []
    for alias, alias_code in (cfg.get("aliases") or {}).items():
        if str(alias_code or "").strip().upper() != target:
            continue
        value = str(alias or "").strip()
        if value and re.search(r"[\u3400-\u9fff]", value):
            names.append(value)
    return tuple(names)


def resolve_airport(entity: str) -> dict | None:
    """Resolve a verified airport entity without fuzzy guessing."""
    rows, aliases, tw_rows = _registry()
    raw = str(entity or "").strip()
    if not raw:
        return None

    for token in re.findall(r"\b[A-Z]{3}\b", raw):
        if token in rows or token in tw_rows:
            row = dict(rows.get(token) or {})
            row.update(tw_rows.get(token) or {})
            row["code"] = token
            return row

    reviewed_code = _reviewed_aliases().get(_norm(raw))
    if reviewed_code and (reviewed_code in rows or reviewed_code in tw_rows):
        row = dict(rows.get(reviewed_code) or {})
        row.update(tw_rows.get(reviewed_code) or {})
        row["code"] = reviewed_code
        return row

    candidates = aliases.get(_norm(raw), set())
    if len(candidates) != 1:
        return None
    code = next(iter(candidates))
    row = dict(rows.get(code) or {})
    row.update(tw_rows.get(code) or {})
    row["code"] = code
    return row


def _slots(article: dict, lang: str):
    block = article.get(lang)
    if not isinstance(block, dict):
        return []
    out = [("title", None, str(block.get("title") or "")),
           ("summary", None, str(block.get("summary") or ""))]
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
    for value in (entity, row.get("name_en"), row.get("name")):
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    city = str(row.get("city") or "").strip()
    patterns = [re.compile(re.escape(value), re.I) for value in values]
    if city:
        city_re = re.escape(city)
        patterns.append(re.compile(
            rf"\b{city_re}\b(?:['’]s)?(?:\s+[A-Za-z0-9'’.-]+){{0,4}}\s+airport\b",
            re.I,
        ))
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
    """Find a reviewed Chinese airport name, including common short forms."""
    values = []
    for value in (entity, row.get("name_zh")):
        value = str(value or "").strip()
        if value and re.search(r"[\u3400-\u9fff]", value) and value not in values:
            values.append(value)
    for value in _reviewed_alias_names(str(row.get("code") or "")):
        if value not in values:
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
    immediate = re.match(r"\s*[（(]\s*([A-Z]{3})\s*[)）]", tail)
    if immediate and immediate.group(1) == code:
        return text
    token = f"（{code}）" if lang == "zh" else f" ({code})"
    return text[:end] + token + text[end:]


def _dedupe_code(article: dict, lang: str, code: str) -> None:
    seen = False
    pattern = re.compile(rf"[（(]\s*{re.escape(code)}\s*[)）]")
    for key, index, text in _slots(article, lang):
        def repl(match):
            nonlocal seen
            if not seen:
                seen = True
                return match.group(0)
            return ""
        cleaned = pattern.sub(repl, text)
        if cleaned != text:
            _set_slot(article, lang, key, index, cleaned)


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
            if name:
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
        _set_slot(article, "en", key, index, text)

    # Chinese: pair airport mentions with resolved English mentions in the
    # equivalent title/summary/paragraph. This avoids asking a transliteration
    # heuristic to invent an airport identity.
    zh_done = set()
    resolved_by_code = {item["code"]: item for item in resolved}
    for slot, matches in by_slot.items():
        key, index = slot
        zh_slot = next((value for k, i, value in _slots(article, "zh")
                        if k == key and i == index), None)
        if zh_slot is None:
            continue
        candidates = _zh_candidates(zh_slot)
        ordered = sorted(matches, key=lambda row: row[0])

        # Prefer the reviewed identity in the equivalent Chinese slot. This
        # handles common short forms such as 芝加哥奧黑爾 that do not include
        # the literal suffix 機場.
        direct_pairs = []
        for _start, _end, code in ordered:
            item = resolved_by_code[code]
            match = _find_zh_identity_match(
                zh_slot, item["entity"], item["row"])
            if match is None:
                direct_pairs = []
                break
            direct_pairs.append((match, code))
        direct_spans = {
            (match.start(), match.end()) for match, _code in direct_pairs
        }
        if len(direct_pairs) == len(ordered) \
                and len(direct_spans) == len(direct_pairs):
            pairs = direct_pairs
        elif len(candidates) >= len(ordered):
            pairs = [
                (match, code)
                for match, (_start, _end, code) in zip(
                    candidates[:len(ordered)], ordered)
            ]
        else:
            continue

        text = zh_slot
        for match, code in sorted(
                pairs, key=lambda pair: pair[0].start(), reverse=True):
            new_text = _insert_code(text, match.start(), match.end(), code, "zh")
            changed |= new_text != text
            text = new_text
            zh_done.add(code)
        _set_slot(article, "zh", key, index, text)

    # Single-airport fallback for bilingual wording that is not structurally
    # aligned. A lone resolved airport cannot be confused with another code.
    if len(resolved) == 1:
        item = resolved[0]
        code = item["code"]
        if code not in en_locations:
            for key, index, text in _slots(article, "en"):
                match = _EN_GENERIC_AIRPORT_RE.search(text)
                if match:
                    new_text = _insert_code(text, match.start(), match.end(), code, "en")
                    changed |= new_text != text
                    _set_slot(article, "en", key, index, new_text)
                    break
        if code not in zh_done:
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
                    if candidates:
                        match = candidates[0]
                        new_text = _insert_code(text, match.start(), match.end(), code, "zh")
                        changed |= new_text != text
                        _set_slot(article, "zh", key, index, new_text)
                        break

    for item in resolved:
        for lang in ("zh", "en"):
            before = "\n".join(value for _k, _i, value in _slots(article, lang))
            _dedupe_code(article, lang, item["code"])
            after = "\n".join(value for _k, _i, value in _slots(article, lang))
            changed |= before != after

    return changed, unresolved


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("airport_codes: no articles yet")
        return 0

    cutoff = now_utc() - timedelta(days=MAX_ARTICLE_AGE_DAYS)
    updated = 0
    unresolved_total = 0
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
                    "airport_codes: no unique IATA match for "
                    + ", ".join(unresolved)
                    + f" in {article.get('id') or path.name}"
                )
            if article_changed:
                changed = True
                updated += 1
        if changed:
            save_json(path, batch)

    print(
        f"airport_codes: {updated} article(s) updated; "
        f"{unresolved_total} unresolved airport entit{'y' if unresolved_total == 1 else 'ies'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
