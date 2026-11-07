"""One-time owner-requested replay of six recorded output-token failures."""
import json
import subprocess

import write
from common import load_json, save_json

SNAPSHOTS = {
    "97710547ad90a13b351b760371888b14f008e036": {
        "g-20261106-2315-1", "g-20261106-2315-2",
        "g-20261106-2315-4", "g-20261106-2315-11"},
    "573ef62653d2e304c50c17edbf44b4196870e3da": {
        "g-20261107-0014-2", "g-20261107-0014-11"},
}


def main():
    targets = []
    for ref, ids in SNAPSHOTS.items():
        snapshot = json.loads(subprocess.check_output(
            ["git", "show", f"{ref}:data/pending.json"], encoding="utf-8"))
        selected = [g for g in snapshot["groups"] if g["id"] in ids]
        if {g["id"] for g in selected} != ids:
            raise RuntimeError("Historical retry sources are incomplete")
        targets.extend(selected)
    original = load_json(write.PENDING_PATH, {})
    # An explicit manual retry bypasses only scheduling/backoff, never source,
    # evidence, factual, duplication or publication gates. Other news is kept.
    original_plan = write.news_retry.RetryLedger.plan
    original_flight_queue = write.flightnews.load_queue
    write.news_retry.RetryLedger.plan = lambda self, groups, maximum: (groups, [])
    write.flightnews.load_queue = lambda: []
    save_json(write.PENDING_PATH, {**original, "groups": targets})
    try:
        write.main()
    finally:
        write.news_retry.RetryLedger.plan = original_plan
        write.flightnews.load_queue = original_flight_queue
        remaining = load_json(write.PENDING_PATH, {}).get("groups", targets)
        urls = {i["url"] for g in targets for i in g["items"]}
        untouched = [g for g in original.get("groups", [])
                     if not {i.get("url") for i in g.get("items", [])}.issubset(urls)]
        save_json(write.PENDING_PATH, {**original, "groups": untouched + remaining})


if __name__ == "__main__":
    main()
