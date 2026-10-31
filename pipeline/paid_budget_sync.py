"""CAS refresh/persist of the shared budget, including failed pipeline runs.

Run only in a CI job holding skytical-paid-api-${github.ref}. Uses the
workflow's repository token; does not read or transmit any model API keys.
"""
import argparse
import base64
import copy
import json
import os
import uuid

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
        if baseline is None:
            raise RuntimeError("shared paid budget preflight was not completed")
        hold = current["reservations"][reservation]
        period = {"day": hold["day"], "month": hold["month"]}
        if baseline.get("escrow") == period:
            return  # the existing remote escrow already bounds this entire day
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
    if mode == "persist" and current == baseline["data"] and not baseline.get("escrow"):
        return
    if remote["sha"] != baseline["sha"]:
        raise RuntimeError("shared budget changed outside the CI spending lock; refusing overwrite")
    outgoing = copy.deepcopy(current)
    if mode == "reserve":
        from paid_budget import policy, _micros
        cfg = policy()
        daily = outgoing["days"][hold["day"]]
        monthly = outgoing["months"][hold["month"]]
        extra = min(_micros(cfg["daily_limit_usd"]) - daily["total"],
                    _micros(cfg["monthly_usd"]) - monthly["total"])
        for counts in (daily, monthly):
            counts["total"] += extra
            counts["draft"] = counts.get("draft", 0) + extra
        escrow_key = "ci-escrow-" + os.environ.get("GITHUB_RUN_ID", uuid.uuid4().hex) + "-" + hold["day"]
        outgoing["reservations"][escrow_key] = {
            **period, "purpose": "draft", "micros": extra, "kind": "ci_escrow"}
    payload = {"message": "Persist paid API budget [skip ci]", "branch": branch,
               "content": base64.b64encode((json.dumps(outgoing, indent=2) + "\n").encode()).decode("ascii")}
    if baseline["sha"]:
        payload["sha"] = baseline["sha"]
    written = requests.put(url, json=payload, headers=headers, timeout=30)
    written.raise_for_status()
    save_json(BASE, {"sha": written.json()["content"]["sha"],
                     "data": current, "escrow": period if mode == "reserve" else None})
    print("paid budget: persisted with compare-and-swap")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("refresh", "persist"))
    sync(parser.parse_args().mode)
