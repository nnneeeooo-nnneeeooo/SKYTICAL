"""Tests for pipeline/companion.py (thin-story same-topic retrieval).

No pytest required — run from the repo root:

    py tests\\test_companion.py

All HTTP mocked; no real Google News call is ever made.
"""
from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-companion-")

sys.path.insert(0, str(REPO / "pipeline"))
import companion  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


SEED_TITLE = ("Boeing's 737 MAX 7 Is About To Receive Its Long-Awaited "
              "FAA Certification")
THIN_GROUP = {"id": "g1", "items": [{
    "title": SEED_TITLE,
    "summary": "Short blurb.",
    "url": "https://simpleflying.com/max7", "source": "Simple Flying"}]}


def rss(entries):
    items = "".join(
        f"<item><title>{t} - {src}</title><link>{link}</link>"
        f"<description>{desc}</description>"
        f'<source url="{href}">{src}</source></item>'
        for t, src, href, link, desc in entries)
    return (f'<?xml version="1.0"?><rss version="2.0"><channel>{items}'
            "</channel></rss>").encode()


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.rss_body = rss([])

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "news.google.com/rss" in url:
            return types.SimpleNamespace(status_code=200,
                                         content=self.rss_body,
                                         headers={})
        # redirect resolution: send everything to the real outlet
        return types.SimpleNamespace(
            status_code=302,
            headers={"Location": "https://www.reuters.com/max7-story"})


fake = FakeHttp()
companion.requests = types.SimpleNamespace(
    get=fake.get, RequestException=Exception)

# ── thinness + query ─────────────────────────────────────────────────────────

check("one-liner group is thin", companion.is_thin(THIN_GROUP))
check("group with fulltext is not thin",
      not companion.is_thin({"items": [dict(THIN_GROUP["items"][0],
                                            fulltext="x" * 500)]}))
check("group with substantial text is not thin",
      not companion.is_thin({"items": [dict(THIN_GROUP["items"][0],
                                            summary="長" * 500)]}))
check("already-enriched group is not searched again",
      not companion.is_thin({"items": [THIN_GROUP["items"][0],
                                       {"title": "t", "companion": True}]}))

query, tokens = companion.build_query(THIN_GROUP)
check("query keeps anchors and drops stopwords",
      "737" in tokens and "max" in tokens and "faa" in tokens
      and "certification" in tokens and "about" not in tokens
      and "long" not in tokens)

# ── candidate filtering ──────────────────────────────────────────────────────

fake.rss_body = rss([
    ("Boeing 737 MAX 7 certification nears FAA finish line", "Reuters",
     "https://www.reuters.com", "https://news.google.com/articles/a",
     "Boeing expects the 737 MAX 7 to be certified soon."),
    ("Boeing 737 MAX 7 nears certification", "Random Aviation Blog",
     "https://randomaviationblog.example", "https://news.google.com/x2",
     "blog take"),
    ("Completely unrelated cruise ship story", "Reuters",
     "https://www.reuters.com", "https://news.google.com/x3", "ships"),
])
cands = companion.search_candidates(query, tokens, lang_zh=False)
check("allowlisted same-topic candidate accepted, blog and off-topic "
      "rejected",
      len(cands) == 1 and cands[0]["source"] == "Reuters")
check("google redirect resolved to the outlet URL",
      cands[0]["url"] == "https://www.reuters.com/max7-story")
check("outlet suffix stripped from the headline",
      cands[0]["title"].endswith("finish line"))

# ── group enrichment end-to-end ──────────────────────────────────────────────

group = {"id": "g9", "items": [dict(THIN_GROUP["items"][0])]}
added = companion.enrich_thin_groups([group])
check("companion merged into the group as an ordinary item",
      added == 1 and len(group["items"]) == 2
      and group["items"][1]["companion"] is True
      and group["items"][1]["source"] == "Reuters")
check("re-running never re-searches the same group",
      companion.enrich_thin_groups([group]) == 0)

rich = {"id": "g10", "items": [{"title": "T", "summary": "長" * 500,
                                "url": "https://example.com"}]}
fake.calls.clear()
check("non-thin groups perform zero searches",
      companion.enrich_thin_groups([rich]) == 0 and fake.calls == [])

# per-run search budget
fake.rss_body = rss([])
thin_groups = [{"id": f"t{i}", "items": [{
    "title": SEED_TITLE, "summary": "s",
    "url": f"https://example.com/{i}"}]} for i in range(5)]
fake.calls.clear()
companion.enrich_thin_groups(thin_groups)
searches = [c for c in fake.calls if "news.google.com/rss" in c]
check("per-run search budget enforced",
      len(searches) == companion.MAX_SEARCHES_PER_RUN)

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
