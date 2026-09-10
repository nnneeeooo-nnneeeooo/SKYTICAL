"""Offline safety and output-contract checks for radar snapshots."""
from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

try:
    import requests  # noqa: F401
except ModuleNotFoundError:  # keep this isolated unit test dependency-free
    requests_stub = types.ModuleType("requests")
    requests_stub.RequestException = Exception
    requests_stub.get = None
    sys.modules["requests"] = requests_stub

import adsb  # noqa: E402
import radar_snapshot  # noqa: E402


def row(**overrides):
    base = {
        "hex": "780aa1", "type": "adsb_icao", "flight": "CAL123 ",
        "t": "A321", "alt_baro": 28000, "gs": 450, "calc_track": 42,
        "lat": 24.1, "lon": 121.2, "seen_pos": 2, "seen": 3,
        "dbFlags": 0, "squawk": "2000", "emergency": "none",
    }
    base.update(overrides)
    return base


def main() -> None:
    rows = [
        row(),
        row(hex="abc001", dbFlags=1),
        row(hex="abc002", dbFlags=4),
        row(hex="abc003", dbFlags=8),
        row(hex="abc004", squawk="7700"),
        row(hex="abc005", seen_pos=31),
        row(hex="~abc006"),
    ]
    payload = radar_snapshot.snapshot_payload(rows, now_ms=1234567890000)
    assert payload["source"] == "ADSB.lol"
    assert payload["source_total"] == 7
    assert payload["filtered"] == 6
    assert payload["now"] == 1234567890000
    assert payload["ac"] == [{
        "hex": "780aa1", "flight": "CAL123 ", "t": "A321",
        "type": "adsb_icao", "alt_baro": 28000, "gs": 450,
        "track": 42, "lat": 24.1, "lon": 121.2,
        "seen_pos": 2, "seen": 3,
    }]
    serialized = json.dumps(payload)
    assert "dbFlags" not in serialized
    assert "squawk" not in serialized
    assert "emergency" not in serialized

    original = adsb.adsb_lol_point
    try:
        adsb.adsb_lol_point = lambda *_: [row()]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "assets" / "radar.json"
            written = radar_snapshot.write_snapshot(output)
            assert json.loads(output.read_text(encoding="utf-8")) == written
    finally:
        adsb.adsb_lol_point = original
    print("test_radar_snapshot: OK")


if __name__ == "__main__":
    main()
