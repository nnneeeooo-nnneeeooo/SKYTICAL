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


@pytest.mark.parametrize("outputs", [96000, 160000])
def test_uncapped_payload_reaches_http_and_settles_full_returned_usage(outputs):
    payload = {"input": "source"}
    response = Mock()
    response.json.return_value = {"usage": {"input_tokens": 20000, "output_tokens": outputs}}
    sender = Mock(return_value=response)
    with patch.object(budget, "datetime") as clock:
        clock.now.return_value = NOW
        assert budget.post(sender, "unused", payload) is response
    assert sender.call_args.args[1] == {"input": "source"}
    assert "max_output_tokens" not in payload
    assert read()["months"]["2026-11"]["total"] == 2500 + outputs // 2
    assert not read()["reservations"]


def test_uncapped_unknown_usage_retains_native_capacity_reservation():
    payload = {"input": "source"}
    token = budget.reserve(payload, now=NOW)
    before = read()
    assert before["reservations"][token]["micros"] == budget._cost(
        len(json.dumps(payload).encode()) + 4096, 128000, 0, budget.policy())
    budget.settle(token, {})
    assert read() == before


@pytest.mark.parametrize("invalid", [0, -1, True, "128000", 1.5])
def test_invalid_explicit_output_limit_is_rejected(invalid):
    with pytest.raises(budget.BudgetDenied):
        budget.reserve({"input": "source", "max_output_tokens": invalid}, now=NOW)


def test_uncapped_output_allows_monthly_and_optional_spending():
    seed(day=39000000, month=79000000, optional=50000000)
    for purpose in ("draft", "review", "summary"):
        assert budget.reserve({"input": "source"}, purpose, now=NOW)
    assert read()["months"]["2026-11"]["total"] > 79000000


def test_no_monthly_or_daily_cap_blocks_http():
    seed(day=29999000, month=99999000)
    response = Mock()
    response.json.return_value = {
        "usage": {"input_tokens": 20000, "output_tokens": 10000}}
    sender = Mock(return_value=response)
    with patch.object(budget, "datetime") as clock:
        clock.now.return_value = NOW
        assert budget.post(sender, "unused", PAYLOAD) is response
    sender.assert_called_once()
    assert read()["months"]["2026-11"]["total"] > 99999000


def test_unlimited_daily_budget_allows_spending_above_old_cap():
    seed(day=5000000, month=5000000)
    assert budget.policy()["daily_limit_usd"] is None
    assert budget.reserve(PAYLOAD, now=NOW)
    assert read()["days"]["2026-11-01"]["total"] > 5000000


def test_review_and_summary_have_no_separate_spending_caps():
    seed(month=59000000, optional=58000000)
    assert budget.reserve(PAYLOAD, "summary", now=NOW)
    assert budget.reserve(PAYLOAD, "review", now=NOW)
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


def test_luna_usage_is_reserved_and_settled_at_luna_rates():
    default = budget.reserve(PAYLOAD, now=NOW)
    luna = budget.reserve(PAYLOAD, model="gpt-6-luna", now=NOW)
    holds = read()["reservations"]
    assert holds[luna]["micros"] == holds[default]["micros"]
    budget.settle(luna, {"usage": {"input_tokens": 800, "output_tokens": 400}},
                  model="gpt-6-luna")
    assert read()["days"]["2026-11-01"]["total"] == holds[default]["micros"] + 300


def test_two_dollar_settled_warning_is_emitted_once(capsys):
    seed(day=1990000, month=1990000)
    for _ in range(3):
        token = budget.reserve(PAYLOAD, now=NOW)
        budget.settle(token, {"usage": {"input_tokens": 20000, "output_tokens": 10000}})
    assert capsys.readouterr().out.count("::warning::") == 1
    assert read()["days"]["2026-11-01"]["warned_usd2"] == 1


def test_preflight_reservation_does_not_trigger_two_dollar_warning(capsys):
    seed(day=1900000, month=1900000)
    token = budget.reserve({"input": "source"}, now=NOW)
    assert token
    assert "warned_usd2" not in read()["days"]["2026-11-01"]
    assert "::warning::" not in capsys.readouterr().out


def test_legacy_low_warning_does_not_suppress_new_two_dollar_threshold(capsys):
    seed(day=2000000, month=2000000)
    row = read()
    row["days"]["2026-11-01"]["warned"] = 1
    budget.save_json(budget._path(), row)
    token = budget.reserve(PAYLOAD, now=NOW)
    budget.settle(token, {"usage": {"input_tokens": 20000, "output_tokens": 10000}})
    assert capsys.readouterr().out.count("::warning::") == 1
    assert read()["days"]["2026-11-01"]["warned_usd2"] == 1


def test_disabled_budget_does_not_create_a_ledger(monkeypatch):
    monkeypatch.delenv("AVWIRE_PAID_BUDGET_ENABLED")
    assert budget.reserve(PAYLOAD) is None
    assert not budget._path().exists()


def test_openai_adapter_rejects_corrupt_ledger_before_network(monkeypatch):
    from providers import OpenAIProvider, ProviderBudgetError
    monkeypatch.setenv("AVWIRE_OPENAI_API_MODEL", "test-private-mapping")
    budget._path().write_text("{}", encoding="utf-8")
    with patch("requests.post") as post:
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


def test_shared_file_lock_tracks_parallel_uncapped_reservations():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: budget.reserve(PAYLOAD, now=NOW), range(8)))
    row = read()
    assert len(tokens) == len(set(tokens)) == 8
    assert row["days"]["2026-11-01"]["total"] == sum(
        hold["micros"] for hold in row["reservations"].values())
    assert row["days"]["2026-11-01"]["total"] > 150000


def test_ci_persists_every_request_hold_then_settled_usage(monkeypatch):
    import base64
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GH_TOKEN", "fake-workflow-token")
    seed()
    budget.save_json(sync.BASE, {"sha": "old", "data": copy.deepcopy(read())})
    token = budget.reserve(PAYLOAD, now=NOW)
    get = Mock(status_code=200)
    get.json.return_value = {"sha": "old"}
    put = Mock()
    put.json.return_value = {"content": {"sha": "hold1"}}
    with patch.object(sync.requests, "get", return_value=get), patch.object(
            sync.requests, "put", return_value=put) as send:
        sync.sync("reserve", reservation=token)
        outgoing = json.loads(base64.b64decode(send.call_args.kwargs["json"]["content"]))
        assert set(outgoing["reservations"]) == {token}
        assert not any(r.get("kind") == "ci_escrow" for r in outgoing["reservations"].values())

        get.json.return_value = {"sha": "hold1"}
        put.json.return_value = {"content": {"sha": "hold2"}}
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        token2 = budget.reserve(PAYLOAD, now=NOW)
        assert send.call_count == 2
        outgoing = json.loads(base64.b64decode(send.call_args.kwargs["json"]["content"]))
        assert set(outgoing["reservations"]) == {token, token2}

        for t in (token, token2):
            budget.settle(t, {"usage": {"input_tokens": 20000, "output_tokens": 10000}})
        get.json.return_value = {"sha": "hold2"}
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



def test_two_dollar_issue_notification_is_assigned_and_deduplicated(monkeypatch):
    repo = "owner/repo"
    headers = {"Authorization": "Bearer test"}
    seed(day=2500000, month=2500000)
    found = Mock(status_code=200)
    found.json.return_value = {"items": []}
    created = Mock(status_code=201)
    with patch.object(sync.requests, "get", return_value=found) as get, patch.object(
            sync.requests, "post", return_value=created) as post:
        sync._notify_daily_usage(repo, headers, read(), now=NOW)
        assert post.call_count == 1
        notice = post.call_args.kwargs["json"]
        assert notice["title"] == "SKYTICAL OpenAI API daily USD 2 alert 2026-11-01"
        assert notice["assignees"] == ["owner"]
        assert "不會限制或停止 API" in notice["body"]

        found.json.return_value = {"items": [{"title": "SKYTICAL Terra API daily USD 2 alert 2026-11-01"}]}
        sync._notify_daily_usage(repo, headers, read(), now=NOW)
        assert post.call_count == 1
        assert get.call_count == 2


def test_two_dollar_notification_ignores_unknown_held_spend():
    seed(day=2900000, month=2900000)
    row = read()
    row["reservations"]["unknown"] = {
        "day": "2026-11-01", "month": "2026-11", "purpose": "draft",
        "micros": 1200000,
    }
    with patch.object(sync.requests, "get") as get, patch.object(
            sync.requests, "post") as post:
        sync._notify_daily_usage("owner/repo", {}, row, now=NOW)
    get.assert_not_called()
    post.assert_not_called()


def test_two_dollar_notification_is_not_triggered_under_threshold():
    seed(day=1999999, month=1999999)
    with patch.object(sync.requests, "get") as get, patch.object(
            sync.requests, "post") as post:
        sync._notify_daily_usage("owner/repo", {}, read(), now=NOW)
    get.assert_not_called()
    post.assert_not_called()
