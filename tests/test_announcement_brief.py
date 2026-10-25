"""Offline announcement safety, zero-call publication and rendering checks."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

_TEMP = tempfile.TemporaryDirectory(prefix="skytical-rule-brief-")
os.environ["AVWIRE_DATA_DIR"] = _TEMP.name
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import announcement_brief as rules
import write
import build
import airport_codes
import fulltext
from providers import GeminiProvider, ProviderError
from jinja2 import Environment, FileSystemLoader

NOW = datetime(2026, 10, 25, 1, tzinfo=timezone.utc)
DELIVERY = "American Airlines has taken delivery of its first Airbus A321XLR."


def group(sentence=DELIVERY, url="https://www.airbus.com/press-release/test"):
    return {"id": "g-announcement", "primarySource": "Airbus", "items": [{
        "title": sentence.rstrip('.'), "url": url, "source": "Airbus",
        "publishedUtc": NOW.isoformat(), "summary": sentence,
        "fulltext": sentence + "\nThe company published this official aviation announcement.",
    }]}


class Announcements(unittest.TestCase):
    def checked(self, source):
        draft = rules.compile_announcement(source, NOW)
        self.assertIsNotNone(draft)
        self.assertIsNone(write.validate_draft(draft, announcement=True))
        self.assertIsNotNone(write.validate_draft(draft))  # No model bypass.
        facts = write.verify_facts(draft, source, rules.WRITER)
        self.assertIsNone(write._evidence_binding_problem(draft, facts))
        self.assertIsNone(write.claim_evidence_problem(facts))
        _, _, error = write.verify_entity_evidence(draft, source, rules.WRITER)
        self.assertIsNone(error)
        self.assertIsNone(write.glossary_problem(draft, source))
        self.assertLessEqual(len(draft['flash']['zh']), 40)
        return draft, facts

    def test_delivery_and_word_number(self):
        draft, _ = self.checked(group())
        self.assertIn("首架", draft['zh']['title'])
        self.assertEqual(draft['eventStatus'], 'confirmed')
        draft, _ = self.checked(group(DELIVERY.replace('its first', 'two')))
        self.assertIn('2架', draft['zh']['title'])

    def test_route_frequency_facility(self):
        for sentence, url, status in [
            ("American Airlines will launch flights between Heathrow Airport and Los Angeles International Airport on November 1, 2026.", "https://news.aa.com/press/test", 'planned'),
            ("American Airlines has resumed services between Heathrow Airport and Los Angeles International Airport on October 24, 2026.", "https://news.aa.com/press/test", 'confirmed'),
            ("American Airlines will increase flights between Heathrow Airport and Los Angeles International Airport from 7 to 14 per week from November 1, 2026.", "https://news.aa.com/press/test", 'planned'),
            ("Heathrow Airport will close Terminal 2 on November 1, 2026.", "https://www.caa.gov.tw/news/test", 'planned'),
        ]:
            with self.subTest(sentence=sentence):
                source = group(sentence, url)
                draft, facts = self.checked(source)
                self.assertEqual(draft['eventStatus'], status)
                article = write.build_article(draft, source, NOW, set(), rules.WRITER, facts, announcement=True)
                self.assertEqual(airport_codes.validate_article(article), [])
                self.assertIn('LHR', draft['zh']['body'][0])

    def test_declines_unsafe_or_incomplete_inputs(self):
        cases = []
        for value in ['may take', 'has not taken', 'is expected to take']:
            cases.append(group(DELIVERY.replace('has taken', value)))
        for prefix in ['Correction: ', 'Although demand may fall, ', 'Media contact: ']:
            source = group(); source['items'][0]['fulltext'] = prefix + DELIVERY
            cases.append(source)
        source = group(); source['items'][0]['fulltext'] = ''; cases.append(source)
        source = group(); source['items'][0]['dateInferred'] = True; cases.append(source)
        source = group(); source['items'][0]['publishedUtc'] = (NOW - timedelta(days=30)).isoformat(); cases.append(source)
        source = group(); source['items'][0]['publishedUtc'] = (NOW + timedelta(days=1)).isoformat(); cases.append(source)
        source = group(); source['items'].append(copy.deepcopy(source['items'][0])); cases.append(source)
        cases.append(group(url='https://www.airbus.com.evil.test/press/test'))
        cases.append(group(url='https://user@www.airbus.com/press/test'))
        cases.append(group(url='https://www.airbus.com:99999/press/test'))
        cases.append(group(DELIVERY.replace('Airbus A321XLR', 'Boeing 787-9')))
        source = group(); source['items'][0]['title'] = 'Airbus opens a training centre'; cases.append(source)
        source = group(); source['items'][0]['title'] = 'American Airlines will receive its first Airbus A321XLR'; cases.append(source)
        cases.append(group(DELIVERY.replace('its first', 'the first')))
        cases.append(group("American Airlines will launch flights between London and Los Angeles on November 1, 2026.", "https://news.aa.com/test"))
        cases.append(group("American Airlines will launch flights between Heathrow Airport and Los Angeles International Airport on February 30, 2026.", "https://news.aa.com/test"))
        cases.append(group("American Airlines will decrease flights between Heathrow Airport and Los Angeles International Airport from 7 to 14 per week from November 1, 2026.", "https://news.aa.com/test"))
        source = group(); source['items'][0]['fulltext'] += '\n' + DELIVERY.replace('American Airlines', 'Delta Air Lines'); cases.append(source)
        for source in cases:
            with self.subTest(source=source):
                self.assertIsNone(rules.compile_announcement(source, NOW))

    def test_normal_contract_cannot_be_lowered_by_draft_flag(self):
        draft = rules.compile_announcement(group(), NOW)
        draft['articleFormat'] = 'announcement'
        draft['_announcement'] = True
        self.assertIsNotNone(write.validate_draft(draft))

    def test_two_enrichment_passes_share_one_fetch_budget(self):
        first, second = group(), group(url='https://news.aa.com/press/other')
        first['items'][0].pop('fulltext'); second['items'][0].pop('fulltext')
        budget = [1]
        with patch.object(fulltext, 'CACHE_PATH', Path(_TEMP.name)/'budget-cache.json'), \
                patch.object(fulltext, 'fetch_fulltext', return_value=DELIVERY) as fetch:
            fulltext.enrich_pending([first], fetch_budget=budget)
            fulltext.enrich_pending([second], fetch_budget=budget)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(budget, [0])
        self.assertNotIn('fulltext', second['items'][0])

    def test_configured_model_is_not_probed_for_eligible_notice(self):
        data = Path(_TEMP.name)
        (data/'pending.json').write_text(json.dumps({'groups': [group()]}), encoding='utf-8')
        provider = GeminiProvider('gemini-3.6-flash')
        with patch.object(write, 'now_utc', return_value=NOW), \
                patch.object(write, 'build_providers', return_value=[provider]), \
                patch.object(write, 'enrich_pending'), \
                patch('companion.enrich_thin_groups') as companion, \
                patch('pla_series.enrich_groups'), \
                patch('free_provider_probe.prepare_routes', side_effect=AssertionError('probe called')), \
                patch.object(write, 'draft_group', side_effect=AssertionError('model called')):
            write.main()
        self.assertEqual(provider.http_calls, 0)
        self.assertEqual(companion.call_args.args[0], [])
        self.assertEqual(json.loads((data/'pending.json').read_text())['groups'], [])

    def test_unsupported_notice_reaches_original_model_path(self):
        data = Path(_TEMP.name)
        source = group(DELIVERY.replace('has taken', 'may take'))
        (data/'pending.json').write_text(json.dumps({'groups': [source]}), encoding='utf-8')
        provider = GeminiProvider('gemini-3.6-flash')
        with patch.object(write, 'now_utc', return_value=NOW), \
                patch.object(write, 'build_providers', return_value=[provider]), \
                patch.object(write, 'enrich_pending'), \
                patch('companion.enrich_thin_groups'), \
                patch('pla_series.enrich_groups'), \
                patch('free_provider_probe.prepare_routes', return_value=[provider]), \
                patch.object(write, 'draft_group', side_effect=ProviderError('offline')) as model:
            write.main()
        self.assertGreater(model.call_count, 0)
        self.assertEqual(json.loads((data/'pending.json').read_text())['groups'][0]['id'], source['id'])

    def test_zero_key_zero_probe_publication_and_second_run(self):
        data = Path(_TEMP.name)
        for path in data.glob('*.json'):path.unlink()
        (data/'articles').mkdir(exist_ok=True)
        for path in (data/'articles').glob('*.json'):path.unlink()
        (data/'pending.json').write_text(json.dumps({'groups': [group()]}), encoding='utf-8')
        with patch.object(write, 'now_utc', return_value=NOW), \
                patch.object(write, 'build_providers', return_value=[]), \
                patch.object(write, 'enrich_pending'), \
                patch('companion.enrich_thin_groups'), \
                patch('pla_series.enrich_groups'), \
                patch('free_provider_probe.prepare_routes', side_effect=AssertionError('probe called')), \
                patch.object(write, 'draft_group', side_effect=AssertionError('model called')):
            write.main()
            write.main()
        rows = [a for path in (data/'articles').glob('*.json') for a in json.loads(path.read_text(encoding='utf-8'))['articles']]
        self.assertEqual(len(rows), 1)
        article = rows[0]
        self.assertEqual(article['writer'], rules.WRITER)
        self.assertEqual(article['articleFormat'], 'announcement')
        self.assertEqual(article['generationMode'], 'rules')
        self.assertEqual(json.loads((data/'pending.json').read_text())['groups'], [])
        self.assertIn(group()['items'][0]['url'], json.loads((data/'seen.json').read_text())['urls'])
        view = build.prep_article(article)
        self.assertEqual(view['article_format'], 'announcement')
        self.assertIsNone(view['writer_model'])
        for lang in ('zh', 'en'):
            a = build.art_view(view, lang)
            ctx = build.base_ctx(lang, 'news', f"news/{article['id']}/",
                                 title=a['title'], description=a['summary'], ticker=[],
                                 build={'date': '2026-10-25 SUN', 'utc_hm': '01:00', 'tpe_hm': '09:00', 'stamp': '2026-10-25 01:00'})
            ctx['a'] = a
            html = Environment(loader=FileSystemLoader(str(ROOT/'templates')), autoescape=True).get_template('article.html').render(**ctx)
            self.assertIn(build.L[lang]['announcementLabel'], html)
            self.assertIn(build.L[lang]['ruleNote'], html)
            self.assertNotIn(build.L[lang]['genNote'], html)
            item = build.search_index_item(view, build.load_search_alias_groups())
            self.assertEqual(item['articleFormat'], 'announcement')
            self.assertEqual(item['models'], [])


if __name__ == '__main__':
    unittest.main()
