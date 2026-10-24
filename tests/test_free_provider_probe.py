"""Offline admission, quarantine, diagnostics and latency regression checks."""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import free_provider_probe as probe
import providers


def response(code, body):
    return SimpleNamespace(status_code=code, json=lambda: body, headers={})


def main():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    p = SimpleNamespace(name='gemini', model='gemini-3.6-flash', label='gemini:test', requires_verification=True)
    paid = SimpleNamespace(name='openai', model='gpt-6', label='openai:paid', requires_verification=False)
    calls = []
    def validate(provider, source, **kwargs):
        calls.append((provider.label, source['id'], kwargs))
        return {'status': 'publish_brief'}, [{'factId': 'F1'}]
    with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'HEALTH_PATH', Path(tmp)/'health.json'):
        with patch.object(probe, 'catalog', return_value={p.model}):
            assert probe.prepare_routes([p, paid], now, validate) == [p, paid]
            assert len(calls) == 1 and calls[0][2]['max_attempt_seconds'] == 180
            assert probe.prepare_routes([p], now+timedelta(hours=1), validate) == [p]
            assert len(calls) == 1, 'verified routes are not probed every hour'
            assert probe.prepare_routes([p], now+timedelta(hours=25), validate) == [p]
            assert len(calls) == 2
        with patch.object(probe, 'catalog', return_value=set()):
            assert probe.prepare_routes([p], now, validate, force=True) == []
            assert probe.load_routes()[p.label]['status'] == 'unavailable'
            assert len(calls) == 2, 'absent model does not receive a generation request'
        with patch.object(probe, 'catalog', side_effect=AssertionError('must remain quarantined')):
            assert not probe.prepare_routes([p], now+timedelta(hours=2), validate)
        def reject(*args, **kwargs):
            return {'status':'reject'}, []
        with patch.object(probe, 'catalog', return_value={p.model}):
            assert not probe.prepare_routes([p], now, reject, force=True)
        assert probe.load_routes()[p.label]['status'] == 'waiting'
        exc = providers.ProviderRouteError(response(400, {'error':{'status':'INVALID_ARGUMENT', 'message':'Unknown name "thinkingConfig". SOURCE secret prompt nvapi-SECRET https://private.example/'}}))
        assert probe.quarantine(p, exc)
        row = probe.load_routes()[p.label]
        assert row['failureClass'] == 'invalid_request'
        diagnostic = json.dumps(row)
        assert 'thinkingConfig' in diagnostic and 'unsupported_field' in diagnostic
        assert all(word not in diagnostic for word in ('SOURCE', 'secret prompt', 'nvapi-SECRET', 'private.example'))
        assert providers.classify_failure(providers.ProviderRouteError(response(404, {}))) == 'model_unavailable'
        assert not probe.quarantine(p, providers.ProviderError('HTTP 503'))
        nim = providers.NvidiaProvider('nvidia/nemotron-3-ultra-550b-a55b')
        attempted = [nim, paid]
        with patch.object(probe, 'catalog', return_value={nim.model, probe.FALLBACK_MODEL}):
            result = probe.prepare_routes(attempted, now, validate, force=True)
        assert [x.model for x in result] == [nim.model, probe.FALLBACK_MODEL, paid.model]
        assert attempted == result, 'added free fallback remains in usage accounting'
        assert all(call[1] == 'free-provider-probe-h140-v1' for call in calls)
    pages = [response(200, {'models':[
        {'name':'models/'+p.model, 'supportedGenerationMethods':['generateContent']},
        {'name':'models/embedding-only', 'supportedGenerationMethods':['embedContent']}],
        'nextPageToken':'second'}), response(200, {'models':[
        {'name':'models/gemini-3.5-flash', 'supportedGenerationMethods':['generateContent']}]})]
    with patch.dict(os.environ, {'GEMINI_API_KEY':'test-only'}), patch.object(probe.requests, 'get', side_effect=pages) as get:
        assert probe.catalog(p) == {p.model, 'gemini-3.5-flash'}
        assert get.call_args_list[1].kwargs['params']['pageToken'] == 'second'
    for cls in (providers.GeminiProvider, providers.NvidiaProvider, providers.OpenRouterProvider):
        assert cls.max_attempt_seconds == 180 and cls.group_budget_seconds >= 360
    assert providers.WechatProvider.max_attempt_seconds == 60
    import write
    free = providers.GeminiProvider('gemini-3.6-flash')
    fallback = providers.OpenAIProvider('gpt-6')
    assert write._preferred_attempt_cap(free) == 180
    assert write._provider_chain_budget([free]) >= 360
    assert write._provider_chain_budget([free, fallback]) >= write._fallback_reserve_seconds([fallback])+180
    print('PASS route verification, fixed-source admission, expiry, 400/404 quarantine, secret-safe errors and 180s budgets')


if __name__ == '__main__':
    main()
