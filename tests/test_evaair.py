import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import common  # noqa: E402
import fetch  # noqa: E402
import fulltext  # noqa: E402


class EvaAirSourceTests(unittest.TestCase):
    def test_source_uses_official_domain_news_index(self):
        source = common.SOURCES["evaair"]

        self.assertEqual(source["kind"], "official")
        self.assertEqual(source["fmt"], "RSS")
        self.assertEqual(source["type"], "rss")
        self.assertIn("news.google.com/rss/search", source["endpoint"])
        self.assertIn("site:evaair.com", source["endpoint"])
        self.assertIn("when:7d", source["endpoint"])
        self.assertIn("www.evaair.com", fulltext.ALLOWED_HOSTS)

    def test_broad_rss_scan_keeps_sparse_airline_story_after_first_25(self):
        entries = [
            {
                "title": f"General business story {index}",
                "link": f"https://www.cna.com.tw/news/afe/general{index}.aspx",
                "summary": "A non-aviation business update.",
            }
            for index in range(fetch.MAX_ITEMS_PER_SOURCE + 5)
        ]
        entries.append({
            "title": "長榮航空12月開航台北直飛德里",
            "link": "https://www.cna.com.tw/news/afe/202608050172.aspx",
            "summary": "每週五班使用A330-300客機飛航。",
        })

        items = fetch._rss_items(
            object(), "cnataiwanfinance", entries,
            "https://feeds.feedburner.com/rsscna/finance",
            max_items=fetch.MAX_RSS_SCAN_ITEMS,
        )
        kept = [item for item in items if fetch._matches_keywords(
            item, common.SOURCES["cnataiwanfinance"]["keywords"])]

        self.assertEqual(len(items), len(entries))
        self.assertEqual([item["title"] for item in kept],
                         ["長榮航空12月開航台北直飛德里"])


if __name__ == "__main__":
    unittest.main()
