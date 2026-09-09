"""Evidence-based image gate shared by selection, cache repair and rendering.

Search queries and generated subjects are NOT evidence of what a photo shows.
This module performs no network I/O; uncertain automatic images fail closed.
"""
from __future__ import annotations

import re
from collections import Counter
from html import unescape
from urllib.parse import unquote, urlsplit

POLICY_VERSION = 2
MAX_STOCK_REUSE = 2  # per rolling seven-day news window; brand art is exempt


def normalized(value):
    return re.sub(r"[^\w]+", " ", unquote(unescape(str(value or ""))).casefold(),
                  flags=re.UNICODE).replace("_", " ").strip()


def phrase(value, text):
    value, text = normalized(value), normalized(text)
    if not value:
        return False
    if re.search(r"[一-鿿]", value):
        return value in text
    return f" {value} " in f" {text} "


def image_key(image):
    """Collapse Commons thumbnail hosts/sizes and safe CDN resize variants."""
    url = image.get("url", "") if isinstance(image, dict) else image
    try:
        p = urlsplit(str(url or ""))
    except ValueError:
        return ""
    path = unquote(p.path)
    if p.hostname in {"upload.wikimedia.org", "thumb.wikimedia.org"}:
        path = path.replace("/thumb/", "/")
        path = re.sub(r"/\d+px-[^/]+$", "", path)
        return "commons:" + path
    path = re.sub(r"-(?:\d{2,4}x\d{2,4}|scaled)(?=\.[^.]+$)", "", path)
    # Keep query parameters that may identify distinct files (CAA attachments).
    from urllib.parse import parse_qsl, urlencode
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query)
                             if not k.startswith("utm_")
                             and k not in {"w", "h", "width", "height", "quality"}))
    return f"{p.hostname or ''}{path}" + (f"?{query}" if query else "")


def manual_image(article, image):
    return (str(article.get("writer") or "").split(":")[0] == "manual"
            or isinstance(image, dict) and image.get("provider") == "manual")


def prepare_image(article, image, captions=None):
    """Promote a legacy source URL only with its exact-image source caption."""
    if isinstance(image, dict) or not image or manual_image(article, image):
        return image
    if captions is None:
        from common import DATA_DIR, load_json
        captions = load_json(DATA_DIR / "image-captions.json", {}).get("images", {})
    cached = captions.get(image) or {}
    sources = {s.get("url") for s in article.get("sources", []) if isinstance(s, dict)}
    if (cached.get("link") not in sources or not cached.get("subject")
            or cached.get("captionSource") not in
            {"source-image-metadata", "og:image:alt"}):
        return None
    return {"url": image, "link": cached["link"], "provider": cached.get("provider"),
            "subject": cached["subject"], "sourceCaption": cached["subject"],
            "kind": "file_photo", "matched": "source:caption",
            "captionSource": cached["captionSource"]}


def evidence(image):
    """Only source-owned metadata, never our matched query or subject label."""
    if image.get("provider") in {"Wikimedia Commons", "Planespotters.net"}:
        parts = [image.get("description", "")]
        for key in ("url", "link"):
            try:
                path = unquote(urlsplit(str(image.get(key) or "")).path)
            except ValueError:
                continue
            parts.append(path.replace("_", " "))
        return " ".join(parts)
    return str(image.get("sourceCaption") or "")


def model_matches(model, text):
    """Preserve variants: A350-900 != -1000, Gripen F != NG, MAX 7 != MAX 8."""
    model = re.sub(r"^(?:Airbus|Boeing|Embraer)\s+", "", model, flags=re.I)
    # Manufacturer subtype digits are compatible within the named series.
    model = re.sub(r"(A\d{3})-([2389])\d{2}\b", r"\g<1>-\g<2>00", model)
    text = re.sub(r"(A\d{3})[ _-]([2389])\d{2}\b", r"\g<1>-\g<2>00", text, flags=re.I)
    aliases = {"MH-139A Grey Wolf": ["MH-139A", "Grey Wolf"],
               "MH-60S Seahawk": ["MH-60S"], "B737 MAX": ["737 MAX"],
               "F-15EX Eagle II": ["F-15EX", "F15EX"],
               "F-4 Phantom": ["F-4 Phantom", "F-4E Phantom"]}
    if any(phrase(a, text) for a in aliases.get(model, [])):
        return True
    text = re.sub(r"\bB(7\d7)(?=F|\b)", r"\1", text, flags=re.I)
    if phrase(model, text):
        return True
    # A bare family is valid only if the article itself names just that family.
    if re.fullmatch(r"A\d{3}|7\d7", model, re.I):
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(model)}(?=[\W_]|neo|F\b|$)", text, re.I))
    if model.lower() == "a330neo":
        return bool(re.search(r"\bA330(?:neo|[- ](?:8|9)\d{2})\b", text, re.I))
    return False


def verified_cargo_model(article):
    """True only when structured entities name a freighter subtype."""
    entities = article.get("entities") or {}
    models = (entities.get("aircraft_models")
              if isinstance(entities, dict) else []) or []
    return any(re.search(
        r"(?:P2F|BCF|BDSF|ERF|freighter|cargo)|(?:[/ -]|\d)C?F\)?$",
        str(model), re.I) for model in models)


def rejection_reason(article, raw, captions=None):
    from image_policy import (article_context_text, article_headline_text,
                              article_is_airport_operations, article_is_cabin_story,
                              article_is_drone_story, article_is_incident,
                              BAD_AIRLINE_INTERIOR_RE)
    import images
    if article.get("articleFormat") == "roundup":
        return "roundup"
    if manual_image(article, raw):
        return None
    im = prepare_image(article, raw, captions)
    if not isinstance(im, dict) or not im.get("url"):
        return "missing-source-evidence"
    ctx = article_context_text(article)
    head = article_headline_text(article)
    ev = evidence(im)
    source_urls = {s.get("url") for s in article.get("sources", []) if isinstance(s, dict)}
    source_bound = im.get("link") in source_urls and bool(im.get("sourceCaption"))
    reg = images.find_registration(article)
    if im.get("provider") == "Planespotters.net":
        # Registration identifies an airframe, not its current livery/product.
        if not reg or im.get("matched") != reg:
            return "registration-mismatch"
        if article_is_airport_operations(article) and not article_is_incident(article):
            return "airframe-not-airport-facility"
        if re.search(r"彩繪|藝術機|塗裝|\blivery\b|客艙|座椅", head, re.I):
            return "airframe-role-unverified"
        if (re.search(r"貨機|貨運|freighter|cargo", head, re.I)
                and not verified_cargo_model(article)):
            return "airframe-role-unverified"
        carrier = images.find_airline(article)
        if carrier and not any(phrase(alias, ev) for alias in images._airline_aliases(carrier)):
            return "airframe-operator-unverified"
        return None
    if not ev.strip():
        return "missing-source-evidence"
    # Documented event images have their own caption, not a generic stock label.
    if im.get("kind") == "event_photo" and not source_bound:
        return "unbound-event-photo"
    stock = not source_bound or im.get("kind") != "event_photo"
    if stock and re.search(r"\b(?:map|logo|diagram|schematic|wreckage|debris|statue|"
                           r"museum|kabiin|mock up|mockup|rendering|model kit)\b|muuseum", normalized(ev)):
        return "non-documentary-stock"
    cabin = article_is_cabin_story(article)
    cabin_evidence = re.search(r"cabin|interior|seat|suite|economy|business.class|頭墊|座椅|客艙|套房", ev, re.I)
    if stock and cabin_evidence and not cabin and not re.search(r"Qsuite|套房|頭等艙|腿部空間", ctx, re.I):
        return "unrelated-interior"
    airline = images.find_airline(article)
    model = images.find_aircraft_type(article)
    airport = images.find_airport(article)
    matched = str(im.get("matched") or "")
    # Exact event caption can describe seats/ceremony without repeating model.
    if source_bound and im.get("kind") == "event_photo":
        event_evidence = f"{ev} {im.get('subject') or ''}"
        if airline and not any(
                phrase(a, event_evidence)
                for a in images._airline_aliases(airline)):
            return "source-airline-unverified"
        return None
    headline_model = images.find_aircraft_type({"en": {"title": head},
                                              "entities": article.get("entities") or {}})
    # A customer, certifier or comparison model in the summary must not replace
    # a named headline organization (e.g. JCB Aero -> generic Boeing 737).
    if not airline and not headline_model:
        organizations = (article.get("entities") or {}).get("organizations") or []
        named = [str(o) for o in organizations if phrase(o, head)]
        if named:
            primary = min(named, key=lambda o: (normalized(head).find(normalized(o)), -len(o)))
            if not phrase(primary, ev) and matched not in {
                    "topic:drone", "topic:volcano:anak-krakatau"}:
                return "headline-organization-unverified"
    if (re.search(r"新.*座椅|套房|頭等艙|premium economy|first class|\bsuites?\b", head, re.I)
            and not cabin_evidence):
        return "cabin-product-unverified"
    if matched == "topic:volcano:anak-krakatau":
        from image_policy import ANAK_KRAKATAU_RE
        return None if ANAK_KRAKATAU_RE.search(head) and ANAK_KRAKATAU_RE.search(ev) else "volcano-mismatch"
    if matched == "topic:drone":
        if (not article_is_drone_story(article) or model or
                re.search(r"military|defen[cs]e|attack|combat|delivery|logistics|medical|cargo|freight|Amazon|軍|國防|攻擊|作戰|配送|物流|醫藥|醫療|貨運", ctx, re.I)):
            return "generic-drone-mismatch"
        return None if re.search(r"quadcopter|drone", ev, re.I) else "drone-unverified"
    # Specific livery, cargo conversion and national operators need evidence too.
    if stock and re.search(r"彩繪|藝術機|塗裝|\blivery\b|\bliveries\b|Sorayama", head, re.I):
        if not re.search(r"livery|liveries|Sorayama|Mountain Ascent|ski|彩繪|塗裝", ev, re.I):
            return "special-livery-unverified"
    if stock and re.search(r"freighter|cargo|客改貨|貨機|貨運", head, re.I):
        if not re.search(r"freighter|cargo|P2F|BCF|BDSF|7\d7[- ]?\d*(?:F|ERF)\b|貨", ev, re.I):
            return "cargo-role-unverified"
    if model:
        if not model_matches(model, ev) and not (reg and phrase(reg, ev)):
            return "aircraft-model-mismatch"
        for pattern, required in (
            (r"Turkish|土耳其", r"Turkish|Turkey|Türk|土耳其"),
            (r"Greek|Greece|希臘", r"Greek|Greece|Hellenic|希臘"),
            (r"Taiwan|臺灣|台灣", r"Taiwan|ROC|Republic of China|臺灣|台灣"),
        ):
            if re.search(r"fighter|F-?\d|戰機", head, re.I) and re.search(pattern, head, re.I) and not re.search(required, ev, re.I):
                return "military-operator-unverified"
    if airline:
        if not any(phrase(alias, ev) for alias in images._airline_aliases(airline)):
            return "airline-mismatch"
        if not model and im.get("provider") == "Wikimedia Commons":
            try:
                if not images._article_year(article)-10 <= int(im.get("photoYear")) <= images._article_year(article):
                    return "stock-age"
            except (TypeError, ValueError):
                return "stock-age-unknown"
        return None
    if model:
        return None
    if airport and (article_is_airport_operations(article) or
                    re.search(r"機場|\bairport\b", head, re.I)):
        tokens = airport[1]
        if all(phrase(t, ev) for t in tokens):
            return None
        # Resolve the full captioned name through the same reviewed registry.
        from airport_codes import resolve_airport
        target = resolve_airport(airport[0])
        if target and target.get("code"):
            for caption in (im.get("description"), im.get("sourceCaption")):
                row = resolve_airport(str(caption or ""))
                if row and row.get("code") == target["code"]:
                    return None
        return "airport-mismatch"
    org = images.find_org(article)
    if org:
        if not any(phrase(t, ev) for t in org[1]):
            return "organization-mismatch"
        if not re.search(r"headquarters|headquarter|總部|entrance|civil aeronautics administration|NTSB", ev, re.I):
            return "organization-subject-unverified"
        try:
            if not images._article_year(article)-10 <= int(im.get("photoYear")) <= images._article_year(article):
                return "stock-age"
        except (TypeError, ValueError):
            return "stock-age-unknown"
        return None
    return "no-primary-visual-entity"


def stock_usage(articles):
    return Counter(image_key(a["image"]) for a in articles
                   if isinstance(a.get("image"), dict)
                   and a["image"].get("kind") == "file_photo"
                   and not manual_image(a, a["image"]))


def enforce_recent(articles_dir=None, cache_path=None):
    """Repair every fresh image before budgets; invalidate rejected cache entries."""
    import images
    from common import DATA_DIR, load_json, save_json
    captions = load_json(DATA_DIR / "image-captions.json", {}).get("images", {})
    cache_path = cache_path or images.CACHE_PATH
    cache = load_json(cache_path, {})
    entries = cache.setdefault("articles", {})
    if articles_dir is None:
        batches = list(images._recent_batches())
    else:
        batches = []
        for p in sorted(articles_dir.glob("*.json"), reverse=True):
            b = load_json(p, {})
            if isinstance(b, dict):
                batches.append((p, b, b.get("articles") or []))
    rows = []
    for p, b, aa in batches:
        for a in aa:
            try:
                if images.parse_iso(a["publishedUtc"]) >= images.now_utc()-images.timedelta(days=7):
                    rows.append((a, p, b))
            except (KeyError, TypeError, ValueError):
                continue
    rows.sort(key=lambda row: (row[0].get("publishedUtc", ""), row[0].get("id", "")), reverse=True)
    usage, changed, decisions = Counter(), set(), []
    for a, p, b in rows:
        raw = a.get("image")
        if not raw:
            continue
        reason = rejection_reason(a, raw, captions)
        im = prepare_image(a, raw, captions)
        key = image_key(im)
        is_stock = isinstance(im, dict) and im.get("kind") == "file_photo" and not manual_image(a, im)
        if not reason and is_stock and usage[key] >= MAX_STOCK_REUSE:
            reason = "stock-reuse-limit"
        if reason:
            # Retain source candidates for later caption recovery/retries.
            if isinstance(raw, str) and not manual_image(a, raw):
                a.setdefault("sourceImageCandidates", [{"url": raw, "sources": a.get("sources", [])}])
            a.pop("image", None)
            entries.pop(a.get("id"), None)
            a["imageSelection"] = {"policyVersion": POLICY_VERSION, "status": "fallback", "reason": reason}
            changed.add(p)
            decisions.append({"id": a.get("id"), "reason": reason})
        else:
            if is_stock:
                usage[key] += 1
            if im != raw:
                a["image"] = im
                changed.add(p)
            if a.pop("imageSelection", None) is not None:
                changed.add(p)
    for p, b, aa in batches:
        if p in changed:
            save_json(p, b)
    if decisions and cache != load_json(cache_path, {}):
        save_json(cache_path, cache)
    print(f"image selection: {len(rows)} recent articles; {len(decisions)} rejected; {len(changed)} batches repaired")
    return decisions


if __name__ == "__main__":
    enforce_recent()
