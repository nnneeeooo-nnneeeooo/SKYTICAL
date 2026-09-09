"""End-to-end evidence, source-order, cache and diversity regressions, offline."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import images
import image_selection as policy
import image_fallbacks
from common import now_utc


def article(title, **extra):
    return {"id": "case", "publishedUtc": now_utc().isoformat(),
            "en": {"title": title}, "zh": {}, "sources": [], **extra}


def photo(filename, **extra):
    return {"url": "https://upload.wikimedia.org/wikipedia/commons/1/11/"+filename+".jpg",
            "provider": "Wikimedia Commons", "kind": "file_photo",
            "description": filename.replace("_", " "), "photoYear": now_utc().year,
            "license": "CC BY 4.0", "subject": filename, **extra}


class ImageSelectionTests(unittest.TestCase):
    def test_medical_logistics_cannot_use_consumer_quadcopter(self):
        im = photo("Quadcopter_Drone_in_flight", matched="topic:drone")
        for title in ("JEDSY medical logistics drone partnership",
                      "新纖引進醫藥物流無人機", "無人機醫療運輸", "Drone cargo services"):
            self.assertEqual(policy.rejection_reason(article(title), im), "generic-drone-mismatch")
        self.assertIsNone(policy.rejection_reason(article("Civil drone market growth"), im))

    def test_search_query_cannot_attest_airline(self):
        im = photo("Air_Canada_A350-900", matched="STARLUX Airlines A350-900",
                   subject="STARLUX Airlines A350-900")
        self.assertEqual(policy.rejection_reason(article("STARLUX Airlines A350-900 delivery"), im), "airline-mismatch")

    def test_exact_variant_and_no_aircraft_model_drift(self):
        cases = [("Airbus A350-1000", "Airbus_A350-900", False),
                 ("Airbus A350-900", "Airbus_A350-941", True),
                 ("Airbus A350", "Airbus_A350-1000", True),
                 ("Gripen F", "Saab_Gripen_NG", False),
                 ("Boeing 737 MAX 7", "Boeing_737_MAX_8", False),
                 ("F-16V", "USAF_F-16", False)]
        for model, filename, valid in cases:
            with self.subTest(model=model):
                self.assertEqual(policy.model_matches(model, filename.replace("_", " ")), valid)

    def test_headline_model_wins_over_background(self):
        a = article("Saab Gripen F first flight", entities={"aircraft_models": ["Airbus A320", "Gripen F"]})
        a["en"]["body"] = ["Airbus A320 is a background comparison."]
        self.assertEqual(images.find_aircraft_type(a), "Gripen F")

    def test_background_registration_is_not_primary(self):
        a = article("Delta Air Lines announces earnings")
        a["en"]["body"] = ["Earnings increased.", "A historical flight used N512DN."]
        self.assertIsNone(images.find_registration(a))

    def test_country_is_not_airline(self):
        self.assertIsNone(images.find_airline(article("美國公布無人機新規則")))

    def test_manufacturer_story_does_not_inherit_customer(self):
        a = article("Boeing 737 MAX 7 receives certification", entities={"airlines": ["Southwest Airlines"]})
        a["en"]["summary"] = "Southwest Airlines has ordered it."
        self.assertIsNone(images.find_airline(a))

    def test_cargo_conversion_cannot_use_passenger_jet(self):
        a = article("IAI Airbus A330 freighter conversion first flight")
        self.assertEqual(policy.rejection_reason(a, photo("Swiss_Airbus_A330-300")), "cargo-role-unverified")

    def test_delivery_is_not_livery(self):
        self.assertIsNone(policy.rejection_reason(article("Airbus A350 delivery"), photo("Airbus_A350-900")))

    def test_special_livery_requires_livery_evidence(self):
        a = article("STARLUX Airlines Sorayama livery A350-1000")
        self.assertIsNotNone(policy.rejection_reason(a, photo("STARLUX_Airlines_A350-900")))

    def test_military_operator_is_required(self):
        a = article("Turkish F-16 fighters scramble", entities={"aircraft_models": ["F-16"]})
        self.assertEqual(policy.rejection_reason(a, photo("USAF_F-16")), "military-operator-unverified")
        self.assertIsNone(policy.rejection_reason(a, photo("Turkish_F-16")))

    def test_museum_fragment_cannot_illustrate_accident(self):
        a = article("Greek F-4 Phantom crashes", entities={"aircraft_models": ["F-4 Phantom"]})
        self.assertEqual(policy.rejection_reason(a, photo("Eesti_Lennundusmuuseum_F-4_kabiin")), "non-documentary-stock")

    def test_iata_code_sign_is_not_iata_organization(self):
        a = article("IATA publishes new manuals")
        self.assertEqual(policy.rejection_reason(a, photo("IATA_code_Soetta_Airport")), "organization-subject-unverified")

    def test_generic_drone_not_military_or_named_hardware(self):
        for title in ("Taiwan defense drone procurement", "LUNA NG drone certification"):
            a = article(title, entities={"aircraft_models": ["LUNA NG"]})
            self.assertIsNone(image_fallbacks.topic_image(a, allow_airport_lookup=False))
        self.assertIsNotNone(image_fallbacks.topic_image(article("Drone import tariffs")))

    def test_topic_rule_does_not_override_model(self):
        a = article("China Airlines A350-1000 delivery")
        self.assertIsNone(image_fallbacks.topic_image(a, allow_airport_lookup=False))

    def test_captioned_rss_wrong_carrier_is_rejected(self):
        a = article("Alaska Airlines sued", entities={"airlines": ["Alaska Airlines"]}, sources=[{"url": "https://publisher.test/story"}])
        url = "https://cdn.test/photo.jpg"
        cache = {url: {"link": a["sources"][0]["url"], "subject": "Hawaiian Airlines jet",
                       "captionSource": "source-image-metadata"}}
        self.assertEqual(policy.rejection_reason(a, url, cache), "airline-mismatch")

    def test_caption_cache_must_bind_exact_source(self):
        a = article("Delta Air Lines news", sources=[{"url": "https://publisher.test/story"}])
        url = "https://cdn.test/photo.jpg"
        cache = {url: {"link": "https://publisher.test/other", "subject": "Delta Air Lines aircraft",
                       "captionSource": "source-image-metadata"}}
        self.assertIsNone(policy.prepare_image(a, url, cache))

    def test_unbound_event_does_not_bypass_gate(self):
        im = {"url": "https://cdn.test/photo.jpg", "kind": "event_photo",
              "provider": "中央社 CNA", "sourceCaption": "華航活動"}
        self.assertEqual(policy.rejection_reason(article("華航舉辦活動"), im), "unbound-event-photo")

    def test_explicit_manual_selection_preserved(self):
        a = article("Editorial choice", writer="manual:editor")
        self.assertIsNone(policy.rejection_reason(a, "https://cdn.test/manual.jpg"))

    def test_certification_company_not_background_aircraft(self):
        a = article("JCB Aero receives Boeing maintenance certification",
                    entities={"organizations": ["JCB Aero", "Boeing"], "aircraft_models": ["Boeing 737-700"]})
        a["en"]["summary"] = "The facility can service Boeing 737-700 aircraft."
        self.assertEqual(policy.rejection_reason(a, photo("Boeing_737-700")), "headline-organization-unverified")

    def test_airframe_registration_does_not_attest_new_operator(self):
        a = article("Delta Air Lines A350 N512DN arrives")
        im = {"url": "https://cdn.planespotters.net/example.jpg", "provider": "Planespotters.net",
              "kind": "airframe_photo", "matched": "N512DN", "link": "https://www.planespotters.net/photo/1"}
        self.assertEqual(policy.rejection_reason(a, im), "airframe-operator-unverified")

    def test_url_identity_handles_resize_but_not_attachment_id(self):
        original = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Test.jpg"
        thumb = "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Test.jpg/1280px-Test.jpg?utm_source=x"
        self.assertEqual(policy.image_key(original), policy.image_key(thumb))
        self.assertNotEqual(policy.image_key("https://caa.gov.tw/FileAtt.ashx?id=1"),
                            policy.image_key("https://caa.gov.tw/FileAtt.ashx?id=2"))

    def test_more_diverse_valid_candidate_beats_first_result(self):
        a = article("Delta Air Lines Airbus A350")
        first, second = photo("Delta_Air_Lines_Airbus_A350_1"), photo("Delta_Air_Lines_Airbus_A350_2")
        payload = {"query": {"pages": {str(i): {"index": i, "title": "File:"+p["description"]+".jpg",
                   "imageinfo": [{"thumburl": p["url"], "extmetadata": {
                       "LicenseShortName": {"value": "CC BY 4.0"}}}]} for i, p in enumerate([first, second])}}}
        class Response:
            status_code = 200
            def json(self): return payload
        with patch.object(images.requests, "get", return_value=Response()):
            found = images.lookup_commons("Delta Air Lines Airbus A350", ["Delta Air Lines", "A350"],
                                          article=a, require_all=True, usage={policy.image_key(first): 1})
        self.assertEqual(found["url"], second["url"])

    def test_failed_provider_continues_to_next(self):
        a = article("Delta Air Lines Airbus A350")
        im = photo("Delta_Air_Lines_Airbus_A350")
        with patch.object(images, "lookup_official_source_photo", side_effect=OSError("offline")), \
                patch.object(images, "lookup_commons", return_value=im):
            self.assertEqual(images.resolve_image(a), im)

    def test_repair_removes_cache_even_with_zero_lookup_budget_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            aa = [article("Delta Air Lines Airbus A350", id=str(i), image=photo("Delta_Air_Lines_Airbus_A350"))
                  for i in range(3)]
            aa.append(article("STARLUX Airlines Airbus A350", id="bad", image=photo("Air_Canada_Airbus_A350")))
            path, cache = root / "batch.json", root / "cache.json"
            path.write_text(json.dumps({"articles": aa}), encoding="utf-8")
            cache.write_text(json.dumps({"articles": {"bad": {"status": "matched", "image": aa[-1]["image"]}}}), encoding="utf-8")
            with patch.object(images, "ARTICLES_DIR", root), patch.object(images, "CACHE_PATH", cache), \
                    patch.object(images, "MAX_LOOKUPS_PER_RUN", 0):
                images.main()
                first = path.read_text(encoding="utf-8")
                images.main()
                self.assertEqual(first, path.read_text(encoding="utf-8"))
            rows = json.loads(first)["articles"]
            self.assertEqual(sum(bool(a.get("image")) for a in rows), 2)
            self.assertNotIn("bad", json.loads(cache.read_text(encoding="utf-8"))["articles"])


if __name__ == "__main__":
    unittest.main()
