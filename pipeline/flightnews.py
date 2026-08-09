"""Bridge between the flightwatch monitor and the hourly news pipeline.

flightwatch.py (every 5 min, zero AI) appends confirmed rare-arrival
candidates to data/flightwatch/queue.json. write.py (hourly) consumes the
queue via this module: assemble_source() renders the ONLY evidence the
model may quote, pseudo_group() adapts an event to the existing
group/validation/verify_facts/review machinery, and the dedicated prompt
(prompts/rare-aircraft-news-zh.txt) forces manual_review output.

The assembled SOURCE never contains live coordinates, headings, altitudes
or tracks - only identities, times, counts and code-computed statistics.
"""
from __future__ import annotations

from common import DATA_DIR, ROOT, load_json, save_json

QUEUE_PATH = DATA_DIR / "flightwatch" / "queue.json"
MAX_EVENTS_PER_RUN = 3

_PROMPT_PATH = ROOT / "prompts" / "rare-aircraft-news-zh.txt"
_AIRLINES_PATH = ROOT / "config" / "airline_icao_codes.json"
_BACKGROUNDS_PATH = ROOT / "config" / "airline_backgrounds.json"
_FALLBACK_PROMPT = (
    "You write a bilingual wire item as JSON (same DRAFT_SCHEMA as the main "
    "pipeline) from ONE <SOURCE type=\"flight_observation\"> block. Use only "
    "its lines; quote them verbatim in facts. Facts use evidenceScope source, "
    "archiveContext false and archiveEventId null. status MUST be manual_review, "
    "cat ops, incident null, riskFlags include unconfirmed_or_developing. "
    "Never guess routes, purposes or flight numbers; never claim firsts.")


def flight_prompt() -> str:
    try:
        text = _PROMPT_PATH.read_text(encoding="utf-8").strip()
        return text or _FALLBACK_PROMPT
    except OSError:
        return _FALLBACK_PROMPT


def load_queue() -> list:
    rows = load_json(QUEUE_PATH, [])
    return rows if isinstance(rows, list) else []


def save_queue(rows: list) -> None:
    save_json(QUEUE_PATH, rows)


def _operator_details(event: dict) -> dict:
    """Merge the queued observation with the curated airline catalogue."""
    operator = dict(event.get("operator") or {})
    cfg = load_json(_AIRLINES_PATH, {})
    rows = cfg.get("airlines") or []
    code = str(operator.get("icao") or "").upper()
    row = next((r for r in rows if isinstance(r, dict)
                and r.get("active", True)
                and str(r.get("icao_code") or "").upper() == code), {})
    regions = cfg.get("regions") or {}
    region_code = operator.get("country_or_region") \
        or row.get("country_or_region")
    region = regions.get(region_code) or {}
    return {
        "icao": code or None,
        "iata": operator.get("iata") or row.get("iata_code"),
        "name": operator.get("name") or row.get("airline_name_en"),
        "name_zh": operator.get("name_zh") or row.get("airline_name_zh_tw"),
        "country_or_region": region_code,
        "region_zh": region.get("zh_tw"),
        "region_en": region.get("en"),
    }


def _background_items(event: dict) -> list[dict]:
    """Return source-bound, date-limited background for this observation."""
    operator = _operator_details(event)
    code = operator.get("icao")
    registration = str((event.get("aircraft") or {}).get("registration")
                       or "").upper()
    confirmed = str((event.get("arrival") or {}).get("confirmedUtc") or "")
    event_date = confirmed[:10]
    profiles = load_json(_BACKGROUNDS_PATH, {}).get("profiles") or []
    profile = next((p for p in profiles if isinstance(p, dict)
                    and str(p.get("icao_code") or "").upper() == code), None)
    if not profile:
        return []
    items = []
    for fact in profile.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        registrations = {str(value).upper()
                         for value in fact.get("registrations") or []}
        if registrations and registration not in registrations:
            continue
        valid_from = str(fact.get("valid_from") or "")
        valid_through = str(fact.get("valid_through") or "")
        if event_date and valid_from and event_date < valid_from:
            continue
        if event_date and valid_through and event_date > valid_through:
            continue
        url = str(fact.get("source_url") or "").strip()
        if not url.startswith("https://"):
            continue
        checked = str(fact.get("checked_on") or "未標示")
        items.append({
            "title": str(fact.get("source_name") or "航空公司背景來源"),
            "url": url,
            "publishedUtc": confirmed,
            "summary": "\n".join([
                str(fact.get("zh") or "").strip(),
                str(fact.get("en") or "").strip(),
                f"背景資料查核日期：{checked}",
                (f"背景資料適用至：{valid_through}"
                 if valid_through else ""),
            ]).strip(),
            "image": None,
            "source": str(fact.get("source_name") or "官方背景來源"),
            "sourceKey": "flight_background",
        })
    return items


def assemble_source(event: dict) -> str:
    """Render the flight observation as line-quotable evidence. Every line
    here may become a verbatim sourceQuote; nothing else may."""
    airport = event.get("airport") or {}
    aircraft = event.get("aircraft") or {}
    operator = _operator_details(event)
    arrival = event.get("arrival") or {}
    rar = event.get("rarity") or {}
    lines = [
        '<SOURCE type="flight_observation">',
        f"事件 ID：{event.get('eventId')}",
        "資料類型：公開 ADS-B 觀測",
        "主要資料來源：Airplanes.live",
        "第二資料來源：ADSB.lol",
        f"交叉確認狀態：{event.get('crossCheck')}",
        f"機場 ICAO：{airport.get('icao')}",
        f"機場名稱：{airport.get('name_zh')}",
        f"航空器 ICAO hex：{aircraft.get('hex')}",
        f"註冊號：{aircraft.get('registration') or '未取得'}",
        f"呼號：{aircraft.get('callsign') or '未取得'}",
        f"營運者 ICAO：{operator.get('icao') or '未識別'}",
        f"營運者 IATA：{operator.get('iata') or '未識別'}",
        f"營運者名稱：{operator.get('name') or '未識別'}",
        f"營運者中文名稱：{operator.get('name_zh') or '未識別'}",
        (f"營運者所屬國家或地區：{operator.get('region_zh')}"
         if operator.get("region_zh") else "營運者所屬國家或地區：未識別"),
        f"航空器 ICAO 機型：{aircraft.get('type') or '未取得'}",
        f"機型顯示名稱：{aircraft.get('type_name') or aircraft.get('type') or '未取得'}",
        f"首次有效觀測時間：{arrival.get('firstSeenUtc')}",
        f"確認抵達時間：{arrival.get('confirmedUtc')}",
        f"抵達判定：{arrival.get('status')}",
        f"確認依據：{arrival.get('basis')}",
        f"有效觀測筆數：{arrival.get('observations')}",
    ]
    if not event.get("bootstrap"):
        lines += [
            f"過去 180 天相同營運者＋機型＋機場組合次數：{rar.get('combo180')}",
            f"過去 365 天相同註冊號抵達該機場次數：{rar.get('reg365')}",
            f"稀有度分數：{rar.get('score')}",
            f"稀有度原因：{'；'.join(rar.get('reasons') or [])}",
        ]
    else:
        lines.append("統計說明：系統觀測歷史累積中，尚無可比較的長期統計")
    lines.append("</SOURCE>")
    return "\n".join(lines)


def pseudo_group(event: dict) -> dict:
    """Adapt an event to the existing group machinery: verify_facts checks
    quotes against items' title+summary, and build_article turns item urls
    into the article's source/attribution links."""
    source_text = assemble_source(event)
    airport = event.get("airport") or {}
    aircraft = event.get("aircraft") or {}
    title = (f"公開 ADS-B 觀測：{aircraft.get('type') or aircraft.get('hex')}"
             f" 抵達 {airport.get('name_zh') or airport.get('icao')}")
    confirmed = (event.get("arrival") or {}).get("confirmedUtc") or ""
    published = confirmed[:16] + "Z" if len(confirmed) >= 16 else confirmed
    items = [{
        "title": title,
        "url": "https://airplanes.live/",
        "publishedUtc": published,
        "summary": source_text,
        "image": None,
        "source": "Airplanes.live",
        "sourceKey": "airplanes_live",
    }]
    if event.get("crossCheck") == "confirmed_by_two_sources":
        items.append({
            "title": title,
            "url": "https://www.adsb.lol/",
            "publishedUtc": published,
            "summary": "第二資料來源交叉確認相符（ODbL 開放資料）。",
            "image": None,
            "source": "ADSB.lol",
            "sourceKey": "adsb_lol",
        })
    items.extend(_background_items(event))
    return {
        "id": event.get("eventId"),
        "primarySource": "Airplanes.live",
        "items": items,
    }
