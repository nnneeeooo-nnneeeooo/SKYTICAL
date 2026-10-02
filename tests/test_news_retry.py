"""Persistent story retry budgets without API calls or production writes."""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import news_retry


def story(n, extra=False):
    urls = [f"https://example.com/news/{n}"]
    if extra:
        urls.append(f"https://official.example.com/news/{n}")
    return {"id": str(n), "items": [{"url": u, "title": "Test news"} for u in urls]}


def main():
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp, patch.object(news_retry, "DATA_DIR", Path(tmp)):
        ledger = news_retry.RetryLedger(now)
        group = story(1)
        for failure, hours in enumerate((2, 6, 24), 1):
            ledger.failure(group, content=True)
            ledger.save()
            ledger = news_retry.RetryLedger(now)
            assert ledger.state(group)[1]["contentFailures"] == failure
            chosen, deferred = ledger.plan([group | {"id": "regenerated"}], 10)
            assert not chosen and len(deferred) == 1
            now += timedelta(hours=hours)
            ledger = news_retry.RetryLedger(now)
            assert ledger.plan([group], 10)[0] == [group]
        ledger.failure(group, content=True)
        ledger.save()
        ledger = news_retry.RetryLedger(now + timedelta(days=1))
        assert ledger.exhausted(group)
        assert not ledger.plan([group], 10)[0]
        renewed = story(1, extra=True)
        assert ledger.plan([renewed], 10)[0] == [renewed]
        assert ledger.state(renewed)[1]["contentFailures"] == 0
        assert not ledger.exhausted(group)
        ledger.failure(renewed, content=True)
        ledger.complete(renewed)
        assert not ledger.rows

        for n in range(5):
            ledger.failure(story(n), content=False)
        ledger.now += timedelta(hours=2)
        fresh = [story(n) for n in range(10, 22)]
        chosen, deferred = ledger.plan([story(n) for n in range(5)] + fresh, 10)
        assert chosen[:8] == fresh[:8]
        assert len(chosen) == 10 and len(deferred) == 7
        assert all(r["contentFailures"] == 0 for r in ledger.rows.values())
        for _ in range(5):
            ledger.failure(story(0), content=False)
        assert not ledger.exhausted(story(0))
        assert ledger.state(story(0))[1]["nextRetryUtc"] == news_retry.iso_minute(
            ledger.now + timedelta(hours=24))
        ledger.save()
        assert not news_retry.RetryLedger(ledger.now + timedelta(days=31)).rows
    print("PASS retry persistence, 2/6/24h backoff, cap, new sources and provider separation")


if __name__ == "__main__":
    main()
