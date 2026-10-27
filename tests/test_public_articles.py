"""Legacy channel-marked URLs redirect; every public discovery URL is neutral."""
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
from public_article import public_article_id, public_asset_url, public_site_url


def test_public_identity():
    assert public_article_id("a-20261024-1855-manual-tsa") == "a-20261024-1855-tsa"
    assert public_article_id("a-manual-recovery-story") == "a-story"
    assert public_article_id("a-20261024-standard-story") == "a-20261024-standard-story"
    assert public_article_id("manual").startswith("a-")
    assert public_article_id(public_article_id("a-manual-story")) == "a-story"
    assert build.page_url("en", "news/a-manual-story/") == "/en/news/a-story/"
    assert build.rel_path("zh", "news/a-manual-story/index.html") == "news/a-story/index.html"
    assert public_asset_url("https://example.com/assets/a-manual-photo.jpg",
                            build.SITE_ORIGIN).endswith("a-manual-photo.jpg")
    assert public_asset_url("https://skytical.tech/assets/a-manual-photo.jpg",
                            build.SITE_ORIGIN).endswith("a-photo.jpg")
    assert public_site_url("https://skytical.tech/en/news/a-manual-story/?utm_source=fb#source",
                           build.SITE_ORIGIN) == "https://skytical.tech/en/news/a-story/?utm_source=fb#source"


def verify_published_site():
    test_public_identity()
    assert build.main() == 0
    articles = build.collect_articles()
    migrated = [a for a in articles if public_article_id(a["id"]) != a["id"]]
    assert migrated
    index = json.loads((build.SITE_DIR / "search-index.json").read_text(encoding="utf-8"))
    indexed = {row["id"]: row for row in index["items"]}
    count = 0
    for article in migrated:
        public_id = public_article_id(article["id"])
        assert article["id"] not in indexed
        assert public_id in indexed
        for lang in article["available_languages"]:
            prefix = "en/" if lang == "en" else ""
            target = build.page_url(lang, f"news/{article['id']}/")
            page = (build.SITE_DIR / prefix / "news" / public_id / "index.html").read_text(encoding="utf-8")
            soup = BeautifulSoup(page, "html.parser")
            assert soup.h1
            assert soup.select_one('link[rel="canonical"]')["href"] == build.SITE_ORIGIN + target
            assert "SKYTICAL manual upload" not in page
            assert article["id"] not in page
            assert indexed[public_id]["url"][lang] == target
            for source in article["sources"]:
                assert soup.find("a", href=source["url"])
            legacy = (build.SITE_DIR / prefix / "news" / article["id"] / "index.html").read_text(encoding="utf-8")
            redirect = BeautifulSoup(legacy, "html.parser")
            assert redirect.select_one('meta[name="robots"]')["content"] == "noindex,follow"
            assert redirect.select_one('link[rel="canonical"]')["href"] == build.SITE_ORIGIN + target
            assert redirect.select_one('meta[http-equiv="refresh"]')["content"] == "0;url=" + target
            assert "location.search + location.hash" in legacy
            assert not redirect.h1
            if article["image"]:
                image_url = article["image"]["url"]
                assert "-manual-" not in image_url
                if urlsplit(image_url).netloc == urlsplit(build.SITE_ORIGIN).netloc:
                    assert (build.SITE_DIR / urlsplit(image_url).path.lstrip("/")).is_file()
            count += 1
    leak = re.compile(r'(?:href|src|content)="[^"\n]*(?:/news/|/assets/a-)[^"\n]*-manual-')
    for path in build.SITE_DIR.rglob("*.html"):
        assert not leak.search(path.read_text(encoding="utf-8")), path
    for path in [*build.SITE_DIR.glob("*sitemap*.xml"), *build.SITE_DIR.rglob("feed.xml")]:
        assert not re.search(r"/news/[^<]*-manual-", path.read_text(encoding="utf-8")), path
    print(f"test_public_articles: OK ({len(migrated)} articles, {count} legacy redirects)")


def main():
    original_site = build.SITE_DIR
    with tempfile.TemporaryDirectory() as directory:
        try:
            build.SITE_DIR = Path(directory) / "site"
            verify_published_site()
        finally:
            build.SITE_DIR = original_site


if __name__ == "__main__":
    main()
