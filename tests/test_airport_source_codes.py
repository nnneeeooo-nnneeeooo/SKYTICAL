"""Source IATA pairs must survive rewriting without city/code guessing."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import airport_codes

SOURCE_URL = "https://www.aerotime.aero/articles/jersey-airport-hit-by-drone-disruption-for-second-consecutive-night"
SOURCE_PAIRS = ("Paris Charles de Gaulle (CDG), London Gatwick (LGW), "
                "London Heathrow (LHR), Southampton (SOU)")


class AirportSourceCodesTests(unittest.TestCase):
    def article(self):
        path = ROOT / "data/articles/scheduled-jersey-airport-drone-disruption-second-night-20261101.json"
        article = json.loads(path.read_text(encoding="utf-8"))["articles"][0]
        article["airportCodeEvidence"] = airport_codes.collect_source_codes([
            {"url": SOURCE_URL, "fulltext": SOURCE_PAIRS}])
        # Test the actual failure even after the committed copy is repaired.
        article["zh"] = {"title": "澤西機場航班受擾", "body": [
            "巴黎戴高樂機場、倫敦蓋特威克、倫敦希斯洛與南安普敦機場航班受影響。"]}
        article["en"] = {"title": "Jersey Airport disruption", "body": [
            "Flights from Paris Charles de Gaulle, London Gatwick, "
            "London Heathrow (LHR) and Southampton were affected."]}
        return article

    def test_jersey_source_pairs_survive_both_languages_and_second_pass(self):
        article = self.article()
        issues = airport_codes.validate_article(article)
        self.assertTrue(any("CDG" in issue for issue in issues))
        self.assertTrue(any("SOU" in issue for issue in issues))
        airport_codes.enforce_article(article)
        self.assertEqual(airport_codes.validate_article(article), [])
        for lang, left, right in (("zh", "（", "）"), ("en", "(", ")")):
            text = " ".join(article[lang]["body"])
            for code in ("CDG", "LGW", "LHR", "SOU"):
                self.assertEqual(text.count(f"{left}{code}{right}"), 1)
            self.assertIn("JER", article[lang]["title"])
        snapshot = copy.deepcopy(article)
        self.assertEqual(airport_codes.enforce_article(article), (False, []))
        self.assertEqual(article, snapshot)

    def test_unquoted_city_is_not_promoted_and_evidence_is_article_local(self):
        article = self.article()
        article.pop("airportCodeEvidence")
        article["entities"] = {}
        article["zh"] = {"title": "航班調整", "body": ["班機自南安普敦抵達倫敦。"]}
        article["en"] = {"title": "Flight update", "body": ["Flights from Southampton to London."]}
        self.assertEqual(airport_codes.enforce_article(article), (False, []))
        self.assertIsNone(airport_codes.resolve_airport("Southampton"))

    def test_wrong_code_unknown_name_and_unbound_quotes_are_not_trusted(self):
        for quote in ("London Heathrow (JFK)", "Unknown Example Airport (SOU)"):
            self.assertEqual(airport_codes.collect_source_codes([
                {"url": SOURCE_URL, "summary": quote}]), [])
        article = self.article()
        article["entities"] = {}
        article["en"] = {"title": "Flight update", "body": ["Flights from Southampton."]}
        article["zh"] = {"title": "航班調整", "body": []}
        article["airportCodeEvidence"][3]["sourceUrl"] = "https://other.example/news"
        airport_codes.enforce_article(article)
        self.assertNotIn("(SOU)", str(article["en"]))
        article["airportCodeEvidence"][3]["sourceUrl"] = SOURCE_URL
        article["airportCodeEvidence"][3]["code"] = "JFK"
        airport_codes.enforce_article(article)
        self.assertNotIn("(JFK)", str(article["en"]))

    def test_conflicting_source_cities_do_not_swallow_named_airports(self):
        article = {"sources": [{"url": SOURCE_URL}], "en": {"title": "Flights",
                   "body": ["London Gatwick and London Heathrow Airport."]}}
        for quote in ("London (LHR)", "London (LHR), London (LGW)"):
            article["airportCodeEvidence"] = airport_codes.collect_source_codes([
                {"url": SOURCE_URL, "summary": quote}])
            airport_codes.enforce_article(article)
            self.assertNotIn("London (", str(article["en"]))
            self.assertIn("London Gatwick (LGW)", article["en"]["body"][0])

    def test_background_cannot_supply_current_airport_aliases(self):
        self.assertEqual(airport_codes.collect_source_codes([
            {"url": SOURCE_URL, "summary": SOURCE_PAIRS,
             "backgroundCompanion": True}]), [])

    def test_boston_logan_name_outranks_wrong_existing_code(self):
        article = {"en": {"title": "Flight update", "body": [
            "Boston Logan International Airport (LGU) to San Francisco International Airport."]}}
        airport_codes.enforce_article(article)
        self.assertIn("Boston Logan International Airport (BOS)", article["en"]["body"][0])
        self.assertNotIn("(LGU)", str(article))
        self.assertEqual(airport_codes.validate_article(article), [])

    def test_writer_captures_pairs_outside_model_facts_and_applies_them(self):
        import write
        draft = {"cat": "ops", "zh": {"title": "南安普敦機場航班調整", "body": [
            "南安普敦機場航班調整。"]}, "en": {"title": "Airport flights updated", "body": [
            "Flights from Southampton were affected."]}}
        group = {"primarySource": "AeroTime", "items": [{"source": "AeroTime",
                 "url": SOURCE_URL, "title": "Airport flights updated",
                 "fulltext": "Flights from Southampton (SOU) were affected."}]}
        article = write.build_article(draft, group, datetime.now(timezone.utc), set(), facts=[])
        self.assertIsNotNone(article)
        self.assertEqual(article["airportCodeEvidence"][0]["sourceQuote"], "Southampton (SOU)")
        self.assertIn("Southampton (SOU)", article["en"]["body"][0])
        self.assertIn("南安普敦機場（SOU）", article["zh"]["body"][0])
        self.assertEqual(airport_codes.validate_article(article), [])
        # A later same-event source need not repeat the original code quote.
        revised_draft = copy.deepcopy(draft)
        revised_draft["en"]["body"] = ["Flights from Southampton were affected."]
        revised_group = copy.deepcopy(group)
        revised_group["items"][0]["fulltext"] = "Airport flights remained disrupted."
        revised = write.build_article(revised_draft, revised_group,
                                      datetime.now(timezone.utc), set(),
                                      facts=[], existing_article=article)
        self.assertEqual(revised["airportCodeEvidence"], article["airportCodeEvidence"])
        self.assertIn("Southampton (SOU)", revised["en"]["body"][0])


if __name__ == "__main__":
    unittest.main()
