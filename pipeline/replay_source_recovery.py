"""Owner-requested replay of five thin-source stories; all content gates apply."""
from __future__ import annotations

import json
import subprocess

import write
from common import DATA_DIR, load_json, norm_url, save_json

TARGETS = [
    ("71d8c71723b1", "simpleflying", "breeze-airways-taking-spirit-airlines"),
    ("71d8c71723b1", "reuters", "spacexs-starship-nears-end-15th"),
    ("f8c6daabad03", "reuters", "thousands-us-flights-canceled-delayed"),
    ("f8c6daabad03", "simpleflying", "iata-half-air-accident-investigations"),
    ("f8c6daabad03", "aerospaceglobalnews", "remarkable-airline-turnarounds-bankruptcy"),
]


def main():
    original = load_json(write.PENDING_PATH, {})
    groups = []
    for number, (ref, key, needle) in enumerate(TARGETS, 1):
        raw = json.loads(subprocess.check_output(
            ["git", "show", f"{ref}:data/raw/{key}.json"], encoding="utf-8"))
        selected = [item for item in raw["items"] if needle in item.get("url", "")]
        if len(selected) != 1:
            raise RuntimeError(f"Replay source {number} is not unique")
        groups.append({"id": f"source-replay-20261116-{number}",
                       "primarySource": selected[0].get("source") or key,
                       "items": selected, "sourceReplayRequested": True})
    urls = {norm_url(i["url"]) for g in groups for i in g["items"]}
    titles = {write._norm_title(i["title"]) for g in groups for i in g["items"]}
    seen = load_json(write.SEEN_PATH, {})
    seen["urls"] = {u: d for u, d in seen.get("urls", {}).items() if norm_url(u) not in urls}
    seen["titles"] = [row for row in seen.get("titles", []) if row[0] not in titles]
    save_json(write.SEEN_PATH, seen)
    # Explicit replay bypasses scheduling only. Duplicate, source and article
    # evidence gates still run, so Muse's existing IATA article is preserved.
    from unittest.mock import patch
    save_json(write.PENDING_PATH, {**original, "groups": groups})
    with patch.object(write.news_retry.RetryLedger, "plan", lambda self, rows, limit: (rows, [])), \
         patch.object(write.flightnews, "load_queue", lambda: []), \
         patch.object(write, "eligible_providers", lambda group, providers: list(providers)):
        try:
            write.main()
        finally:
            remaining = load_json(write.PENDING_PATH, {}).get("groups", groups)
            untouched = [g for g in original.get("groups", []) if not
                         {norm_url(str(i.get("url") or "")) for i in g.get("items", [])} & urls]
            save_json(write.PENDING_PATH, {**original, "groups": untouched + remaining})
            report = {"targets": [{"id": g["id"], "title": g["items"][0]["title"]}
                                  for g in groups],
                      "pending": [g["id"] for g in remaining]}
            save_json(DATA_DIR / "source-replay-report.json", report)


if __name__ == "__main__":
    main()
