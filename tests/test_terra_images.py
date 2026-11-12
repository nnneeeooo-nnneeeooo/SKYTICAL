"""Terra image search accepts only independently licensed, relevant files."""
import json
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import build
import terra_images as terra
from image_selection import rejection_reason


ARTICLE = json.loads((Path(__file__).resolve().parents[1] /
                      "data/articles/2026-11-12T14.json").read_text(encoding="utf-8"))["articles"][0]
AIRCRAFT_IMAGE = {
    "url": "https://upload.wikimedia.org/wikipedia/commons/EVA_Air_Boeing_787-10.jpg",
    "link": "https://commons.wikimedia.org/wiki/File:EVA_Air_Boeing_787-10.jpg",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "credit": "Photographer", "license": "CC BY 4.0",
    "subject": "EVA Air Boeing 787-10", "description": "EVA Air Boeing 787-10",
    "photoYear": 2026,
}


def _commons(license_name, artist="Photographer"):
    return {"query": {"pages": {"1": {
        "index": 1, "title": "File:Pingtung tourism landscape.jpg",
        "imageinfo": [{
            "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/pingtung.jpg",
            "descriptionshorturl": "https://commons.wikimedia.org/wiki/File:Pingtung_tourism_landscape.jpg",
            "extmetadata": {"LicenseShortName": {"value": license_name},
                            "Artist": {"value": artist},
                            "DateTimeOriginal": {"value": "2026-01-01"}},
        }],
    }}}}


def test_pingtung_aircraft_is_rejected():
    assert rejection_reason(ARTICLE, AIRCRAFT_IMAGE) == "tourism-event-aircraft-stock"


def test_terra_selection_requires_commons_license_and_visual_choice(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = _commons("CC BY 4.0")
    monkeypatch.setattr(terra.requests, "get", Mock(return_value=response))
    calls = iter([{"queries": ["Pingtung tourism"]}, {"index": 0}])
    monkeypatch.setattr(terra, "_ask", lambda *args, **kwargs: next(calls))
    result = terra.find_image(ARTICLE, {})
    assert result["selectionModel"] == "gpt-6.1-terra"
    assert result["credit"] == "Photographer"
    assert result["license"] == "CC BY 4.0"
    assert build.normalize_image(result)["selectionModel"] == "gpt-6.1-terra"
    assert build.normalize_image(AIRCRAFT_IMAGE)["selectionModel"] is None


def test_noncommercial_and_uncredited_photos_fail_closed(monkeypatch):
    response = Mock(status_code=200)
    monkeypatch.setattr(terra.requests, "get", Mock(return_value=response))
    for license_name, artist in (("CC BY-NC 4.0", "Photographer"),
                                 ("CC BY 4.0", "")):
        response.json.return_value = _commons(license_name, artist)
        assert terra._candidates(ARTICLE, ["Pingtung tourism"], {}) == []


def test_terra_can_decline_image(monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = _commons("CC0 1.0")
    monkeypatch.setattr(terra.requests, "get", Mock(return_value=response))
    calls = iter([{"queries": ["Pingtung tourism"]}, {"index": None}])
    monkeypatch.setattr(terra, "_ask", lambda *args, **kwargs: next(calls))
    assert terra.find_image(ARTICLE, {}) is None
