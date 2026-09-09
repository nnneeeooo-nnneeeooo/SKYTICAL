"""Recover a cited publisher's lead photograph before stock-image fallback.

Publisher adapters must bind the lead metadata image to a captioned body
figure. An unrelated sidebar image or an uncaptioned Open Graph image is not
enough. Keep the original caption for provenance; never infer a free license.
"""
import re
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from common import USER_AGENT
from image_captions import clean_description


def supported_source(article):
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
    path = re.sub(r"-\d{2,4}x\d{2,4}(?=\.[^.]+$)", "", parts.path)
    return re.sub(r"\.webp$", "", path, flags=re.I)


def _aerotime_subject(article):
    """Describe an exact article-bound event photo with verified entities."""
    entities = article.get("entities") or {}
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
        credit = clean_description(" ".join(caption.stripped_strings))
        subject = _aerotime_subject(article)
        if not credit or not subject:
            continue
        return {
            "url": url, "link": source_url,
            "subject": subject, "sourceCaption": credit,
            "credit": credit, "license": None,
            "provider": "AeroTime", "kind": "event_photo",
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
    host = urlsplit(url).hostname
    if host in {"www.cna.com.tw", "cna.com.tw"}:
        return parse_cna_photo(response.text, url)
    if host == "www.aerotime.aero":
        return parse_aerotime_photo(response.text, url, article)
    return None
