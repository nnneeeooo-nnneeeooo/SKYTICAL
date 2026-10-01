"""Read-boundary normalization for persisted SKYTICAL article records.

Historical JSON is append-only and spans multiple schema generations.  This
module turns any dictionary-shaped article row into the current read contract
without rewriting the archive on disk. Required publication identity and
source fields are deliberately not invented; build.py still rejects rows that
lack those essentials.
"""
from __future__ import annotations

from copy import deepcopy

ARTICLE_SCHEMA_VERSION = 1

_OPTIONAL_LIST_FIELDS = (
    "availableLanguages",
    "writerModels",
    "sourceImageCandidates",
    "facts",
    "riskFlags",
    "entityEvidence",
)


def _language_block(value) -> dict:
    block = deepcopy(value) if isinstance(value, dict) else {}
    body = block.get("body")
    if isinstance(body, str):
        body = [body]
    elif not isinstance(body, list):
        body = []
    return {
        **block,
        "title": str(block.get("title") or ""),
        "summary": str(block.get("summary") or ""),
        "body": [str(item) for item in body if str(item).strip()],
    }


def normalize_article_record(raw) -> dict | None:
    """Return a current-schema copy of one persisted article row.

    Optional fields always exist after this boundary. The function never
    mutates the caller's object and never fabricates required identity,
    timestamp, or source evidence.
    """
    if not isinstance(raw, dict):
        return None

    article = deepcopy(raw)
    article["schemaVersion"] = ARTICLE_SCHEMA_VERSION
    article["archived"] = article.get("archived") is True
    article["primarySource"] = str(article.get("primarySource") or "")
    article["image"] = article.get("image")
    article["zh"] = _language_block(article.get("zh"))
    article["en"] = _language_block(article.get("en"))

    sources = article.get("sources")
    article["sources"] = list(sources) if isinstance(sources, list) else []

    for key in _OPTIONAL_LIST_FIELDS:
        value = article.get(key)
        article[key] = list(value) if isinstance(value, list) else []

    entities = article.get("entities")
    article["entities"] = deepcopy(entities) if isinstance(entities, dict) else {}
    airlines = article["entities"].get("airlines")
    article["entities"]["airlines"] = (
        list(airlines) if isinstance(airlines, list) else []
    )

    article["writer"] = (
        str(article.get("writer")) if isinstance(article.get("writer"), str)
        else None
    )
    article["articleFormat"] = (
        article.get("articleFormat")
        if article.get("articleFormat") in ("full", "brief", "roundup")
        else "full"
    )
    return article
