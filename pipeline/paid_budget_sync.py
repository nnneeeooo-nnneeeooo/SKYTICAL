"""CAS refresh/persist of the shared budget, including failed pipeline runs.

Run only in a CI job holding skytical-paid-api-${github.ref}. Uses the
workflow's repository token; does not read or transmit any model API keys.
"""
import argparse
import base64
import json
import os
from datetime import datetime, timedelta, timezone

import requests

from common import DATA_DIR, save_json

BASE = DATA_DIR / ".paid-budget-base.json"
PATH = DATA_DIR / "paid-budget.json"
TPE = timezone(timedelta(hours=8))


def _notify_daily_usage(repo, headers, ledger, now=None):
    """Open at most one assigned GitHub issue per Taipei day after USD 2 settled.

    Old monthly escrows and unfinished/unknown reservations are never treated
    as settled spending. The exact issue title is also the idempotency key.
    """
    from paid_budget import policy, _micros

    threshold = _micros(policy()["daily_warning_usd"])
    today = (now or datetime.now(timezone.utc)).astimezone(TPE).date()
    for date in (today - timedelta(days=1), today):
        day = date.isoformat()
        counts = ledger.get("days", {}).get(day) or {}
        unsettled = sum(
            hold["micros"] for hold in ledger.get("reservations", {}).values()
            if hold["day"] == day
        )
        settled_usd_micro = counts.get("total", 0) - unsettled
        if settled_usd_micro < threshold:
            continue

        title = f"SKYTICAL OpenAI API daily USD 2 alert {day}"
        legacy_title = f"SKYTICAL Terra API daily USD 2 alert {day}"
        params = {
            "q": f'repo:{repo} is:issue in:title "SKYTICAL" "API daily USD 2 alert" {day}',
            "per_page": 50,
        }
        found = requests.get(
            "https://api.github.com/search/issues",
            params=params, headers=headers, timeout=30,
        )
        found.raise_for_status()
        if any(item.get("title") in {title, legacy_title}
               for item in found.json().get("items", [])):
            continue

        body = (
            f"SKYTICAL 的 OpenAI API 用量於 **{day}（臺灣時間）** "
            f"達到每日 **US$2** 提醒門檻。\n\n"
            f"截至本次結算，站內帳本估算的已結算支出為 "
            f"**US$ {settled_usd_micro / 1_000_000:.2f}**。\n\n"
            "這是通知，**不會限制或停止 API 呼叫**；站內沒有每日或每月"
            "的金額硬上限。記帳採保守單價估算，未結算或用量不明的請求"
            "仍保留預留額；此數字不代表 OpenAI 帳戶的完整帳單，"
            "也不包括其他程式或專案的用量。\n\n"
            "記帳檔：data/paid-budget.json。"
        )
        created = requests.post(
            f"https://api.github.com/repos/{repo}/issues",
            json={
                "title": title,
                "body": body,
                "assignees": [os.environ.get(
                    "SKYTICAL_BUDGET_NOTIFY_USER", repo.split("/", 1)[0]
                )],
            },
            headers=headers, timeout=30,
        )
        created.raise_for_status()
        print(f"::notice::Daily OpenAI US$2 GitHub alert created for {day}")



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
        if mode == "persist":
            _notify_daily_usage(repo, headers, current)
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
    print("paid API usage: persisted with compare-and-swap")
    if mode == "persist":
        _notify_daily_usage(repo, headers, current)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("refresh", "persist"))
    sync(parser.parse_args().mode)
