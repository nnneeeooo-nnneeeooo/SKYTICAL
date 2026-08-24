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
    def __init__(self, status=200, data=None, text=""):
        self.status_code = status
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self):
        self.calls = []
        self.planespotters = FakeResp(200, {"photos": []})
        self.commons = FakeResp(200, {})
        self.source_pages = {}

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs.get("params")))
        if "planespotters" in url:
            return self.planespotters
        if url in self.source_pages:
            return self.source_pages[url]
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
    fake.source_pages.clear()
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
starlux_story = make_article(
    "a", "STARLUX Airlines opens Prague route after China Airlines")
starlux_story["entities"]["airlines"] = [
    "Starlux Airlines", "China Airlines"]
check("primary airline entity outranks a comparison carrier",
      images.find_airline(starlux_story) == "STARLUX Airlines")
starlux_story["entities"]["airlines"] = []
check("earlier lead airline wins when entity ordering is unavailable",
      images.find_airline(starlux_story) == "STARLUX Airlines")
indigo_story = make_article(
    "a", "IndiGo appoints an executive formerly at British Airways")
indigo_story["entities"]["airlines"] = ["IndiGo", "British Airways"]
check("primary IndiGo entity outranks an executive's former airline",
      images.find_airline(indigo_story) == "IndiGo")
uni_story = make_article("a", "立榮申請停飛台北花蓮航線")
uni_story["entities"]["airlines"] = ["華信航空", "立榮航空"]
check("headline order corrects a comparison carrier listed first",
      images.find_airline(uni_story) == "UNI Air")
air_astana_story = make_article("a", "Air Astana extends Dubai suspension")
air_astana_story["entities"]["airlines"] = ["Air Astana", "Air Canada"]
check("unknown verified airline entity is kept instead of dictionary drift",
      images.find_airline(air_astana_story) == "Air Astana")
check("aircraft family match never over-claims a sub-variant",
      images.find_aircraft_type(make_article(
          "a", "The Airbus A350 landed")) == "Airbus A350")
check("ICAO type code A359 maps to its display name",
      images.find_aircraft_type(make_article(
          "a", "DAL flight, type A359, arrived")) == "Airbus A350-900")
check("no visual entity -> resolve_image returns None without HTTP",
      (fake.calls.clear() is None
       and images.resolve_image(make_article(
           "a", "Global travel demand keeps rising")) is None
       and fake.calls == []))
check("island wording maps to the airport photo query with zh subject",
      images.find_airport(make_article("a", "澎湖離島航線加班"))
      == ("Magong Airport Penghu", ["Magong"], "澎湖馬公機場"))
check("agency stories fall back to an official-agency photo query",
      images.find_org(make_article("a", "FAA announces new drone rule"))
      == ("Federal Aviation Administration headquarters",
          ["Federal Aviation"], "美國聯邦航空總署（FAA）總部"))
check("substring 'faa' inside a word never triggers the org match",
      images.find_org(make_article("a", "shortfaall of capacity")) is None)
military_story = make_article("a", "MH-60S Seahawk hard-lands in California")
military_story["entities"]["aircraft_models"] = [
    "MH-60S Seahawk", "HH-60W Jolly Green II"]
check("verified military aircraft entity extends the type matcher",
      images.find_aircraft_type(military_story) == "MH-60S Seahawk")
airport_story = make_article("a", "Incheon airport installs queue barrier")
airport_story["entities"]["airports"] = ["Incheon International Airport"]
check("verified global airport entity becomes a strict lookup target",
      images.find_airport(airport_story)
      == ("Incheon International Airport", ["Incheon"],
          "Incheon International Airport"))

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

reset()
fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0,
          "title": "File:China Airlines Airbus A350-900.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-a350.jpg",
              "extmetadata": {
                  "LicenseShortName": {"value": "CC BY-SA 4.0"},
                  "Artist": {"value": "Wrong Carrier"}}}]},
    "2": {"index": 1,
          "title": "File:STARLUX Airlines Airbus A350-900.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/starlux-a350.jpg",
              "extmetadata": {
                  "LicenseShortName": {"value": "CC BY 4.0"},
                  "Artist": {"value": "Correct Carrier"}}}]},
}}})
strict_match = images.lookup_commons(
    "STARLUX Airlines Airbus A350-900",
    ["A350", "STARLUX Airlines"],
    require_all=True,
)
check("airline and aircraft must both match the Commons title",
      strict_match["url"]
      == "https://upload.wikimedia.org/starlux-a350.jpg")

fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0,
          "title": "File:China Airlines B-180 Boeing 737-209.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-1986.jpg",
              "extmetadata": {
                  "DateTimeOriginal": {"value": "1986"},
                  "LicenseShortName": {"value": "Public domain"},
                  "Artist": {"value": "Unknown"}}}]},
    "2": {"index": 1,
          "title": "File:China Airlines Boeing 737-800 2026.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-2026.jpg",
              "extmetadata": {
                  "DateTimeOriginal": {"value": "2026-02-15"},
                  "LicenseShortName": {"value": "CC BY 4.0"},
                  "Artist": {"value": "Recent Photographer"}}}]},
}}})
recent_generic = images.lookup_commons(
    "China Airlines aircraft", ["China Airlines"],
    min_year=2016, prefer_recent=True)
check("generic airline fallback rejects old fleet photos and picks newest",
      recent_generic["url"]
      == "https://upload.wikimedia.org/china-2026.jpg"
      and recent_generic["photoYear"] == 2026)

fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0,
          "title": "File:Premium Economy Class - China Airlines Airbus A350 2026.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-cabin-2026.jpg",
              "extmetadata": {
                  "DateTimeOriginal": {"value": "2026-01-01"},
                  "LicenseShortName": {"value": "CC BY 4.0"},
                  "Artist": {"value": "Cabin Photographer"}}}]},
    "2": {"index": 1,
          "title": "File:China Airlines Boeing 777-300ER exterior 2025.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-exterior-2025.jpg",
              "extmetadata": {
                  "DateTimeOriginal": {"value": "2025-01-01"},
                  "LicenseShortName": {"value": "CC BY 4.0"},
                  "Artist": {"value": "Exterior Photographer"}}}]},
}}})
generic_exterior = images.lookup_commons(
    "China Airlines aircraft exterior", ["China Airlines"],
    min_year=2016, prefer_recent=True,
    reject_title_re=images._BAD_AIRLINE_INTERIOR_RE)
check("generic airline fallback rejects a newer cabin file in favor of exterior aircraft",
      generic_exterior["url"]
      == "https://upload.wikimedia.org/china-exterior-2025.jpg")

fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0,
          "title": "File:China Airlines Premium Economy Class 2026.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/china-cabin-only.jpg",
              "extmetadata": {
                  "DateTimeOriginal": {"value": "2026-01-01"},
                  "LicenseShortName": {"value": "CC BY 4.0"},
                  "Artist": {"value": "Cabin Photographer"}}}]},
}}})
check("generic airline fallback returns no image when only cabin files match",
      images.lookup_commons(
          "China Airlines aircraft exterior", ["China Airlines"],
          min_year=2016, prefer_recent=True,
          reject_title_re=images._BAD_AIRLINE_INTERIOR_RE) is None)

generic_china_story = make_article(
    "a-generic-china", "China Airlines provides relief flight assistance")
generic_china_story["entities"]["airlines"] = ["China Airlines"]
old_generic_airline_image = {
    "url": "https://upload.wikimedia.org/china-1986.jpg",
    "link": "https://commons.wikimedia.org/w/old",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "matched": "China Airlines aircraft", "subject": "China Airlines",
}
fresh_generic_airline_image = dict(old_generic_airline_image,
                                   photoYear=now_utc().year)
check("cached generic airline photo without a recent capture year is stale",
      not images.existing_image_matches(
          generic_china_story, old_generic_airline_image)
      and images.existing_image_matches(
          generic_china_story, fresh_generic_airline_image))

cabin_generic_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Premium_Economy_Class_-_China_Airlines.jpg")
check("cached generic airline cabin photo is stale",
      not images.existing_image_matches(
           generic_china_story, cabin_generic_image))

brussels_story = make_article("a-brussels", "Brussels Airlines opens Arctic routes")
brussels_story["entities"]["airlines"] = ["Brussels Airlines", "Lufthansa"]
lufthansa_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Lufthansa_aircraft.jpg",
    matched="Lufthansa aircraft",
    subject="Lufthansa",
)
check("cached comparison-carrier photo is stale",
      not images.existing_image_matches(brussels_story, lufthansa_image))

weather_story = make_article("a-weather", "Typhoon changes Taiwan airlines flights")
weather_story["entities"]["airlines"] = [
    "Tigerair Taiwan", "China Airlines", "STARLUX Airlines"]
tigerair_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Tigerair_Taiwan_A320.jpg",
    matched="Tigerair Taiwan aircraft",
    subject="Tigerair Taiwan",
)
check("verified secondary carrier is allowed for a multi-airline weather story",
      images.existing_image_matches(weather_story, tigerair_image))

facility_story = make_article("a-facility", "Incheon airport installs queue barrier")
facility_story["entities"]["airports"] = ["Incheon International Airport"]
a320_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Lufthansa_A320.jpg",
    matched="Airbus A320 aircraft",
    subject="Airbus A320",
)
check("aircraft photo is stale for an airport-facility story",
      not images.existing_image_matches(facility_story, a320_image))
airport_facility_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Incheon_airport_queue.jpg",
    matched="Incheon International Airport",
    subject="Incheon International Airport",
)
check("strict airport match remains compatible with an airport-facility story",
      images.existing_image_matches(facility_story, airport_facility_image))

drone_story = make_article("a-drone", "Amazon expands drone delivery service")
drone_image = {
    "url": "https://upload.wikimedia.org/Quadcopter_Drone_in_flight.jpg",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "matched": "topic:drone", "subject": "drone file photo",
}
check("topic fallback remains compatible with its headline",
      images.existing_image_matches(drone_story, drone_image))

malaysia_story = make_article("a-malaysia", "Malaysia Airlines completes drug testing")
malaysia_story["entities"]["airlines"] = ["Malaysia Airlines"]
wreckage_image = dict(
    fresh_generic_airline_image,
    url="https://upload.wikimedia.org/Malaysia_Airlines_wreckage.png",
    matched="Malaysia Airlines aircraft",
    subject="Malaysia Airlines",
)
check("wreckage image is stale for a non-incident airline story",
      not images.existing_image_matches(malaysia_story, wreckage_image))

incident_story = make_article("a-incident", "Cirrus Vision Jet hard-lands on runway")
incident_story["entities"]["aircraft_models"] = ["Cirrus Vision Jet"]
incident_story["entities"]["airports"] = ["Driggs-Reed Memorial Airport"]
check("incident with a verified aircraft type does not fall back to a generic airport",
      images.resolve_image(incident_story) is None)

air_macau_story = make_article(
    "a-air-macau", "Air Macau Airbus A321neo B-MBU arrived")
wrong_airline_image = {
    "url": "https://upload.wikimedia.org/KLM_Airbus_A321neo.jpg",
    "link": "https://commons.wikimedia.org/w/klm",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "matched": "Airbus A321neo aircraft", "subject": "Airbus A321neo",
}
exact_airframe_image = {
    "url": "https://upload.wikimedia.org/Air_Macau_B-MBU.jpg",
    "link": "https://commons.wikimedia.org/w/bmbu",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "matched": "B-MBU", "subject": "Air Macau Airbus A321neo B-MBU",
}
check("revised article rejects a generic photo from another airline",
      not images.existing_image_matches(
          air_macau_story, wrong_airline_image))
check("exact-registration Commons photo remains compatible",
      images.existing_image_matches(air_macau_story, exact_airframe_image))

# org fallback end-to-end, with the logo/map title filter
reset()
fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0, "title": "File:FAA logo.svg", "imageinfo": [{
        "thumburl": "https://upload.wikimedia.org/logo.png",
        "extmetadata": {"LicenseShortName": {"value": "Public domain"},
                        "Artist": {"value": "FAA"}}}]},
    "2": {"index": 1,
          "title": "File:Federal Aviation Administration headquarters.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/faa-hq.jpg",
              "descriptionshorturl": "https://commons.wikimedia.org/w/9",
              "extmetadata": {
                  "DateTimeOriginal": {"value": str(now_utc().year)},
                  "LicenseShortName": {"value": "CC BY-SA 3.0"},
                  "Artist": {"value": "Photographer"}}}]},
}}})
p = write_batch([make_article("a-org", "FAA announces enforcement action")])
images.main()
art = read_batch(p)[0]
check("agency fallback attaches the building photo, never the logo",
      art["image"]["url"] == "https://upload.wikimedia.org/faa-hq.jpg"
      and "logo" not in art["image"]["url"])
check("photo carries its zh subject caption",
      art["image"]["subject"] == "美國聯邦航空總署（FAA）總部")

old_caa_file = {
    "url": "https://upload.wikimedia.org/caa-1948.jpg",
    "link": "https://commons.wikimedia.org/w/old-caa",
    "provider": "Wikimedia Commons", "kind": "file_photo",
    "matched": "交通部民用航空局", "subject": "交通部民用航空局",
    "photoYear": 1948,
}
caa_story = make_article("a-caa", "Taiwan CAA holds drone meeting")
caa_story["zh"]["body"] = ["交通部民用航空局召開無人機管理會議"]
check("cached generic agency photo that is too old is stale",
      not images.existing_image_matches(caa_story, old_caa_file))

reset()
caa_url = "https://www.caa.gov.tw/NewsPublish-Content.aspx?nid=2574"
caa_story["sources"] = [{"name": "CAA Taiwan", "url": caa_url}]
fake.source_pages[caa_url] = FakeResp(200, text='''
<a href="../FileAtt.ashx?lang=1&amp;id=41286"
 class="download-filebase"
 title="民航局舉辦遙控無人機管理業務工作會議1.jpg">photo</a>
''')
official = images.resolve_image(caa_story)
check("official CAA release attachment wins as the event photo",
      official["url"]
      == "https://www.caa.gov.tw/FileAtt.ashx?lang=1&id=41286"
      and official["kind"] == "event_photo"
      and official["link"] == caa_url)

# ── cache behaviour ──────────────────────────────────────────────────────────

reset()
fake.commons = FakeResp(200, {"query": {"pages": {
    "1": {"index": 0,
          "title": "File:Air Macau B-MBU Airbus A321neo.jpg",
          "imageinfo": [{
              "thumburl": "https://upload.wikimedia.org/Air_Macau_B-MBU.jpg",
              "descriptionshorturl": "https://commons.wikimedia.org/w/bmbu",
              "extmetadata": {
                  "LicenseShortName": {"value": "CC BY-SA 4.0"},
                  "Artist": {"value": "Air Macau Photographer"}}}]},
}}})
p = write_batch([make_article(
    "a-stale-airline", "Air Macau Airbus A321neo B-MBU arrived",
    image=dict(wrong_airline_image))])
(TMP / "images.json").write_text(json.dumps({"articles": {
    "a-stale-airline": {"status": "matched",
                        "image": wrong_airline_image}}}), encoding="utf-8")
images.main()
art = read_batch(p)[0]
cache = json.loads((TMP / "images.json").read_text(encoding="utf-8"))
check("stale airline photo and cached match are replaced together",
      art["image"]["url"]
      == "https://upload.wikimedia.org/Air_Macau_B-MBU.jpg"
      and "KLM" not in json.dumps(art["image"])
      and cache["articles"]["a-stale-airline"]["image"]["url"]
      == "https://upload.wikimedia.org/Air_Macau_B-MBU.jpg")

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
                             "kind": "unverified_event"})["kind"]
      == "file_photo")
check("verified official event-photo kind is preserved",
      build.normalize_image({"url": "https://www.caa.gov.tw/photo.jpg",
                             "kind": "event_photo"})["kind"]
      == "event_photo")
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

published = json.loads(
    (REPO / "data" / "articles" / "2026-08-03T12.json")
    .read_text(encoding="utf-8"))["articles"]
by_id = {article["id"]: article for article in published}
starlux_published = by_id[
    "a-20260803-1232-starlux-airlines-launches-first-european"]
indigo_published = by_id[
    "a-20260803-1232-willie-walsh-begins-first-day-as-indigo"]
check("published STARLUX article uses official brand and matching aircraft",
      "星宇航空" in starlux_published["zh"]["title"]
      and "星達航空" not in json.dumps(starlux_published, ensure_ascii=False)
      and "Starlux_Airlines_Airbus_A350-900" in
      starlux_published["image"]["url"]
      and "China_Airlines" not in starlux_published["image"]["url"])
check("published IndiGo article uses owner-approved name and aircraft",
      "IndiGo（印度靛藍航空）" in indigo_published["zh"]["title"]
      and "印地高" not in json.dumps(indigo_published, ensure_ascii=False)
      and "IndiGo_VT-IJB_A320neo" in indigo_published["image"]["url"]
      and "British_Airways" not in indigo_published["image"]["url"])

all_published_images = []
for article_path in (REPO / "data" / "articles").glob("*.json"):
    batch = json.loads(article_path.read_text(encoding="utf-8"))
    for article in batch.get("articles") or []:
        image = article.get("image") or ""
        all_published_images.append(
            str(image.get("url") or "") if isinstance(image, dict)
            else str(image))
check("retired B-180 accident airframe is absent from published images",
      not any("China_Airlines_B-180_Boeing_737-209" in url
              for url in all_published_images))

print(f"\n{CHECKS} checks passed, {FAILED} failed"
      if not FAILED else f"\n{CHECKS - FAILED}/{CHECKS} passed, "
      f"{FAILED} FAILED")
sys.exit(1 if FAILED else 0)
