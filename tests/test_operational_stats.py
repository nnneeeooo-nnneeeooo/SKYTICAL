"""Regression checks for the homepage operational-statistics contract."""

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import build, fetch  # noqa: E402


class _Response:
    def json(self):
        return {
            "total_flights": 99999,
            "total_delays_worldwide": 4201,
            "total_cancellations_worldwide": 318,
        }


def main() -> None:
    original_request = fetch._request
    original_key = os.environ.get("AEROAPI_KEY")
    os.environ["AEROAPI_KEY"] = "test-key"
    fetch._request = lambda session, url, headers: _Response()
    try:
        stats = fetch._fetch_flightaware(
            object(), {"endpoint": "https://example.test/aeroapi"})
    finally:
        fetch._request = original_request
        if original_key is None:
            os.environ.pop("AEROAPI_KEY", None)
        else:
            os.environ["AEROAPI_KEY"] = original_key

    assert stats == {
        "delaysWorldwide": 4201,
        "cancellationsWorldwide": 318,
    }

    available = build.stats_views({
        "seriousThisWeek": 7,
        "flightAwareStatus": "ok",
        **stats,
    }, "zh")
    assert available["tiles"]["delay"] == "4,201"
    assert available["tiles"]["cancellations"] == "318"
    assert "FlightAware AeroAPI" in available["note"]

    unconfigured = build.stats_views({
        "seriousThisWeek": 7,
        "flightAwareStatus": "unconfigured",
    }, "zh")
    assert unconfigured["tiles"]["delay"] == "來源未設定"
    assert unconfigured["tiles"]["cancellations"] == "來源未設定"
    assert "尚未設定" in unconfigured["note"]

    print("test_operational_stats: OK")


if __name__ == "__main__":
    main()
