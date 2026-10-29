"""Offline discovery contracts: model output never becomes source evidence."""
import os
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'pipeline'))
import news_search as n
import dedupe
from common import load_json, save_json, iso_minute


def main():
    now = datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
    url = 'https://www.airbus.com/en/newsroom/story'
    text = 'Original verified source sentence about aircraft testing. ' * 8
    def page(date):
        return ('<html><head><meta property="article:published_time" content="'+date+'"></head>'
                '<body><article><h1>Original aircraft testing headline</h1><p>'+text+'</p></article></body></html>').encode()
    def response(date):
        return SimpleNamespace(status_code=200, content=page(date))
    with patch.object(n.fulltext, 'robots_allows', return_value=True), patch.object(n.requests, 'get', return_value=response('2026-10-29T10:00:00Z')) as get:
        item = n.fetch_candidate(url, now)
        assert item['summary'] == '' and text.strip() in item['fulltext']
        assert item['title'] == 'Original aircraft testing headline'
        assert item['publishedUtc'] == '2026-10-29T10:00Z'
        assert get.call_args.kwargs['allow_redirects'] is False
        for blocked in ['https://evil.example/story','http://www.airbus.com/x','https://www.airbus.com@evil.example/x','https://www.airbus.com:444/x']:
            assert n.fetch_candidate(blocked, now) is None
        assert get.call_count == 1
    for date in ['2026-10-29', '2026-10-29T10:00:00', '2026-10-20T10:00:00Z', '2026-10-30T10:00:00Z', 'invalid']:
        with patch.object(n.fulltext, 'robots_allows', return_value=True), patch.object(n.requests, 'get', return_value=response(date)):
            assert n.fetch_candidate(url, now) is None
    structured = n.BeautifulSoup('<script type="application/ld+json">{"@graph":[{"@type":"NewsArticle","datePublished":"2026-10-29T11:00:00Z"}]}</script>', 'lxml')
    assert n._page_date(structured, now).hour == 11
    with patch.object(n.fulltext, 'robots_allows', return_value=False), patch.object(n.requests, 'get') as get:
        assert n.fetch_candidate(url, now) is None and not get.called
    with patch.object(n.fulltext, 'robots_allows', return_value=True), patch.object(n.requests, 'get', return_value=SimpleNamespace(status_code=302)):
        assert n.fetch_candidate(url, now) is None
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'news-search.json'
        env = {'NEWS_WEB_SEARCH':'true','OPENAI_API_KEY':'test-secret','AVWIRE_OPENAI_API_MODEL':'private-test-model'}
        sections = {'aviation_incidents':[{'sources':[{'url':url}]}]}
        with patch.object(n, 'STATE_PATH', path), patch.object(n, 'now_utc', return_value=now), patch.dict(os.environ,env), patch.object(n.grounded,'call_openai_grounded',return_value=({},None)) as call, patch.object(n.grounded,'sanitize_items',return_value=(sections,[])), patch.object(n,'fetch_candidate',return_value=item):
            n.main()
            n.main()
            assert call.call_count == 1
            state = load_json(path,{})
            assert state['nextAttemptUtc'] == iso_minute(now+timedelta(hours=6))
            assert state['items'][0]['title'] == item['title']
            assert 'test-secret' not in str(state) and 'private-test-model' not in str(state)
            assert n.cached_items(now+timedelta(days=2)) == []
        path.unlink()
        with patch.object(n,'STATE_PATH',path), patch.object(n,'now_utc',return_value=now), patch.dict(os.environ,env), patch.object(n.grounded,'call_openai_grounded',side_effect=RuntimeError('private body')) as call:
            n.main()
            n.main()
            assert call.call_count == 1 and load_json(path,{})['status']=='failed'
        save_json(path,{'items':[item]})
        with patch.object(dedupe,'DATA_DIR',Path(tmp)), patch.object(dedupe,'SOURCES',{}), patch.object(n,'now_utc',return_value=now):
            assert dedupe._load_raw_items() == [item]
    print('PASS news discovery: original page evidence, date/host/robots/redirect gates, bounded paid attempts, cache expiry and dedupe intake')


if __name__ == '__main__':
    main()
