"""Validate ChatGPT-authored articles without a model API or network access.

This checks the publication contract, not the truth of source claims. The
scheduled agent must read and verify original sources before writing a file.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"a-[A-Za-z0-9._-]+\Z")


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def web_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and not parsed.username and not parsed.password
                and not any(c.isspace() for c in value)
                and parsed.hostname not in {"news.google.com", "www.google.com"})
    except ValueError:
        return False


def validate_article(row, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(row, dict):
        raise ValueError("article must be an object")
    if not ID_RE.fullmatch(str(row.get("id", ""))):
        raise ValueError("invalid article id")
    meta = row.get("scheduledNews")
    if not isinstance(meta, dict) or meta.get("version") != 1:
        raise ValueError("scheduledNews.version must be 1")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{5,159}", str(meta.get("eventKey", ""))):
        raise ValueError("invalid eventKey")
    checked = timestamp(meta.get("checkedUtc"))
    publication = timestamp(row.get("publishedUtc"))
    source_time = timestamp(row.get("sourcePublishedUtc"))
    if any(t > now + timedelta(minutes=5) for t in (checked, publication, source_time)):
        raise ValueError("future timestamp")
    if source_time > publication or checked > publication + timedelta(minutes=5):
        raise ValueError("source/check time after publication")
    if row.get("cat") not in {"safety", "reg", "biz", "ops", "mil"}:
        raise ValueError("invalid category")
    if row.get("availableLanguages") != ["zh", "en"]:
        raise ValueError("both zh and en required")
    for lang in ("zh", "en"):
        side = row.get(lang)
        if not isinstance(side, dict):
            raise ValueError(f"missing {lang}")
        for key in ("title", "summary"):
            if not isinstance(side.get(key), str) or not side[key].strip():
                raise ValueError(f"missing {lang}.{key}")
        body = side.get("body")
        if (not isinstance(body, list) or len(body) < 2
                or any(not isinstance(p, str) or not p.strip() for p in body)):
            raise ValueError(f"invalid {lang}.body")
    models = row.get("writerModels")
    if (not isinstance(models, list) or not models
            or any(not isinstance(m, str) or not m.strip() for m in models)
            or row.get("writer") != "scheduled:" + models[0]):
        raise ValueError("explicit, consistent model attribution required")
    sources = row.get("sources")
    if (not isinstance(sources, list) or not sources
            or any(not isinstance(s, dict) or not s.get("name")
                   or not web_url(s.get("url")) for s in sources)):
        raise ValueError("original HTTPS sources required")
    if not row.get("primarySource"):
        raise ValueError("primarySource required")
    source_urls = {s["url"] for s in sources}
    facts = meta.get("facts")
    if (not isinstance(facts, list) or not facts
            or any(not isinstance(f, dict)
                   or not isinstance(f.get("claim"), str) or not f["claim"].strip()
                   or f.get("sourceUrl") not in source_urls for f in facts)):
        raise ValueError("source-bound fact notes required")


def validate_directory(directory, now=None):
    ids, events = {}, {}
    count = 0
    for path in sorted(Path(directory).glob("*.json")):
        scheduled = path.name.startswith("scheduled-")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            if scheduled:
                raise ValueError(f"{path.name}: invalid JSON")
            continue
        rows = payload.get("articles") if isinstance(payload, dict) else None
        if scheduled and (not isinstance(rows, list) or not rows):
            raise ValueError(f"{path.name}: nonempty articles array required")
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                if scheduled:
                    raise ValueError(f"{path.name}: article must be an object")
                continue
            if row.get("archived") is True:
                continue
            is_scheduled = scheduled or "scheduledNews" in row
            article_id = row.get("id")
            if not isinstance(article_id, str):
                if is_scheduled:
                    validate_article(row, now)
                continue
            if article_id in ids and (is_scheduled or ids[article_id][1]):
                raise ValueError(f"duplicate article id: {article_id}")
            ids[article_id] = (path.name, is_scheduled)
            if is_scheduled:
                validate_article(row, now)
                event = row["scheduledNews"]["eventKey"]
                if event in events:
                    raise ValueError(f"duplicate scheduled event: {event}")
                events[event] = path.name
                count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--articles-dir", type=Path, default=ROOT / "data/articles")
    args = parser.parse_args()
    try:
        count = validate_directory(args.articles_dir)
    except ValueError as exc:
        parser.exit(1, f"scheduled news validation failed: {exc}\n")
    print(f"scheduled news: {count} validated")


if __name__ == "__main__":
    main()
