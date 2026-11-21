"""Run the same public-source cohort through three SKYTICAL drafting routes."""
import contextlib
import copy
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
from providers import CloudflareProvider, GeminiProvider, classify_failure, safe_failure_message

ROUTES = {
    "cloudflare-120b": (CloudflareProvider, "@cf/openai/gpt-oss-120b"),
    "gemini-36": (GeminiProvider, "gemini-3.6-flash"),
    "gemini-38": (GeminiProvider, "gemini-3.8-flash"),
}
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


def run_route(name):
    cls, model = ROUTES[name]
    groups = json.loads((OUT / "cohort.json").read_text(encoding="utf-8"))
    results = []
    provider = cls(model)
    if not provider.available():
        save(OUT / f"{name}.json", [{"id": g["id"], "gate": "credentialsUnavailable"} for g in groups])
        return
    for group in groups:
        row = {"id": group["id"]}
        before = provider.http_calls
        start = time.monotonic()
        draft = provider.draft

        def capture(*args, **kwargs):
            raw = draft(*args, **kwargs)
            row["draft"] = copy.deepcopy(raw)
            return raw

        provider.draft = capture
        check_log = io.StringIO()
        try:
            with contextlib.redirect_stdout(check_log):
                result, facts = write._validated_draft(provider, group, tries=1, max_attempt_seconds=120)
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
        row["seconds"] = round(time.monotonic() - start, 2)
        results.append(row)
        save(OUT / f"{name}.json", results)
        print(f"{name} {group['id']}: {row['gate']} {row.get('failure', '')}", flush=True)
        time.sleep(max(0, 15 - row["seconds"]))


def prepare():
    fixture = json.loads((ROOT / "config/free_provider_probe.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        eligible = [item for item in pool.map(candidate, SOURCES) if item]
    items = [fixture["items"][0], *eligible][:10]
    if len(items) != 10:
        raise RuntimeError(f"Only {len(items)} sources had sufficient extracted text")
    groups = [{"id": f"bench-{i:02d}", "primarySource": item["source"], "items": [item]}
              for i, item in enumerate(items, 1)]
    save(OUT / "cohort.json", groups)
    for group in groups:
        print(f"{group['id']}: {group['items'][0]['title']}", flush=True)
    def invoke(route):
        subprocess.run([sys.executable, __file__, route], check=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(invoke, ROUTES))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    if len(sys.argv) == 2:
        run_route(sys.argv[1])
    else:
        prepare()
