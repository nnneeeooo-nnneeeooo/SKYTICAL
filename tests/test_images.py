"""Tests for pipeline/images.py (auto photo matching, offline).

No pytest required — run from the repo root:

    py tests\\test_images.py

All HTTP is mocked; no real Planespotters/Wikimedia call is ever made.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import types
from datetime import timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="avwire-images-"))
os.environ["AVWIRE_DATA_DIR"] = str(TMP)

sys.path.insert(0, str(REPO / "pipeline"))
import images  # noqa: E402
import build  # noqa: E402
from common import now_utc  # noqa: E402

CHECKS = 0
FAILED = 0


def check(name, cond):
    global CHECKS, FAILED
    CHECKS += 1
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAILED += 1


# ── HTTP mock ────────────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.planespotters = FakeResp(200, {"photos": []})
        self.commons = FakeResp(200, {})

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        if "planespotters" in url:
            return self.planespotters
        return self.commons


fake = FakeHttp()
images.requests = types.SimpleNamespace(get=fake.get)

PS_HIT = FakeResp(200, {"photos": [{
    "thumbnail_large": {"src": "https://cdn.planespotters.net/x_large.jpg"},
    "link": "https://www.planespotters.net/photo/123",
    "photographer": "Jane Spotter",
}]})
COMMONS_HIT = FakeResp(200, {"query": {"pages": {
    "1": {"index": 2, "title": "File:Random building.jpg", "imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/no.jpg",
        "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"},
                        "Artist": {"value": "X"}}}]},
    "2": {"index": 1, "title": "File:Delta Air Lines Airbus A350-941.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/delta-a350.jpg",
              "descriptionshorturl": "https://commons.wikimedia.org/w/1",
              "extmetadata": {
                  "LicenseShortName": {"value": "CC BY-SA 4.0"},
                  "Artist": {"value": "<a href='#'>Some Photographer</a>"},
              }}]},
    "3": {"index": 0, "title": "File:Delta A350 copyrighted.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/nonfree.jpg",
              "extmetadata": {
                  "LicenseShortName": {"value": "All rights reserved"},
                  "Artist": {"value": "Y"}}}]},
}}})


def make_article(art_id, body_en, published=None, image=None):
    published = published or now_utc()
    return {
        "id": art_id,
        "publishedUtc": published.astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%MZ"),
        "cat": "ops", "primarySource": "T", "image": image,
        "zh": {"title": "標題", "summary": "摘要", "body": ["內文"]},
        "en": {"title": body_en, "summary": body_en, "body": [body_en]},
        "sources": [{"name": "S", "url": "https://example.gov/x"}],
        "writer": "nvidia:test", "facts": [], "riskFlags": [],
        "eventStatus": "confirmed",
        "entities": {"organizations": [], "locations": [],
                     "event_dates": []},
    }


def write_batch(articles, fname="b.json"):
    p = TMP / "articles" / fname
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"articles": articles}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def read_batch(p):
    return json.loads(p.read_text(encoding="utf-8"))["articles"]


def reset():
    shutil.rmtree(TMP / "articles", ignore_errors=True)
    try:
        (TMP / "images.json").unlink()
    except FileNotFoundError:
        pass
    fake.calls.clear()
    fake.planespotters = FakeResp(200, {"photos": []})
    fake.commons = FakeResp(200, {})


# ── entity extraction guards ─────────────────────────────────────────────────

check("registration found in article text",
      images.find_registration(make_article(
          "a", "Delta A350 registration N512DN arrived")) == "N512DN")
check("plain N95 is never treated as a registration",
      images.find_registration(make_article(
          "a", "Airport staff wore N95 masks")) is None)
check("airline dictionary match (Delta Air Lines)",
      images.find_airline(make_article(
          "a", "A Delta Air Lines flight arrived")) == "Delta Air Lines")
check("aircraft family match never over-claims a sub-variant",
      images.find_aircraft_type(make_article(
          "a", "The Airbus A350 landed")) == "Airbus A350")
check("ICAO type code A359 maps to its display name",
      images.find_aircraft_type(make_article(
          "a", "DAL flight, type A359, arrived")) == "Airbus A350-900")
check("no visual entity -> resolve_image returns None without HTTP",
      (fake.calls.clear() is None
       and images.resolve_image(make_article("a", "FAA policy update"))
       is None and fake.calls == []))

# ── tier 1: planespotters by registration ────────────────────────────────────

reset()
fake.planespotters = PS_HIT
p = write_batch([make_article("a-reg", "Delta A350 N512DN arrived")])
images.main()
art = read_batch(p)[0]
check("registration match embeds the same-airframe photo",
      art["image"]["url"] == "https://cdn.planespotters.net/x_large.jpg"
      and art["image"]["kind"] == "airframe_photo"
      and art["image"]["provider"] == "Planespotters.net")
check("photographer credit and backlink preserved",
      art["image"]["credit"] == "Jane Spotter"
      and art["image"]["link"] == "https://www.planespotters.net/photo/123")

# ── tier 2: commons with license + token filters ────────────────────────────

reset()
fake.commons = COMMONS_HIT
p = write_batch([make_article("a-com", "Delta Air Lines Airbus A350 news")])
images.main()
art = read_batch(p)[0]
check("commons picks the free-licensed, token-matching file",
      art["image"]["url"] == "https://upload.wikimedia.org/delta-a350.jpg"
      and art["image"]["license"] == "CC BY-SA 4.0"
      and art["image"]["kind"] == "file_photo")
check("artist HTML stripped in credit",
      art["image"]["credit"] == "Some Photographer")
check("non-free and token-mismatched files rejected",
      "nonfree" not in json.dumps(art["image"])
      and "Random building" not in json.dumps(art["image"]))

# ── cache behaviour ──────────────────────────────────────────────────────────

reset()
fake.commons = COMMONS_HIT
p = write_batch([make_article("a-cache", "Delta Air Lines Airbus A350")])
images.main()
n_first = len(fake.calls)
arts = read_batch(p)
for a in arts:  # simulate the next hourly run on a fresh article copy
    a["image"] = None
write_batch(arts)
fake.calls.clear()
images.main()
check("matched result is reused from cache with zero HTTP calls",
      n_first >= 1 and fake.calls == []
      and read_batch(p)[0]["image"]["kind"] == "file_photo")

reset()
p = write_batch([make_article("a-none", "Delta Air Lines Airbus A350")])
fake.commons = FakeResp(200, {})  # no results
images.main()
fake.calls.clear()
images.main()
check("negative result is not retried before the retry window",
      fake.calls == [] and read_batch(p)[0]["image"] is None)

reset()
existing = {"url": "https://example.org/keep.jpg", "kind": "file_photo"}
p = write_batch([make_article("a-keep", "Delta Air Lines Airbus A350",
                              image=dict(existing))])
images.main()
check("existing images are never overwritten or re-looked-up",
      read_batch(p)[0]["image"] == existing and fake.calls == [])

# ── network failure never breaks the pipeline ────────────────────────────────

reset()
write_batch([make_article("a-err", "Delta Air Lines Airbus A350")])


def _boom(url, **kw):
    raise OSError("network down")


images.requests = types.SimpleNamespace(get=_boom)
check("network failure -> exit 0, article simply keeps no image",
      images.main() == 0)
images.requests = types.SimpleNamespace(get=fake.get)

# ── build-side normalization & honest labels ─────────────────────────────────

img = build.normalize_image({"url": "https://upload.wikimedia.org/a.jpg",
                             "link": "https://commons.wikimedia.org/w/1",
                             "credit": "P", "license": "CC BY 4.0",
                             "provider": "Wikimedia Commons",
                             "kind": "file_photo"})
check("normalize_image keeps attribution fields",
      img["credit"] == "P" and img["license"] == "CC BY 4.0"
      and img["kind"] == "file_photo")
check("normalize_image rejects non-http urls",
      build.normalize_image({"url": "javascript:alert(1)"}) is None
      and build.normalize_image("data:text/html,x") is None)
check("legacy string image still accepted",
      build.normalize_image("https://x.example/y.jpg")["kind"]
      == "file_photo")
check("unknown kind coerced to file_photo (never fake 'event photo')",
      build.normalize_image({"url": "https://x.example/y.jpg",
                             "kind": "event_photo"})["kind"]
      == "file_photo")
check("honest file-photo labels present in both languages",
      "資料照片（非事件現場照片）" in
      (REPO / "pipeline" / "build.py").read_text(encoding="utf-8")
      and "File photo (not from this event)" in
      (REPO / "pipeline" / "build.py").read_text(encoding="utf-8"))
check("images.py needs no API key and calls no paid endpoint",
      all(m not in (REPO / "pipeline" / "images.py")
          .read_text(encoding="utf-8")
          for m in ("API_KEY", "apikey", "newsapi", "bing", "serpapi",
                    "perplexity")))

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
