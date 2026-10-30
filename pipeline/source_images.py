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


PARSER_VERSION = 5
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
        candidates.append(img.get("src") or img.get("data-src") or "")
    seen = set()
    for raw in candidates:
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
            if not any(image_identity(img.get(key, ""), source_url) == identity
                       for key in ("src", "data-src", "data-lazy-src")):
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
        if (parts.scheme == "https" and parts.hostname in
                {"www.cna.com.tw", "cna.com.tw"}
                and re.fullmatch(r"/news/[a-z]+/\d+\.aspx", parts.path)):
            return url
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
        if not img or not caption or _cna_image_key(img.get("src", "")) != key:
            continue
        original = " ".join(caption.stripped_strings)
        credit_match = re.search(r"[（(]([^（）()]+提供)[）)]", original)
        # Only supplied publicity photos are supported by this adapter.
        if not credit_match:
            continue
        subject = clean_description(re.split(r"[（(]", original, maxsplit=1)[0])
        if not subject:
            continue
        # Preserve complete source wording separately; show a short caption.
        subject = re.split(r"[。；]", subject, maxsplit=1)[0].strip()
        if len(subject) > 100:
            continue
        return {"url": url, "link": source_url,
                "subject": subject, "sourceCaption": original,
                "credit": credit_match.group(1), "provider": "中央社 CNA",
                "kind": "event_photo", "matched": "source:cna"}
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
