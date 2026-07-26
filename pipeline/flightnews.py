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
_FALLBACK_PROMPT = (
    "You write a bilingual wire item as JSON (same DRAFT_SCHEMA as the main "
    "pipeline) from ONE <SOURCE type=\"flight_observation\"> block. Use only "
    "its lines; quote them verbatim in facts. status MUST be manual_review, "
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


def assemble_source(event: dict) -> str:
    """Render the flight observation as line-quotable evidence. Every line
    here may become a verbatim sourceQuote; nothing else may."""
    airport = event.get("airport") or {}
    aircraft = event.get("aircraft") or {}
    operator = event.get("operator") or {}
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
        f"營運者名稱：{operator.get('name') or '未識別'}",
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
    return {
        "id": event.get("eventId"),
        "primarySource": "Airplanes.live",
        "items": items,
    }
