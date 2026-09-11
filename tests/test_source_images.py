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
    monkeypatch.setattr(images, "lookup_source_photo", lambda _: source.parse_cna_photo(HTML, URL))
    monkeypatch.setattr(images, "resolve_image", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("stock lookup")))
    images.main()
    assert json.loads(path.read_text(encoding="utf-8"))["articles"][0]["image"]["url"] == PHOTO


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
