"""ADS-B provider layer + field sanitization for the rare-aircraft monitor.

Two public community data sources behind one thin interface:

    airplanes_live_point()  PRIMARY wide-area scan
                            https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}
    adsb_lol_point() /
    adsb_lol_icao()         SECONDARY, candidate confirmation only
                            https://api.adsb.lol/v2/...

Operating rules baked in (both services are volunteer-run, no SLA):
- radius is clamped to 250 nm; ONE wide-area request per scheduler run
- the secondary source is queried only for already-suspicious candidates
- HTTP 429 aborts the run's provider (respect Retry-After; no hammering)
- 5xx / DNS / TLS / timeout: at most one retry, then give up for this run
- a provider failure raises ProviderDown - callers must treat it as
  "unknown sky", NEVER as "no aircraft"
- explicit User-Agent; optional API keys via env for the future
  (AIRPLANES_LIVE_API_KEY / ADSBLOL_API_KEY) - never sent to the frontend

Attribution: Airplanes.live community feed (non-commercial use);
ADSB.lol open data (ODbL). Keep both names in any public display.
"""
from __future__ import annotations

import os
import time

import requests

from common import USER_AGENT

MAX_RADIUS_NM = 250


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


TIMEOUT = _int_env("FLIGHT_TRACKING_REQUEST_TIMEOUT_SECONDS", 20)
RETRIES = _int_env("FLIGHT_TRACKING_MAX_PROVIDER_RETRIES", 1)


class ProviderDown(Exception):
    """This provider is unusable for the rest of the run."""


def _enabled(name: str, default: str = "true") -> bool:
    return (os.environ.get(name) or default).strip().lower() == "true"


def _get_json(url: str, key_env: str):
    headers = {"User-Agent": USER_AGENT}
    api_key = os.environ.get(key_env)
    if api_key:  # optional, for future authenticated tiers
        headers["Authorization"] = f"Bearer {api_key}"
    attempts = 1 + max(RETRIES, 0)
    last = "unknown error"
    for attempt in range(attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last = type(exc).__name__
            if attempt + 1 < attempts:
                time.sleep(2)
                continue
            raise ProviderDown(last) from exc
        if resp.status_code == 429:
            # Respect the service: stop for this run, never tight-retry.
            raise ProviderDown(
                f"HTTP 429 (Retry-After {resp.headers.get('Retry-After')})")
        if resp.status_code >= 500:
            last = f"HTTP {resp.status_code}"
            if attempt + 1 < attempts:
                time.sleep(2)
                continue
            raise ProviderDown(last)
        if resp.status_code >= 400:
            raise ProviderDown(f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderDown("invalid JSON body") from exc
    raise ProviderDown(last)


def airplanes_live_point(lat: float, lon: float, radius_nm: float) -> list:
    if not _enabled("AIRPLANES_LIVE_ENABLED"):
        raise ProviderDown("disabled by AIRPLANES_LIVE_ENABLED")
    radius = min(float(radius_nm), MAX_RADIUS_NM)
    data = _get_json(
        f"https://api.airplanes.live/v2/point/{lat:.4f}/{lon:.4f}/{radius:g}",
        "AIRPLANES_LIVE_API_KEY")
    aircraft = data.get("ac") if isinstance(data, dict) else None
    return aircraft if isinstance(aircraft, list) else []


def adsb_lol_point(lat: float, lon: float, radius_nm: float) -> list:
    if not _enabled("ADSBLOL_ENABLED"):
        raise ProviderDown("disabled by ADSBLOL_ENABLED")
    radius = min(float(radius_nm), MAX_RADIUS_NM)
    data = _get_json(
        f"https://api.adsb.lol/v2/point/{lat:.4f}/{lon:.4f}/{radius:g}",
        "ADSBLOL_API_KEY")
    aircraft = data.get("ac") if isinstance(data, dict) else None
    return aircraft if isinstance(aircraft, list) else []


def adsb_lol_icao(icao_hex: str) -> list:
    if not _enabled("ADSBLOL_ENABLED"):
        raise ProviderDown("disabled by ADSBLOL_ENABLED")
    data = _get_json(f"https://api.adsb.lol/v2/icao/{icao_hex.lower()}",
                     "ADSBLOL_API_KEY")
    aircraft = data.get("ac") if isinstance(data, dict) else None
    return aircraft if isinstance(aircraft, list) else []


# --------------------------------------------------------------------------
# field parsing / sanitization (v2 aircraft dicts, shared by both sources)

# dbFlags bits per the readsb/airplanes.live convention
DB_MILITARY = 1
DB_INTERESTING = 2
DB_PIA = 4
DB_LADD = 8

EMERGENCY_SQUAWKS = ("7500", "7600", "7700")

# `type` field = POSITION SOURCE (never the airframe type, which is `t`)
LOW_CONFIDENCE_SOURCES = ("tisb", "other", "mode_s", "mlat")
GROUND_VEHICLE_SOURCES = ("adsb_icao_nt",)

MAX_SEEN_POS_S = 30.0   # older positions are not evidence for THIS pass
MAX_SEEN_S = 60.0       # aircraft not heard for this long are stale


def _float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_aircraft(raw: dict):
    """Normalize one v2 aircraft entry. Returns None for unusable rows.

    Field notes (per Airplanes.live/ADSB.lol v2):
      t         airframe ICAO type code   <-- the AIRCRAFT TYPE
      type      position source (adsb_icao/mlat/tisb/...) - NOT the type
      alt_baro  int feet OR the literal string "ground"
      flight    callsign, often right-padded with spaces
      ownOp     database-supplied registered owner/operator label
      hex       ICAO 24-bit address; "~" prefix = non-ICAO (TIS-B et al.)
    """
    if not isinstance(raw, dict):
        return None
    icao_hex = str(raw.get("hex") or "").strip().lower()
    if not icao_hex:
        return None
    alt_baro = raw.get("alt_baro")
    if isinstance(alt_baro, str):
        alt_baro = alt_baro.strip().lower()
        if alt_baro != "ground":
            alt_baro = _float(alt_baro)  # tolerate numeric strings
    source_type = str(raw.get("type") or "").strip().lower()
    return {
        "hex": icao_hex,
        "non_icao": icao_hex.startswith("~"),
        "registration": str(raw.get("r") or "").strip() or None,
        "aircraft_type": str(raw.get("t") or "").strip().upper() or None,
        "callsign": str(raw.get("flight") or "").strip() or None,
        "operator_name": str(raw.get("ownOp") or "").strip()[:160] or None,
        "alt_baro": alt_baro,                  # feet, "ground", or None
        "alt_geom": _float(raw.get("alt_geom")),
        "ground_speed": _float(raw.get("gs")),
        "vertical_rate": _float(raw.get("baro_rate")
                                if raw.get("baro_rate") is not None
                                else raw.get("geom_rate")),
        "lat": _float(raw.get("lat")),
        "lon": _float(raw.get("lon")),
        "seen": _float(raw.get("seen")),
        "seen_pos": _float(raw.get("seen_pos")),
        "source_type": source_type,
        "db_flags": int(raw.get("dbFlags") or 0),
        "emergency": str(raw.get("emergency") or "").strip().lower() or None,
        "squawk": str(raw.get("squawk") or "").strip() or None,
    }


def sensitive_reason(ac: dict):
    """Non-empty reason string when this aircraft must NEVER enter the
    public news flow (spec section 7). The reason is log-safe (no position).
    """
    if ac["db_flags"] & DB_MILITARY:
        return "military (dbFlags)"
    if ac["db_flags"] & DB_PIA:
        return "PIA address"
    if ac["db_flags"] & DB_LADD:
        return "LADD limited"
    if ac.get("squawk") in EMERGENCY_SQUAWKS:
        return f"emergency squawk {ac['squawk']}"
    if ac.get("emergency") not in (None, "none"):
        return f"emergency state {ac['emergency']}"
    return None


def position_ok(ac: dict) -> bool:
    """True when this row carries a position usable as arrival evidence."""
    if ac.get("lat") is None or ac.get("lon") is None:
        return False
    if ac.get("source_type") in GROUND_VEHICLE_SOURCES:
        return False
    seen_pos = ac.get("seen_pos")
    if seen_pos is None or seen_pos > MAX_SEEN_POS_S:
        return False
    seen = ac.get("seen")
    if seen is not None and seen > MAX_SEEN_S:
        return False
    return True


def low_confidence(ac: dict) -> bool:
    return ac.get("source_type") in LOW_CONFIDENCE_SOURCES
