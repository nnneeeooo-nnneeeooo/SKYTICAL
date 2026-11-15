"""Per-item automatic/manual image jobs, safe rendering and legacy migration."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build
import images
import industry_roundup
import roundup_images as ri
import terra_images
from image_selection import rejection_reason
from test_industry_roundup import article


def photo(n):
    return {"url": f"https://example.com/{n}.jpg", "subject": f"Aircraft photo {n}",
            "description": f"Aircraft photo {n}", "credit": f"Photographer {n}",
            "link": f"https://example.com/source/{n}", "license": "CC BY 4.0",
            "provider": "manual", "curated": True, "kind": "file_photo"}


def roundup():
    now = datetime.now(timezone.utc)
    state = {"items": [], "lastEdition": ""}
    for n in (1, 2, 3):
        industry_roundup.add(state, article(n), now)
    return industry_roundup.compile_due(state, now, [])


def render(a, lang):
    view = build.art_view(build.prep_article(a), lang)
    ctx = build.base_ctx(lang, "news", f"news/{a['id']}/", title=view["title"],
                         description=view["summary"], ticker=[], build={})
    ctx["a"] = view
    html = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=True).get_template("article.html").render(**ctx)
    return BeautifulSoup(html, "html.parser")


def test_exact_slot_count_mixed_images_and_fallback_in_both_languages():
    a = roundup()
    a["roundupItems"][0]["image"] = photo(1)
    a["roundupItems"][2]["image"] = dict(photo(3), selectionModel="gpt-6.1-terra")
    for lang in ("zh", "en"):
        soup = render(a, lang)
        slides = json.loads(soup.select_one("#hero-candidates").string)
        assert len(slides) == len(soup.select("[data-hero-index]")) == 3
        assert [s["image"]["url"] if s["image"] else None for s in slides] == [
            photo(1)["url"], None, photo(3)["url"]]
        assert "SKYTICAL" in slides[1]["image_caption"]
        assert "Image Powered By GPT 6.1" in slides[2]["image_caption"]
        assert "Photographer 3" in slides[2]["image_caption"]
        assert "CC BY 4.0" in slides[2]["image_caption"]
        for slide in slides:
            assert soup.select_one(slide["url"]) is not None


def test_all_missing_images_still_render_one_default_per_item():
    soup = render(roundup(), "zh")
    assert soup.select_one("#hero-story-image[data-image-fallback]")["src"].find("skytical-social.png") >= 0
    assert len(json.loads(soup.select_one("#hero-candidates").string)) == 3


def test_manual_gpt_images_survive_both_stages_and_normalization(monkeypatch, tmp_path):
    a = roundup()
    a["editorialImageLocked"] = True
    a["image"] = photo(99)  # Stale cover must never overwrite canonical GPT slots.
    for n, item in enumerate(a["roundupItems"], 1):
        item["image"] = photo(n)
        item["editorialImageLocked"] = True
    batch = {"articles": [a]}
    path = tmp_path / "batch.json"
    monkeypatch.setattr(images, "_recent_batches", lambda: [(path, batch, [a])])
    monkeypatch.setattr(images, "enforce_recent", lambda: None)
    monkeypatch.setattr(images, "ARTICLES_DIR", tmp_path)
    monkeypatch.setattr(images, "CACHE_PATH", tmp_path / "images.json")
    monkeypatch.setattr(images, "resolve_image", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("manual slot replaced")))
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(terra_images, "CACHE_PATH", tmp_path / "terra.json")
    monkeypatch.setattr(terra_images, "find_image", lambda *_: (_ for _ in ()).throw(AssertionError("manual slot replaced")))
    images.main()
    terra_images.main()
    assert [i["image"] for i in a["roundupItems"]] == [photo(n) for n in (1, 2, 3)]
    assert len(build.art_view(build.prep_article(a), "zh")["roundup_slides"]) == 3


def test_automatic_stages_receive_individual_sources_and_update_every_slot(monkeypatch, tmp_path):
    a = roundup()
    path = tmp_path / "batch.json"
    batch = {"articles": [a]}
    monkeypatch.setattr(images, "ARTICLES_DIR", tmp_path)
    monkeypatch.setattr(images, "CACHE_PATH", tmp_path / "images.json")
    monkeypatch.setattr(images, "_recent_batches", lambda: [(path, batch, [a])])
    monkeypatch.setattr(images, "enforce_recent", lambda: None)
    monkeypatch.setattr(images, "supported_source", lambda _: None)
    seen = []
    def resolve(ctx, **kwargs):
        seen.append(ctx)
        assert len(ctx["sources"]) == 1
        n = int(ctx["zh"]["title"][-1])
        return photo(n) if n != 2 else None
    monkeypatch.setattr(images, "resolve_image", resolve)
    images.main()
    assert len(seen) == 3
    assert [bool(i.get("image")) for i in a["roundupItems"]] == [True, False, True]
    # Terra sees only the remaining unfilled item; all manual pictures survive.
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setattr(terra_images, "CACHE_PATH", tmp_path / "terra.json")
    monkeypatch.setattr(terra_images, "find_image", lambda ctx, usage: dict(photo(2), selectionModel=terra_images.MODEL))
    terra_images.main()
    assert [i["image"]["url"] for i in a["roundupItems"]] == [photo(n)["url"] for n in (1, 2, 3)]


def test_legacy_published_images_are_inherited_without_repeating_cover(monkeypatch):
    a = roundup()
    for i in a["roundupItems"]:
        i.pop("imageContext"); i.pop("image")
    originals = {article(2)["id"]: dict(article(2), image=photo(2))}
    monkeypatch.setattr(ri, "_originals", lambda _: originals)
    a["image"] = photo(2)
    adapter = ri.ImageBatch([a]); adapter.sync()
    assert [bool(i["image"]) for i in a["roundupItems"]] == [False, True, False]
    assert a["image"]["roundupItemNumber"] == 2
    assert "第 2 則" in build._hero_image_caption(build.prep_article(a)["image"], "zh")


def test_wrong_subject_is_rejected_per_item_and_safety_roundups_stay_excluded():
    a = roundup()
    a["roundupItems"][0]["imageContext"]["zh"]["title"] = "長榮航空波音787客機"
    a["roundupItems"][0]["imageContext"]["en"]["title"] = "EVA Air Boeing 787 aircraft"
    wrong = dict(photo(1), provider="Wikimedia Commons", curated=False,
                 description="Delta Air Lines Boeing 737 aircraft", matched="Delta Air Lines")
    a["roundupItems"][0]["image"] = wrong
    assert rejection_reason(ri.context(a, a["roundupItems"][0], 0), wrong)
    assert build.art_view(build.prep_article(a), "zh")["roundup_slides"][0]["image"] is None
    safety = dict(a, roundupKind=None)
    assert images.resolve_image(safety) is None
