"""Recovery never turns model search prose into factual evidence."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import source_recovery as recovery
import news_search
import news_retry


def story():
    return {"id": "g1", "items": [{"title": "IATA accident investigation final reports",
            "url": "https://simpleflying.com/iata-reports/", "summary": ""}]}


def test_verified_pages_only_and_credit(tmp_path):
    group = story()
    urls = ["https://www.iata.org/news/reports", "https://untrusted.example/x"]
    item = {"url": urls[0], "title": "IATA accident investigation reports",
            "fulltext": "Verified source text. " * 20}
    with patch.object(recovery, "CACHE_PATH", tmp_path / "cache.json"), \
         patch.object(recovery, "_search", return_value=urls), \
         patch.object(news_search, "fetch_candidate", return_value=item) as fetch:
        assert recovery.recover(group)
        assert fetch.call_count == 1
        assert group["items"][-1]["sourceRecoveryModel"] == "gpt-6.1-terra"
        assert group["items"][-1]["fulltext"].startswith("Verified")
        assert not recovery.recover(group)
        cache = json.loads((tmp_path / "cache.json").read_text())
        assert next(iter(cache.values()))["diagnostics"][-1]["status"] == "host_not_approved"


def test_no_page_no_credit_and_backoff(tmp_path):
    with patch.object(recovery, "CACHE_PATH", tmp_path / "cache.json"), \
         patch.object(recovery, "_search", return_value=["https://www.iata.org/news/a"]) as search, \
         patch.object(news_search, "fetch_candidate", return_value=None):
        g = story()
        assert not recovery.recover(g)
        assert "sourceRecoveryModel" not in g
        assert not recovery.recover(story())
        assert search.call_count == 1


def test_model_typed_url_without_tool_source_is_discarded():
    data = {"status": "completed", "output": [
        {"type": "web_search_call", "status": "completed", "action": {"sources": [
            {"url": "https://www.iata.org/news/real"}]}},
        {"type": "message", "content": [{"type": "output_text", "text": json.dumps({
            "urls": ["https://www.iata.org/news/real", "https://www.iata.org/news/invented"]})}]}]}
    from paid_budget import post
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), \
         patch("paid_budget.post", return_value=SimpleNamespace(status_code=200, json=lambda: data)) as call, \
         patch("usage.record_providers"):
        assert recovery._search(story()) == ["https://www.iata.org/news/real"]
        payload = call.call_args.args[2]
        assert payload["model"] == "gpt-6.1-terra"
        assert "max_output_tokens" not in payload
        assert payload["tool_choice"] == "required"
        assert payload["max_tool_calls"] == 8


def test_search_passes_real_enabled_accounting(tmp_path):
    import paid_budget
    data = {"status": "completed", "usage": {"input_tokens": 100, "output_tokens": 10},
            "output": [{"type": "web_search_call", "status": "completed", "action": {"sources": []}},
                       {"type": "message", "content": [{"type": "output_text", "text": '{"urls":[]}'}]}]}
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test", "AVWIRE_PAID_BUDGET_ENABLED": "true",
                                    "GITHUB_ACTIONS": "false"}), \
         patch.object(paid_budget, "DATA_DIR", tmp_path), \
         patch.object(recovery.requests, "post", return_value=SimpleNamespace(status_code=200, json=lambda: data)) as post, \
         patch("usage.record_providers"):
        assert recovery._search(story()) == []
        assert post.call_count == 1
        ledger = json.loads((tmp_path / "paid-budget.json").read_text())
        assert not ledger["reservations"]
        assert sum(day["draft"] for day in ledger["days"].values()) > 0


def test_insufficient_never_exhausts(tmp_path):
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    with patch.object(news_retry, "DATA_DIR", tmp_path):
        ledger = news_retry.RetryLedger(now)
        for _ in range(8):
            ledger.insufficient(story())
            ledger.now += timedelta(hours=6)
        assert not ledger.exhausted(story())
        assert ledger.state(story())[1]["failureClass"] == "source_insufficient"
        assert ledger.plan([story()], 10)[0]


def test_reject_classification():
    assert recovery.insufficient_rejection({"decisionReason": "only a headline"}, story())
    assert not recovery.insufficient_rejection({"decisionReason": "outside aviation scope"}, story())
    group = story()
    group["items"][0]["fulltext"] = "Incomplete existing article text. " * 30
    assert not recovery.needs_evidence(group)
    assert recovery.needs_evidence(group, {"failureClass": "source_insufficient"})


def test_recovery_date_window_preserves_original_dates():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup('<meta property="article:published_time" content="2026-11-12T12:00:00Z">', 'lxml')
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    assert news_search._page_date(soup, now) is None
    assert news_search._page_date(soup, now, timedelta(days=14)).day == 12


def test_retry_survives_rss_rollover(tmp_path):
    import dedupe
    group = story()
    group["items"][0].update(source="IATA", sourceKey="iata", publishedUtc="2026-11-15T12:00Z")
    with patch.object(news_retry, "DATA_DIR", tmp_path), \
         patch.object(dedupe, "DATA_DIR", tmp_path), \
         patch.object(dedupe, "RAW_DIR", tmp_path / "empty-raw"), \
         patch.object(news_search, "cached_items", return_value=[]):
        ledger = news_retry.RetryLedger(datetime(2026, 11, 16, tzinfo=timezone.utc))
        ledger.insufficient(group)
        ledger.save()
        restored = dedupe._load_raw_items()
        assert len(restored) == 1
        assert restored[0]["url"] == group["items"][0]["url"]
        assert restored[0]["publishedUtc"] == "2026-11-15T12:00Z"
        assert "fulltext" not in restored[0]
        ledger.complete(group)
        ledger.save()
        assert dedupe._load_raw_items() == []
