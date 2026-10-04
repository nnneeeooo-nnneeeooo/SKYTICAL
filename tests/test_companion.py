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
        self.background_body = rss([])

    def get(self, url, **kwargs):
        self.calls.append(url)
        if "news.google.com/rss" in url:
            body = (self.rss_body if "when%3A2d" in url
                    else self.background_body)
            return types.SimpleNamespace(status_code=200,
                                         content=body,
                                         headers={})
        # redirect resolution: send everything to the real outlet
        if url.endswith("/context"):
            destination = "https://www.apnews.com/context-story"
        elif url.endswith("/badredirect"):
            destination = "https://untrusted.example/story"
        else:
            destination = "https://www.reuters.com/max7-story"
        return types.SimpleNamespace(
            status_code=302,
            headers={"Location": destination})


fake = FakeHttp()
companion.requests = types.SimpleNamespace(
    get=fake.get, RequestException=Exception)

# ── thinness + query ─────────────────────────────────────────────────────────

check("one-liner group is thin", companion.is_thin(THIN_GROUP))
check("single-source fulltext still needs independent coverage",
      companion.is_thin({"items": [dict(THIN_GROUP["items"][0],
                                        fulltext="x" * 2000)]}))
check("substantial single-source text still needs independent coverage",
      companion.is_thin({"items": [dict(THIN_GROUP["items"][0],
                                        summary="長" * 2000)]}))
diverse = {"items": [
    {"title": f"ANA E190-E2 order update {i}",
     "summary": "Independent source material. " * 20,
     "source": f"Outlet {i}"}
    for i in range(companion.TARGET_SOURCE_COUNT)
]}
check("diverse substantial group needs no companion search",
      not companion.is_thin(diverse))
check("network work is bounded and parallel",
      companion.TIMEOUT[1] <= 12
      and companion.SEARCH_WORKERS > 1
      and companion.RESOLVE_WORKERS > 1
      and companion.MAX_RESOLVE_CANDIDATES
      == companion.MAX_ITEMS_PER_GROUP * 2)

query, tokens = companion.build_query(THIN_GROUP)
check("query keeps anchors and drops stopwords",
      "737" in tokens and "max" in tokens and "faa" in tokens
      and "certification" in tokens and "about" not in tokens
      and "long" not in tokens)
background_query, background_anchors, _ = companion.build_background_query(
    THIN_GROUP)
check("background query keeps model anchors and adds context terms",
      "737" in background_anchors and "max" in background_anchors
      and "maintenance" in background_query and "history" in background_query)

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
    ("Boeing 737 MAX 7 certification background", "Reuters",
     "https://www.reuters.com", "https://news.google.com/articles/badredirect",
     "A related story."),
])
cands = companion.search_candidates(query, tokens, lang_zh=False)
check("allowlisted same-topic candidate accepted, blog, off-topic and unsafe "
      "rejected",
      len(cands) == 1 and cands[0]["source"] == "Reuters")
check("google redirect resolved to the outlet URL",
      cands[0]["url"] == "https://www.reuters.com/max7-story")
check("outlet suffix stripped from the headline",
      cands[0]["title"].endswith("finish line"))

# A Google app-shell response without an outlet redirect is not publishable
# as a companion source and must be discarded rather than exposed verbatim.
unresolved_http = types.SimpleNamespace(
    get=lambda url, **kwargs: types.SimpleNamespace(
        status_code=200, headers={}))
original_requests = companion.requests
companion.requests = types.SimpleNamespace(
    get=unresolved_http.get, RequestException=Exception)
try:
    check("unresolved Google News link fails closed",
          companion._resolve("https://news.google.com/rss/articles/nope") is None)
finally:
    companion.requests = original_requests

# ── group enrichment end-to-end ──────────────────────────────────────────────

fake.rss_body = rss([
    ("Boeing 737 MAX 7 certification nears FAA finish line", "Reuters",
     "https://www.reuters.com", "https://news.google.com/articles/event",
     "Boeing expects the 737 MAX 7 to be certified soon."),
])
fake.background_body = rss([
    ("Boeing 737 MAX 7 certification history and fleet plans", "AP News",
     "https://apnews.com", "https://news.google.com/articles/context",
     "Boeing's 737 MAX 7 certification history and fleet plans."),
])
group = {"id": "g9", "items": [dict(THIN_GROUP["items"][0])]}
added = companion.enrich_thin_groups([group])
check("current and background companions merge with distinct scopes",
      added == 2 and len(group["items"]) == 3
      and group["items"][1]["companion"] is True
      and group["items"][1]["source"] == "Reuters"
      and group["items"][2]["source"] == "AP News"
      and group["items"][2]["backgroundCompanion"] is True)
background_calls = [c for c in fake.calls
                    if "news.google.com/rss" in c
                    and "when%3A2d" not in c]
check("background search has no recency window and requests context",
      len(background_calls) == 1
      and "maintenance" in background_calls[0]
      and "when%3A2d" not in background_calls[0])
check("re-running never duplicates an existing outlet or URL",
      companion.enrich_thin_groups([group]) == 0 and len(group["items"]) == 3)

rich = {"id": "g10", **diverse}
fake.calls.clear()
check("source-diverse groups perform zero searches",
      companion.enrich_thin_groups([rich]) == 0 and fake.calls == [])

fake.rss_body = rss([])
fake.background_body = rss([])
roundup = {"id": "g11", "groupKind": "safety_roundup",
           "items": [dict(THIN_GROUP["items"][0])]}
fake.calls.clear()
companion.enrich_thin_groups([roundup])
check("independent-event safety roundups skip broad background searches",
      not any("news.google.com/rss" in url and "when%3A2d" not in url
              for url in fake.calls))

# per-run search budget
fake.rss_body = rss([])
fake.background_body = rss([])
thin_groups = [{"id": f"t{i}", "items": [{
    "title": SEED_TITLE, "summary": "s",
    "url": f"https://example.com/{i}"}]} for i in range(5)]
fake.calls.clear()
companion.enrich_thin_groups(thin_groups)
searches = [c for c in fake.calls if "news.google.com/rss" in c]
current_searches = [c for c in searches if "when%3A2d" in c]
background_searches = [c for c in searches if "when%3A2d" not in c]
check("per-run current-event search budget enforced",
      len(current_searches)
      == min(companion.MAX_SEARCHES_PER_RUN, len(thin_groups)))
check("per-run background search budget enforced",
      len(background_searches)
      == min(companion.MAX_BACKGROUND_SEARCHES_PER_RUN, len(thin_groups)))

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
if __name__ == "__main__":
    sys.exit(1 if FAILED else 0)
