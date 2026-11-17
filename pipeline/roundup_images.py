"""One independent, source-scoped image job per industry-roundup item.

Canonical manual/API contract: roundupItems[i].image (normal image object or
null) and optional editorialImageLocked. imageContext freezes the component's
own evidence so unrelated airlines/events never compete in one image query.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
import re

from common import ARTICLES_DIR, load_json, norm_url

CONTEXT_FIELDS = ("cat", "zh", "en", "sources", "entities", "incident",
                  "sourceImageCandidates", "sourcePublishedUtc")


def is_industry(article):
    return article.get("articleFormat") == "roundup" and article.get("roundupKind") == "industry"


@lru_cache(maxsize=4)
def _originals(directory):
    result = {}
    for path in Path(directory).glob("*.json"):
        payload = load_json(path, {})
        if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
            result.update({a.get("id"): a for a in payload["articles"] if isinstance(a, dict)})
    return result


def context(article, item, index):
    """Read frozen evidence, or reconstruct legacy editions from their own copy."""
    saved = item.get("imageContext")
    if isinstance(saved, dict):
        result = deepcopy(saved)
    else:
        original = _originals(str(ARTICLES_DIR)).get(item.get("articleId")) or {}
        urls = {norm_url(u) for u in item.get("sourceUrls", [])}
        original_urls = {norm_url(s.get("url", "")) for s in original.get("sources", [])
                         if isinstance(s, dict)}
        result = {k: deepcopy(original[k]) for k in CONTEXT_FIELDS if k in original
                  and urls & original_urls}
        result["sources"] = [deepcopy(s) for s in article.get("sources", [])
                             if isinstance(s, dict) and norm_url(s.get("url", "")) in urls]
        for lang in ("zh", "en"):
            paragraphs = (article.get(lang) or {}).get("body") or []
            text = paragraphs[index + 1] if len(paragraphs) > index + 1 else ""
            heading, _, summary = str(text).partition("\n")
            result[lang] = {"title": re.sub(r"^\d+\.\s*", "", heading),
                            "summary": summary, "body": [summary] if summary else []}
    result.update(id=f"{article['id']}-image-{index + 1}", articleFormat="brief",
                  _galleryLimit=1,
                  publishedUtc=article.get("publishedUtc"),
                  editorialImageLocked=bool(article.get("editorialImageLocked")
                                           or item.get("editorialImageLocked")))
    return result


def item_images(article):
    """Return slots without mutating stored data, including legacy images."""
    from image_selection import image_key, rejection_reason
    rows = article.get("roundupItems") or []
    rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    slots = []
    legacy = article.get("image")
    for index, item in enumerate(rows):
        ctx = context(article, item, index)
        image = item.get("image")
        if not image and not ctx["editorialImageLocked"]:
            original = _originals(str(ARTICLES_DIR)).get(item.get("articleId")) or {}
            candidate = original.get("image")
            bound = {norm_url(u) for u in item.get("sourceUrls", [])}
            originals = {norm_url(s.get("url", "")) for s in original.get("sources", [])
                         if isinstance(s, dict)}
            if candidate and bound & originals and not rejection_reason(ctx, candidate):
                image = deepcopy(candidate)
        slots.append({"context": ctx, "image": image, "item": item})
    number = legacy.get("roundupItemNumber") if isinstance(legacy, dict) else None
    if type(number) is int and 1 <= number <= len(slots):
        target = slots[number - 1]
        if "image" not in target["item"]:
            target["image"] = deepcopy(legacy)
            target["image"].pop("roundupItemNumber", None)
    # A legacy/manual cover is migrated once, never repeated across all slots.
    if legacy and not any(image_key(s["image"]) == image_key(legacy) for s in slots):
        candidate = dict(legacy) if isinstance(legacy, dict) else legacy
        if isinstance(candidate, dict):
            candidate.pop("curated", None)
        target = next((s for s in slots if "image" not in s["item"]
                       and not rejection_reason(s["context"], candidate)), None)
        if target:
            target["image"] = deepcopy(legacy)
    return slots


class ImageBatch:
    """Adapt existing image stages to nested slots and synchronize their writes."""
    def __init__(self, articles):
        self.source = articles
        self.before = deepcopy(articles)
        self.articles, self.bindings = [], []
        for article in articles:
            if not is_industry(article):
                self.articles.append(article)
                continue
            for slot in item_images(article):
                item, job = slot["item"], slot["context"]
                item.setdefault("imageContext", {k: deepcopy(job[k]) for k in CONTEXT_FIELDS if k in job})
                job["image"] = deepcopy(slot["image"])
                job["images"] = deepcopy(item.get("images") or [])
                if "imageSelection" in item:
                    job["imageSelection"] = deepcopy(item["imageSelection"])
                self.articles.append(job)
                self.bindings.append((article, item, job))

    def sync(self):
        parents = {}
        for parent, item, job in self.bindings:
            item["image"] = deepcopy(job.get("image"))
            if job.get("images") or "images" in item:
                item["images"] = deepcopy(job.get("images") or [])
            if "imageSelection" in job:
                item["imageSelection"] = deepcopy(job["imageSelection"])
            else:
                item.pop("imageSelection", None)
            parents[id(parent)] = parent
        for parent in parents.values():
            parent.pop("imageSelection", None)
            cover = next(((index, i["image"]) for index, i in enumerate(parent["roundupItems"])
                          if i.get("image")), None)
            parent["image"] = ({**deepcopy(cover[1]), "roundupItemNumber": cover[0] + 1}
                               if cover and isinstance(cover[1], dict) else
                               cover[1] if cover else None)
        return self.source != self.before


def expand_batches(batches):
    """Keep batch JSON and its per-item job adapter together."""
    return [(path, batch, ImageBatch(articles)) for path, batch, articles in batches]
