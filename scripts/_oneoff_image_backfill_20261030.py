#!/usr/bin/env python3
"""One-time, bounded, source-backed image backfill; remove before merging."""
import concurrent.futures
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import images
from image_selection import image_key

START = datetime(2026, 9, 30, 0, tzinfo=timezone.utc)
END = datetime(2026, 10, 24, 0, tzinfo=timezone.utc)
OFFICIAL = {
    "mediarenditions.airbus.com": "Airbus",
    "mediaassets.airbus.com": "Airbus",
    "www.airbus.com": "Airbus",
    "www.eurocontrol.int": "EUROCONTROL",
    "images.nasa.gov": "NASA",
    "www.nasa.gov": "NASA",
    "boeing.mediaroom.com": "Boeing",
    "www.faa.gov": "FAA",
}
images.TIMEOUT = (4, 10)
def in_window(a):
    try:
        when = datetime.fromisoformat(str(a.get("publishedUtc") or "").replace("Z", "+00:00"))
        return START <= when.astimezone(timezone.utc) < END
    except (TypeError, ValueError):
        return False

def official_candidate(a):
    for c in a.get("sourceImageCandidates") or []:
        if not isinstance(c, dict):
            continue
        url = str(c.get("url") or "")
        name = OFFICIAL.get((urlsplit(url).hostname or "").lower())
        urls = {s.get("url") for s in a.get("sources") or [] if isinstance(s, dict)}
        if not name or not any(s.get("url") in urls for s in c.get("sources") or [] if isinstance(s, dict)):
            continue
        if not re.search(r"\.(?:jpe?g|png|webp)(?:\?|$)|/resize\?", url, re.I):
            continue
        return {
            "url": url,
            "link": next((s["url"] for s in c["sources"] if s.get("url") in urls), ""),
            "credit": name,
            "license": None,
            "provider": name,
            "kind": "source_image",
            "matched": "editorial:official-source-image",
            "subject": (a.get("en") or {}).get("title") or (a.get("zh") or {}).get("title"),
            "description": "本篇所引官方新聞稿的原始配圖；圖片拍攝時間及是否為事件現場以原發布單位說明為準。",
            "curated": True,
        }
    return None

def resolve(item):
    path, a = item
    id_ = a.get("id")
    try:
        photo = official_candidate(a)
        if photo is None:
            photo = images.resolve_image(a, usage=Counter())
        if photo and images.existing_image_matches(a, photo):
            return (path, id_, photo, "matched")
        return (path, id_, None, "no-suitable-source-photo")
    except Exception as err:
        return (path, id_, None, type(err).__name__ + ": " + str(err)[:100])

def main():
    inputs = {}
    tasks = []
    for path in sorted((ROOT / "data/articles").glob("*.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        wanted = [a for a in doc.get("articles") or []
                  if isinstance(a, dict) and in_window(a) and a.get("archived") is not True
                  and not (isinstance(a.get("image"), dict) and a["image"].get("url"))]
        if wanted:
            inputs[path] = doc
            tasks.extend((path, a) for a in wanted if a.get("articleFormat") != "roundup")
    print("BACKFILL_TOTAL_MISSING", sum(len([a for a in doc.get("articles") or [] if in_window(a) and not (a.get("image") or {}).get("url")]) for doc in inputs.values()), "TASKS", len(tasks), flush=True)
    outputs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        for result in concurrent.futures.as_completed([pool.submit(resolve, x) for x in tasks]):
            outputs.append(result.result())
    successes = {}
    missing = []
    for path, id_, photo, reason in outputs:
        if photo:
            successes[id_] = photo
        else:
            article = next(a for a in inputs[path]["articles"] if a.get("id") == id_)
            missing.append({"id": id_, "title": article.get("zh", {}).get("title"), "reason": reason,
                            "source": (article.get("sources") or [{}])[0].get("url")})
    updated = 0
    for path, doc in inputs.items():
        for a in doc.get("articles") or []:
            if a.get("id") in successes and not (a.get("image") or {}).get("url"):
                a["image"] = successes[a["id"]]
                updated += 1
        if any(a.get("id") in successes for a in doc.get("articles") or []):
            original = path.read_text(encoding="utf-8")
            compact = original.lstrip().startswith('{"articles"')
            path.write_text(json.dumps(doc, ensure_ascii=False, indent=None if compact else 2) + "\n", encoding="utf-8")
    report = {"updated": updated, "remaining": missing, "countRemaining": len(missing),
              "roundupSkipped": len(tasks) < sum(len([a for a in doc.get("articles") or [] if in_window(a) and not (a.get("image") or {}).get("url")]) for doc in inputs.values())}
    (ROOT / "scripts/_oneoff_image_backfill_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("BACKFILL_ATTACHED", updated, "REMAINING", len(missing), flush=True)
    for a in missing:
        print("MISSING", a["id"], a["title"], a["reason"], flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
