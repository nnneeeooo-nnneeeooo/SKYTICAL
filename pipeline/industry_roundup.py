"""Hold verified routine stories and compile one article per six-hour edition.

This queue contains drafts that passed write.py's ordinary evidence gates.
It is never an alternate source-verification path.
"""
from __future__ import annotations

from datetime import timedelta, timezone

from common import DATA_DIR, iso_minute, load_json, norm_url, parse_iso, save_json

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
        group_id: str = "", event_key: str = "") -> bool:
    """Store a verified article once, even when a later source group repeats it."""
    urls = _urls(article)
    if not urls or not article.get("facts"):
        return False
    for row in state["items"]:
        previous = row.get("article") if isinstance(row, dict) else None
        if isinstance(previous, dict) and (
                urls & _urls(previous)
                or event_key and row.get("eventKey") == event_key):
            return False
    state["items"].append({"enqueuedUtc": iso_minute(now),
                           "routeReason": reason, "sourceGroupId": group_id,
                           "eventKey": event_key, "article": article})
    return True


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
        reason = ("expired" if age > MAX_AGE else
                  "already_published" if (_urls(article) & live_urls
                                           or row.get("eventKey") in live_events) else
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
    facts = []
    for number, row in enumerate(selected, 1):
        article = row["article"]
        for language in ("zh", "en"):
            block = article.get(language) or {}
            paragraphs = block.get("body") or []
            paragraph = next((p.strip() for p in paragraphs
                              if isinstance(p, str) and p.strip()), "")
            if not paragraph:
                paragraph = str(block.get("summary") or "").strip()
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
        for fact in article.get("facts") or []:
            if isinstance(fact, dict) and fact.get("evidenceScope") == "source":
                facts.append({**fact, "factId": f"F{len(facts) + 1}"})
    if any(not any(norm_url(str(f.get("sourceUrl") or "")) in _urls(row["article"])
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
        "writer": "rules:verified-industry-roundup",
        "generationMode": "verified-source-compilation",
    }
    if source_dates:
        roundup["sourcePublishedUtc"] = max(source_dates)
    return roundup


def save_state(state: dict) -> None:
    save_json(QUEUE_PATH, state)
