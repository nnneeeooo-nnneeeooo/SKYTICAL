"""Recover a cited publisher's lead photograph before stock-image fallback.

Publisher adapters bind photographs to exact-image captions or alt text.
Official airline/airport pictures are accepted directly with attribution;
subject checks still apply. Keep provenance and never infer a free license.
"""
import re
from html import unescape
from urllib.parse import urljoin, urlsplit
from pathlib import Path
from functools import lru_cache

import requests
from bs4 import BeautifulSoup

from common import USER_AGENT, load_json
from image_captions import clean_description, source_description, image_identity


PARSER_VERSION = 6
_AEROTIME_STOCK_CREDIT_RE = re.compile(
    r"Shutterstock|Wikimedia Commons|Getty Images?|Adobe Stock|"
    r"Unsplash|Pexels|Flickr", re.I)


@lru_cache(maxsize=1)
def official_providers():
    return load_json(Path(__file__).resolve().parent.parent /
                     "config" / "official_image_sources.json", {}).get("providers", {})


def official_provider(url):
    try:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.username or parts.password:
            return None
        host = (parts.hostname or "").lower()
        for domain, name in official_providers().items():
            if host == domain or host.endswith("." + domain):
                return name
    except ValueError:
        pass
    return None


def _image_url(img, page_url):
    """Return one real lazy/srcset/src image URL, resolved to an absolute URL."""
    for attr in ("data-lazy-src", "data-src", "data-original", "src"):
        value = img.get(attr)
        if not isinstance(value, str) or not value.strip():
            continue
        url = urljoin(page_url, unescape(value.strip()))
        identity = image_identity(url)
        if (identity[0] and not re.search(
                r"(?:^|[/_.-])(?:placeholder|spacer|blank|pixel|loading)(?:[/_.-]|$)",
                identity[1], re.I)):
            return url
    for attr in ("data-srcset", "srcset"):
        value = img.get(attr)
        if not isinstance(value, str):
            continue
        # A srcset is a set of sizes for one image; use its largest declared
        # candidate and never turn the responsive variants into a gallery.
        options = []
        for item in value.split(","):
            pieces = item.strip().split()
            if not pieces:
                continue
            width = 0
            if len(pieces) > 1:
                match = re.fullmatch(r"(\d+(?:\.\d+)?)(w|x)", pieces[1])
                if match:
                    width = float(match.group(1)) * (100000 if match.group(2) == "x" else 1)
            options.append((width, pieces[0]))
        for _, raw in sorted(options, reverse=True):
            url = urljoin(page_url, unescape(raw))
            identity = image_identity(url)
            if (identity[0] and not re.search(
                    r"(?:^|[/_.-])(?:placeholder|spacer|blank|pixel|loading)(?:[/_.-]|$)",
                    identity[1], re.I)):
                return url
    return ""


def parse_official_photo(html, source_url):
    """Accept official airline/airport pictures without a license-text gate.

    A caption/alt tied to the exact image still supplies the visual evidence.
    Default to a file photo: official publication alone never proves that the
    photograph depicts the event described by our article.
    """
    provider = official_provider(source_url)
    if not provider:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for meta in soup.select('meta[property="og:image"], meta[name="twitter:image"]'):
        candidates.append(meta.get("content", ""))
    for img in soup.select("article img, main img"):
        candidates.append(_image_url(img, source_url))
    seen = set()
    for raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        url = urljoin(source_url, unescape(raw))
        identity = image_identity(url)
        if not identity[0] or identity in seen:
            continue
        if re.search(r"(?:^|[/_.-])(?:logo|favicon|avatar|sprite|icon|placeholder)(?:[/_.-]|$)",
                     identity[1], re.I):
            continue
        seen.add(identity)
        # Keep the real source-owned caption, never substitute our headline.
        description = source_description(html, url, source_url)
        if not description:
            continue
        subject = description["subject"]
        credit = provider
        for img in soup.find_all("img"):
            img_urls = [img.get(key, "") for key in
                        ("src", "data-src", "data-lazy-src", "data-original")]
            for key in ("srcset", "data-srcset"):
                img_urls.extend(part.strip().split()[0] for part in
                                str(img.get(key, "")).split(",") if part.strip())
            if not any(image_identity(value, source_url) == identity
                       for value in img_urls):
                continue
            figure = img.find_parent("figure")
            caption = figure.find("figcaption") if figure else None
            if caption:
                # Preserve original photographer attribution as well as the
                # official publisher even when it names an outside agency.
                text = " ".join(caption.stripped_strings)
                if text:
                    credit = text
            break
        yield {"url": url, "link": source_url, "provider": provider,
               "credit": credit, "license": None, "kind": "file_photo",
               "subject": subject, "sourceCaption": subject,
               "captionSource": description["captionSource"],
               "matched": "source:official"}


def supported_source(article):
    # Official airline/airport sources outrank secondary publishers.
    for source in article.get("sources") or []:
        url = source.get("url", "") if isinstance(source, dict) else ""
        if official_provider(url):
            return url
    for source in article.get("sources") or []:
        url = source.get("url", "") if isinstance(source, dict) else ""
        parts = urlsplit(url)
        if (parts.scheme == "https" and parts.hostname == "www.aerotime.aero"
                and re.fullmatch(r"/articles/[a-z0-9-]+/?", parts.path)):
            return url
    return None


def can_upgrade(article):
    """Leave manually selected, source and exact-airframe images intact."""
    from image_selection import manual_image
    if manual_image(article, article.get("image")):
        return False
    if article.get("articleFormat") == "roundup":
        return False
    image = article.get("image")
    if (isinstance(image, dict)
            and image.get("provider") == "AeroTime"
            and image.get("matched") == "source:aerotime"):
        return True
    return not image or (
        isinstance(image, dict)
        and image.get("provider") == "Wikimedia Commons"
        and image.get("kind") == "file_photo")


def _cna_image_key(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "imgcdn.cna.com.tw"
            or not re.fullmatch(r"/www/WebPhotos/\d+/\d{8}/[^/]+\.jpg", parts.path)):
        return None
    return re.sub(r"/WebPhotos/\d+/", "/WebPhotos/", parts.path)


def parse_cna_photo(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    lead = soup.find("meta", property="og:image")
    url = lead.get("content", "") if lead else ""
    key = _cna_image_key(url)
    if not key:
        return None
    for figure in soup.select("figure.floatImg"):
        img = figure.find("img")
        caption = figure.find("figcaption")
        if (not img or not caption
                or not any(_cna_image_key(img.get(attr, "")) == key
                           for attr in ("src", "data-src", "data-lazy-src"))):
            continue
        original = " ".join(caption.stripped_strings)
        credit_match = re.search(r"[（(]([^（）()]+提供)[）)]", original)
        reporter = re.search(r"中央社記者[^，。；（）()\s]{1,20}攝(?:影)?", original)
        if not credit_match and not reporter:
            continue
        # Keep position notes such as （中） in an event caption. They are
        # not photographer credits and must not truncate the actual subject.
        first_sentence = re.split(r"[。；]", original, maxsplit=1)[0]
        first_sentence = re.sub(r"[（(][^（）()]*提供[）)]", "", first_sentence)
        subject = clean_description(first_sentence)
        if not subject:
            continue
        # Preserve complete source wording separately; show a short caption.
        if len(subject) > 100:
            continue
        return {"url": url, "link": source_url,
                "subject": subject, "sourceCaption": original,
                "credit": (credit_match.group(1) if credit_match
                           else reporter.group(0)),
                "license": None, "provider": "中央社 CNA",
                "kind": ("file_photo" if re.search(r"資料照|檔案照", original)
                         else "event_photo"),
                "matched": "source:cna"}
    return None


def _aerotime_image_key(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "www.aerotime.aero"
            or not re.fullmatch(
                r"/images/\d{4}/\d{2}/[^/]+\.(?:jpe?g|png|webp)",
                parts.path, re.I)):
        return None
    # WordPress commonly serves ``name-800x500.jpg.webp`` while og:image
    # keeps ``name.jpg``.  Remove the delivery wrapper before normalising the
    # resize suffix so both URLs bind to the exact same source photograph.
    path = re.sub(r"\.webp$", "", parts.path, flags=re.I)
    return re.sub(r"-\d{2,4}x\d{2,4}(?=\.[^.]+$)", "", path)


def _aerotime_credit(value):
    """Keep a real caption credit, including short organisation acronyms."""
    if not isinstance(value, str):
        return ""
    raw = " ".join(BeautifulSoup(unescape(value), "html.parser").stripped_strings)
    raw = re.sub(r"\s+", " ", raw).strip()
    match = re.search(
        r"\b(?:photo\s+)?credit\s*[:：]\s*([^()]+)", raw, re.I)
    candidate = match.group(1).strip() if match else raw
    cleaned = clean_description(candidate)
    if cleaned:
        return cleaned
    # ``clean_description`` deliberately rejects descriptions shorter than
    # four characters.  Credits such as IAI, ANA and GE are nevertheless
    # meaningful attribution.  Accept only acronym-shaped leftovers and keep
    # rejecting generic placeholders such as "Image" or "Photo".
    candidate = re.sub(
        r"^(?:©|credit\s*[:：]|photo\s+credit\s*[:：])\s*", "", candidate,
        flags=re.I).strip()
    if (re.fullmatch(r"[A-Z0-9][A-Z0-9&.+/' -]{1,19}", candidate)
            and candidate.casefold() not in {"image", "photo", "picture"}):
        return candidate
    return ""


def _aerotime_subject(article, image_text=""):
    """Describe an exact article-bound event photo with verified entities."""
    entities = article.get("entities") or {}
    models = (entities.get("aircraft_models")
              if isinstance(entities, dict) else []) or []
    if image_text and models:
        from image_selection import model_matches
        matching = [
            clean_description(str(value))
            for value in models
            if clean_description(str(value))
            and model_matches(str(value), image_text)
        ]
        # Structured entities often contain both a full subtype and a shorter
        # alias.  Keep the most concrete description rather than displaying
        # both (for example, F-15E Strike Eagle instead of F-15E + F-15).
        matching = [
            value for value in matching
            if not any(
                value.casefold() != other.casefold()
                and value.casefold() in other.casefold()
                for other in matching
            )
        ]
        if matching:
            return " ".join(dict.fromkeys(matching))
    values = []
    for key in ("airlines", "aircraft_models", "registration_numbers"):
        group = entities.get(key) if isinstance(entities, dict) else []
        if group:
            value = clean_description(str(group[0]))
            if value and value not in values:
                values.append(value)
    return " ".join(values)


def parse_aerotime_photo(html, source_url, article):
    """Return AeroTime's credited lead event image, never an unbound OG ad."""
    soup = BeautifulSoup(html, "html.parser")
    lead = soup.find("meta", property="og:image")
    url = lead.get("content", "") if lead else ""
    key = _aerotime_image_key(url)
    if not key:
        return None
    for figure in soup.select("figure.cs-entry__post-media"):
        img = figure.find("img")
        caption = figure.find("figcaption")
        if (not img or not caption
                or _aerotime_image_key(img.get("src", "")) != key):
            continue
        caption_text = " ".join(caption.stripped_strings)
        credit = _aerotime_credit(caption_text)
        article_subject = _aerotime_subject(
            article, f"{urlsplit(url).path} {img.get('alt', '')} {caption_text}")
        is_stock = bool(_AEROTIME_STOCK_CREDIT_RE.search(caption_text))
        image_subject = clean_description(img.get("alt", ""))
        subject = image_subject if is_stock else article_subject
        if not credit or not subject:
            continue
        source_caption = caption_text
        if is_stock:
            # For publisher-selected stock, retain the source-owned alt text as
            # evidence so the shared gate can still reject a wrong airline or
            # aircraft.  Never relabel stock as an event photograph.
            source_caption = f"{image_subject}. {caption_text}"
        return {
            "url": url, "link": source_url,
            "subject": subject, "sourceCaption": source_caption,
            "credit": credit, "license": None,
            "provider": "AeroTime",
            "kind": "file_photo" if is_stock else "event_photo",
            "matched": "source:aerotime",
        }
    return None


def lookup_source_photo(article):
    url = supported_source(article)
    if not url:
        return None
    response = requests.get(url, timeout=(5, 15),
                            headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    # Do not accept a redirect to a different article or publisher.
    if response.url.rstrip("/") != url.rstrip("/"):
        return None
    if official_provider(url):
        from image_selection import rejection_reason
        return next((photo for photo in parse_official_photo(response.text, url)
                     if not rejection_reason(article, photo)), None)
    host = urlsplit(url).hostname
    if host in {"www.cna.com.tw", "cna.com.tw"}:
        return parse_cna_photo(response.text, url)
    if host == "www.aerotime.aero":
        return parse_aerotime_photo(response.text, url, article)
    return None


def lookup_source_photos(article):
    """Read all supported cited pages and all caption-bound editorial figures.

    Existing parsers still enforce credits, exact-image captions and source
    identity; sidebar cards, ads and uncaptained thumbnails never become photos.
    """
    from image_selection import rejection_reason, image_key
    found, seen = [], set()
    for source in article.get("sources") or []:
        url = source.get("url", "") if isinstance(source, dict) else ""
        if supported_source({"sources": [{"url": url}]}) != url or not url:
            continue
        try:
            response = requests.get(url, timeout=(5, 15), headers={"User-Agent": USER_AGENT})
            response.raise_for_status()
            if response.url.rstrip("/") != url.rstrip("/"):
                continue
            html = response.text
            if official_provider(url):
                candidates = list(parse_official_photo(html, url))
            else:
                soup = BeautifulSoup(html, "html.parser")
                cna = urlsplit(url).hostname in {"www.cna.com.tw", "cna.com.tw"}
                selector = "figure.floatImg" if cna else "figure.cs-entry__post-media, figure.wp-block-image"
                candidates = []
                for figure in soup.select(selector):
                    img = figure.find("img")
                    if not img or not figure.find("figcaption"):
                        continue
                    # Publishers often leave a tracking/placeholder URL in src
                    # while the actual image lives in a lazy-loading attribute.
                    # Use the best real image field, resolving relative URLs
                    # against the cited page. The adapters below still enforce
                    # each publisher's exact image host/path and caption rules.
                    image_url = _image_url(img, url)
                    if not image_url:
                        continue
                    fragment = BeautifulSoup(str(figure), "html.parser")
                    fragment_img = fragment.find("img")
                    # Bind the adapter to the chosen real image, regardless of
                    # a stale placeholder src retained by the publisher.
                    fragment_img["src"] = image_url
                    if not cna:
                        fragment.find("figure")["class"] = ["cs-entry__post-media"]
                    meta = fragment.new_tag("meta", property="og:image", content=image_url)
                    fragment.insert(0, meta)
                    candidate = (parse_cna_photo(str(fragment), url) if cna else
                                 parse_aerotime_photo(str(fragment), url, article))
                    if candidate:
                        candidates.append(candidate)
            for photo in candidates:
                key = image_key(photo)
                if key not in seen and not rejection_reason(article, photo):
                    found.append(photo)
                    seen.add(key)
        except (requests.RequestException, ValueError, TypeError, KeyError):
            continue
    return found
