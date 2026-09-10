"""Build a filtered, short-lived ADS-B snapshot for the public radar page."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import adsb

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "site" / "assets" / "radar.json"
PUBLIC_FIELDS = (
    "hex", "flight", "t", "type", "alt_baro", "gs", "track",
    "baro_rate", "geom_rate", "lat", "lon", "seen_pos", "seen",
)


def public_row(raw: dict) -> dict | None:
    """Return the minimum public row, or None when it must fail closed."""
    parsed = adsb.parse_aircraft(raw)
    if (not parsed or parsed["non_icao"] or adsb.sensitive_reason(parsed)
            or not adsb.position_ok(parsed)):
        return None
    row = {key: raw[key] for key in PUBLIC_FIELDS if key in raw}
    if row.get("track") is None and raw.get("calc_track") is not None:
        row["track"] = raw["calc_track"]
    return row


def snapshot_payload(rows: list, now_ms: int | None = None) -> dict:
    public = [row for raw in rows if (row := public_row(raw)) is not None]
    return {
        "now": now_ms if now_ms is not None else int(time.time() * 1000),
        "source": "ADSB.lol",
        "source_total": len(rows),
        "filtered": len(rows) - len(public),
        "ac": public,
    }


def write_snapshot(output: Path) -> dict:
    rows = adsb.adsb_lol_point(23.7, 120.9, 250)
    if not rows:
        raise adsb.ProviderDown("ADSB.lol returned no aircraft")
    payload = snapshot_payload(rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8", newline="\n")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    payload = write_snapshot(args.output)
    print(
        f"radar snapshot: {len(payload['ac'])} public / "
        f"{payload['source_total']} source rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
