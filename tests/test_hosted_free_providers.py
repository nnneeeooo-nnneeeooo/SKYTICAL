"""Offline contracts for Groq and Workers AI; never sends credentials."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import providers
import free_provider_probe as probe
from editorial_policy import is_free_provider


def response(body, status=200):
    return SimpleNamespace(status_code=status, json=lambda: body, headers={})


def main():
    creds = {'GROQ_API_KEY': 'test-groq', 'CLOUDFLARE_API_TOKEN': 'test-cf',
             'CLOUDFLARE_ACCOUNT_ID': 'a'*32}
    for cls in (providers.GroqProvider, providers.CloudflareProvider):
        with patch.dict(os.environ, {}, clear=True):
            assert not cls().available()
        with patch.dict(os.environ, creds, clear=True):
            p = cls()
            assert p.available() and p.requires_verification and is_free_provider(p)
            assert [x.name for x in providers.build_providers()] == ['groq', 'cloudflare']
            good = response({'choices': [{'finish_reason': 'stop', 'message': {
                'content': '{"ok":1}', 'reasoning_content': '{"leak":1}'}}],
                'usage': {'prompt_tokens': 11, 'completion_tokens': 3}})
            with patch.object(providers.requests, 'post', return_value=good) as post:
                assert p.draft('sys', 'user', {'type': 'object'}) == {'ok': 1}
                request = post.call_args
                assert request.args[0] == p._endpoint()
                body = request.kwargs['json']
                assert body['model'] == p.model and body['max_tokens'] == p.output_tokens
                assert 'JSON Schema' in body['messages'][1]['content']
                assert not any(k in body for k in ('thinking', 'reasoning_effort', 'chat_template_kwargs'))
                assert p.usage['inputTokens'] == 11 and p.usage['outputTokens'] == 3
                assert 'test-cf' not in str(p.request_log) and 'test-groq' not in str(p.request_log)
            with patch.object(providers.requests, 'post', return_value=good) as post:
                p.draft('sys', 'user', {'properties': {'status': {}}})
                system = post.call_args.kwargs['json']['messages'][0]['content']
                assert '180-320' in system and '90-150' in system
                assert 'never pad or repeat' in system
            broken = response({'choices': [{'message': {'content': '{"ok":1,,'}}]})
            with patch.object(providers.requests, 'post', side_effect=[broken, good]) as post:
                assert p.draft('sys', 'user', {}) == {'ok': 1}
                assert post.call_count == 2 and p.repair_calls == 1
                assert post.call_args.kwargs['json']['max_tokens'] == p.repair_tokens
            for status, exc in [(401, providers.ProviderAuthError),
                                (429, providers.ProviderQuotaError),
                                (404, providers.ProviderRouteError),
                                (503, providers.ProviderError)]:
                try:
                    p._check_status(response({}, status))
                    raise AssertionError('failure accepted')
                except exc:
                    pass
            for finish in ('length',):
                try:
                    p._final_text(response({'choices': [{'finish_reason': finish}]}))
                    raise AssertionError('truncation accepted')
                except providers.ProviderError:
                    pass
            data = ({'result': [{'name': p.model}], 'success': True}
                    if p.name == 'cloudflare' else {'data': [{'id': p.model}]})
            with patch.object(probe.requests, 'get', return_value=response(data)) as get:
                assert probe.catalog(p) == {p.model}
                assert ('cloudflare.com' if p.name == 'cloudflare' else 'groq.com') in get.call_args.args[0]
            # An unverified new service must use the same admission fixture.
            import tempfile
            from datetime import datetime, timezone
            with tempfile.TemporaryDirectory() as tmp, patch.object(probe, 'HEALTH_PATH', Path(tmp)/'health.json'), patch.object(probe, 'catalog', return_value={p.model}):
                assert probe.prepare_routes([p], datetime.now(timezone.utc), lambda *a, **kw: ({'status': 'reject'}, [])) == []
    with patch.dict(os.environ, {**creds, 'CLOUDFLARE_ACCOUNT_ID': '../bad'}, clear=True):
        assert not providers.CloudflareProvider().available()
    try:
        providers.GroqProvider()._check_status(response({'error': {
            'message': 'Limit 8000, Requested 9000. SOURCE PRIVATE gsk_SECRET'}}, 413))
        raise AssertionError('oversized request accepted')
    except providers.ProviderError as exc:
        assert 'token_limit=8000 requested_tokens=9000' in str(exc)
        assert 'PRIVATE' not in str(exc) and 'gsk_SECRET' not in str(exc)
    import manual_draft
    with patch.dict(os.environ, creds, clear=True):
        selected = manual_draft._providers_for({
            'model': 'cloudflare:@cf/qwen/qwen3-30b-a3b-fp8',
            'reasoningTier': 'deep'})
        assert [p.name for p in selected] == ['cloudflare', 'groq']
        assert manual_draft.CUSTOM_MODEL_RE.fullmatch(selected[0].label)
    import write
    p = providers.GroqProvider()
    prompts = []
    def reject(system, user, schema):
        prompts.append(user)
        return {'status': 'reject', 'reason': 'insufficient evidence'}
    with patch.object(write, 'group_prompt', return_value='SOURCE_TEST'), patch.object(
            write, 'validate_draft', side_effect=['exact quote required', None]), patch.object(
            p, 'draft', side_effect=reject):
        result, facts = write._validated_draft(p, {'id': 'test'}, tries=2)
    assert result['status'] == 'reject' and facts == [] and len(prompts) == 2
    assert 'SOURCE_TEST' in prompts[1] and 'exact quote required' in prompts[1]
    assert 'PREVIOUS DRAFT (untrusted' not in prompts[1]
    assert 'gsk_SECRET'  not in providers.safe_failure_message('failed gsk_SECRET')
    print('PASS hosted providers: credentials, routing, payload, usage, repair, errors, catalog and admission')


if __name__ == '__main__':
    main()
