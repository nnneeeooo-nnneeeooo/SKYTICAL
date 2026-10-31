"""Offline spending boundaries, unknown charges and shared-ledger CAS."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import paid_budget as budget
import paid_budget_sync as sync

NOW = datetime(2026, 10, 31, 16, 1, tzinfo=timezone.utc)
PAYLOAD = {"input": "source", "max_output_tokens": 48000}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("AVWIRE_PAID_BUDGET_ENABLED", "true")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(budget, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sync, "PATH", tmp_path / "paid-budget.json")
    monkeypatch.setattr(sync, "BASE", tmp_path / ".paid-budget-base.json")


def seed(day=0, month=0, optional=0):
    row = {"schemaVersion": 1, "days": {"2026-11-01": {"total": day, "draft": day}},
           "months": {"2026-11": {"total": month, "draft": month-optional, "review": optional}},
           "reservations": {}}
    budget.save_json(budget._path(), row)


def read():
    return json.loads(budget._path().read_text(encoding="utf-8"))


def test_reserve_reconciles_reasoning_once_and_uses_taipei_day():
    token = budget.reserve(PAYLOAD, now=NOW)
    row = read()
    assert "2026-11-01" in row["days"]
    assert row["days"]["2026-11-01"]["total"] >= 24000
    budget.settle(token, {"usage": {"input_tokens": 20000, "output_tokens": 10000,
                                  "output_tokens_details": {"reasoning_tokens": 9000}}})
    assert read()["months"]["2026-11"]["total"] == 7500
    assert not read()["reservations"]


@pytest.mark.parametrize("day,month", [(1499000, 1499000), (0, 29999000)])
def test_daily_and_monthly_limits_block_before_http(day, month):
    seed(day, month)
    sender = Mock()
    with patch.object(budget, "datetime") as clock:
        clock.now.return_value = NOW
        with pytest.raises(budget.BudgetDenied):
            budget.post(sender, "unused", PAYLOAD)
    sender.assert_not_called()


def test_elective_work_cannot_use_twenty_dollar_drafting_allocation():
    seed(month=9999000, optional=9999000)
    with pytest.raises(budget.BudgetDenied, match="reserved for drafting"):
        budget.reserve(PAYLOAD, "summary", now=NOW)
    assert budget.reserve(PAYLOAD, "draft", now=NOW)


def test_summary_and_review_share_unused_optional_allocation():
    seed(month=8000000, optional=8000000)
    assert budget.reserve(PAYLOAD, "summary", now=NOW)


def test_timeout_and_missing_usage_keep_full_charge():
    sender = Mock(side_effect=TimeoutError())
    with pytest.raises(TimeoutError):
        budget.post(sender, "unused", PAYLOAD)
    before = read()
    token = next(iter(before["reservations"]))
    budget.settle(token, {"error": {"message": "unusable response"}})
    assert read() == before


def test_month_rollover_does_not_erase_old_holds():
    seed(day=1500000, month=30000000)
    december = NOW.replace(month=12, day=1)
    token = budget.reserve(PAYLOAD, now=december)
    assert read()["months"]["2026-11"]["total"] == 30000000
    assert token in read()["reservations"]


@pytest.mark.parametrize("bad", ["{}", "not json", '{"schemaVersion": 1, "days": {}, "months": {"x": {"total": -1}}, "reservations": {}}'])
def test_corrupt_ledger_fails_closed(bad):
    budget._path().write_text(bad, encoding="utf-8")
    with pytest.raises(budget.BudgetDenied):
        budget.reserve(PAYLOAD, now=NOW)


def test_search_and_unknown_model_are_bounded():
    token = budget.reserve({**PAYLOAD, "tools": [{"type": "web_search"}], "max_tool_calls": 4}, now=NOW)
    assert read()["reservations"][token]["micros"] > 190000
    with pytest.raises(budget.BudgetDenied):
        budget.reserve({**PAYLOAD, "tools": [{}]}, now=NOW)
    with pytest.raises(budget.BudgetDenied):
        budget.reserve(PAYLOAD, model="unpriced-model", now=NOW)


def test_warning_is_emitted_once(capsys):
    seed(day=795000, month=795000)
    for _ in range(2):
        token = budget.reserve(PAYLOAD, now=NOW)
        budget.settle(token, {"usage": {"input_tokens": 20000, "output_tokens": 10000}})
    assert capsys.readouterr().out.count("::warning::") == 1


def test_disabled_budget_does_not_create_a_ledger(monkeypatch):
    monkeypatch.delenv("AVWIRE_PAID_BUDGET_ENABLED")
    assert budget.reserve(PAYLOAD) is None
    assert not budget._path().exists()


def test_openai_adapter_blocks_before_network(monkeypatch):
    from providers import OpenAIProvider, ProviderBudgetError
    monkeypatch.setenv("AVWIRE_OPENAI_API_MODEL", "test-private-mapping")
    seed(day=1500000, month=1500000)
    with patch.object(budget, "datetime") as clock, patch("requests.post") as post:
        clock.now.return_value = NOW
        with pytest.raises(ProviderBudgetError):
            OpenAIProvider()._post_json("unused", PAYLOAD, {}, False)
    post.assert_not_called()


def test_sync_does_not_overwrite_concurrent_remote_change(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-workflow-token")
    seed()
    data = read()
    budget.save_json(sync.BASE, {"sha": "old", "data": copy.deepcopy(data)})
    budget.reserve(PAYLOAD, now=NOW)
    response = Mock(status_code=200)
    response.json.return_value = {"sha": "new"}
    with patch.object(sync.requests, "get", return_value=response), patch.object(sync.requests, "put") as put:
        with pytest.raises(RuntimeError, match="refusing overwrite"):
            sync.sync("persist")
    put.assert_not_called()


def test_shared_file_lock_prevents_parallel_overspend():
    from concurrent.futures import ThreadPoolExecutor
    cfg = budget.policy()
    cfg["daily_limit_usd"] = 0.06
    cfg["daily_warning_usd"] = 0.04
    def attempt(_):
        try:
            return budget.reserve(PAYLOAD, now=NOW)
        except budget.BudgetDenied:
            return None
    with patch.object(budget, "policy", return_value=cfg), ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(attempt, range(8)))
    assert sum(bool(t) for t in tokens) == 2
    assert read()["days"]["2026-11-01"]["total"] <= 60000


def test_ci_pre_request_escrow_bounds_run_and_final_write_releases_unused_budget(monkeypatch):
    import base64
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-workflow-token")
    seed()
    budget.save_json(sync.BASE, {"sha": "old", "data": copy.deepcopy(read())})
    token = budget.reserve(PAYLOAD, now=NOW)
    get = Mock(status_code=200)
    get.json.return_value = {"sha": "old"}
    put = Mock()
    put.json.return_value = {"content": {"sha": "escrow"}}
    with patch.object(sync.requests, "get", return_value=get), patch.object(sync.requests, "put", return_value=put) as send:
        sync.sync("reserve", reservation=token)
        outgoing = json.loads(base64.b64decode(send.call_args.kwargs["json"]["content"]))
        assert outgoing["days"]["2026-11-01"]["total"] == 1500000
        assert any(r.get("kind") == "ci_escrow" for r in outgoing["reservations"].values())
        # More calls that day require no further remote commit. Local spending
        # remains subject to the ordinary daily/monthly/category checks.
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        token2 = budget.reserve(PAYLOAD, now=NOW)
        assert send.call_count == 1
        assert read()["days"]["2026-11-01"]["total"] < 100000
        for t in (token, token2):
            budget.settle(t, {"usage": {"input_tokens": 20000, "output_tokens": 10000}})
        get.json.return_value = {"sha": "escrow"}
        put.json.return_value = {"content": {"sha": "settled"}}
        sync.sync("persist")
        outgoing = json.loads(base64.b64decode(send.call_args.kwargs["json"]["content"]))
        assert outgoing["days"]["2026-11-01"]["total"] == 15000
        assert not outgoing["reservations"]
        assert json.loads(sync.BASE.read_text())["sha"] == "settled"


def test_ci_remote_reservation_failure_prevents_paid_http(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-workflow-token")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    seed()
    budget.save_json(sync.BASE, {"sha": "old", "data": copy.deepcopy(read())})
    sender = Mock()
    with patch.object(sync.requests, "get", side_effect=ConnectionError("offline")):
        with pytest.raises(budget.BudgetDenied, match="could not be persisted"):
            budget.post(sender, "unused", PAYLOAD)
    sender.assert_not_called()
    assert read()["reservations"]


def test_ci_without_preflight_does_not_spend(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    sender = Mock()
    with pytest.raises(budget.BudgetDenied):
        budget.post(sender, "unused", PAYLOAD)
    sender.assert_not_called()


def test_first_shared_ledger_imports_existing_cloud_audit_cost(monkeypatch):
    import base64
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-workflow-token")
    missing = Mock(status_code=404)
    old = Mock(status_code=200)
    old.json.return_value = {"content": base64.b64encode(json.dumps({"days": {"2026-11-01": 4989}, "months": {"2026-11": 4989}}).encode()).decode()}
    with patch.object(sync.requests, "get", side_effect=[missing, old]):
        sync.sync("refresh")
    assert read()["months"]["2026-11"] == {"total": 4989, "review": 4989}


def test_long_context_price_reservation_includes_premiums():
    cfg = budget.policy()
    assert budget._cost(300000, 48000, 0, cfg) == 111000
