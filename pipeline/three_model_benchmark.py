"""Run the same public-source cohort through three SKYTICAL drafting routes."""
import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fulltext
import write
from common import now_utc
from draft_recovery import draft_timeout
from providers import OpenAIProvider, classify_failure, safe_failure_message
SOURCES = (
    ("airbus", 0), ("boeing", 0), ("ntsb", 0), ("caataiwan", 0), ("faa", 1),
    ("iata", 2), ("rollsroyce", 0), ("evaair", 0), ("embraer", 0), ("easa", 3),
    ("caataiwan", 1), ("boeing", 1), ("cnataiwanairlines", 0),
    ("airbus", 2), ("aerotime", 0), ("faa", 2), ("easa", 1),
)
OUT = Path(os.environ["BENCH_OUTPUT"])
ROOT = Path(__file__).resolve().parents[1]


def save(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def candidate(ref):
    name, index = ref
    entries = json.loads((ROOT / "data" / "raw" / f"{name}.json").read_text(encoding="utf-8"))
    if len(entries["items"]) <= index:
        return None
    item = entries["items"][index]
    body = fulltext.fetch_fulltext(item["url"])
    if not body or len(body) < 460:
        print(f"source {name}/{index}: insufficient extracted body")
        return None
    return {**item, "source": entries.get("source") or name, "sourceKey": name, "fulltext": body}


def run_route(shard):
    groups = json.loads((OUT / "cohort.json").read_text(encoding="utf-8"))[shard::2]
    path = OUT / f"terra-{shard}.json"
    results = []
    provider = OpenAIProvider("gpt-6.1-terra")
    if not provider.available():
        save(path, [{"id": g["id"], "gate": "credentialsUnavailable"} for g in groups])
        return
    for group in groups:
        row = {"id": group["id"]}
        before = provider.http_calls
        usage_before = dict(provider.usage)
        start = time.monotonic()
        draft = provider.draft

        def capture(*args, **kwargs):
            raw = draft(*args, **kwargs)
            row["draft"] = copy.deepcopy(raw)
            return raw

        provider.draft = capture
        check_log = io.StringIO()
        try:
            with contextlib.redirect_stdout(check_log), draft_timeout(300):
                result, facts = write._validated_draft(provider, group, tries=1)
                if result and result.get("status") in {"publish", "publish_brief"}:
                    article = write.build_article(result, group, now_utc(), set(), provider.label, facts)
                    row["gate"] = "pass" if article else "buildRejected"
                    if article:
                        row["article"] = {k: article[k] for k in ("zh", "en", "articleFormat")}
                else:
                    row["gate"] = "reject" if result else "noDraft"
        except write.DraftInvalid as exc:
            row.update(gate="validationRejected", detail=safe_failure_message(exc, limit=350))
        except Exception as exc:
            row.update(gate="requestFailed", failure=classify_failure(exc),
                       detail=safe_failure_message(exc, limit=350))
        finally:
            provider.draft = draft
        row["checkLog"] = check_log.getvalue()[:1600]
        row["calls"] = provider.http_calls - before
        row["usage"] = {key: value - usage_before[key] for key, value in provider.usage.items()}
        row["seconds"] = round(time.monotonic() - start, 2)
        results.append(row)
        save(path, results)
        print(f"terra {group['id']}: {row['gate']} {row.get('failure', '')}", flush=True)


def prepare():
    def digest(text):
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    fixture = json.loads((ROOT / "config/free_provider_probe.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / "config/terra-compare-manifest.json").read_text(encoding="utf-8"))
    if (digest(write.SYSTEM_PROMPT) != manifest["system"]
            or digest(json.dumps(write.DRAFT_SCHEMA, sort_keys=True)) != manifest["schema"]):
        raise RuntimeError("System prompt or draft schema differs from the preceding benchmark")
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = {item["url"]: item for item in pool.map(candidate, SOURCES) if item}
    probe = fixture["items"][0]
    items[probe["url"]] = probe
    groups = []
    for index, source in enumerate(manifest["sources"], 1):
        item = items.get(source["url"])
        if not item:
            raise RuntimeError(f"Original source unavailable for bench-{index:02d}")
        group = {"id": f"bench-{index:02d}", "primarySource": item["source"], "items": [item]}
        if digest(write.group_prompt(group)) != source["prompt"]:
            raise RuntimeError(f"Prompt differs from original for {group['id']}")
        groups.append(group)
    save(OUT / "cohort.json", groups)
    for group in groups:
        print(f"{group['id']}: {group['items'][0]['title']}", flush=True)
    def invoke(shard):
        subprocess.run([sys.executable, __file__, str(shard)], check=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(invoke, (0, 1)))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) == 2:
        run_route(int(sys.argv[1]))
    else:
        prepare()
