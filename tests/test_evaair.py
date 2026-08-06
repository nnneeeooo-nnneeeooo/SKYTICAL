import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import common  # noqa: E402
import fetch  # noqa: E402
import fulltext  # noqa: E402


EVA_HTML = """
<main>
  <article class="news-card">
    <div>Aug 5, 2026 News Releases</div>
    <h3>EVA Air To Launch Nonstop Taipei－Delhi Service on December 1</h3>
    <a href="/en-global/about-eva-air/news/news-releases/2026-08-05-direct-flights-from-taipei-to-delhi.html">
      <img src="/images/delhi.png" alt="EVA Air To Launch Nonstop Taipei－Delhi Service on December 1">
    </a>
    <p>Expands South Asia Network and Enhances India－North America Connectivity.</p>
    <a href="/en-global/about-eva-air/news/news-releases/2026-08-05-direct-flights-from-taipei-to-delhi.html">
      More Information
    </a>
  </article>
  <article class="news-card">
    <div>Jul 15, 2026 News Releases</div>
    <a title="EVA Air President Interviewed by IATA Airlines Magazine"
       href="/en-global/about-eva-air/news/news-releases/2026-07-15-iata-airlines-interview.html">
      More Information
    </a>
    <p>The interview covers teamwork, resilience and future network plans.</p>
  </article>
  <a href="/en-global/about-eva-air/news/travel-news/2026-08-05-promotion.html">
    A promotion outside the official news-release path
  </a>
</main>
"""


class EvaAirSourceTests(unittest.TestCase):
    def test_source_uses_direct_official_newsroom(self):
        source = common.SOURCES["evaair"]

        self.assertEqual(source["kind"], "official")
        self.assertEqual(source["type"], "html")
        self.assertIs(fetch.HTML_PARSERS["evaair"], fetch._parse_evaair)
        self.assertIn("www.evaair.com", fulltext.ALLOWED_HOSTS)

    def test_parser_keeps_unique_dated_release_cards_with_material(self):
        items = fetch._parse_evaair(
            BeautifulSoup(EVA_HTML, "lxml"),
            "https://www.evaair.com/en-global/about-eva-air/news/news-releases/",
        )

        self.assertEqual(len(items), 2)
        self.assertEqual(
            items[0]["title"],
            "EVA Air To Launch Nonstop Taipei－Delhi Service on December 1",
        )
        self.assertEqual(items[0]["published"].isoformat(),
                         "2026-08-05T00:00:00+00:00")
        self.assertIn("South Asia Network", items[0]["summary"])
        self.assertEqual(items[0]["image"],
                         "https://www.evaair.com/images/delhi.png")
        self.assertTrue(all(common.item_has_material(item) for item in items))


if __name__ == "__main__":
    unittest.main()
