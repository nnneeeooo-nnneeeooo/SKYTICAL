"""CAS refresh/persist of the shared budget, including failed pipeline runs.

Run only in a CI job holding skytical-paid-api-${github.ref}. Uses the
workflow's repository token; does not read or transmit any model API keys.
"""
import argparse
import base64
import json
import os

import requests

from common import DATA_DIR, save_json

BASE = DATA_DIR / ".paid-budget-base.json"
PATH = DATA_DIR / "paid-budget.json"


def sync(mode, reservation=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    headers = {"Authorization": "Bearer " + os.environ["GH_TOKEN"],
               "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/data/paid-budget.json"
    if mode == "persist" and not BASE.exists():
        return  # preflight failed before spending was enabled
    baseline = json.loads(BASE.read_text(encoding="utf-8")) if BASE.exists() else None
    current = json.loads(PATH.read_text(encoding="utf-8")) if PATH.exists() else None
    if mode == "reserve":
        if baseline is None or current is None:
            raise RuntimeError("shared paid usage preflight was not completed")
        if reservation not in current.get("reservations", {}):
            raise RuntimeError("unknown paid API reservation")
    response = requests.get(url, params={"ref": branch}, headers=headers, timeout=30)
    if response.status_code == 404:
        remote = {"sha": None, "content": None}
    else:
        response.raise_for_status()
        remote = response.json()
    if mode == "refresh":
        if remote["content"] is None:
            data = {"schemaVersion": 1, "days": {}, "months": {}, "reservations": {}}
            # The independent airport audit predates this shared ledger.
            # Preserve its conservative paid totals instead of restarting at 0.
            prior = requests.get(url.replace("paid-budget.json", "iata-audit/state.json"),
                                 params={"ref": branch}, headers=headers, timeout=30)
            if prior.status_code != 404:
                prior.raise_for_status()
                audit = json.loads(base64.b64decode(prior.json()["content"]))
                for period in ("days", "months"):
                    for stamp, amount in audit[period].items():
                        if type(amount) is not int or amount < 0:
                            raise ValueError("invalid legacy airport spending ledger")
                        data[period][stamp] = {"total": amount, "review": amount}
        else:
            data = json.loads(base64.b64decode(remote["content"]).decode("utf-8"))
        save_json(PATH, data)
        save_json(BASE, {"sha": remote["sha"], "data": data})
        # Validate the refreshed ledger before any subsequent API step.
        from paid_budget import _locked, policy
        policy()
        with _locked():
            pass
        return
    if current == baseline["data"]:
        return
    if remote["sha"] != baseline["sha"]:
        raise RuntimeError("shared paid usage changed outside the CI spending lock; refusing overwrite")
    # With no monthly allowance, persist each actual request's conservative
    # upper-bound hold before HTTP instead of escrowing the remaining month.
    outgoing = current
    payload = {"message": "Persist paid API budget [skip ci]", "branch": branch,
               "content": base64.b64encode((json.dumps(outgoing, indent=2) + "\n").encode()).decode("ascii")}
    if baseline["sha"]:
        payload["sha"] = baseline["sha"]
    written = requests.put(url, json=payload, headers=headers, timeout=30)
    written.raise_for_status()
    save_json(BASE, {"sha": written.json()["content"]["sha"],
                     "data": current})
    print("paid budget: persisted with compare-and-swap")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("refresh", "persist"))
    sync(parser.parse_args().mode)
