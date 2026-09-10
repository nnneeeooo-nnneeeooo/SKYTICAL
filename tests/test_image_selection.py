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
    def test_visual_profiles_are_auditable_and_not_a_single_airline_exception(self):
        profiles = list(images._visual_profiles.values())
        self.assertGreaterEqual(len(profiles), 9)
        for profile in profiles:
            with self.subTest(airline=profile.get("airline")):
                self.assertTrue(str(profile.get("source") or "").startswith("https://"))
                self.assertRegex(str(profile.get("verified_utc") or ""), r"^20\d\d-")
                self.assertIsInstance(profile.get("flagship"), list)
                self.assertFalse(
                    set(profile.get("flagship") or [])
                    & set(profile.get("excluded_generic") or []))

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

    def test_verified_entity_registration_supports_9s_prefix(self):
        a = article(
            "Trans Air Cargo Service DC-8-73CF 9S-AJO runway excursion",
            entities={"registration_numbers": ["9S-AJO", "OB-2231P"]})
        self.assertEqual(images.find_registration(a), "9S-AJO")

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

    def test_airline_profiles_apply_the_same_role_rules_across_carriers(self):
        cases = (
            ("China Airlines reports annual earnings", "Airbus A350-900"),
            ("EVA Air reports annual earnings", "Boeing 787-10"),
            ("STARLUX Airlines reports annual earnings", "Airbus A350-1000"),
            ("Delta Air Lines reports annual earnings", "Airbus A350-900"),
        )
        for title, expected in cases:
            a = article(title, entities={"airlines": [title.split(" reports")[0]]})
            airline = images.find_airline(a)
            self.assertEqual(images.preferred_airline_models(a, airline)[0], expected)

    def test_airline_profiles_separate_cargo_from_passenger_images(self):
        a = article("China Airlines cargo revenue rises",
                    entities={"airlines": ["China Airlines"]})
        self.assertEqual(images.airline_visual_role(a), "cargo")
        self.assertEqual(images.preferred_airline_models(a, "China Airlines")[:2],
                         ["Boeing 777F", "Boeing 747-400F"])
        self.assertEqual(
            images.profiled_airline_stock_reason(
                a, "China Airlines", "China Airlines Airbus A350-900"),
            "airline-role-mismatch")

    def test_nonrepresentative_generic_stock_is_rejected_but_exact_story_is_not(self):
        generic = article("China Airlines reports annual earnings",
                          entities={"airlines": ["China Airlines"]})
        old = photo("China_Airlines_Boeing_737-800")
        self.assertEqual(policy.rejection_reason(generic, old),
                         "nonrepresentative-airline-stock")
        exact = article("China Airlines Boeing 737-800 maintenance update",
                        entities={"airlines": ["China Airlines"],
                                  "aircraft_models": ["Boeing 737-800"]})
        self.assertIsNone(policy.rejection_reason(exact, old))

    def test_unprofiled_airline_is_not_guessed(self):
        a = article("Air Astana reports annual earnings",
                    entities={"airlines": ["Air Astana"]})
        self.assertEqual(images.preferred_airline_models(a, "Air Astana"), [])

    def test_published_china_airlines_737_photos_require_a_737_story(self):
        root = Path(__file__).resolve().parents[1] / "data" / "articles"
        violations = []
        for path in root.glob("*.json"):
            batch = json.loads(path.read_text(encoding="utf-8"))
            for row in batch.get("articles") or []:
                image = row.get("image") or {}
                if not isinstance(image, dict):
                    continue
                identity = f"{image.get('url', '')} {image.get('subject', '')}"
                if "China_Airlines_Boeing_737" not in identity and \
                        "China Airlines Boeing 737" not in identity:
                    continue
                if "737" not in images.article_headline_text(row):
                    violations.append(row.get("id"))
        self.assertEqual(violations, [])

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

    def test_exact_airframe_and_verified_freighter_subtype_are_allowed(self):
        a = article(
            "Trans Air Cargo Service DC-8 freighter 9S-AJO runway excursion",
            entities={
                "airlines": ["Trans Air Cargo Service"],
                "aircraft_models": ["DC-8-73CF", "DC-8"],
                "registration_numbers": ["9S-AJO"],
            })
        im = {
            "url": "https://cdn.planespotters.net/9s-ajo.jpg",
            "provider": "Planespotters.net", "kind": "airframe_photo",
            "matched": "9S-AJO",
            "description": "Trans Air Cargo Service DC-8-73CF 9S-AJO",
            "link": "https://www.planespotters.net/photo/9s-ajo-trans-air-cargo-service",
        }
        self.assertIsNone(policy.rejection_reason(a, im))
        a["entities"]["aircraft_models"] = ["DC-8"]
        self.assertEqual(
            policy.rejection_reason(a, im), "airframe-role-unverified")

    def test_bound_aerotime_event_uses_verified_subject(self):
        url = "https://www.aerotime.aero/articles/dc-8-runway-excursion"
        a = article(
            "Trans Air Cargo Service DC-8 freighter 9S-AJO runway excursion",
            sources=[{"url": url}],
            entities={"airlines": ["Trans Air Cargo Service"]})
        im = {
            "url": "https://www.aerotime.aero/images/2026/09/dc8.jpeg",
            "link": url, "provider": "AeroTime", "kind": "event_photo",
            "matched": "source:aerotime", "sourceCaption": "Bystander video",
            "subject": "Trans Air Cargo Service DC-8-73CF 9S-AJO",
        }
        self.assertIsNone(policy.rejection_reason(a, im))

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

    def test_landscape_aircraft_photo_beats_portrait_result(self):
        a = article("Delta Air Lines Airbus A350")
        payload = {"query": {"pages": {
            "1": {"index": 0, "title": "File:Delta Air Lines Airbus A350-941 portrait.jpg",
                  "imageinfo": [{"thumburl": "https://upload.wikimedia.org/portrait.jpg",
                                 "width": 1200, "height": 1800,
                                 "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}}}]},
            "2": {"index": 1, "title": "File:Delta Air Lines Airbus A350-941 landscape.jpg",
                  "imageinfo": [{"thumburl": "https://upload.wikimedia.org/landscape.jpg",
                                 "width": 2400, "height": 1400,
                                 "extmetadata": {"LicenseShortName": {"value": "CC BY 4.0"}}}]},
        }}}
        class Response:
            status_code = 200
            def json(self): return payload
        with patch.object(images.requests, "get", return_value=Response()):
            found = images.lookup_commons(
                "Delta Air Lines Airbus A350", ["Delta Air Lines"],
                article=a, require_all=True, required_model="Airbus A350-900",
                prefer_landscape=True)
        self.assertEqual(found["url"], "https://upload.wikimedia.org/landscape.jpg")

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
