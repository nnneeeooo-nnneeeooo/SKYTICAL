"""Validate ChatGPT-authored articles without a model API or network access.

This checks the publication contract, not the truth of source claims. The
scheduled agent must read and verify original sources before writing a file.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ID_RE = re.compile(r"a-[A-Za-z0-9._-]+\Z")
ARTICLE_CLOCKS = (
    "publishedUtc", "sortUtc", "sortDateOnly", "sourcePublishedUtc", "sourceDateOnly", "updatedUtc",
)
IMAGE_FIELDS = ("image", "images", "attachments", "sourceImageCandidates", "imageContext")


def _image_fields(row):
    items = row.get("roundupItems") or []
    return (
        *(row.get(key) for key in IMAGE_FIELDS),
        tuple(tuple(item.get(key) for key in IMAGE_FIELDS)
              for item in items if isinstance(item, dict)),
    )


def _article_copy(row):
    text_fields = ("title", "summary", "body")
    return (
        *(tuple((row.get(lang) or {}).get(key) or "" for key in text_fields)
          for lang in ("zh", "en")),
        row.get("primarySource"), row.get("sources") or [],
        [{key: value for key, value in item.items()
          if key not in IMAGE_FIELDS and key != "editorialImageLocked"}
         for item in row.get("roundupItems") or [] if isinstance(item, dict)],
    )


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return result


def validate_chronology(row, previous=None, *, manual=False, now=None):
    """Check new or modified date fields without rewriting the legacy archive."""
    now = now or datetime.now(timezone.utc)
    changed = {key for key in ARTICLE_CLOCKS
               if previous is None or row.get(key) != previous.get(key)}
    if previous is not None:
        check_time_changed = (
            (row.get("scheduledNews") or {}).get("checkedUtc")
            != (previous.get("scheduledNews") or {}).get("checkedUtc")
            or row.get("checkedUtc") != previous.get("checkedUtc")
        )
        same_copy = _article_copy(row) == _article_copy(previous)
        if same_copy and _image_fields(row) != _image_fields(previous):
            if changed or check_time_changed:
                raise ValueError("image-only edits must preserve article timestamps")
        if not same_copy and changed.intersection({"publishedUtc", "sortUtc", "sortDateOnly"}):
            raise ValueError("content updates must preserve first publication and sort time")
        if not changed:
            return
    if manual and previous is None and not row.get("sortUtc"):
        raise ValueError("new manual or scheduled articles require sortUtc")

    publication = timestamp(row.get("publishedUtc"))
    sort_time = timestamp(row["sortUtc"]) if row.get("sortUtc") else publication
    update = timestamp(row["updatedUtc"]) if row.get("updatedUtc") else publication
    source = timestamp(row["sourcePublishedUtc"]) if row.get("sourcePublishedUtc") else None
    if sort_time > publication:
        raise ValueError("sortUtc must be at or before publishedUtc")
    if update < publication:
        raise ValueError("updatedUtc must be at or after publishedUtc")
    if source and source > update:
        raise ValueError("sourcePublishedUtc must be at or before publication or update")
    if update > now + timedelta(minutes=5):
        raise ValueError("future publication or update time")
    if "sourceDateOnly" in row and (type(row["sourceDateOnly"]) is not bool or source is None):
        raise ValueError("sourceDateOnly requires a boolean and a source timestamp")
    if manual and source and "sourceDateOnly" not in row and (
            previous is None or "sourcePublishedUtc" in changed):
        raise ValueError("sourceDateOnly must record the source's time precision")
    if row.get("sourceDateOnly") and source.astimezone(timezone.utc).time() != datetime.min.time():
        raise ValueError("date-only sources use 00:00:00Z on the reported date")
    if "sortDateOnly" in row and (type(row["sortDateOnly"]) is not bool or not row.get("sortUtc")):
        raise ValueError("sortDateOnly requires a boolean and a sort timestamp")
    if row.get("sortDateOnly") and sort_time.astimezone(timezone.utc).time() != datetime.min.time():
        raise ValueError("date-only timeline entries use 00:00:00Z on the reported date")
    if manual and previous is None and row.get("sourceDateOnly") and sort_time == source:
        if row.get("sortDateOnly") is not True:
            raise ValueError("a date-only timeline entry must preserve sortDateOnly")


def validate_chronology_diff(base):
    def git(*args, check=True):
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        if check and result.returncode:
            raise ValueError(result.stderr.strip())
        return result.stdout if result.returncode == 0 else ""

    directories = ("data/articles", "data/editorial-overrides")
    paths = set(git("diff", "--name-only", base, "--", *directories).splitlines())
    paths.update(git("ls-files", "--others", "--exclude-standard", "--", *directories).splitlines())

    def rows(content):
        data = json.loads(content) if content else {}
        if isinstance(data, dict):
            return {row["id"]: row for row in data.get("articles", [data])
                    if isinstance(row, dict) and isinstance(row.get("id"), str)}
        return {}

    count = 0
    for name in sorted(paths):
        path = ROOT / name
        if path.suffix != ".json" or not path.is_file():
            continue
        overriding = name.startswith("data/editorial-overrides/")
        previous = rows(git("show", f"{base}:{name}", check=False))
        for article_id, row in rows(path.read_text(encoding="utf-8")).items():
            original = previous.get(article_id)
            if overriding and original is None:
                matches = git("grep", "-lF", "-e", f'"{article_id}"', base,
                              "--", "data/articles", check=False)
                for location in matches.splitlines():
                    original = rows(git("show", location)).get(article_id)
                    if original:
                        break
            if original == row or row.get("archived") is True:
                continue
            manual = (path.name.startswith(("manual-", "scheduled-"))
                      or str(row.get("writer", "")).startswith(("manual:", "scheduled:"))
                      or "scheduledNews" in row)
            if original is None and not manual:
                continue
            try:
                validate_chronology(row, original, manual=manual)
            except ValueError as exc:
                raise ValueError(f"{name} ({article_id}): {exc}") from exc
            count += 1
    return count


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
    # A follow-up keeps publishedUtc; its newer sources are bounded by updatedUtc.
    latest = publication
    if row.get("updatedUtc") is not None:
        latest = max(publication, timestamp(row["updatedUtc"]))
    if any(t > now + timedelta(minutes=5)
           for t in (checked, publication, source_time, latest)):
        raise ValueError("future timestamp")
    if source_time > latest or checked > latest + timedelta(minutes=5):
        raise ValueError("source/check time after publication or update")
    if row.get("cat") not in {"safety", "reg", "biz", "ops", "mil", "feature"}:
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
    parser.add_argument("--chronology-base", help="validate changes from this Git ref")
    args = parser.parse_args()
    try:
        if args.chronology_base:
            count = validate_chronology_diff(args.chronology_base)
            print(f"news chronology: {count} changed articles validated")
            return
        count = validate_directory(args.articles_dir)
    except ValueError as exc:
        parser.exit(1, f"scheduled news validation failed: {exc}\n")
    print(f"scheduled news: {count} validated")


if __name__ == "__main__":
    main()
