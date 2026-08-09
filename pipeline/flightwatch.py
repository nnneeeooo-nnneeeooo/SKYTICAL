"""Taiwan rare-aircraft arrival monitor (runs every ~5 min via Actions).

Pure code-side detection - NO AI is ever called from this module:

    scan (Airplanes.live, ONE wide-area query)
      -> sanitize + sensitive/privacy exclusion (adsb.py)
      -> assign aircraft to nearby civil airports (config/tw_civil_airports)
      -> per-aircraft track state machine (multi-observation, never a
         single snapshot): observed / approaching / probable_arrival /
         confirmed_arrival / overflight / insufficient_data
      -> rarity scoring (explainable 0-100, config-driven, bootstrap-aware)
      -> cross-check candidates against ADSB.lol (secondary source)
      -> event registry + stable event ids (no duplicate news, ever)
      -> queue publishable candidates for the HOURLY news pipeline
         (write.py drafts them with the dedicated prompt and forces
         manual_review; this module never publishes anything)

Persistence lives in data/flightwatch/ (committed by the monitor workflow
only when something changed): state.json (tracks, pruned to 60 min),
history.json (rarity statistics), events.json (event registry),
queue.json (candidates awaiting the news stage).

Failure rules: any provider failure leaves every file untouched - an API
outage is "unknown sky", never "no aircraft" and never a reason to touch
the news site. Feature is OFF unless FLIGHT_TRACKING_ENABLED=true.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import adsb
from common import DATA_DIR, ROOT, load_json, save_json

CONFIG_DIR = ROOT / "config"
FW_DIR = DATA_DIR / "flightwatch"
STATE_PATH = FW_DIR / "state.json"
HISTORY_PATH = FW_DIR / "history.json"
EVENTS_PATH = FW_DIR / "events.json"
QUEUE_PATH = FW_DIR / "queue.json"

# --- tunables (env-overridable; sane defaults per the spec) ---------------
CENTER_LAT = float(os.environ.get("TW_ADSB_CENTER_LAT") or 23.7)
CENTER_LON = float(os.environ.get("TW_ADSB_CENTER_LON") or 120.9)
RADIUS_NM = min(float(os.environ.get("TW_ADSB_RADIUS_NM") or 250), 250.0)

SCORE_THRESHOLD = int(os.environ.get("RARE_AIRCRAFT_SCORE_THRESHOLD") or 60)
OPERATOR_WINDOW_DAYS = int(
    os.environ.get("RARE_AIRCRAFT_OPERATOR_WINDOW_DAYS") or 180)
REGISTRATION_WINDOW_DAYS = int(
    os.environ.get("RARE_AIRCRAFT_REGISTRATION_WINDOW_DAYS") or 365)
PUBLICATION_DELAY_MIN = int(
    os.environ.get("FLIGHT_TRACKING_PUBLICATION_DELAY_MINUTES") or 30)
BOOTSTRAP_DAYS = 30          # empty history must not make everything "rare"
TRACK_RETENTION_MIN = 60     # keep at most this much per-aircraft history
EVENT_EXPIRE_HOURS = 24      # candidates without evidence die quietly
APPROACH_ALT_FT = 3000       # last-point ceiling for trajectory arrivals
OVERFLIGHT_ALT_FT = 15000    # passing this high is never an arrival
RECLIMB_FT = 2000            # climb-out after low point => not an arrival
TAXI_MAX_GS_KT = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    rad = math.radians
    dlat = rad(lat2 - lat1)
    dlon = rad(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rad(lat1)) * math.cos(rad(lat2))
         * math.sin(dlon / 2) ** 2)
    return 6371.0 * 2 * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# configuration loading + validation

class ConfigError(Exception):
    pass


def load_airports() -> list:
    data = load_json(CONFIG_DIR / "tw_civil_airports.json", {})
    overrides = (load_json(CONFIG_DIR / "normal_airport_operations.json", {})
                 .get("overrides") or {})
    return validate_airports(data.get("airports"), overrides)


def validate_airports(airports, overrides: dict) -> list:
    if not isinstance(airports, list) or not airports:
        raise ConfigError("tw_civil_airports.json missing airports[]")
    seen_icao = set()
    valid = []
    for ap in airports:
        icao = str(ap.get("icao") or "")
        if not (len(icao) == 4 and icao.isalpha() and icao.isupper()):
            raise ConfigError(f"bad airport ICAO {icao!r}")
        if icao in seen_icao:
            raise ConfigError(f"duplicate airport ICAO {icao}")
        seen_icao.add(icao)
        iata = ap.get("iata")
        if iata not in (None, "") and len(str(iata)) != 3:
            raise ConfigError(f"{icao}: bad IATA {iata!r}")
        lat, lon = ap.get("lat"), ap.get("lon")
        if not (isinstance(lat, (int, float)) and -90 <= lat <= 90):
            raise ConfigError(f"{icao}: bad lat {lat!r}")
        if not (isinstance(lon, (int, float)) and -180 <= lon <= 180):
            raise ConfigError(f"{icao}: bad lon {lon!r}")
        if not (isinstance(ap.get("arrival_geofence_km"), (int, float))
                and ap["arrival_geofence_km"] > 0):
            raise ConfigError(f"{icao}: bad arrival_geofence_km")
        extra = overrides.get(icao) or {}
        ap = dict(ap)
        ap["normal_operator_codes"] = sorted(
            set(ap.get("normal_operator_codes") or [])
            | set(extra.get("normal_operator_codes") or []))
        ap["normal_aircraft_types"] = sorted(
            set(ap.get("normal_aircraft_types") or [])
            | set(extra.get("normal_aircraft_types") or []))
        if ap.get("enabled", True):
            valid.append(ap)
    return valid


def load_airlines() -> dict:
    rows = load_json(CONFIG_DIR / "airline_icao_codes.json", {}) \
        .get("airlines") or []
    return {str(r.get("icao_code")): r for r in rows
            if isinstance(r, dict) and r.get("active", True)}


def load_watchlist() -> list:
    rows = load_json(CONFIG_DIR / "rare_aircraft_watchlist.json", {}) \
        .get("watchlist") or []
    return [r for r in rows if isinstance(r, dict) and r.get("enabled")]


def load_type_names() -> dict:
    return load_json(CONFIG_DIR / "aircraft_types.json", {}) \
        .get("types") or {}


def operator_from_callsign(callsign, airlines: dict):
    """(operator_icao, operator_name|None). Never invents a name; a bare
    registration-style callsign is NOT parsed as an airline code."""
    if not callsign:
        return None, None
    cs = str(callsign).strip().upper()
    if len(cs) >= 4 and cs[:3].isalpha() and cs[3].isdigit():
        code = cs[:3]
        row = airlines.get(code)
        return code, (row or {}).get("airline_name_en")
    return None, None


def operator_from_observation(ac: dict, airlines: dict):
    """Resolve a known airline without asking the model to infer it.

    The callsign designator remains the primary key.  When it is absent or
    unknown, ``ownOp`` from the ADS-B database is accepted only when it
    exactly matches a curated airline name in ``airline_icao_codes.json``.
    Free-form provider labels are never published directly.
    """
    code, name = operator_from_callsign(ac.get("callsign"), airlines)
    if name:
        return code, name
    supplied = str(ac.get("operator_name") or "").strip().casefold()
    if supplied:
        for known_code, row in airlines.items():
            known_names = {
                str(row.get("airline_name_en") or "").strip().casefold(),
                str(row.get("airline_name_zh_tw") or "").strip().casefold(),
            }
            if supplied in known_names:
                return known_code, row.get("airline_name_en")
    return code, name


# --------------------------------------------------------------------------
# arrival state machine (multi-observation; never a single snapshot)

def assess_track(points: list, airport: dict) -> str:
    """points: time-ascending observation dicts for one aircraft near one
    airport, each with ts/lat/lon/alt_baro/ground_speed/distance_km/quality.
    """
    usable = [p for p in points if p.get("quality") == "good"]
    if not usable:
        return "insufficient_data"
    last = usable[-1]
    alts = [p["alt_baro"] for p in usable
            if isinstance(p.get("alt_baro"), (int, float))]

    # Climb-out after the low point => go-around / departure, not arrival.
    if alts:
        low = min(alts)
        after_low = alts[alts.index(low):]
        if after_low and max(after_low) > low + RECLIMB_FT:
            return "overflight"

    on_ground = last.get("alt_baro") == "ground"
    in_fence = last["distance_km"] <= airport["arrival_geofence_km"]

    if on_ground and in_fence:
        gs = last.get("ground_speed")
        if gs is not None and gs > TAXI_MAX_GS_KT + 40:
            return "insufficient_data"  # ground-speed says still rolling out fast
        # Need at least one PRIOR observation showing approach/descent:
        # a first-ever ground sighting alone could be a departure taxi.
        for prev in usable[:-1]:
            prev_alt = prev.get("alt_baro")
            descending = (isinstance(prev_alt, (int, float))
                          and prev_alt < OVERFLIGHT_ALT_FT)
            closing = prev["distance_km"] > last["distance_km"]
            if descending or closing:
                return "confirmed_arrival"
        return "insufficient_data"

    airborne = [p for p in usable
                if isinstance(p.get("alt_baro"), (int, float))]
    if len(airborne) >= 3:
        dists = [p["distance_km"] for p in airborne]
        alt_series = [p["alt_baro"] for p in airborne]
        descending = alt_series[-1] < alt_series[0] - 500
        closing = dists[-1] < dists[0] - 2
        near = dists[-1] <= airport["arrival_geofence_km"] * 2
        low_enough = alt_series[-1] <= APPROACH_ALT_FT
        mlat_only = all(p.get("low_confidence") for p in airborne)
        if descending and closing and near and low_enough and not mlat_only:
            return "probable_arrival"
    if airborne:
        last_alt = airborne[-1]["alt_baro"]
        if last_alt >= OVERFLIGHT_ALT_FT:
            return "overflight"
        dists = [p["distance_km"] for p in airborne]
        if len(dists) >= 2 and dists[-1] < dists[0]:
            return "approaching"
    return "observed"


# --------------------------------------------------------------------------
# cross-source confirmation

def cross_check(primary: dict, secondary_rows: list) -> str:
    """Compare the candidate against the secondary source's view."""
    match = None
    for raw in secondary_rows or []:
        ac = adsb.parse_aircraft(raw)
        if ac and ac["hex"] == primary["hex"]:
            match = ac
            break
    if match is None:
        return "secondary_unavailable"
    for key in ("registration", "aircraft_type"):
        a, b = primary.get(key), match.get(key)
        if a and b and a.upper() != b.upper():
            return "conflicting_sources"
    ca = (primary.get("callsign") or "").strip().upper()
    cb = (match.get("callsign") or "").strip().upper()
    if ca and cb and ca != cb:
        return "conflicting_sources"
    pa, pb = primary.get("alt_baro"), match.get("alt_baro")
    if (pa == "ground") != (pb == "ground"):
        if isinstance(pb if pa == "ground" else pa, (int, float)) and \
                (pb if pa == "ground" else pa) > 10000:
            return "conflicting_sources"
    if None not in (primary.get("lat"), primary.get("lon"),
                    match.get("lat"), match.get("lon")):
        if haversine_km(primary["lat"], primary["lon"],
                        match["lat"], match["lon"]) > 30:
            return "conflicting_sources"
    if not adsb.position_ok(match):
        return "confirmed_by_primary_only"
    return "confirmed_by_two_sources"


# --------------------------------------------------------------------------
# rarity scoring (explainable, config-driven, never AI)

def in_bootstrap(history: dict, now: datetime) -> bool:
    first = history.get("firstRunUtc")
    if not first:
        return True
    try:
        return now - parse_ts(first) < timedelta(days=BOOTSTRAP_DAYS)
    except ValueError:
        return True


def _recent(history: dict, days: int, now: datetime, **match) -> int:
    cutoff = now - timedelta(days=days)
    count = 0
    for row in history.get("arrivals") or []:
        try:
            when = parse_ts(row["confirmedUtc"])
        except (KeyError, ValueError):
            continue
        if when < cutoff:
            continue
        if all(row.get(k) == v for k, v in match.items() if v is not None):
            count += 1
    return count


def rarity(ac: dict, operator_icao, airport: dict, history: dict,
           watchlist: list, now: datetime):
    """(score 0-100, reasons list, watchlisted bool). Explainable only."""
    score, reasons = 0, []
    icao = airport["icao"]
    combo_180 = _recent(history, OPERATOR_WINDOW_DAYS, now,
                        airport_icao=icao, operator_icao=operator_icao,
                        aircraft_type=ac.get("aircraft_type"))
    reg_365 = _recent(history, REGISTRATION_WINDOW_DAYS, now,
                      airport_icao=icao, registration=ac.get("registration"))
    combo_30 = _recent(history, 30, now, airport_icao=icao,
                       operator_icao=operator_icao,
                       aircraft_type=ac.get("aircraft_type"))

    if operator_icao and operator_icao not in airport["normal_operator_codes"]:
        score += 35
        reasons.append(f"營運者 {operator_icao} 非 {icao} 常態業者 (+35)")
    if combo_180 == 0:
        score += 25
        reasons.append(
            f"過去 {OPERATOR_WINDOW_DAYS} 天無相同營運者+機型+機場紀錄 (+25)")
    if ac.get("registration") and reg_365 == 0:
        score += 15
        reasons.append(
            f"過去 {REGISTRATION_WINDOW_DAYS} 天此註冊號未曾抵達 {icao} (+15)")
    if ac.get("aircraft_type") and \
            ac["aircraft_type"] not in airport["normal_aircraft_types"]:
        score += 15
        reasons.append(f"機型 {ac['aircraft_type']} 非 {icao} 常見機型 (+15)")
    if ac.get("db_flags", 0) & adsb.DB_INTERESTING:
        score += 10
        reasons.append("資料庫 interesting 旗標 (+10)")

    if operator_icao and operator_icao in airport["normal_operator_codes"]:
        score -= 40
        reasons.append(f"{operator_icao} 為 {icao} 常態業者 (-40)")
    if ac.get("aircraft_type") in airport["normal_aircraft_types"]:
        score -= 15
        reasons.append("常見機型 (-15)")
    if combo_30 > 0:
        score -= 30 * min(combo_30, 2)
        reasons.append(f"最近 30 天已出現 {combo_30} 次 (-{30 * min(combo_30, 2)})")

    score = max(0, min(100, score))

    for row in watchlist:
        if row.get("airport_icao") not in (None, icao):
            continue
        if row.get("operator_icao") not in (None, operator_icao):
            continue
        if row.get("aircraft_type") not in (None, ac.get("aircraft_type")):
            continue
        if row.get("registration") not in (None, ac.get("registration")):
            continue
        reasons.append(f"watchlist: {row.get('note') or 'match'}")
        return score, reasons, True
    return score, reasons, False


# --------------------------------------------------------------------------
# event identity + registry

def event_id(icao_hex: str, airport_icao: str, arrival_date: str) -> str:
    digest = hashlib.sha256(
        f"{icao_hex.lower()}|{airport_icao}|arrival|{arrival_date}"
        .encode("utf-8")).hexdigest()
    return f"fw-{digest[:16]}"


# --------------------------------------------------------------------------
# main scheduler pass

def _load_state():
    state = load_json(STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def _prune_tracks(tracks: dict, now: datetime) -> dict:
    cutoff = now - timedelta(minutes=TRACK_RETENTION_MIN)
    kept = {}
    for key, points in tracks.items():
        fresh = []
        for p in points:
            try:
                if parse_ts(p["ts"]) >= cutoff:
                    fresh.append(p)
            except (KeyError, ValueError):
                continue
        if fresh:
            kept[key] = fresh[-24:]  # a point every ~5 min: 2 h hard cap
    return kept


def _save_if_changed(path: Path, obj, before: str) -> bool:
    after = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    if after == before:
        return False
    save_json(path, obj)
    return True


def main() -> None:
    if (os.environ.get("FLIGHT_TRACKING_ENABLED") or "false").lower() != "true":
        print("flightwatch: disabled (FLIGHT_TRACKING_ENABLED != true)")
        return

    now = utcnow()
    airports = load_airports()
    airlines = load_airlines()
    watchlist = load_watchlist()
    type_names = load_type_names()

    stats = {k: 0 for k in (
        "provider_requests", "provider_failures", "aircraft_returned",
        "aircraft_after_validation", "sensitive_aircraft_skipped",
        "stale_positions_skipped", "non_icao_addresses_skipped",
        "candidate_aircraft", "approaching_aircraft", "probable_arrivals",
        "confirmed_arrivals", "overflights", "rarity_candidates",
        "duplicate_events_skipped", "secondary_confirmations",
        "conflicting_sources", "manual_review_events")}

    # ONE wide-area scan per run; failure leaves every file untouched.
    stats["provider_requests"] += 1
    try:
        raw_rows = adsb.airplanes_live_point(CENTER_LAT, CENTER_LON, RADIUS_NM)
    except adsb.ProviderDown as exc:
        stats["provider_failures"] += 1
        print(f"flightwatch: primary provider unavailable ({exc}); "
              "state untouched - an API failure is NOT an empty sky")
        print("flightwatch stats: "
              + " ".join(f"{k}={v}" for k, v in stats.items()))
        return
    stats["aircraft_returned"] = len(raw_rows)

    state = _load_state()
    before_state = json.dumps(state, ensure_ascii=False, sort_keys=True)
    history = load_json(HISTORY_PATH, {})
    if not isinstance(history, dict):
        history = {}
    history.setdefault("firstRunUtc", iso(now))
    history.setdefault("arrivals", [])
    before_history = json.dumps(history, ensure_ascii=False, sort_keys=True)
    events = load_json(EVENTS_PATH, {})
    if not isinstance(events, dict):
        events = {}
    before_events = json.dumps(events, ensure_ascii=False, sort_keys=True)
    queue = load_json(QUEUE_PATH, [])
    if not isinstance(queue, list):
        queue = []
    before_queue = json.dumps(queue, ensure_ascii=False, sort_keys=True)

    tracks = state.get("tracks") or {}
    bootstrap = in_bootstrap(history, now)

    # --- ingest this scan into per-aircraft/airport tracks ----------------
    latest: dict = {}
    for raw in raw_rows:
        ac = adsb.parse_aircraft(raw)
        if ac is None:
            continue
        if ac["non_icao"]:
            stats["non_icao_addresses_skipped"] += 1
            continue
        if adsb.sensitive_reason(ac):
            # Never track, log positions for, or publish these.
            stats["sensitive_aircraft_skipped"] += 1
            continue
        if not adsb.position_ok(ac):
            stats["stale_positions_skipped"] += 1
            continue
        stats["aircraft_after_validation"] += 1
        for airport in airports:
            dist = haversine_km(ac["lat"], ac["lon"],
                                airport["lat"], airport["lon"])
            if dist > airport["approach_radius_nm"] * 1.852:
                continue
            key = f"{ac['hex']}@{airport['icao']}"
            point = {
                "ts": iso(now), "provider": "airplanes_live",
                "lat": round(ac["lat"], 3), "lon": round(ac["lon"], 3),
                "alt_baro": ac["alt_baro"],
                "ground_speed": ac["ground_speed"],
                "vertical_rate": ac["vertical_rate"],
                "distance_km": round(dist, 2),
                "quality": "good",
                "low_confidence": adsb.low_confidence(ac),
            }
            tracks.setdefault(key, []).append(point)
            latest[key] = (ac, airport)

    # --- evaluate every touched track --------------------------------------
    for key, (ac, airport) in latest.items():
        status = assess_track(tracks[key], airport)
        if status == "approaching":
            stats["approaching_aircraft"] += 1
            continue
        if status == "overflight":
            stats["overflights"] += 1
            continue
        if status == "probable_arrival":
            stats["probable_arrivals"] += 1
            # v1: probable-only is never enough to queue news; keep tracking.
            continue
        if status != "confirmed_arrival":
            continue
        stats["confirmed_arrivals"] += 1

        arrival_date = now.strftime("%Y-%m-%d")
        eid = event_id(ac["hex"], airport["icao"], arrival_date)
        if eid in events:
            stats["duplicate_events_skipped"] += 1
            continue

        operator_icao, operator_name = operator_from_observation(ac, airlines)
        operator_row = airlines.get(operator_icao) or {}
        score, reasons, watchlisted = rarity(
            ac, operator_icao, airport, history, watchlist, now)

        history["arrivals"].append({
            "airport_icao": airport["icao"],
            "operator_icao": operator_icao,
            "aircraft_type": ac.get("aircraft_type"),
            "registration": ac.get("registration"),
            "arrival_date": arrival_date,
            "confirmation_level": "confirmed_arrival",
            "first_seen_at": tracks[key][0]["ts"],
            "confirmedUtc": iso(now),
        })

        rare_enough = watchlisted or score >= SCORE_THRESHOLD
        if not rare_enough:
            events[eid] = {"status": "rejected", "reason": "below threshold",
                           "score": score, "at": iso(now)}
            continue
        stats["rarity_candidates"] += 1

        # Secondary source ONLY now, for this one candidate.
        stats["provider_requests"] += 1
        try:
            secondary = adsb.adsb_lol_icao(ac["hex"])
            cross = cross_check(ac, secondary)
        except adsb.ProviderDown:
            stats["provider_failures"] += 1
            cross = "secondary_unavailable"
        if cross == "confirmed_by_two_sources":
            stats["secondary_confirmations"] += 1
        elif cross == "conflicting_sources":
            stats["conflicting_sources"] += 1
            events[eid] = {"status": "rejected",
                           "reason": "conflicting sources", "at": iso(now)}
            continue

        first_ts = tracks[key][0]["ts"]
        events[eid] = {
            "status": "candidate", "at": iso(now), "score": score,
            "airport": airport["icao"], "hex": ac["hex"],
        }
        stats["manual_review_events"] += 1
        queue.append({
            "eventId": eid,
            "queuedUtc": iso(now),
            "notBeforeUtc": iso(now + timedelta(
                minutes=PUBLICATION_DELAY_MIN)),
            "bootstrap": bootstrap,
            "crossCheck": cross,
            "airport": {k: airport[k] for k in
                        ("icao", "iata", "name_zh", "name_en")},
            "aircraft": {
                "hex": ac["hex"],
                "registration": ac.get("registration"),
                "type": ac.get("aircraft_type"),
                "type_name": type_names.get(ac.get("aircraft_type") or ""),
                "callsign": ac.get("callsign"),
            },
            "operator": {
                "icao": operator_icao,
                "iata": operator_row.get("iata_code"),
                "name": operator_name,
                "name_zh": operator_row.get("airline_name_zh_tw"),
                "country_or_region": operator_row.get("country_or_region"),
            },
            "arrival": {
                "status": "confirmed_arrival",
                "firstSeenUtc": first_ts,
                "confirmedUtc": iso(now),
                "basis": "位於機場地理圍欄內且 alt_baro 為 ground",
                "observations": len(tracks[key]),
            },
            "rarity": {
                "score": score, "reasons": reasons,
                "watchlisted": watchlisted,
                "combo180": _recent(history, OPERATOR_WINDOW_DAYS, now,
                                    airport_icao=airport["icao"],
                                    operator_icao=operator_icao,
                                    aircraft_type=ac.get("aircraft_type")) - 1,
                "reg365": _recent(history, REGISTRATION_WINDOW_DAYS, now,
                                  airport_icao=airport["icao"],
                                  registration=ac.get("registration")) - 1,
            },
        })

    # --- expiry + retention -------------------------------------------------
    state["tracks"] = _prune_tracks(tracks, now)
    cutoff_hist = now - timedelta(days=REGISTRATION_WINDOW_DAYS + 30)
    history["arrivals"] = [
        r for r in history["arrivals"]
        if r.get("confirmedUtc") and parse_ts(r["confirmedUtc"]) >= cutoff_hist
    ][-5000:]
    expire_before = now - timedelta(hours=EVENT_EXPIRE_HOURS)
    for eid, row in list(events.items()):
        if row.get("status") == "tracking":
            try:
                if parse_ts(row["at"]) < expire_before:
                    events[eid]["status"] = "expired"
            except (KeyError, ValueError):
                events[eid]["status"] = "expired"

    changed = _save_if_changed(STATE_PATH, state, before_state)
    changed |= _save_if_changed(HISTORY_PATH, history, before_history)
    changed |= _save_if_changed(EVENTS_PATH, events, before_events)
    changed |= _save_if_changed(QUEUE_PATH, queue, before_queue)

    print("flightwatch stats: "
          + " ".join(f"{k}={v}" for k, v in stats.items())
          + f" state_changed={changed} bootstrap={bootstrap}")


if __name__ == "__main__":
    main()
