"""Cargo-led articles must never retain a generic passenger-aircraft photo."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import image_fallbacks
import images
from image_policy import article_is_cargo_story


def article(title, summary="", airline="China Airlines"):
    return {
        "publishedUtc": "2026-09-07T13:10Z",
        "zh": {"title": title, "summary": summary},
        "en": {"title": title, "summary": summary},
        "entities": {"airlines": [airline]},
    }


def test_cargo_signal_is_specific_to_headline_context():
    assert article_is_cargo_story(
        article("華航9/16起再漲貨運燃油附加費"))
    assert article_is_cargo_story(article("China Airlines freighter operations"))
    assert not article_is_cargo_story(article("華航擴大客運航網"))


def test_generic_passenger_photo_is_stale_for_cargo_story():
    story = article("華航9/16起再漲貨運燃油附加費")
    passenger = {
        "provider": "Wikimedia Commons", "kind": "file_photo",
        "matched": "topic:china-airlines",
        "subject": "China Airlines Boeing 737-800", "photoYear": 2026,
        "url": "https://upload.wikimedia.org/china-737.jpg",
    }
    cargo = {
        **passenger,
        "matched": "topic:china-airlines-cargo",
        "subject": "China Airlines Cargo Boeing 777F",
        "url": "https://upload.wikimedia.org/china-cargo-777f.jpg",
    }
    assert not images.existing_image_matches(story, passenger)
    assert images.existing_image_matches(story, cargo)


def test_resolver_uses_cargo_query_before_generic_airline():
    story = article("華航9/16起再漲貨運燃油附加費")
    calls = []

    def fake_lookup(query, tokens, **kwargs):
        calls.append((query, tokens, kwargs))
        return {"matched": query}

    originals = {
        name: getattr(images, name)
        for name in ("lookup_official_source_photo", "find_registration",
                     "find_aircraft_type", "find_airport", "lookup_commons")
    }
    images.lookup_official_source_photo = lambda _: None
    images.find_registration = lambda _: None
    images.find_aircraft_type = lambda _: None
    images.find_airport = lambda _: None
    images.lookup_commons = fake_lookup
    try:
        result = images.resolve_image(story)
    finally:
        for name, value in originals.items():
            setattr(images, name, value)

    assert result["matched"] == "China Airlines Cargo aircraft"
    assert calls[0][1] == ["China Airlines", "Cargo"]
    assert calls[0][2]["require_all"] is True


def test_vetted_fallback_is_a_cargo_aircraft():
    fallback = image_fallbacks.topic_image(
        article("華航9/16起再漲貨運燃油附加費"))
    assert fallback["matched"] == "topic:china-airlines-cargo"
    assert fallback["subject"] == "China Airlines Cargo Boeing 777F"
    assert "737-800" not in fallback["subject"]


def main() -> int:
    checks = (
        ("cargo signal is specific to headline context",
         test_cargo_signal_is_specific_to_headline_context),
        ("generic passenger photo is stale for cargo story",
         test_generic_passenger_photo_is_stale_for_cargo_story),
        ("resolver uses cargo query before generic airline",
         test_resolver_uses_cargo_query_before_generic_airline),
        ("vetted fallback is a cargo aircraft",
         test_vetted_fallback_is_a_cargo_aircraft),
    )
    failed = 0
    for name, check in checks:
        try:
            check()
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failed += 1
        else:
            print(f"PASS {name}")
    print(f"{len(checks)} checks passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
