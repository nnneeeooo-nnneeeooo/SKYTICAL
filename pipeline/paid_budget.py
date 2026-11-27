"""Pre-request, persistent USD reservations for the site's OpenAI API budget.

Only enabled by AVWIRE_PAID_BUDGET_ENABLED=true (production workflows opt in).
Unknown/aborted requests keep their entire reservation. No prompts, secrets,
wire model names or response bodies enter this ledger. CI writers must share
the paid-budget concurrency group and refresh/persist this file on every run.
"""
from __future__ import annotations

import json
import math
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from common import DATA_DIR, ROOT, save_json
from model_config import BRIEFING_OPENAI_MODEL, OPENAI_DEFAULT_MODEL

CONFIG_PATH = ROOT / "config" / "luna_policy.json"
TPE = timezone(timedelta(hours=8))
# Accounting only; both configured OpenAI models have this native output capacity.
OPENAI_OUTPUT_RESERVATION_TOKENS = 128_000


class BudgetDenied(RuntimeError):
    pass


def enabled():
    return os.environ.get("AVWIRE_PAID_BUDGET_ENABLED", "").lower() == "true"


def policy():
    """Rates and a notification threshold only; neither day nor month is capped."""
    with CONFIG_PATH.open(encoding="utf-8") as stream:
        row = json.load(stream)
    # Preserve the original strict configuration validation, now without
    # treating the daily notification threshold as a monetary spending cap.
    for key, value in row.items():
        if key == "daily_limit_usd" and value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            raise BudgetDenied("invalid paid usage accounting configuration")
    for key in ("daily_warning_usd", "input_usd_per_million", "output_usd_per_million"):
        if row.get(key, 0) <= 0:
            raise BudgetDenied("invalid paid usage accounting configuration")
    if row.get("daily_limit_usd") is not None:
        raise BudgetDenied("daily spending must remain uncapped")
    return row


def _path():
    return DATA_DIR / "paid-budget.json"


@contextmanager
def _locked():
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            if path.exists():
                try:
                    row = json.loads(path.read_text(encoding="utf-8"))
                    if row["schemaVersion"] != 1:
                        raise ValueError()
                    for period in ("days", "months"):
                        if not isinstance(row[period], dict):
                            raise ValueError()
                        for counts in row[period].values():
                            if not isinstance(counts, dict) or any(
                                    type(v) is not int or v < 0 for v in counts.values()):
                                raise ValueError()
                            if (set(counts) - {"total", "draft", "review", "summary", "warned", "warned_usd2"}
                                    or counts.get("total", 0) != sum(counts.get(k, 0) for k in ("draft", "review", "summary"))):
                                raise ValueError()
                    if not isinstance(row["reservations"], dict):
                        raise ValueError()
                except (ValueError, KeyError, TypeError) as exc:
                    raise BudgetDenied("paid budget ledger is unreadable; refusing spend") from exc
            else:
                row = {"schemaVersion": 1, "days": {}, "months": {}, "reservations": {}}
            yield row
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _micros(usd):
    return math.ceil(usd * 1_000_000)


def _cost(inputs, outputs, tools, cfg):
    # 1.25x input price also bounds explicit cache-write charges. Reasoning
    # is already part of output_tokens; never add it a second time.
    long_context = inputs > 272_000
    return math.ceil(inputs * cfg["input_usd_per_million"] * 1.25 * (2 if long_context else 1)
                     + outputs * cfg["output_usd_per_million"] * (1.5 if long_context else 1) + tools * 10_000)


def output_reservation_tokens(payload):
    outputs = payload.get("max_output_tokens")
    if outputs is None:
        return OPENAI_OUTPUT_RESERVATION_TOKENS
    if type(outputs) is not int or outputs <= 0:
        raise BudgetDenied("invalid paid output limit")
    return outputs


def _model_policy(model):
    cfg = policy()
    if model == OPENAI_DEFAULT_MODEL:
        return cfg
    if model == BRIEFING_OPENAI_MODEL:
        # https://developers.openai.com/api/docs/models/gpt-6-luna
        return {**cfg, "input_usd_per_million": 0.10, "output_usd_per_million": 0.50}
    raise BudgetDenied("no configured budget price for this OpenAI model")


def reserve(payload, purpose="draft", model=OPENAI_DEFAULT_MODEL, now=None):
    if not enabled():
        return None
    if purpose not in {"draft", "review", "summary"}:
        raise BudgetDenied("unknown paid budget purpose")
    cfg = _model_policy(model)
    tools = payload.get("max_tool_calls", 0) if payload.get("tools") else 0
    if payload.get("tools") and not tools:
        raise BudgetDenied("unbounded paid tools")
    # UTF-8 bytes conservatively bound prompt tokens, with room for framing.
    inputs = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 4096
    if tools:
        inputs += 1_050_000  # bound dynamic search context by the model context window
    outputs = output_reservation_tokens(payload)
    amount = _cost(inputs, outputs, tools, cfg)
    local = (now or datetime.now(timezone.utc)).astimezone(TPE)
    day, month = local.date().isoformat(), local.strftime("%Y-%m")
    with _locked() as row:
        daily = row["days"].setdefault(day, {})
        monthly = row["months"].setdefault(month, {})
        token = uuid.uuid4().hex
        row["reservations"][token] = {"day": day, "month": month, "purpose": purpose, "micros": amount}
        for counts in (daily, monthly):
            counts["total"] = counts.get("total", 0) + amount
            counts[purpose] = counts.get(purpose, 0) + amount
        save_json(_path(), row)
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # Persist this request's conservative hold BEFORE sending paid HTTP.
            # A failed final ledger write cannot erase unknown charges.
            try:
                from paid_budget_sync import sync
                sync("reserve", reservation=token)
            except Exception as exc:
                raise BudgetDenied("shared paid budget reservation could not be persisted") from exc
    return token


def settle(token, data, *, model=OPENAI_DEFAULT_MODEL):
    if token is None:
        return
    meta = data.get("usage") or {}
    if not all(type(meta.get(key)) is int and meta[key] >= 0 for key in ("input_tokens", "output_tokens")):
        return  # uncertain spend remains fully charged
    cfg = _model_policy(model)
    tool_calls = sum(1 for item in data.get("output", [])
                     if isinstance(item, dict) and item.get("type") == "web_search_call")
    actual = _cost(meta["input_tokens"], meta["output_tokens"], tool_calls, cfg)
    with _locked() as row:
        hold = row["reservations"].pop(token)
        # A provider exceeding our bound is accounted in full, never hidden.
        delta = actual - hold["micros"]
        for period, key in (("days", "day"), ("months", "month")):
            counts = row[period][hold[key]]
            counts["total"] += delta
            counts[hold["purpose"]] += delta
        daily = row["days"][hold["day"]]
        # Alert on settled usage, never on the exaggerated preflight hold.
        # Unknown/aborted calls retain their conservative reservation.
        outstanding = sum(
            pending["micros"] for pending in row["reservations"].values()
            if pending["day"] == hold["day"]
        )
        confirmed = daily["total"] - outstanding
        if confirmed >= _micros(cfg["daily_warning_usd"]) and not daily.get("warned_usd2"):
            daily["warned_usd2"] = 1
            print(f"::warning::SKYTICAL OpenAI API confirmed daily usage reached "
                  f"US${cfg['daily_warning_usd']:.2f} on {hold['day']} Taipei time; "
                  "this is a notification, not a spending cap")
        save_json(_path(), row)


def post(sender, url, payload, *, purpose="draft", model=OPENAI_DEFAULT_MODEL, **kwargs):
    token = reserve(payload, purpose, model)
    response = sender(url, payload, **kwargs)
    try:
        data = response.json()
    except (ValueError, TypeError):
        return response  # retain the full hold for unaccounted errors
    settle(token, data, model=model)
    return response
