"""Bounded Groq minute-window recovery; never relax source verification."""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import providers
import free_provider_probe as probe


def response(status, body, headers=None):
    return SimpleNamespace(status_code=status, json=lambda: body, headers=headers or {})


def main():
    minute = response(429, {'error': {'message': 'Rate limit on tokens per minute (TPM). SOURCE gsk_SECRET'}}, {'retry-after': '12.5'})
    good = response(200, {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":1}'}}], 'usage': {'prompt_tokens': 11, 'completion_tokens': 3}})
    with patch.dict(os.environ, {'GROQ_API_KEY': 'test-key'}):
        p = providers.GroqProvider()
        with patch.object(providers.requests, 'post', side_effect=[minute, good]) as post, patch.object(providers.time, 'sleep') as sleep:
            assert p.draft('system', 'source', {'type': 'object'}) == {'ok': 1}
        assert post.call_count == 2 and sleep.call_args.args == (12.5,)
        assert p.http_calls == 2 and p.usage['usageEvents'] == 1
        assert len(p.request_log) == 2 and 'gsk_SECRET' not in str(p.request_log)
        assert p._response_schema is None
        p = providers.GroqProvider()
        with patch.object(providers.requests, 'post', return_value=minute) as post, patch.object(providers.time, 'sleep') as sleep:
            try:
                p.draft('sys', 'source', {})
                raise AssertionError('second rate limit accepted')
            except providers.ProviderError as exc:
                assert not isinstance(exc, providers.ProviderQuotaError)
                assert providers.classify_failure(exc) == 'rate_limit'
        assert post.call_count == 2 and sleep.call_count == 1
        assert p._response_schema is None
        for delay in ('NaN', 'inf', '-1', '0', '61', 'invalid'):
            assert p._minute_retry_delay(response(429, {'error': {'message': 'tokens per minute'}}, {'retry-after': delay})) is None
        daily = response(429, {'error': {'message': 'tokens per day (TPD) exceeded'}}, {'retry-after': '12'})
        with patch.object(providers.requests, 'post', return_value=daily) as post, patch.object(providers.time, 'sleep') as sleep:
            try:
                p.draft('sys', 'source', {})
                raise AssertionError('daily quota accepted')
            except providers.ProviderQuotaError:
                pass
        assert post.call_count == 1 and not sleep.called
        # Unsupported Groq models do not receive GPT-OSS-only schema options.
        q = providers.GroqProvider('other-model')
        with patch.object(providers.requests, 'post', return_value=good) as post:
            q.draft('sys', 'source', {'type': 'object'})
            assert 'response_format' not in post.call_args.kwargs['json']
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'HEALTH_PATH', Path(tmp)/'routes.json'):
        limited = probe.record('groq:test', failure='rate_limit', now=now)
        quota = probe.record('groq:daily', failure='quota', now=now)
        assert probe.parse_iso(limited['untilUtc']) == now + timedelta(minutes=1)
        assert probe.parse_iso(quota['untilUtc']) == now + timedelta(hours=6)
        assert probe.PROBE_VERSION == 3
    print('PASS native schema, finite Retry-After, one retry, quota isolation, accounting and minute cooldown')


if __name__ == '__main__':
    main()
