"""Bounded OpenAI news discovery; only independently fetched pages enter dedupe.

Search summaries and model-supplied dates are never article evidence. Public
model labels stay gpt-6; the existing secret resolves the actual API model.
"""
from __future__ import annotations
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from common import DATA_DIR, load_json, save_json, now_utc, parse_iso, iso_minute, norm_url
import fulltext
import grounded

STATE_PATH = DATA_DIR / 'news-search.json'
MAX_PAGES = 8
INTERVAL = timedelta(hours=6)


def _allowed(url):
    try:
        p = urlsplit(url)
        return (p.scheme == 'https' and p.hostname in fulltext.ALLOWED_HOSTS
                and not p.username and not p.password and p.port in (None, 443))
    except (ValueError, TypeError):
        return False


def _page_date(soup, now):
    values = []
    for meta in soup.find_all('meta'):
        if str(meta.get('property') or meta.get('name') or '').lower() in {
                'article:published_time', 'article:modified_time', 'datepublished', 'datemodified'}:
            values.append(meta.get('content'))
    def dates(node):
        if isinstance(node, list):
            for child in node:
                dates(child)
        elif isinstance(node, dict):
            kind = node.get('@type', [])
            kind = [kind] if isinstance(kind, str) else kind
            if any(x in {'NewsArticle', 'Article', 'ReportageNewsArticle'} for x in kind):
                values.extend([node.get('datePublished'), node.get('dateModified')])
            if '@graph' in node:
                dates(node['@graph'])
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            dates(json.loads(script.string or ''))
        except (ValueError, TypeError):
            continue
    for value in values:
        try:
            # A bare date or timezone-less string is not verified timing.
            from datetime import datetime
            dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
            if dt.tzinfo and now - timedelta(hours=24) <= dt <= now:
                return dt
        except (ValueError, TypeError):
            continue
    return None


def fetch_candidate(url, now):
    if not _allowed(url) or not fulltext.robots_allows(url):
        return None
    # Fail closed on redirects: never send a request to an unchecked target.
    try:
        r = requests.get(url, headers=fulltext.HEADERS, timeout=fulltext.TIMEOUT,
                         allow_redirects=False)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    html = r.content
    soup = BeautifulSoup(html, 'lxml')
    date = _page_date(soup, now)
    title = soup.find('h1')
    text = fulltext.extract_text(html)
    if not date or not title or len(text) < 200:
        return None
    title = title.get_text(' ', strip=True)[:300]
    if not title:
        return None
    host = urlsplit(url).hostname
    return {'title': title, 'url': url, 'publishedUtc': iso_minute(date),
            'source': host, 'sourceKey': 'search_' + host.replace('.', '_'),
            'summary': '', 'fulltext': text, 'discoveredBy': 'openai:gpt-6+search'}


def cached_items(now=None, path=None):
    now = now or now_utc()
    state = load_json(path or STATE_PATH, {})
    if not isinstance(state, dict):
        return []
    items = []
    for item in state.get('items') or []:
        try:
            valid = (isinstance(item, dict) and _allowed(item.get('url'))
                     and bool(item.get('title')) and len(item.get('fulltext') or '') >= 200
                     and now - timedelta(hours=24) <= parse_iso(item['publishedUtc']) <= now)
        except (ValueError, TypeError, KeyError):
            valid = False
        if valid:
            items.append(item)
    return items[:MAX_PAGES]


def main():
    if os.environ.get('NEWS_WEB_SEARCH', '').lower() != 'true':
        return
    if not os.environ.get('OPENAI_API_KEY') or not os.environ.get('AVWIRE_OPENAI_API_MODEL'):
        print('news-search: skipped (credentials/model mapping unavailable)')
        return
    now = now_utc()
    state = load_json(STATE_PATH, {})
    try:
        if now < parse_iso(state['nextAttemptUtc']):
            print('news-search: cached; next search not due')
            return
    except (ValueError, TypeError, KeyError):
        pass
    # Reserve the window even on failure; no hourly paid retry storm.
    state = {'nextAttemptUtc': iso_minute(now + INTERVAL),
             'checkedUtc': iso_minute(now), 'items': cached_items(now)}
    save_json(STATE_PATH, state)
    try:
        window = SimpleNamespace(window_start=now - timedelta(hours=24), window_end=now)
        data, _ = grounded.call_openai_grounded(window)
        sections, _ = grounded.sanitize_items(data, [], {}, now, window)
        urls = list(dict.fromkeys(norm_url(s['url']) for rows in sections.values()
                                 for item in rows for s in item['sources']
                                 if _allowed(s['url'])))[:MAX_PAGES]
        found = []
        for url in urls:
            item = fetch_candidate(url, now)
            if item:
                found.append(item)
        # Preserve still-fresh discoveries until expiry, even if a later sweep is empty.
        by_url = {norm_url(x['url']): x for x in state['items']}
        by_url.update({norm_url(x['url']): x for x in found})
        state['items'] = sorted(by_url.values(), key=lambda x: x['publishedUtc'], reverse=True)[:MAX_PAGES]
        state['status'] = 'completed'
        print(f'news-search: independently fetched {len(found)} candidate(s); normal publication gates apply')
    except Exception as exc:
        state['status'] = 'failed'
        # Finite class only: never print provider bodies, model mapping or keys.
        print(f'::warning::news-search failed ({type(exc).__name__}); continuing ordinary sources')
    save_json(STATE_PATH, state)


if __name__ == '__main__':
    main()
