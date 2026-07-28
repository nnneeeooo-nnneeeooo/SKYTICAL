"""Offline checks for official manufacturer sources and UI visibility.

Run from the repository root:

    python tests/test_manufacturer_sources.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-manufacturers-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)
sys.path.insert(0, str(REPO / "pipeline"))

import briefing  # noqa: E402
import build  # noqa: E402
import common  # noqa: E402
import fetch  # noqa: E402
import fulltext  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, condition):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if condition else "FAIL ") + name)
    if not condition:
        FAILED += 1


expected = {
    "airbus", "boeing", "embraer", "rollsroyce", "geaerospace",
    "prattwhitney", "iae", "cfm", "atr", "safran", "bombardier", "comac",
}
feeds = {
    row["key"]: row
    for row in common.MANUFACTURER_SOURCE_CATALOG.get("feeds", [])
}

check("manufacturer catalog has version 1",
      common.MANUFACTURER_SOURCE_CATALOG.get("schemaVersion") == 1)
check("requested aircraft and engine manufacturers are registered",
      expected == set(feeds) and expected.issubset(common.SOURCES))
check("Airbus and Boeing are public sources",
      all(feeds[key].get("public") is True for key in ("airbus", "boeing")))
check("other manufacturer feeds are hidden from public source status",
      all(feeds[key].get("public") is False
          for key in expected - {"airbus", "boeing"}))
check("all manufacturer feed URLs use HTTPS",
      all(urlsplit(row[field]).scheme == "https"
          for row in feeds.values() for field in ("url", "endpoint")))

social_hosts = {"x.com", "twitter.com", "facebook.com", "www.facebook.com",
                "instagram.com", "www.instagram.com"}
social = common.MANUFACTURER_SOURCE_CATALOG.get("socialAccounts", [])
check("official social accounts are metadata-only",
      bool(social)
      and all(row.get("crawl") is False for row in social)
      and all(urlsplit(row.get("url", "")).netloc.lower() in social_hosts
              for row in social))
check("social platforms are never fetch endpoints",
      not any(urlsplit(row["endpoint"]).netloc.lower() in social_hosts
              for row in feeds.values()))
check("social platforms are excluded from full-text allowlist",
      fulltext.ALLOWED_HOSTS.isdisjoint(social_hosts))

# Airbus has a direct, source-owned HTML parser rather than an aggregator.
airbus_html = """
<article class="awx-card">
  <a href="/en/newsroom/press-releases/2026-07-example"
     title="Example release">
    <h3 class="awx-card__title">Example Airbus release</h3>
    <p class="awx-card__summary">Airbus announced a verifiable new update.</p>
    <time datetime="2026-07-28T08:00:00Z">28 July 2026</time>
    <img src="/media/example.jpg">
  </a>
</article>
<article class="awx-card">
  <a href="/en/newsroom/events/example">
    <h3 class="awx-card__title">Event card must not enter news</h3>
    <time datetime="2026-07-29T08:00:00Z">29 July 2026</time>
  </a>
</article>
"""
parsed = fetch._parse_airbus(
    BeautifulSoup(airbus_html, "lxml"), feeds["airbus"]["endpoint"])
check("Airbus parser keeps dated stories/releases only",
      len(parsed) == 1
      and parsed[0]["title"] == "Example Airbus release"
      and parsed[0]["summary"].startswith("Airbus announced")
      and parsed[0]["url"].startswith("https://www.airbus.com/"))

# Persisted source status carries visibility, and every public consumer
# applies it.  Existing rows with no public field remain visible.
success = {"airbus": "2026-07-28T08:00Z", "boeing": "2026-07-28T08:00Z"}
fetch._write_sources(success)
source_rows = json.loads((TMP / "sources.json").read_text(encoding="utf-8"))
by_key = {row["key"]: row for row in source_rows}
check("sources.json persists manufacturer visibility",
      by_key["airbus"]["public"] is True
      and by_key["boeing"]["public"] is True
      and by_key["embraer"]["public"] is False)

public_rows = build.merged_sources(source_rows)
public_keys = {row["key"] for row in public_rows}
check("homepage/sources-page data shows Airbus and Boeing",
      {"airbus", "boeing"}.issubset(public_keys))
check("homepage/sources-page data hides other manufacturers",
      not (expected - {"airbus", "boeing"}) & public_keys)

brief_rows, _warnings = briefing.checked_sources_snapshot()
brief_names = {row["name"] for row in brief_rows}
check("briefing source status follows the same visibility rule",
      feeds["airbus"]["name"] in brief_names
      and feeds["boeing"]["name"] in brief_names
      and feeds["embraer"]["name"] not in brief_names)
check("legacy source rows without public remain compatible",
      any(row["key"] == "faa"
          for row in build.merged_sources([{"key": "faa", "ok": True}])))

official_hosts = {
    "airbus.com", "boeing.mediaroom.com", "embraer.com",
    "rolls-royce.com", "geaerospace.com", "prattwhitney.com",
    "cfmaeroengines.com", "atr-aircraft.com", "safran-group.com",
    "bombardier.com", "comac.cc",
}
check("official manufacturer article hosts may be full-text enriched",
      official_hosts.issubset(fulltext.ALLOWED_HOSTS))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{CHECKS - FAILED}/{CHECKS} checks passed")
raise SystemExit(1 if FAILED else 0)
