"""Original source photographs must outrank provisional airline stock images."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import images
import source_images as source

URL = "https://www.cna.com.tw/news/ahel/202609070138.aspx"
PHOTO = "https://imgcdn.cna.com.tw/www/WebPhotos/1024/20260907/photo.jpg"
HTML = f'''<meta property="og:image" content="{PHOTO}">
<figure class="floatImg center"><img src="{PHOTO.replace('/1024/', '/800/')}">
<figcaption>華航名古屋航線限定頭墊紙。（華航提供）中央社記者傳真 115年9月7日</figcaption>
</figure>'''


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
