"""Fail-closed, bilingual templates for narrowly recognized official notices.

No model, network request or free-form translation. Unsupported wording stays
on the existing writer path. Only a complete, affirmative source sentence can
fill a template; title/RSS text alone is never publication evidence.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlsplit

from airport_codes import resolve_airport
from common import NEWS_MAX_AGE_HOURS, load_json, parse_iso

ROOT = Path(__file__).resolve().parent.parent
WRITER = "rules:announcement-v1"
ENTITY_KEYS = ("organizations", "airlines", "aircraft_models", "airports",
               "locations", "flight_numbers", "registration_numbers", "event_dates")
_UNSAFE = re.compile(
    r"\b(?:not|never|no longer|may|might|could|consider\w*|expect\w*|"
    r"propos\w*|plans?|planned|subject to|pending|if|unless|despite|although|reportedly|"
    r"correction|corrected|revised|cancel\w*|accident|injur\w*|fatal\w*|"
    r"investigat\w*)\b|更正|撤回|取消|疑似|事故|傷亡", re.I)
_AIRPORT = r"[A-Za-z][A-Za-z '’.-]{2,65}Airport"
_DATE = r"[A-Z][a-z]+ \d{1,2}, 20\d{2}"
_MODEL = r"(?:Airbus A(?:220|319|320|321|330|350|380)[A-Za-z0-9-]*|Boeing (?:737|747|757|767|777|787)[A-Za-z0-9-]*|Embraer E\d{3}[A-Za-z0-9-]*)"
_NUMBER = {"first": 1, "one": 1, "two": 2, "three": 3, "four": 4,
           "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}


@lru_cache(maxsize=1)
def settings():
    rules = load_json(ROOT / "config/announcement_rules.json", {})
    glossary = load_json(ROOT / "config/zh_glossary.json", {})
    registry = load_json(ROOT / "config/airline_icao_codes.json", {}).get('airlines', [])
    names = {row['airline_name_en']: row.get('airline_name_zh_tw') or row['airline_name_en']
             for row in registry if row.get('airline_name_en') and row.get('active') is not False}
    names.update({**glossary.get("translate_soft", {}), **glossary.get("translate", {})})
    return rules, names


def candidate_item(group, now):
    rules, _ = settings()
    if not rules.get("enabled") or group.get("groupKind") or group.get('updateCandidate'):
        return None
    items = group.get("items") or []
    if len(items) != 1 or not isinstance(items[0], dict):
        return None
    item = items[0]
    try:
        url = urlsplit(item.get("url") or "")
        port = url.port
        stamp = parse_iso(item.get("publishedUtc") or "")
        age = now - stamp
    except (TypeError, ValueError, AttributeError):
        return None
    allowed = set(rules.get("manufacturerHosts", [])) | set(rules.get("airlineHosts", {})) | set(rules.get("authorityHosts", []))
    if (url.scheme != "https" or port not in (None, 443) or url.hostname not in allowed or url.username
            or url.password or item.get("dateInferred")
            or not timedelta(0) <= age <= timedelta(hours=NEWS_MAX_AGE_HOURS)):
        return None
    return item


def _airport(name):
    # A city alone cannot establish an airport. Resolve only an explicit name.
    if not name.endswith("Airport"):
        return None
    row = resolve_airport(name)
    if not row or not row.get("code"):
        return None
    _, names = settings()
    return f"{names.get(name, name)}（{row['code']}）", f"{name} ({row['code']})"


def _date(value):
    try:
        day = datetime.strptime(value, "%B %d, %Y")
    except ValueError:
        return None
    return f"{day.year}年{day.month}月{day.day}日"


@lru_cache(maxsize=1)
def _actor_pattern():
    rules, names = settings()
    # Known proper names remain in their source spelling when no reviewed
    # Chinese translation exists. Never invent an airline or airport name.
    carriers = {name for name in names if re.search(r"\bAir(?:lines|ways)?\b|Air Lines|KLM|Lufthansa|Emirates|JetBlue|Ryanair|easyJet", name)}
    registry = load_json(ROOT / "config/airline_icao_codes.json", {}).get('airlines', [])
    carriers.update(row['airline_name_en'] for row in registry
                    if row.get('airline_name_en') and row.get('active') is not False)
    carriers.update(name for values in rules.get("airlineHosts", {}).values() for name in values)
    return "(?:" + "|".join(re.escape(name) for name in sorted(carriers, key=len, reverse=True)) + ")"


def _sentence_copy(sentence, host):
    rules, names = settings()
    actor = _actor_pattern()
    match = re.fullmatch(
        rf"(?P<core>(?P<actor>{actor}) has taken delivery of (?P<owner>its |the )?"
        rf"(?P<count>first|one|two|three|four|five|six|seven|eight|nine|ten|[1-9]\d?) "
        rf"(?P<model>{_MODEL})(?: aircraft)?(?: from (?:Airbus|Boeing|Embraer))?)(?:\.|, .+\.)", sentence)
    maker = rules.get("manufacturerHosts", {}).get(host)
    if match and ((maker and match['model'].startswith(maker + ' '))
                  or match['actor'] in rules.get("airlineHosts", {}).get(host, [])):
        values = match.groupdict()
        if values['count'] == 'first' and values['owner'] != 'its ':
            return None
        count = _NUMBER.get(values['count']) or int(values['count'])
        quantity = "首架" if values['count'] == 'first' else f"{count}架"
        title = f"{names.get(values['actor'], values['actor'])}接收{quantity}{values['model']}"
        return "delivery", title, title + '。', "confirmed", {"airlines": [values['actor']], "aircraft_models": [values['model']]}, values['core'] + '.'
    # Route/frequency notices must be published by the airline they describe.
    actors = rules.get("airlineHosts", {}).get(host, [])
    match = re.fullmatch(
        rf"(?P<actor>{actor}) (?P<verb>will launch|has launched|will resume|has resumed) "
        rf"(?:a )?(?:new )?(?:non-stop |direct )?(?:flights|services?|route) between (?P<a>{_AIRPORT}) and (?P<b>{_AIRPORT}) "
        rf"(?:on|from) (?P<date>{_DATE})\.", sentence)
    frequency = re.fullmatch(
        rf"(?P<actor>{actor}) (?P<verb>will increase|has increased|will decrease|has decreased) "
        rf"flights between (?P<a>{_AIRPORT}) and (?P<b>{_AIRPORT}) from (?P<old>[1-9]\d?) to (?P<new>[1-9]\d?) "
        rf"(?:flights )?per week (?:on|from) (?P<date>{_DATE})\.", sentence)
    if (match or frequency) and (match or frequency)['actor'] in actors:
        row = (match or frequency).groupdict()
        a, b, day = _airport(row['a']), _airport(row['b']), _date(row['date'])
        if not a or not b or a[1] == b[1] or not day:
            return None
        planned = row['verb'].startswith('will ')
        who = names.get(row['actor'], row['actor'])
        if frequency:
            old, new = int(row['old']), int(row['new'])
            increase = 'increase' in row['verb']
            if (new <= old if increase else new >= old):
                return None
            action = "增加" if increase else "減少"
            title = f"{who}{'預計' if planned else '已'}{action}航班"
            zh = f"{who}{'預計' if planned else '已'}於{day}將{a[0]}與{b[0]}之間的航班，由每週{old}班調整為每週{new}班。"
            kind = 'frequency'
        else:
            action = "恢復" if 'resume' in row['verb'] else "開航"
            title = f"{who}{'預計' if planned else '已'}{action}{a[0]}至{b[0]}航線"
            zh = f"{who}{'預計' if planned else '已'}於{day}{action}{a[0]}與{b[0]}之間的航班服務。"
            kind = 'route'
        en = sentence.replace(row['a'], a[1]).replace(row['b'], b[1])
        return kind, title, zh, "planned" if planned else "confirmed", {"airlines": [row['actor']], "airports": [row['a'], row['b']]}, en
    match = re.fullmatch(
        rf"(?P<airport>{_AIRPORT}) (?P<verb>will open|has opened|will close|has closed) "
        rf"(?P<facility>Terminal [1-9]|Gate [A-Z]?\d{{1,3}}|Runway \d{{2}}[LCR]?) "
        rf"(?:on|from) (?P<date>{_DATE})\.", sentence)
    if match and host in rules.get("authorityHosts", []):
        row = match.groupdict(); airport, day = _airport(row['airport']), _date(row['date'])
        if not airport or not day:
            return None
        planned = row['verb'].startswith('will ')
        action = "關閉" if 'clos' in row['verb'] else "啟用"
        facility = row['facility'].replace('Terminal ', '第') + '航廈' if row['facility'].startswith('Terminal ') else row['facility']
        title = f"{airport[0]}{'預計' if planned else '已'}{action}{facility}"
        zh = f"{airport[0]}{'預計' if planned else '已'}於{day}{action}{facility}。"
        return 'facility', title, zh, "planned" if planned else "confirmed", {"airports": [row['airport']]}, sentence.replace(row['airport'], airport[1])
    return None


def compile_announcement(group, now):
    item = candidate_item(group, now)
    if not item or not isinstance(item.get('fulltext'), str):
        return None
    text = item['fulltext']
    if len(text) < 50 or re.search(r'\b(?:correction|corrected|revised|withdrawn)\b|更正|撤回', text, re.I):
        return None
    if _UNSAFE.search(str(item.get('title') or '')):
        return None
    paragraphs = [line.strip() for line in text.splitlines() if line.strip() and line.strip() != str(item.get('title') or '').strip()]
    found = []
    late_event = False
    for index, paragraph in enumerate(paragraphs):
        if _UNSAFE.search(paragraph) or re.search(r'^(?:About |Media contact|Press contact|Copyright)', paragraph, re.I):
            continue
        for sentence in re.split(r'(?<=[.!?])\s+', paragraph):
            # Preserve the original quote, removing only a conventional dateline
            # for the grammar match; no dates are inferred from that prefix.
            clean = re.sub(r'^[A-Za-z ,\d]{3,65}20\d{2}\s*[–—-]\s*', '', sentence)
            row = _sentence_copy(clean, urlsplit(item['url']).hostname)
            if row:
                if index < 3:
                    found.append((row, sentence))
                else:
                    late_event = True
    if len(found) != 1 or late_event:
        return None
    row, quote = found[0]
    kind, title, zh, status, entity_values, en = row
    # Bind the extracted sentence to the actual page headline, rather than
    # accepting a recommendation card about another event on that page.
    headline = str(item.get('title') or '').casefold()
    if status == 'confirmed' and re.search(r'\bwill\b|預計|將', headline):
        return None
    _, names = settings()
    for value in entity_values.get('airlines', []):
        if value.casefold() not in headline and names.get(value, value).casefold() not in headline:
            return None
    for value in entity_values.get('aircraft_models', []):
        if value.split(' ', 1)[-1].casefold() not in headline:
            return None
    for value in entity_values.get('airports', []):
        if value.casefold() not in headline and names.get(value, value).casefold() not in headline:
            return None
    entities = {key: entity_values.get(key, []) for key in ENTITY_KEYS}
    fact = {"factId": "F1", "claim": quote, "sourceQuote": quote,
            "sourceUrl": item['url'], "evidenceScope": "source",
            "archiveEventId": None, "archiveContext": False}
    flash_zh = title if len(title) <= 40 else {
        'delivery': '官方交機公告', 'route': '航空公司航線公告',
        'frequency': '航空公司航班調整公告', 'facility': '機場設施公告',
    }[kind]
    return {
        "status": "publish_brief", "decisionReason": "", "cat": "biz" if kind == 'delivery' else "ops",
        "zh": {"title": title, "summary": zh, "body": [zh]},
        "en": {"title": re.sub(r'\.$', '', en), "summary": en, "body": [en]},
        "flash": {"zh": flash_zh, "en": re.sub(r'\.$', '', en), "hot": False},
        "facts": [fact], "headlineSupportedBy": ["F1"], "summarySupportedBy": ["F1"],
        "entities": entities, "entityEvidence": [
            {"entityType": key, "value": value, "sourceQuote": quote, "sourceUrl": item['url']}
            for key, values in entity_values.items() for value in values],
        "eventStatus": status, "riskFlags": [], "requiresHumanReview": False, "incident": None,
    }
