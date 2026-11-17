"""Gallery contracts: relevance, provider failures, full results and rendering."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from unittest.mock import Mock

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
import images
import image_galleries as galleries
import source_images
import terra_images
from roundup_images import ImageBatch
from test_roundup_images import roundup, photo, render


def story():
    return {"id": "a-gallery-starlux", "publishedUtc": datetime.now(timezone.utc).isoformat(),
            "cat": "ops", "articleFormat": "full", "primarySource": "STARLUX",
            "sources": [{"name": "STARLUX", "url": "https://www.starlux-airlines.com/news"}],
            "zh": {"title": "星宇航空大洋洲新航線", "summary": "星宇航空規劃新航線。",
                   "body": ["規劃使用 A330-900 執飛。", "首度開航大洋洲。"]},
            "en": {"title": "STARLUX plans Oceania route", "summary": "STARLUX plans new flights.",
                   "body": ["The route will use an A330-900 aircraft.", "The first Oceania route."]}}


def stock(n, model="A330-900"):
    return dict(photo(n), provider="Wikimedia Commons", curated=False,
                subject=f"STARLUX Airlines Airbus {model} aircraft {n}",
                description=f"STARLUX Airlines Airbus {model} aircraft {n}", photoYear=2026)


def test_body_only_unambiguous_equipment_rejects_wrong_model():
    a = story()
    assert images.find_aircraft_type(a) == "Airbus A330-900"
    assert len(galleries.verified(a, [stock(1), stock(2, "A350-900")])) == 1
    a["en"]["body"].append("Other background: A350-900.")
    assert images.find_aircraft_type(a) is None


def test_three_best_results_survive_and_event_is_first_without_duplicates():
    a = story()
    candidates = [stock(n) for n in range(25)]
    event = dict(stock(99), kind="event_photo", curated=True)
    result = galleries.verified(a, [*candidates, event, deepcopy(candidates[0]),
                                    dict(stock(100), url="javascript:alert(1)")])
    assert len(result) == 3
    assert result[0]["kind"] == "event_photo"


def test_collect_keeps_existing_on_provider_failure_and_takes_all_commons(monkeypatch):
    a = dict(story(), image=stock(0))
    monkeypatch.setattr(source_images, "lookup_source_photos", Mock(side_effect=ValueError("offline")))
    lookup = Mock(return_value=[stock(n) for n in range(1, 14)])
    monkeypatch.setattr(images, "lookup_commons", lookup)
    assert len(galleries.collect(a)) == 3
    assert lookup.call_args.kwargs["all_matches"] is True


def test_manual_gallery_bilingual_render_credits_and_cover():
    a = story()
    a["images"] = [dict(stock(n), curated=True, subjectEn=f"English aircraft {n}") for n in range(12)]
    a["image"] = a["images"][0]
    for lang in ("zh", "en"):
        soup = render(a, lang)
        slides = json.loads(soup.select_one("#hero-candidates").string)
        assert len(slides) == len(soup.select("[data-hero-index]")) == 3
        assert soup.select_one("#hero-story-title") is None
        assert slides[0]["image"]["url"] == a["image"]["url"]
        for slide in slides:
            assert "CC BY 4.0" in slide["image_caption"]
            assert "Photographer" in slide["image_caption"]
            assert soup.select_one(slide["url"])
        if lang == "en":
            assert slides[0]["image_alt"] == "English aircraft 0"


def test_roundup_multiple_images_keep_each_item_anchor_and_sync():
    a = roundup()
    a["roundupItems"][0].update(image=photo(1), images=[photo(1), photo(2)])
    a["roundupItems"][1].update(image=photo(3), images=[photo(3)])
    adapter = ImageBatch([a])
    adapter.articles[0]["images"].append(photo(4))
    adapter.sync()
    assert len(a["roundupItems"][0]["images"]) == 3
    for lang in ("zh", "en"):
        soup = render(a, lang)
        slides = json.loads(soup.select_one("#hero-candidates").string)
        assert [s["url"] for s in slides] == ["#roundup-item-1", "#roundup-item-2", "#roundup-item-3"]


def test_empty_and_single_image_do_not_create_empty_controls():
    a = story()
    for photos in ([], [stock(1)]):
        a["images"] = photos
        soup = render(a, "zh")
        assert not soup.select_one("#hero-candidates")
        if not photos:
            assert soup.select_one("[data-image-fallback]")


def test_manual_upload_provider_keeps_existing_public_label():
    a = dict(story(), image=dict(photo(1), provider="SKYTICAL manual upload"))
    assert build.prep_article(a)["image"]["provider"] == "SKYTICAL"


def test_locked_gallery_is_not_overwritten_by_automatic_job(monkeypatch, tmp_path):
    a = dict(story(), images=[photo(1), photo(2)], image=photo(1), editorialImageLocked=True)
    batch = {"articles": [a]}
    monkeypatch.setattr(images, "_recent_batches", lambda: [(tmp_path / "batch.json", batch, [a])])
    monkeypatch.setattr(galleries, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(galleries, "collect", Mock(side_effect=AssertionError("locked")))
    before = deepcopy(a)
    galleries.main()
    assert a == before


def test_terra_retains_all_visually_approved_images_across_batches(monkeypatch):
    candidates = [dict(stock(n), selectionModel=terra_images.MODEL) for n in range(14)]
    monkeypatch.setattr(terra_images, "_queries", lambda _: ["STARLUX A330-900"])
    monkeypatch.setattr(terra_images, "_candidates", lambda *_: candidates)
    monkeypatch.setattr(terra_images, "_ask", lambda content, **kw: {
        "indices": list(range(len([c for c in content if c['type'] == 'input_image'])))})
    assert len(terra_images.find_images(story(), {})) == 3
