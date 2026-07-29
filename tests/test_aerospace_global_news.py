import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import common  # noqa: E402
import fetch  # noqa: E402


AGN_HTML = """
<main>
  <article>
    <a href="/news/ga-ats-gives-the-do228-a-new-lease-of-life-with-nxt-launch/">
      GA-ATS gives the Do228 a new lease of life with NXT launch
    </a>
    <a href="/topic/do228-nxt/">Do228 NXT</a>
    <span>July 29, 2026</span>
  </article>
  <article>
    <a href="/news/ga-ats-gives-the-do228-a-new-lease-of-life-with-nxt-launch/">
      GA-ATS gives the Do228 a new lease of life with NXT launch
    </a>
    <span>July 29, 2026</span>
  </article>
  <article>
    <a href="/news/china-c919-high-altitude-variant-completes-maiden-flight/">
      China C919 high-altitude variant completes maiden flight
    </a>
    <span>July 28, 2026</span>
  </article>
  <aside>
    <a href="/news/undated-recommendation/">Undated recommendation article</a>
  </aside>
</main>
"""


class AerospaceGlobalNewsTests(unittest.TestCase):
    def test_source_is_public_direct_html_feed(self):
        source = common.SOURCES["aerospaceglobalnews"]

        self.assertEqual(source["name"], "Aerospace Global News")
        self.assertEqual(source["kind"], "media")
        self.assertEqual(source["fmt"], "HTML")
        self.assertEqual(
            source["endpoint"],
            "https://aerospaceglobalnews.com/latest-news/",
        )
        self.assertEqual(source["type"], "html")
        self.assertTrue(source.get("public", True))
        self.assertIs(
            fetch.HTML_PARSERS["aerospaceglobalnews"],
            fetch._parse_aerospaceglobalnews,
        )

    def test_latest_news_parser_keeps_unique_dated_articles(self):
        items = fetch._parse_aerospaceglobalnews(
            BeautifulSoup(AGN_HTML, "lxml"),
            "https://aerospaceglobalnews.com/latest-news/",
        )

        self.assertEqual(
            [item["title"] for item in items],
            [
                "GA-ATS gives the Do228 a new lease of life with NXT launch",
                "China C919 high-altitude variant completes maiden flight",
            ],
        )
        self.assertEqual(
            [item["url"] for item in items],
            [
                (
                    "https://aerospaceglobalnews.com/news/"
                    "ga-ats-gives-the-do228-a-new-lease-of-life-with-nxt-launch/"
                ),
                (
                    "https://aerospaceglobalnews.com/news/"
                    "china-c919-high-altitude-variant-completes-maiden-flight/"
                ),
            ],
        )
        self.assertEqual(
            [item["published"].isoformat() for item in items],
            [
                "2026-07-29T00:00:00+00:00",
                "2026-07-28T00:00:00+00:00",
            ],
        )


if __name__ == "__main__":
    unittest.main()
