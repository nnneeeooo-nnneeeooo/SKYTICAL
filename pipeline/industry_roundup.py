"""Hold verified routine stories and compile one article per six-hour edition.

This queue contains drafts that passed write.py's ordinary evidence gates.
It is never an alternate source-verification path.
"""
from __future__ import annotations

import copy
from datetime import timedelta, timezone

from common import (BASE_PATH, DATA_DIR, SITE_ORIGIN, iso_minute,
                    is_transport_headline, load_json, norm_url, parse_iso, save_json)
from public_article import public_news_path

QUEUE_PATH = DATA_DIR / "industry-roundup-queue.json"
TAIPEI = timezone(timedelta(hours=8))  # Taiwan has no daylight-saving time.
MAX_AGE = timedelta(hours=48)
MAX_ITEMS = 8


def _urls(article: dict) -> set[str]:
    return {norm_url(str(source.get("url") or ""))
            for source in article.get("sources") or []
            if (isinstance(source, dict) and source.get("url")
                and not str(source.get("name") or "").startswith("Archive:"))}


def load_state() -> dict:
    state = load_json(QUEUE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    rows = state.get("items")
    history = state.get("history")
    return {"lastEdition": str(state.get("lastEdition") or ""),
            "items": rows if isinstance(rows, list) else [],
            "history": history if isinstance(history, list) else []}


def add(state: dict, article: dict, now, *, reason: str = "",
        group_id: str = "", event_key: str = "", published_excerpt=False) -> bool:
    """Store a verified article once, even when a later source group repeats it."""
    urls = _urls(article)
    if not urls or (not article.get("facts") and not published_excerpt):
        return False
    for row in state["items"]:
        previous = row.get("article") if isinstance(row, dict) else None
        if isinstance(previous, dict) and (
                urls & _urls(previous)
                or event_key and row.get("eventKey") == event_key):
            return False
    state["items"].append({"enqueuedUtc": iso_minute(now),
                           "routeReason": reason, "sourceGroupId": group_id,
                           "eventKey": event_key, "article": article,
                           "publishedExcerptId": article["id"] if published_excerpt else None})
    return True


def collect_published(state, published_articles, now):
    """Curate exact excerpts of recent published copy, including Muse imports.

    This does not create new reporting or alter originals. Publication, text,
    sources and freshness are checked again by compile_due before inclusion.
    """
    from editorial_policy import publication_route
    included = {item.get("articleId") for article in published_articles
                for item in article.get("roundupItems", []) if isinstance(item, dict)}
    added = 0
    for article in sorted(published_articles, key=lambda a: str(a.get("publishedUtc", "")), reverse=True):
        if (article.get("id") in included or article.get("archived")
                or article.get("articleFormat") == "roundup"
                or article.get("cat") in {"safety", "reg", "feature"}
                or article.get("riskFlags") or not is_transport_headline(article)):
            continue
        try:
            if not timedelta(0) <= now - parse_iso(article.get("publishedUtc", "")) <= MAX_AGE:
                continue
        except (ValueError, TypeError):
            continue
        zh, en = article.get("zh") or {}, article.get("en") or {}
        if not all(block.get("title") and block.get("summary") and block.get("body")
                   for block in (zh, en)):
            continue
        if len("".join(zh["body"])) > 600 or len(" ".join(en["body"]).split()) > 450:
            continue
        group = {"items": [{"title": en["title"] + " " + zh["title"],
                            "summary": en["summary"] + " " + zh["summary"]}]}
        if publication_route(group, {"articleFormat": "brief"}).route != "industry_roundup":
            continue
        added += add(state, copy.deepcopy(article), now, reason="published_short_excerpt",
                     published_excerpt=True)
    return added


def has_group(state: dict, group: dict) -> bool:
    urls = {norm_url(str(item.get("url") or ""))
            for item in group.get("items") or []
            if isinstance(item, dict) and item.get("url")}
    event_key = str(group.get("eventKey") or "")
    return bool(any(
        (urls & _urls(row["article"]))
        or (event_key and row.get("eventKey") == event_key)
        for row in state["items"]
        if isinstance(row, dict) and isinstance(row.get("article"), dict)))


def compile_due(state: dict, now, published_articles: list[dict]) -> dict | None:
    """Publish when two stories are ready, at most once per Taipei six-hour slot."""
    live_urls = set().union(*(_urls(article) for article in published_articles))
    live_by_id = {a.get("id"): a for a in published_articles}
    live_included = {item.get("articleId") for a in published_articles
                     for item in a.get("roundupItems", [])
                     if isinstance(item, dict) and item.get("articleId")}
    live_events = {str(item.get("eventKey"))
                   for article in published_articles
                   for item in [article] + (article.get("roundupItems") or [])
                   if isinstance(item, dict) and item.get("eventKey")}
    retained = []
    history = state.setdefault("history", [])
    for row in state["items"]:
        article = row.get("article") if isinstance(row, dict) else None
        if not isinstance(article, dict) or not _urls(article):
            continue
        try:
            age = now - parse_iso(str(row.get("enqueuedUtc") or ""))
        except (TypeError, ValueError):
            continue
        excerpt_id = row.get("publishedExcerptId")
        original = live_by_id.get(excerpt_id) if excerpt_id else None
        valid_excerpt = bool(original and all(article.get(k) == original.get(k)
                                              for k in ("zh", "en", "sources", "publishedUtc")))
        if valid_excerpt:
            age = max(age, now - parse_iso(original["publishedUtc"]))
        reason = ("invalid_published_excerpt" if excerpt_id and not valid_excerpt else
                  "expired" if age > MAX_AGE else
                  "already_published" if excerpt_id in live_included else
                  "already_published" if (_urls(article) & live_urls
                                           or row.get("eventKey") in live_events) and not valid_excerpt else
                  "invalid_time" if age < timedelta(0) else "")
        if reason:
            history.append({"articleId": str(article.get("id") or ""),
                            "atUtc": iso_minute(now), "reason": reason})
            continue
        retained.append(row)
    state["items"] = retained
    state["history"] = history[-200:]
    local = now.astimezone(TAIPEI)
    edition = f"{local.date().isoformat()}-{local.hour // 6 * 6:02d}"
    if state["lastEdition"] == edition:
        return None
    if len(retained) < 2:
        return None

    selected = retained[:MAX_ITEMS]
    sources, source_urls = [], set()
    body = {"zh": ["以下消息涉及彼此獨立的航空產業事件，並無已知直接關聯。"],
            "en": ["These aviation industry updates concern independent events with no stated direct relationship."]}
    if any(row.get("publishedExcerptId") for row in selected):
        body["zh"][0] += "本期含站內已刊報導摘錄，原文與原始來源保留於來源列表。"
        body["en"][0] += " This edition includes excerpts of previously published reports; original reports and sources are linked below."
    facts = []
    for number, row in enumerate(selected, 1):
        article = row["article"]
        for language in ("zh", "en"):
            block = article.get(language) or {}
            paragraphs = block.get("body") or []
            # Reuse the checked summary, including status/conditions, verbatim.
            paragraph = str(block.get("summary") or "").strip() or next(
                (p.strip() for p in paragraphs if isinstance(p, str) and p.strip()), "")
            if not paragraph:
                return None
            names = [str(source.get("name") or "").split(" — ", 1)[0]
                     for source in article.get("sources") or []
                     if isinstance(source, dict) and source.get("url")
                     and not str(source.get("name") or "").startswith("Archive:")]
            credit = "、".join(dict.fromkeys(names))[:100] if language == "zh" \
                else ", ".join(dict.fromkeys(names))[:100]
            suffix = f"（來源：{credit}）" if language == "zh" else f" (Source: {credit})"
            heading = str(block.get("title") or "").strip()
            body[language].append(f"{number}. {heading}\n{paragraph}{suffix}")
        for source in article.get("sources") or []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            if url and norm_url(url) not in source_urls:
                source_urls.add(norm_url(url))
                sources.append({"name": str(source.get("name") or "")[:160],
                                "url": url})
        if row.get("publishedExcerptId"):
            sources.append({"name": "SKYTICAL — " + article["zh"]["title"],
                            "url": SITE_ORIGIN.rstrip("/") + BASE_PATH + "/" +
                                   public_news_path("news/" + article["id"] + "/")})
        for fact in article.get("facts") or []:
            if isinstance(fact, dict) and fact.get("evidenceScope") == "source":
                facts.append({**fact, "factId": f"F{len(facts) + 1}"})
    if any(not row.get("publishedExcerptId") and not any(norm_url(str(f.get("sourceUrl") or "")) in _urls(row["article"])
                   for f in facts) for row in selected):
        return None
    state["lastEdition"] = edition
    state["items"] = retained[len(selected):]
    count = len(selected)
    source_dates = [str(row["article"].get("sourcePublishedUtc") or "")
                    for row in selected if row["article"].get("sourcePublishedUtc")]
    roundup = {
        "id": f"a-{local.strftime('%Y%m%d')}-industry-roundup-{local.hour // 6 * 6:02d}",
        "publishedUtc": iso_minute(now),
        "cat": "biz", "articleFormat": "roundup", "roundupKind": "industry",
        "roundupItems": [{"articleId": row["article"]["id"],
                          "publishedExcerpt": bool(row.get("publishedExcerptId")),
                          "eventKey": row.get("eventKey", ""),
                          "sourceUrls": sorted(_urls(row["article"]))}
                         for row in selected],
        "primarySource": "Multiple aviation sources",
        "image": None, "sourceImageCandidates": [],
        "zh": {"title": "航空短訊彙整：" + "；".join(
                   row["article"]["zh"]["title"] for row in selected[:2]),
               "summary": f"本期收錄{count}則獨立消息：" + "、".join(
                   row["article"]["zh"]["title"] for row in selected[:3]) + "。",
               "body": body["zh"]},
        "en": {"title": "Aviation briefs: " + "; ".join(
                   row["article"]["en"]["title"] for row in selected[:2]),
               "summary": f"{count} independent updates: " + "; ".join(
                   row["article"]["en"]["title"] for row in selected[:3]) + ".",
               "body": body["en"]},
        "sources": sources, "facts": facts,
        "writer": ("rules:published-news-roundup" if any(row.get("publishedExcerptId") for row in selected)
                   else "rules:verified-industry-roundup"),
        "generationMode": ("published-news-compilation" if any(row.get("publishedExcerptId") for row in selected)
                           else "verified-source-compilation"),
    }
    if source_dates:
        roundup["sourcePublishedUtc"] = max(source_dates)
    return roundup


def save_state(state: dict) -> None:
    save_json(QUEUE_PATH, state)
