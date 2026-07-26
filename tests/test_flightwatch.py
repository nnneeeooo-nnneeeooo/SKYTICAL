"""Offline tests for the rare-aircraft monitor + its news-pipeline bridge.

Run from the repo root:  py tests\\test_flightwatch.py

Everything is mocked: no Airplanes.live, no ADSB.lol, no AI API, no quota.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-flightwatch-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP / "data")
sys.path.insert(0, str(ROOT / "pipeline"))

import adsb  # noqa: E402
import common  # noqa: E402
import flightnews  # noqa: E402
import flightwatch  # noqa: E402
import providers  # noqa: E402
import write  # noqa: E402

_pass = 0
_fail = 0


def check(cond, label):
    global _pass, _fail
    if cond:
        _pass += 1
    else:
        _fail += 1
        print(f"FAIL: {label}")


NOW = datetime.now(timezone.utc)


def ts(minutes_ago: float) -> str:
    return flightwatch.iso(NOW - timedelta(minutes=minutes_ago))


RCKH = {
    "icao": "RCKH", "iata": "KHH", "name_zh": "高雄國際機場",
    "name_en": "Kaohsiung International Airport",
    "lat": 22.5771, "lon": 120.3498, "arrival_geofence_km": 4.0,
    "approach_radius_nm": 35, "airport_class": "international",
    "enabled": True,
    "normal_operator_codes": ["CAL", "EVA", "MDA", "TTW"],
    "normal_aircraft_types": ["A320", "A321", "A21N", "B738", "AT76"],
}


# --------------------------------------------------------------------------
def test_parse_and_sanitize():
    raw = {"hex": "A1B2C3", "r": "N501DN", "t": "a359",
           "type": "adsb_icao", "flight": "DAL123   ",
           "alt_baro": "ground", "gs": 12.5, "lat": 22.58, "lon": 120.35,
           "seen": 1.2, "seen_pos": 0.8, "dbFlags": 0, "squawk": "2000"}
    ac = adsb.parse_aircraft(raw)
    check(ac["hex"] == "a1b2c3", "hex normalized to lowercase")
    check(ac["aircraft_type"] == "A359", "`t` parsed as the AIRCRAFT type")
    check(ac["source_type"] == "adsb_icao",
          "`type` kept as position source, never the airframe type")
    check(ac["callsign"] == "DAL123", "trailing callsign spaces trimmed")
    check(ac["alt_baro"] == "ground", 'alt_baro "ground" survives as string')
    check(adsb.position_ok(ac), "fresh positioned row usable")

    sparse = adsb.parse_aircraft({"hex": "abc123"})
    check(sparse is not None and sparse["aircraft_type"] is None
          and sparse["lat"] is None, "missing optional fields never crash")
    check(not adsb.position_ok(sparse), "row without lat/lon skipped")
    check(adsb.parse_aircraft({"r": "B-12345"}) is None,
          "row without hex is unusable")

    stale = adsb.parse_aircraft(dict(raw, seen_pos=45.0))
    check(not adsb.position_ok(stale), "seen_pos > 30s excluded")
    vehicle = adsb.parse_aircraft(dict(raw, type="adsb_icao_nt"))
    check(not adsb.position_ok(vehicle), "ground vehicles never 'arrive'")

    tilde = adsb.parse_aircraft(dict(raw, hex="~2a44f0"))
    check(tilde["non_icao"], "~ prefixed non-ICAO address flagged")

    check(adsb.sensitive_reason(adsb.parse_aircraft(dict(raw, dbFlags=1))),
          "dbFlags military bit excluded")
    check(adsb.sensitive_reason(adsb.parse_aircraft(dict(raw, dbFlags=4))),
          "PIA excluded")
    check(adsb.sensitive_reason(adsb.parse_aircraft(dict(raw, dbFlags=8))),
          "LADD excluded")
    check(adsb.sensitive_reason(adsb.parse_aircraft(dict(raw, squawk="7700"))),
          "emergency squawk excluded")
    check(adsb.sensitive_reason(
        adsb.parse_aircraft(dict(raw, emergency="general"))),
        "emergency state excluded")
    check(adsb.sensitive_reason(ac) is None, "clean airliner passes")
    print("test_parse_and_sanitize: done")


def _pt(minutes_ago, dist_km, alt, gs=140, low_conf=False):
    return {"ts": ts(minutes_ago), "distance_km": dist_km, "alt_baro": alt,
            "ground_speed": gs, "quality": "good",
            "low_confidence": low_conf}


def test_arrival_state_machine():
    st = flightwatch.assess_track
    check(st([_pt(0, 2.0, 35000)], RCKH) == "overflight",
          "single high pass over RCKH is an overflight, never an arrival")
    reclimb = [_pt(15, 30, 8000), _pt(10, 12, 3500), _pt(5, 3, 1200),
               _pt(0, 9, 5200)]
    check(st(reclimb, RCKH) == "overflight",
          "approach followed by re-climb is not an arrival")
    descending = [_pt(12, 40, 9000), _pt(6, 18, 4500), _pt(0, 5, 2200)]
    check(st(descending, RCKH) == "probable_arrival",
          "three descending closing points without ground = probable only")
    grounded = [_pt(8, 25, 6000), _pt(0, 1.5, "ground", gs=15)]
    check(st(grounded, RCKH) == "confirmed_arrival",
          "approach observation + in-fence ground state = confirmed")
    check(st([_pt(0, 1.5, "ground", gs=10)], RCKH) == "insufficient_data",
          "first-ever ground sighting alone could be a departure taxi")
    mlat = [_pt(12, 40, 9000, low_conf=True), _pt(6, 18, 4500, low_conf=True),
            _pt(0, 5, 2200, low_conf=True)]
    check(st(mlat, RCKH) not in ("probable_arrival", "confirmed_arrival"),
          "MLAT-only trajectory can never confirm an arrival")
    check(st([], RCKH) == "insufficient_data", "empty track is insufficient")
    print("test_arrival_state_machine: done")


def test_cross_check():
    primary = adsb.parse_aircraft(
        {"hex": "a1b2c3", "r": "N501DN", "t": "A359", "flight": "DAL123",
         "alt_baro": "ground", "lat": 22.577, "lon": 120.35,
         "seen_pos": 1.0, "seen": 2.0, "type": "adsb_icao"})
    twin = {"hex": "A1B2C3", "r": "N501DN", "t": "A359",
            "flight": "DAL123  ", "alt_baro": "ground",
            "lat": 22.58, "lon": 120.36, "seen_pos": 3.0, "seen": 4.0,
            "type": "adsb_icao"}
    check(flightwatch.cross_check(primary, [twin])
          == "confirmed_by_two_sources",
          "same hex + close position cross-confirms (callsign padding ok)")
    check(flightwatch.cross_check(primary, [dict(twin, r="N999XX")])
          == "conflicting_sources", "registration conflict blocks the event")
    check(flightwatch.cross_check(primary, [dict(twin, t="B744")])
          == "conflicting_sources", "type conflict blocks the event")
    check(flightwatch.cross_check(primary, [])
          == "secondary_unavailable", "no secondary match = unavailable")
    stale_twin = dict(twin, seen_pos=120.0)
    check(flightwatch.cross_check(primary, [stale_twin])
          == "confirmed_by_primary_only",
          "stale secondary data cannot fully confirm")
    print("test_cross_check: done")


def test_rarity_and_bootstrap():
    old_history = {"firstRunUtc": flightwatch.iso(NOW - timedelta(days=90)),
                   "arrivals": []}
    dal = adsb.parse_aircraft(
        {"hex": "a1b2c3", "r": "N501DN", "t": "A359", "flight": "DAL123",
         "lat": 22.58, "lon": 120.35, "seen_pos": 1, "type": "adsb_icao"})
    score, reasons, wl = flightwatch.rarity(
        dal, "DAL", RCKH, old_history, [], NOW)
    check(score >= flightwatch.SCORE_THRESHOLD,
          f"DAL+A359+RCKH scores rare ({score})")
    check(any("+35" in r for r in reasons) and any("+25" in r for r in reasons),
          "rarity reasons are explainable")

    cal = adsb.parse_aircraft(
        {"hex": "b1b2b3", "r": "B-18201", "t": "A321", "flight": "CAL581",
         "lat": 22.58, "lon": 120.35, "seen_pos": 1, "type": "adsb_icao"})
    score2, _, _ = flightwatch.rarity(cal, "CAL", RCKH, old_history, [], NOW)
    check(score2 < flightwatch.SCORE_THRESHOLD,
          f"normal operator+type never rare even with EMPTY history ({score2})")

    busy = {"firstRunUtc": old_history["firstRunUtc"], "arrivals": [
        {"airport_icao": "RCKH", "operator_icao": "DAL",
         "aircraft_type": "A359", "registration": "N501DN",
         "confirmedUtc": ts(60 * 24 * d)} for d in (3, 9)]}
    score3, _, _ = flightwatch.rarity(dal, "DAL", RCKH, busy, [], NOW)
    check(score3 < score, "repeat visits within 30 days score much lower")

    fresh = {"firstRunUtc": flightwatch.iso(NOW - timedelta(days=2)),
             "arrivals": []}
    check(flightwatch.in_bootstrap(fresh, NOW), "young history = bootstrap")
    check(not flightwatch.in_bootstrap(old_history, NOW),
          "90-day history leaves bootstrap")

    _, _, watchlisted = flightwatch.rarity(
        dal, "DAL", RCKH, old_history,
        [{"operator_icao": "DAL", "aircraft_type": "A359",
          "registration": None, "airport_icao": "RCKH",
          "minimum_score_override": 0, "enabled": True}], NOW)
    check(watchlisted, "watchlist match flagged")

    op, name = flightwatch.operator_from_callsign(
        "DAL123", {"DAL": {"airline_name_en": "Delta Air Lines"}})
    check(op == "DAL" and name == "Delta Air Lines", "callsign -> operator")
    op2, name2 = flightwatch.operator_from_callsign("XYZ987", {})
    check(op2 == "XYZ" and name2 is None,
          "unknown code keeps icao, NEVER invents an airline name")
    op3, _ = flightwatch.operator_from_callsign("N501DN", {})
    check(op3 is None, "registration-style callsign not parsed as airline")
    print("test_rarity_and_bootstrap: done")


def test_event_identity_and_config():
    a = flightwatch.event_id("A1B2C3", "RCKH", "2026-07-26")
    b = flightwatch.event_id("a1b2c3", "RCKH", "2026-07-26")
    c = flightwatch.event_id("a1b2c3", "RCKH", "2026-07-27")
    check(a == b, "event id stable across hex case (5-min rerun safe)")
    check(a != c, "a later-date arrival is a NEW event")

    airports = flightwatch.load_airports()
    icaos = {ap["icao"] for ap in airports}
    for need in ("RCTP", "RCSS", "RCKH", "RCMQ", "RCNN"):
        check(need in icaos, f"required airport {need} configured")
    try:
        flightwatch.validate_airports(
            [dict(RCKH), dict(RCKH)], {})
        check(False, "duplicate ICAO must fail validation")
    except flightwatch.ConfigError:
        check(True, "duplicate ICAO fails validation")
    try:
        flightwatch.validate_airports([dict(RCKH, lat=123.0)], {})
        check(False, "bad latitude must fail validation")
    except flightwatch.ConfigError:
        check(True, "latitude outside range fails validation")
    print("test_event_identity_and_config: done")


FLIGHT_EVENT = {
    "eventId": "fw-abc123def4567890",
    "queuedUtc": ts(90),
    "notBeforeUtc": ts(60),  # delay already passed
    "bootstrap": False,
    "crossCheck": "confirmed_by_two_sources",
    "airport": {"icao": "RCKH", "iata": "KHH",
                "name_zh": "高雄國際機場",
                "name_en": "Kaohsiung International Airport"},
    "aircraft": {"hex": "a1b2c3", "registration": "N501DN", "type": "A359",
                 "type_name": "Airbus A350-900", "callsign": "DAL123"},
    "operator": {"icao": "DAL", "name": "Delta Air Lines"},
    "arrival": {"status": "confirmed_arrival", "firstSeenUtc": ts(120),
                "confirmedUtc": (NOW - timedelta(minutes=95))
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "basis": "位於機場地理圍欄內且 alt_baro 為 ground",
                "observations": 5},
    "rarity": {"score": 90, "reasons": ["營運者 DAL 非 RCKH 常態業者 (+35)"],
               "watchlisted": True, "combo180": 0, "reg365": 0},
}


def test_source_assembly_privacy():
    text = flightnews.assemble_source(FLIGHT_EVENT)
    for needed in ("機場 ICAO：RCKH", "營運者 ICAO：DAL",
                   "航空器 ICAO 機型：A359", "抵達判定：confirmed_arrival",
                   "主要資料來源：Airplanes.live"):
        check(needed in text, f"SOURCE line present: {needed}")
    lowered = text.lower()
    for banned in ("lat", "lon", "緯度", "經度", "22.5", "120.3"):
        check(banned not in lowered, f"no live position in SOURCE ({banned})")
    boot = flightnews.assemble_source(dict(FLIGHT_EVENT, bootstrap=True))
    check("過去 180 天" not in boot and "統計說明" in boot,
          "bootstrap SOURCE carries no rarity statistics to quote")
    print("test_source_assembly_privacy: done")


class FakeProvider:
    def __init__(self, name, script):
        self.name = name
        self.label = f"{name}:fake"
        self.script = list(script)
        self.calls = 0

    def available(self):
        return True

    def draft(self, system_prompt, user_prompt, schema):
        self.calls += 1
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step


def _flight_draft(quote="機場 ICAO：RCKH", status="publish"):
    empty_entities = {k: [] for k in write.ENTITY_KEYS}
    return {
        "status": status, "decisionReason": "",
        "cat": "ops",
        "zh": {"title": "達美航空 A350-900 現身高雄機場之公開觀測紀錄",
               "summary": "公開 ADS-B 觀測資料顯示一架 A350-900 抵達高雄國際機場，"
                          "本站監測系統已確認其落地狀態，詳細背景仍待人工確認後發布。",
               "body": ["第一段。", "第二段。"]},
        "en": {"title": "Public ADS-B data shows Delta A350-900 arrival at "
                        "Kaohsiung",
               "summary": "Public ADS-B observation data indicates an Airbus "
                          "A350-900 arrived at Kaohsiung International "
                          "Airport. The observation was confirmed on the "
                          "ground by the site's monitoring system and "
                          "awaits human editorial review before any "
                          "publication of further detail.",
               "body": ["Para one.", "Para two."]},
        "flash": {"zh": "ADS-B 觀測：A350 抵達高雄", "en": "ADS-B: A350 at KHH",
                  "hot": False},
        "incident": None,
        "facts": [{"factId": "F1", "claim": "抵達機場為高雄國際機場",
                   "sourceQuote": quote}],
        "headlineSupportedBy": ["F1"], "summarySupportedBy": ["F1"],
        "entities": empty_entities, "eventStatus": "confirmed",
        "riskFlags": [], "requiresHumanReview": False,
    }


def _reset_data():
    import shutil
    data = Path(os.environ["AVWIRE_DATA_DIR"])
    if data.exists():
        shutil.rmtree(data)
    (data / "flightwatch").mkdir(parents=True)
    (data / "articles").mkdir()


def _run_write_with(providers_list):
    original = write.build_providers
    write.build_providers = lambda: providers_list
    try:
        write.main()
    finally:
        write.build_providers = original


def test_flight_events_into_review_queue():
    _reset_data()
    flightnews.save_queue([json.loads(json.dumps(FLIGHT_EVENT))])
    solo = FakeProvider("gemini", [_flight_draft(status="publish")])
    _run_write_with([solo])

    check(solo.calls == 1, f"one AI call for one event, got {solo.calls}")
    review = common.load_json(Path(os.environ["AVWIRE_DATA_DIR"])
                              / "review.json", [])
    check(len(review) == 1, "flight event landed in the review queue")
    entry = review[0]
    check(entry["draft"]["status"] == "manual_review"
          and entry["draft"]["requiresHumanReview"] is True,
          "publish output was FORCED down to manual_review")
    check("unconfirmed_or_developing" in entry["draft"]["riskFlags"],
          "risk flag enforced on flight events")
    check(entry["flight"]["eventId"] == FLIGHT_EVENT["eventId"]
          and entry["flight"]["crossCheck"] == "confirmed_by_two_sources",
          "flight metadata stored with the review entry")
    check(entry["group"]["items"][0]["url"] == "https://airplanes.live/"
          and entry["group"]["items"][1]["url"] == "https://www.adsb.lol/",
          "attribution links become the article's sources")
    check(flightnews.load_queue() == [], "queue emptied after queuing")
    # No articles were published (manual_review only).
    articles_dir = Path(os.environ["AVWIRE_DATA_DIR"]) / "articles"
    check(not list(articles_dir.glob("*.json")),
          "nothing auto-published for a rare-aircraft event")
    print("test_flight_events_into_review_queue: done")


def test_flight_no_candidates_no_ai():
    _reset_data()
    solo = FakeProvider("gemini", [_flight_draft()])
    _run_write_with([solo])
    check(solo.calls == 0, f"empty queue means ZERO AI calls, got {solo.calls}")
    print("test_flight_no_candidates_no_ai: done")


def test_flight_bad_quote_and_reject():
    _reset_data()
    flightnews.save_queue([json.loads(json.dumps(FLIGHT_EVENT))])
    solo = FakeProvider("gemini",
                        [_flight_draft(quote="this line is nowhere")])
    _run_write_with([solo])
    check(common.load_json(Path(os.environ["AVWIRE_DATA_DIR"])
                           / "review.json", []) == [],
          "unverifiable sourceQuote never reaches the review queue")
    check(len(flightnews.load_queue()) == 1,
          "event stays queued for the next hour after provider failure")

    _reset_data()
    flightnews.save_queue([json.loads(json.dumps(FLIGHT_EVENT))])
    solo = FakeProvider("gemini", [{"status": "reject",
                                    "decisionReason": "insufficient"}])
    _run_write_with([solo])
    check(flightnews.load_queue() == [] and solo.calls == 1,
          "model reject drops the event without provider shopping")

    _reset_data()
    future = json.loads(json.dumps(FLIGHT_EVENT))
    future["notBeforeUtc"] = flightwatch.iso(NOW + timedelta(hours=2))
    flightnews.save_queue([future])
    solo = FakeProvider("gemini", [_flight_draft()])
    _run_write_with([solo])
    check(solo.calls == 0 and len(flightnews.load_queue()) == 1,
          "publication delay holds the event without AI calls")
    print("test_flight_bad_quote_and_reject: done")


def main():
    tests = [
        test_parse_and_sanitize,
        test_arrival_state_machine,
        test_cross_check,
        test_rarity_and_bootstrap,
        test_event_identity_and_config,
        test_source_assembly_privacy,
        test_flight_events_into_review_queue,
        test_flight_no_candidates_no_ai,
        test_flight_bad_quote_and_reject,
    ]
    import traceback
    crashed = False
    for test in tests:
        try:
            test()
        except Exception:
            crashed = True
            print(f"ERROR in {test.__name__}:")
            traceback.print_exc()
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{_pass} checks passed, {_fail} failed")
    if _fail or crashed:
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
