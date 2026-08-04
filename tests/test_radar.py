"""Offline build regression checks for the public Taiwan flight-radar page."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    assert build.writer_model(
        "nvidia:nvidia/nemotron-3-super-120b-a12b"
    ) == "Nemotron 3 Super"
    assert build.writer_model(
        "gemini:gemini-3.6-flash"
    ) == "Gemini 3.6 Flash"
    assert build.writer_model(
        "anthropic:claude-opus-5"
    ) == "Claude Opus 5"
    assert build.writer_model(
        "openai:gpt-5.6-sol"
    ) == "GPT-5.6 Sol"
    assert build.writer_model("unknown:model") is None

    assert build.main() == 0

    zh = (ROOT / "site" / "radar" / "index.html").read_text(encoding="utf-8")
    en = (ROOT / "site" / "en" / "radar" / "index.html").read_text(
        encoding="utf-8")
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "radar.js").read_text(encoding="utf-8")
    zh_articles = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "site" / "news").glob("*/index.html")
    ]
    en_articles = [
        path.read_text(encoding="utf-8")
        for path in (ROOT / "site" / "en" / "news").glob("*/index.html")
    ]

    for page in (zh, en):
        assert 'id="radar-map"' in page
        assert "https://api.airplanes.live/v2/point/23.7000/120.9000/250" in page
        assert "https://api.adsbdb.com/v0/callsign" in page
        assert 'data-default-callsign-mode="iata"' in page
        assert 'id="radar-callsign-icao"' in page
        assert 'id="radar-callsign-iata"' in page
        assert page.index('id="radar-callsign-iata"') < page.index(
            'id="radar-callsign-icao"')
        code_match = re.search(
            r'<script id="radar-airline-codes" type="application/json">'
            r'(.*?)</script>', page, re.DOTALL)
        assert code_match
        airline_codes = json.loads(code_match.group(1))
        assert {
            code: airline_codes[code]
            for code in ("CAL", "EVA", "SJX", "TTW", "MDA", "UIA", "DAC")
        } == {
            "CAL": "CI", "EVA": "BR", "SJX": "JX", "TTW": "IT",
            "MDA": "AE", "UIA": "B7", "DAC": "DA",
        }
        assert (
            'id="radar-callsign-icao" class="seg-btn" type="button"\n'
            '                data-callsign-mode="icao" aria-pressed="false"'
        ) in page
        assert (
            'id="radar-callsign-iata" class="seg-btn active" type="button"\n'
            '                data-callsign-mode="iata" aria-pressed="true"'
        ) in page
        assert "ADSBdb" in page
        assert "https://tile.openstreetmap.org" not in page  # lives in JS
        assert "leaflet@1.9.4" in page
        assert "sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" in page
        assert "API_KEY" not in page
    assert "代碼顯示" in zh
    assert "航班呼號" not in zh
    assert "Code format" in en
    assert "Callsign format" not in en
    assert "台灣民航雷達" in zh
    assert "Taiwan civil flight radar" in en
    assert 'href="/avwire/radar/"' in home

    assert "flags & (1 | 4 | 8)" in js
    assert '["7500", "7600", "7700"]' in js
    assert "seenPos > 30" in js
    assert "refreshMs" in js and "300000" in js
    assert "callsign_iata" in js
    assert 'const airlineIataCodes = parseJson("radar-airline-codes", {})' in js
    assert "row.callsign.startsWith(row.operator)" in js
    assert "row.callsign.slice(row.operator.length)" in js
    assert 'root.dataset.defaultCallsignMode === "icao" ? "icao" : "iata"' in js
    assert '["icao", "iata"].includes(savedCallsignMode)' in js
    assert "flightroute.origin" in js
    assert "flightroute.destination" in js
    assert "routeConcurrency = 4" in js
    assert "routeCacheKey" in js
    assert "https://tile.openstreetmap.org/{z}/{x}/{y}.png" in js
    assert "textContent" in js

    assert any(
        "本文由自動化系統彙整生成，內容以原始來源為準 • "
        "Nemotron 3 Super" in page
        for page in zh_articles
    )
    assert any(
        "本文由自動化系統彙整生成，內容以原始來源為準 • "
        "Nemotron 3 Ultra" in page
        for page in zh_articles
    )
    assert any(
        "This article was compiled automatically; the original sources "
        "prevail • Nemotron 3 Super" in page
        for page in en_articles
    )
    assert not any("為準。 • " in page for page in zh_articles)
    assert all("AI 撰稿模型" not in page for page in zh_articles)
    assert all("Drafted by" not in page for page in en_articles)
    assert all("model-mark" not in page for page in zh_articles + en_articles)
    print("test_radar: OK")


if __name__ == "__main__":
    main()
