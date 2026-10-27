"""Public article identities must not encode the private publishing channel."""
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit


def public_article_id(article_id: str) -> str:
    parts = article_id.split("-")
    if "manual" not in [part.lower() for part in parts]:
        return article_id
    # Keep established dates and story slugs; never expose workflow markers.
    result = "-".join(part for part in parts
                      if part.lower() not in {"manual", "recovery"})
    if result in {"", "a"}:
        return "a-" + hashlib.sha256(article_id.encode()).hexdigest()[:16]
    return result if result.startswith("a-") else "a-" + result


def public_news_path(path: str) -> str:
    return re.sub(r"^(news/)([^/]+)(/|$)",
                  lambda match: match[1] + public_article_id(match[2]) + match[3],
                  path)


def public_asset_url(url: str, origin: str, base: str = "") -> str:
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc != urlsplit(origin).netloc:
        return url
    prefix = base + "/assets/"
    if not parsed.path.startswith(prefix):
        return url
    name = parsed.path[len(prefix):]
    if not name.startswith("a-") or "/" in name:
        return url
    return urlunsplit(parsed._replace(path=prefix + public_article_id(name)))


def public_site_url(url: str, origin: str, base: str = "") -> str:
    url = public_asset_url(url, origin, base)
    parsed = urlsplit(url)
    if parsed.netloc and parsed.netloc != urlsplit(origin).netloc:
        return url
    for prefix in (base + "/", base + "/en/"):
        if parsed.path.startswith(prefix + "news/"):
            path = prefix + public_news_path(parsed.path[len(prefix):])
            return urlunsplit(parsed._replace(path=path))
    return url
