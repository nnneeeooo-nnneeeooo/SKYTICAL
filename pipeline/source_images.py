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
    return None


def can_upgrade(article):
    """Leave manually selected, source and exact-airframe images intact."""
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
    return parse_cna_photo(response.text, url)
