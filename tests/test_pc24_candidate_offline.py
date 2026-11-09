"""Pure-stdlib, offline editorial preflight for the staged PC-24 candidate.

Usage: python3 tests/test_pc24_candidate_offline.py
This script performs NO network, provider, GitHub, publication, or write calls.
It is a candidate-focused smoke test, not the full production draft/evidence gate.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "editorial" / "candidates" / "pc24-grass-runways-20261109.md"

OFFICIAL_SOURCES = (
    "https://www.pilatus-aircraft.com/en/news/pc-24-certified-for-take-offs-and-landings-on-unpaved-runways-plus-steep-approaches",
    "https://www.pilatus-aircraft.com/en/news/unpaved-extreme-the-pc-24-rolls-up-its-sleeves",
    "https://www.pilatus-aircraft.com/assets/files/Technical-Publications/Ground-Servicing-Guide_PC-24.pdf",
)
EDITORIAL_NARRATION = re.compile(
    r"(?:本文|本報導|這篇(?:文章|報導)).{0,60}"
    r"(?:採用|使用|引用|補足|補充|核對|交叉確認|資料來源|來源資料)"
    r"|(?:標題|摘要)(?:則|同時|也)?(?:指出|稱|提及|列出|描述|表示|將|以)"
)
METADATA_FACT = re.compile(
    r"(?:item is attributed to Simple Flying|item is listed as published at)",
    re.IGNORECASE,
)


def valid_sequential_fact_ids(ids):
    """Illustrate the gate: fact IDs must be F1, F2, ... after filtering."""
    return ids == [f"F{i}" for i in range(1, len(ids) + 1)]


def extract_reading_copy(markdown):
    start = markdown.index("## 中文候選稿")
    end = markdown.index("## English review copy")
    return markdown[start:end]


class PC24CandidateOfflineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = CANDIDATE.read_text(encoding="utf-8")
        cls.copy = extract_reading_copy(cls.document)

    def test_exists_and_explicit_hold(self):
        self.assertIn("offline candidate / HOLD", self.document)
        self.assertIn("not publication-ready", self.document)
        self.assertIn("No image is cleared for publication", self.document)

    def test_manufacturer_sources_present(self):
        for url in OFFICIAL_SOURCES:
            with self.subTest(url=url):
                self.assertIn(url, self.document)

    def test_safety_conditions_in_reader_copy(self):
        for phrase in ("2020 年", "2018 年", "gravel kit", "AFM Supplement 02473", "02444", "不得"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.copy)

    def test_no_process_narration_in_reading_copy(self):
        self.assertIsNone(EDITORIAL_NARRATION.search(self.copy))

    def test_no_source_metadata_as_verifiable_fact(self):
        self.assertIsNone(METADATA_FACT.search(self.copy))
        self.assertNotIn("2026-11-06T23:00Z", self.copy)

    def test_fact_ids_need_renumbering_after_drops(self):
        self.assertTrue(valid_sequential_fact_ids(["F1", "F2", "F3"]))
        self.assertFalse(valid_sequential_fact_ids(["F1", "F3"]))
        self.assertFalse(valid_sequential_fact_ids(["F2"]))
        self.assertTrue(valid_sequential_fact_ids(["F1"]))

    def test_not_a_news_feed_record(self):
        self.assertNotIn('"status": "publish"', self.document)
        self.assertNotIn('"publishedUtc":', self.document)
        self.assertNotIn('"image": "http', self.document)


if __name__ == "__main__":
    unittest.main(verbosity=2)
