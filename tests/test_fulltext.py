"""Tests for pipeline/fulltext.py + its write.py integration (offline).

No pytest required — run from the repo root:

    py tests\\test_fulltext.py

All HTTP is mocked; robots.txt honoring, allowlisting, caching, caps and
the prompt/verification consistency are checked without any real fetch.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-fulltext-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)

sys.path.insert(0, str(REPO / "pipeline"))
import fulltext  # noqa: E402
import write  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


class FakeResp:
    def __init__(self, status=200, text=""):
        self.status_code = status
        self.text = text


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.routes = {}

    def get(self, url, **kwargs):
        self.calls.append(url)
        for prefix, resp in self.routes.items():
            if url.startswith(prefix):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return FakeResp(404, "")


fake = FakeHttp()
fulltext.requests = types.SimpleNamespace(
    get=fake.get, RequestException=Exception)

LONG_PARA = ("The Federal Aviation Administration announced the results of "
             "its counter drone operations during the tournament, seizing "
             "more than seven hundred drones across host cities. " * 4)
PAGE_HTML = f"""
<html><head><script>var x=1;</script><style>.a{{}}</style></head><body>
<nav><a>Home</a><a>About</a></nav>
<header>FAA newsroom</header>
<main>
  <h1>Successful Counter-Drone Efforts Helped Keep Millions Safe</h1>
  <p>{LONG_PARA}</p>
  <p>Transportation Secretary Sean P. Duffy said the operation was the
  most comprehensive airspace security effort in United States history,
  involving federal, state and local partners working together.</p>
  <li>Short</li>
</main>
<footer>Contact us</footer>
</body></html>
"""


def reset():
    fake.calls.clear()
    fake.routes.clear()
    fulltext._robots_cache.clear()
    try:
        (TMP / "fulltext.json").unlink()
    except FileNotFoundError:
        pass


ROBOTS_OK = FakeResp(404, "")
ROBOTS_DENY = FakeResp(200, "User-agent: *\nDisallow: /")

# ── allowlist + robots ───────────────────────────────────────────────────────

reset()
check("non-allowlisted host is never fetched",
      fulltext.fetch_fulltext("https://evil.example/a") is None
      and fake.calls == [])
check("news.google.com redirects are not allowlisted",
      fulltext.fetch_fulltext(
          "https://news.google.com/rss/articles/x") is None
      and fake.calls == [])

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_DENY
check("robots Disallow is honored (page never requested)",
      fulltext.fetch_fulltext("https://www.faa.gov/newsroom/x") is None
      and fake.calls == ["https://www.faa.gov/robots.txt"])

reset()
fake.routes["https://www.faa.gov/robots.txt"] = OSError("net down")
check("unreachable robots.txt fails closed",
      fulltext.fetch_fulltext("https://www.faa.gov/newsroom/x") is None)

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
fake.routes["https://www.faa.gov/newsroom/x"] = FakeResp(200, PAGE_HTML)
text = fulltext.fetch_fulltext("https://www.faa.gov/newsroom/x")
check("allowlisted page fetched when robots absent (404)",
      text is not None and "seven hundred drones" in text)
check("extraction keeps main content, drops nav/script/short items",
      "Home" not in text and "var x=1" not in text and "Short" not in text
      and "Sean P. Duffy" in text)
check("stored text capped", len(text) <= fulltext.MAX_STORED_CHARS)

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
fake.routes["https://www.faa.gov/thin"] = FakeResp(
    200, "<html><body><p>Too short to add value here.</p></body></html>")
check("near-empty extraction returns None (feed summary suffices)",
      fulltext.fetch_fulltext("https://www.faa.gov/thin") is None)

# ── enrich_pending: caching + caps ───────────────────────────────────────────

def group_with(urls):
    return {"id": "g1", "items": [
        {"title": f"T{i}", "summary": "s", "url": u}
        for i, u in enumerate(urls)]}


reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
fake.routes["https://www.faa.gov/newsroom/x"] = FakeResp(200, PAGE_HTML)
g = group_with(["https://www.faa.gov/newsroom/x",
                "https://random.example/y"])
n = fulltext.enrich_pending([g])
check("enrich attaches fulltext to allowlisted items only",
      n == 1 and "seven hundred drones" in g["items"][0]["fulltext"]
      and "fulltext" not in g["items"][1])

page_calls = [c for c in fake.calls if "newsroom" in c]
g2 = group_with(["https://www.faa.gov/newsroom/x"])
fulltext.enrich_pending([g2])
check("second run served from cache (no new page request)",
      [c for c in fake.calls if "newsroom" in c] == page_calls
      and "seven hundred drones" in g2["items"][0]["fulltext"])

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
fake.routes["https://www.faa.gov/miss"] = FakeResp(500, "")
g = group_with(["https://www.faa.gov/miss"])
fulltext.enrich_pending([g])
first_calls = len(fake.calls)
fulltext.enrich_pending([group_with(["https://www.faa.gov/miss"])])
check("failed page is negative-cached (no immediate refetch)",
      len(fake.calls) == first_calls)

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
for i in range(12):
    fake.routes[f"https://www.faa.gov/p{i}"] = FakeResp(200, PAGE_HTML)
groups = [group_with([f"https://www.faa.gov/p{i}"]) for i in range(12)]
fulltext.enrich_pending(groups)
page_hits = [c for c in fake.calls if "/p" in c]
check("per-run fetch budget enforced",
      len(page_hits) == fulltext.MAX_FETCHES_PER_RUN)

reset()
fake.routes["https://www.faa.gov/robots.txt"] = ROBOTS_OK
for i in range(4):
    fake.routes[f"https://www.faa.gov/q{i}"] = FakeResp(200, PAGE_HTML)
g = group_with([f"https://www.faa.gov/q{i}" for i in range(4)])
fulltext.enrich_pending([g])
check("at most MAX_ITEMS_PER_GROUP items enriched per group",
      sum(1 for it in g["items"] if it.get("fulltext"))
      == fulltext.MAX_ITEMS_PER_GROUP)

# ── write.py integration: prompt + quote verification consistency ────────────

item = {"title": "FAA counter-drone results", "summary": "short summary",
        "url": "https://www.faa.gov/newsroom/x",
        "fulltext": "A" * 3990 + " UNIQUE-TAIL-MARKER beyond the cap"}
group = {"id": "g9", "primarySource": "FAA", "items": [item]}
prompt = write.group_prompt(group)
check("group_prompt shows the full text block",
      "full text (fetched by the pipeline" in prompt
      and prompt.count("A" * 100) > 0)
check("prompt never shows text beyond the shared cap constant",
      "UNIQUE-TAIL-MARKER" not in prompt)

quote_in = "counter drone operations during the tournament"
draft = {"facts": [
    {"factId": "F1", "claim": "c1", "sourceQuote": quote_in},
    {"factId": "F2", "claim": "c2",
     "sourceQuote": "UNIQUE-TAIL-MARKER beyond the cap"},
]}
item2 = {"title": "t", "summary": "s",
         "fulltext": ("Results of counter drone operations during the "
                      "tournament were announced by the agency today.")}
ok = write.verify_facts(draft, {"items": [item2]}, "test")
check("quote from full text verifies verbatim",
      any(f["sourceQuote"] == quote_in for f in ok))
item3 = {"title": "t", "summary": "s", "fulltext": item["fulltext"]}
ok3 = write.verify_facts(draft, {"items": [item3]}, "test")
check("quote beyond the prompt cap is dropped (model never saw it)",
      not any("UNIQUE-TAIL-MARKER" in f["sourceQuote"] for f in ok3))

# a "quote" straddling two fields is not contiguous in any real source
straddle = {"facts": [{"factId": "F1", "claim": "x",
                       "sourceQuote": "tail of summary head of fulltext"}]}
item4 = {"title": "t", "summary": "something tail of summary",
         "fulltext": "head of fulltext continues here with more text"}
check("field-straddling quotes are rejected",
      write.verify_facts(straddle, {"items": [item4]}, "test") == [])

check("nested SOURCE-tag smuggling is neutralized to a fixpoint",
      "</SOURCE" not in write._clean_source_text("</SOURCE</SOURCE>>")
      and "<SOURCE" not in write._clean_source_text("<SOURCE<SOURCE>>"))

check("system prompt: model never fetches, pipeline does",
      "you never fetch anything yourself" in write.SYSTEM_PROMPT)
check("system prompt scales body length with evidence, forbids padding",
      "4 to 7 substantive" in write.SYSTEM_PROMPT
      and "Never pad, repeat, editorialize" in write.SYSTEM_PROMPT)
check("zh summary spec unchanged (80-140)",
      "80 to 140 Chinese characters" in write.SYSTEM_PROMPT)

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
