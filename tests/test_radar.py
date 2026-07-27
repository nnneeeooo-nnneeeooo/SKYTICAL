"""Offline build regression checks for the public Taiwan flight-radar page."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    assert build.main() == 0

    zh = (ROOT / "site" / "radar" / "index.html").read_text(encoding="utf-8")
    en = (ROOT / "site" / "en" / "radar" / "index.html").read_text(
        encoding="utf-8")
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "radar.js").read_text(encoding="utf-8")

    for page in (zh, en):
        assert 'id="radar-map"' in page
        assert "https://api.airplanes.live/v2/point/23.7000/120.9000/250" in page
        assert "https://tile.openstreetmap.org" not in page  # lives in JS
        assert "leaflet@1.9.4" in page
        assert "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" in page
        assert "API_KEY" not in page
    assert "台灣民航雷達" in zh
    assert "Taiwan civil flight radar" in en
    assert 'href="/avwire/radar/"' in home

    assert "flags & (1 | 4 | 8)" in js
    assert '["7500", "7600", "7700"]' in js
    assert "seenPos > 30" in js
    assert "refreshMs" in js and "300000" in js
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in js
    assert "textContent" in js
    print("test_radar: OK")


if __name__ == "__main__":
    main()
