"""Original source photographs must outrank provisional airline stock images."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import images
import source_images as source
from image_selection import rejection_reason

URL = "https://www.cna.com.tw/news/ahel/202609070138.aspx"
PHOTO = "https://imgcdn.cna.com.tw/www/WebPhotos/1024/20260907/photo.jpg"
HTML = f'''<meta property="og:image" content="{PHOTO}">
<figure class="floatImg center"><img src="{PHOTO.replace('/1024/', '/800/')}">
<figcaption>華航名古屋航線限定頭墊紙。（華航提供）中央社記者傳真 115年9月7日</figcaption>
</figure>'''
AEROTIME_URL = "https://www.aerotime.aero/articles/dc-8-runway-excursion"
AEROTIME_PHOTO = "https://www.aerotime.aero/images/2026/09/dc8congo.jpeg"
AEROTIME_HTML = f'''<meta property="og:image" content="{AEROTIME_PHOTO}">
<figure class="cs-entry__post-media post-media">
<img src="{AEROTIME_PHOTO.replace('.jpeg', '-800x500.jpeg')}">
<figcaption class="cs-entry__caption-text">Bystander video</figcaption>
</figure>'''
AEROTIME_ARTICLE = {
    "entities": {
        "airlines": ["Trans Air Cargo Service"],
        "aircraft_models": ["DC-8-73CF"],
        "registration_numbers": ["9S-AJO"],
    }
}


def test_captioned_body_photo_and_resize_variants():
    photo = source.parse_cna_photo(HTML, URL)
    assert photo["url"] == PHOTO
    assert photo["subject"] == "華航名古屋航線限定頭墊紙"
    assert photo["credit"] == "華航提供"
    assert "license" not in photo
    assert "115年" in photo["sourceCaption"]


def test_reject_unrelated_og_and_uncredited_photo():
    assert source.parse_cna_photo(HTML.replace('src="'+PHOTO.replace('/1024/', '/800/'), 'src="https://example.com/other.jpg'), URL) is None
    assert source.parse_cna_photo(HTML.replace("華航提供", "記者攝影"), URL) is None
    assert source.parse_cna_photo(f'<meta property="og:image" content="{PHOTO}">', URL) is None


def test_aerotime_exact_lead_event_photo_with_credit_and_entities():
    photo = source.parse_aerotime_photo(
        AEROTIME_HTML, AEROTIME_URL, AEROTIME_ARTICLE)
    assert photo["url"] == AEROTIME_PHOTO
    assert photo["subject"] == \
        "Trans Air Cargo Service DC-8-73CF 9S-AJO"
    assert photo["credit"] == "Bystander video"
    assert photo["license"] is None
    assert photo["kind"] == "event_photo"
    assert source.supported_source({
        "sources": [{"url": AEROTIME_URL}]}) == AEROTIME_URL


def test_aerotime_webp_resize_and_short_corporate_credit():
    original = "https://www.aerotime.aero/images/2026/09/a330-first-flight.jpg"
    html = f'''<meta property="og:image" content="{original}">
    <figure class="cs-entry__post-media post-media">
    <img src="{original.replace('.jpg', '-800x500.jpg.webp')}">
    <figcaption>IAI</figcaption></figure>'''
    photo = source.parse_aerotime_photo(html, AEROTIME_URL,
                                        AEROTIME_ARTICLE)
    assert photo["url"] == original
    assert photo["credit"] == "IAI"


def test_aerotime_subject_uses_the_aircraft_identified_by_the_caption():
    article = {
        "entities": {
            "aircraft_models": [
                "A-10 Thunderbolt II", "F-15E Strike Eagle", "F-15E"],
        },
    }
    html = AEROTIME_HTML.replace(
        "Bystander video",
        "A USAF F-15E Strike Eagle in Jordan. Credit: U.S. Air Force photo",
    )
    photo = source.parse_aerotime_photo(html, AEROTIME_URL, article)
    assert photo["subject"] == "F-15E Strike Eagle"


def test_aerotime_subject_can_use_the_source_owned_image_filename():
    original = (
        "https://www.aerotime.aero/images/2026/09/"
        "Vietravel-Airlines-Airbus-A321-200-VN-A290.jpg")
    html = f'''<meta property="og:image" content="{original}">
    <figure class="cs-entry__post-media post-media">
    <img src="{original.replace('.jpg', '-800x500.jpg.webp')}"
         alt="Vietravel Airlines">
    <figcaption>Vietravel Airlines</figcaption></figure>'''
    article = {
        "entities": {
            "airlines": ["Vietravel Airlines", "Vietnam Airlines"],
            "aircraft_models": ["A220", "A321", "A350-900", "A321-200"],
        },
    }
    photo = source.parse_aerotime_photo(html, AEROTIME_URL, article)
    assert photo["subject"] == "A321-200"


def test_aerotime_short_generic_credit_remains_rejected():
    html = AEROTIME_HTML.replace("Bystander video", "Photo")
    assert source.parse_aerotime_photo(
        html, AEROTIME_URL, AEROTIME_ARTICLE) is None


def test_aerotime_stock_uses_source_alt_and_shared_entity_gate():
    original = "https://www.aerotime.aero/images/2026/09/air-force-one.jpg"
    html = f'''<meta property="og:image" content="{original}">
    <figure class="cs-entry__post-media post-media">
    <img src="{original.replace('.jpg', '-800x500.jpg.webp')}"
         alt="Air Force One Boeing 747 in Qatar">
    <figcaption>Bogac Erkan / Shutterstock.com</figcaption></figure>'''
    article = {
        "sources": [{"url": AEROTIME_URL}],
        "entities": {
            "airlines": ["Lufthansa"],
            "aircraft_models": ["Boeing 747"],
        },
        "en": {"title": "Lufthansa Boeing 747 delayed"},
    }
    photo = source.parse_aerotime_photo(html, AEROTIME_URL, article)
    assert photo["kind"] == "file_photo"
    assert photo["subject"] == "Air Force One Boeing 747 in Qatar"
    assert "Shutterstock" in photo["sourceCaption"]
    assert rejection_reason(article, photo) == "airline-mismatch"


def test_aerotime_rejects_unbound_or_uncredited_lead_image():
    assert source.parse_aerotime_photo(
        AEROTIME_HTML.replace("dc8congo-800x500", "different-800x500"),
        AEROTIME_URL, AEROTIME_ARTICLE) is None
    assert source.parse_aerotime_photo(
        AEROTIME_HTML.replace("Bystander video", "Image"),
        AEROTIME_URL, AEROTIME_ARTICLE) is None


def test_protect_manual_and_exact_airframe_images():
    for image in ["https://example.com/manual.jpg", {"provider": "manual"},
                  {"provider": "Planespotters", "kind": "airframe_photo"}]:
        assert not source.can_upgrade({"image": image})
    assert not source.can_upgrade({"articleFormat": "roundup"})
    assert source.supported_source({"sources": [{"url": URL+"/sidebar"}]}) is None


def test_aerotime_source_image_is_reparsed_after_parser_upgrade():
    assert source.can_upgrade({
        "image": {
            "provider": "AeroTime",
            "kind": "event_photo",
            "matched": "source:aerotime",
        }
    })


def setup_batch(tmp_path, monkeypatch, image=None):
    article = {"id": "test", "publishedUtc": images.now_utc().isoformat(),
               "sources": [{"url": URL}]}
    if image:
        article["image"] = image
    path = tmp_path / "batch.json"
    path.write_text(json.dumps({"articles": [article]}), encoding="utf-8")
    monkeypatch.setattr(images, "ARTICLES_DIR", tmp_path)
    monkeypatch.setattr(images, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(images, "existing_image_matches", lambda *args: True)
    monkeypatch.setattr(images, "enforce_recent", lambda: [])
    return path


def test_upgrade_stock_without_rss_image_and_idempotence(tmp_path, monkeypatch):
    path = setup_batch(tmp_path, monkeypatch,
                       {"provider": "Wikimedia Commons", "kind": "file_photo"})
    calls = []
    monkeypatch.setattr(images, "lookup_source_photo",
                        lambda article: calls.append(article) or source.parse_cna_photo(HTML, URL))
    monkeypatch.setattr(images, "resolve_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stock lookup")))
    images.main()
    assert json.loads(path.read_text(encoding="utf-8"))["articles"][0]["image"]["url"] == PHOTO
    images.main()
    assert len(calls) == 1


def test_missing_image_prefers_source(tmp_path, monkeypatch):
    path = setup_batch(tmp_path, monkeypatch)
    batch = json.loads(path.read_text(encoding="utf-8"))
    batch["articles"][0]["imageSelection"] = {
        "policyVersion": 2,
        "status": "fallback",
        "reason": "source-aircraft-model-unverified",
    }
    path.write_text(json.dumps(batch), encoding="utf-8")
    monkeypatch.setattr(images, "lookup_source_photo", lambda _: source.parse_cna_photo(HTML, URL))
    monkeypatch.setattr(images, "resolve_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stock lookup")))
    images.main()
    article = json.loads(path.read_text(encoding="utf-8"))["articles"][0]
    assert article["image"]["url"] == PHOTO
    assert "imageSelection" not in article


def test_failure_keeps_fallback_and_retries(tmp_path, monkeypatch):
    fallback = {"provider": "Wikimedia Commons", "kind": "file_photo"}
    path = setup_batch(tmp_path, monkeypatch, fallback)
    calls = []
    def fail(_):
        calls.append(1)
        raise TimeoutError()
    monkeypatch.setattr(images, "lookup_source_photo", fail)
    images.main()
    images.main()
    assert len(calls) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["articles"][0]["image"] == fallback
    cache = json.loads(images.CACHE_PATH.read_text(encoding="utf-8"))
    cache["sources"][URL]["next_retry_utc"] = "2000-01-01T00:00:00+00:00"
    images.CACHE_PATH.write_text(json.dumps(cache), encoding="utf-8")
    images.main()
    assert len(calls) == 2


def test_parser_upgrade_retries_old_negative_source_cache(tmp_path, monkeypatch):
    path = setup_batch(tmp_path, monkeypatch)
    images.CACHE_PATH.write_text(json.dumps({
        "articles": {},
        "sources": {URL: {
            "image": None,
            "rejection_reason": "no-event-photo",
            "next_retry_utc": "2999-01-01T00:00:00+00:00",
        }},
    }), encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        images, "lookup_source_photo",
        lambda article: calls.append(article) or source.parse_cna_photo(
            HTML, URL))
    monkeypatch.setattr(
        images, "resolve_image",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stock lookup")))
    images.main()
    assert len(calls) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["articles"][0][
        "image"]["url"] == PHOTO


OFFICIAL_URL = "https://news.klm.com/a350-update/"
OFFICIAL_PHOTO = "https://media.klm.com/aircraft/a350.jpg"
OFFICIAL_HTML = f'''<meta property="og:image" content="{OFFICIAL_PHOTO}">
<meta property="og:image:alt" content="KLM Airbus A350-900 on the apron">
<main><figure><img src="{OFFICIAL_PHOTO}" alt="KLM Airbus A350-900 on the apron">
<figcaption>KLM Airbus A350-900. Photo credit: Jane Doe / KLM</figcaption>
</figure></main>'''


def official_article(url=OFFICIAL_URL):
    return {"id": "official-test", "sources": [{"url": url}],
            "en": {"title": "KLM Airbus A350-900 service update", "body": []},
            "entities": {"airlines": ["KLM"], "aircraft_models": ["Airbus A350-900"]}}


def test_official_domain_identity_and_source_priority():
    assert source.official_provider(OFFICIAL_URL) == "KLM"
    assert source.official_provider("https://www.changiairport.com/media/photo.html") == "Changi Airport Group"
    for url in ("https://klm.com.evil.example/photo", "https://fakeklm.com/photo",
                "https://klm.com@evil.example/photo", "http://news.klm.com/photo"):
        assert source.official_provider(url) is None
    assert source.supported_source({"sources": [
        {"url": URL}, {"url": OFFICIAL_URL}]}) == OFFICIAL_URL


def test_official_photo_needs_no_license_statement_and_keeps_credit():
    photo = next(source.parse_official_photo(OFFICIAL_HTML, OFFICIAL_URL))
    assert photo["url"] == OFFICIAL_PHOTO
    assert photo["link"] == OFFICIAL_URL
    assert photo["provider"] == "KLM"
    assert "Jane Doe / KLM" in photo["credit"]
    assert photo["license"] is None
    assert photo["kind"] == "file_photo"
    assert rejection_reason(official_article(), photo) is None
    # No figure/credit required: official exact-image alt metadata is enough.
    photo = next(source.parse_official_photo(OFFICIAL_HTML.split('<main>')[0], OFFICIAL_URL))
    assert photo["credit"] == "KLM"
    assert photo["kind"] != "event_photo"


def test_official_missing_image_evidence_and_wrong_aircraft_still_rejected():
    assert list(source.parse_official_photo(
        f'<meta property="og:image" content="{OFFICIAL_PHOTO}">', OFFICIAL_URL)) == []
    assert list(source.parse_official_photo(OFFICIAL_HTML, "https://example.com/news")) == []
    wrong = OFFICIAL_HTML.replace("A350-900", "Boeing 737-800")
    photo = next(source.parse_official_photo(wrong, OFFICIAL_URL))
    assert rejection_reason(official_article(), photo) == "aircraft-model-mismatch"


def test_official_lookup_skips_bad_lead_and_accepts_matching_body(monkeypatch):
    from types import SimpleNamespace
    html = OFFICIAL_HTML.replace('property="og:image"', 'property="unused"')
    html = '<meta property="og:image" content="https://media.klm.com/logo.png">' + html
    response = SimpleNamespace(url=OFFICIAL_URL, text=html,
                               raise_for_status=lambda: None)
    monkeypatch.setattr(source.requests, "get", lambda *args, **kwargs: response)
    photo = source.lookup_source_photo(official_article())
    assert photo["url"] == OFFICIAL_PHOTO
    # Redirects cannot turn an official source into a different publisher.
    response.url = "https://example.com/redirect"
    assert source.lookup_source_photo(official_article()) is None


def test_official_photo_is_attached_and_cached_before_commons(tmp_path, monkeypatch):
    path = setup_batch(tmp_path, monkeypatch)
    article = official_article()
    article["publishedUtc"] = images.now_utc().isoformat()
    path.write_text(json.dumps({"articles": [article]}), encoding="utf-8")
    from types import SimpleNamespace
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(url=url, text=OFFICIAL_HTML, raise_for_status=lambda: None)
    monkeypatch.setattr(source.requests, "get", get)
    monkeypatch.setattr(images, "resolve_image", lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("official image should precede stock lookup")))
    assert images.main() == 0
    published = json.loads(path.read_text(encoding="utf-8"))["articles"][0]
    assert published["image"]["matched"] == "source:official"
    assert published["image"]["license"] is None
    assert images.main() == 0
    assert calls == [OFFICIAL_URL]
