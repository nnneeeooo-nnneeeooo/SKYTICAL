"""Select up to five verified results, ranked for article carousels.

The network budget limits jobs; each article displays at most five photos.
Manual galleries use the same `images` list; `image` remains the feed cover.
"""
from datetime import timedelta
from urllib.parse import urlsplit

from common import DATA_DIR, load_json, now_utc, parse_iso, save_json
from image_selection import image_key, manual_image, prepare_image, rejection_reason, stock_usage

CACHE_PATH = DATA_DIR / "image-galleries.json"
VERSION = 3
MAX_IMAGES = 5
JOBS_PER_RUN = 8


def rank(article, image):
    """Event > exact registration > airline/model > location > generic stock."""
    import images
    from image_selection import evidence, model_matches, phrase
    text = evidence(image)
    registration = images.find_registration(article)
    airline, model = images.find_airline(article), images.find_aircraft_type(article)
    same_airline = bool(airline and any(phrase(alias, text) for alias in images._airline_aliases(airline)))
    same_model = bool(model and model_matches(model, text))
    return (image.get("kind") == "event_photo",
            bool(registration and phrase(registration, text)),
            same_airline and same_model, same_model, same_airline,
            image.get("link") in {s.get("url") for s in article.get("sources", []) if isinstance(s, dict)})


def verified(article, candidates, captions=None):
    """Fail closed for every photo, deduplicate resize variants, keep stable ties."""
    found, seen = [], set()
    for raw in candidates:
        image = prepare_image(article, raw, captions)
        if not isinstance(image, dict) or rejection_reason(article, image, captions):
            continue
        key = image_key(image)
        if not key or key in seen:
            continue
        try:
            if urlsplit(str(image.get("url", ""))).scheme not in {"http", "https"}:
                continue
        except ValueError:
            continue
        seen.add(key)
        found.append(image)
    limit = 1 if article.get("_galleryLimit") == 1 else MAX_IMAGES
    return sorted(found, key=lambda image: rank(article, image), reverse=True)[:limit]


def collect(article, usage=None):
    import images
    from source_images import lookup_source_photos
    from image_policy import article_is_airport_operations, article_is_incident
    candidates = [article.get("image"), *(article.get("images") or [])]
    try:
        candidates.extend(lookup_source_photos(article))
    except Exception as exc:
        print(f"gallery: source lookup: {type(exc).__name__}")
    airline = images.find_airline(article)
    model = images.find_aircraft_type(article)
    airport = images.find_airport(article)
    queries = []
    if airport and article_is_airport_operations(article) and not (article_is_incident(article) and model):
        query, tokens, subject = airport
        queries.append((query, tokens, dict(subject=subject, require_all=True,
                                            reject_title_re=images.BAD_AIRPORT_TITLE_RE)))
    elif model:
        query = f"{airline} {model}" if airline else f"{model} aircraft"
        queries.append((query, [airline] if airline else [],
                        dict(subject=query.removesuffix(" aircraft"), require_all=True,
                             prefer_landscape=True, reject_title_re=images.BAD_AIRCRAFT_TITLE_RE)))
    elif airline:
        models = images.preferred_airline_models(article, airline)
        for representative in models[:images.MAX_PROFILE_MODEL_QUERIES]:
            queries.append((f"{airline} {representative}", [airline],
                            dict(subject=f"{airline} {representative}", require_all=True,
                                 required_model=representative, prefer_recent=True,
                                 prefer_landscape=True,
                                 min_year=images._article_year(article)-images.GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS,
                                 reject_title_re=images._BAD_AIRLINE_IMAGE_RE)))
        if not models and images.airline_visual_role(article) != "cargo":
            queries.append((f"{airline} aircraft exterior", [airline],
                            dict(subject=airline, prefer_recent=True,
                                 min_year=images._article_year(article)-images.GENERIC_AIRLINE_MAX_PHOTO_AGE_YEARS,
                                 reject_title_re=images._BAD_AIRLINE_IMAGE_RE)))
    for query, tokens, kwargs in queries:
        try:
            candidates.extend(images.lookup_commons(query, tokens, article=article,
                                                     usage=usage, all_matches=True, **kwargs) or [])
        except Exception as exc:
            print(f"gallery: Commons lookup: {type(exc).__name__}")
    return verified(article, candidates)


def main():
    import images
    from roundup_images import expand_batches
    batches = expand_batches(list(images._recent_batches()))
    cache = load_json(CACHE_PATH, {})
    now = now_utc()
    usage = stock_usage([a for _, _, adapter in batches for a in adapter.articles])
    attempted = 0
    changed_batches = [False] * len(batches)
    # Schedule empty slots first across every recent batch, preserving the
    # adapter/article order within each priority class.
    jobs = [(batch_index, article)
            for batch_index, (_, _, adapter) in enumerate(batches)
            for article in adapter.articles
            if not article.get("editorialImageLocked")
            and not manual_image(article, article.get("image"))
            and article.get("articleFormat") != "roundup"]
    jobs.sort(key=lambda job: bool(job[1].get("image") or job[1].get("images")))
    for batch_index, article in jobs:
        art_id = article.get("id")
        entry = cache.get(art_id) or {}
        try:
            if entry.get("version") == VERSION and parse_iso(entry["retryUtc"]) > now:
                continue
        except (KeyError, TypeError, ValueError):
            pass
        if attempted >= JOBS_PER_RUN:
            break
        attempted += 1
        photos = collect(article, usage)
        cache[art_id] = {"version": VERSION, "checkedUtc": now.isoformat(),
                         "retryUtc": (now + timedelta(hours=24 if photos else 6)).isoformat()}
        if photos and (article.get("images") != photos or article.get("image") != photos[0]):
            previous_usage = stock_usage([article])
            article["images"], article["image"] = photos, photos[0]
            article.pop("imageSelection", None)
            usage.subtract(previous_usage)
            usage.update(stock_usage([article]))
            changed_batches[batch_index] = True
    for index, (path, batch, adapter) in enumerate(batches):
        if adapter.sync() or changed_batches[index]:
            save_json(path, batch)
    if attempted:
        save_json(CACHE_PATH, cache)
    print(f"gallery: checked {attempted} image jobs")
    return 0
