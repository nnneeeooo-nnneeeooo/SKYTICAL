"""Rendered article fallback contract, independent of template branch syntax."""
from pathlib import Path
import sys

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pipeline'))
import build


@pytest.mark.parametrize('has_image', [False, True])
def test_article_template_always_has_a_visual_fallback(has_image):
    photo = {'url':'https://example.com/photo.jpg','subject':'Aircraft file photo',
             'description':'Aircraft file photo','provider':'manual','curated':True,
             'kind':'file_photo'} if has_image else None
    raw = {'id':'a-render-fallback','cat':'biz','publishedUtc':'2026-11-15T12:00Z',
           'zh':{'title':'航空公司公布消息','summary':'已核對的摘要。','body':['已核對的內容。']},
           'en':{'title':'Airline update','summary':'Verified summary.','body':['Verified copy.']},
           'sources':[{'name':'Source','url':'https://example.com/story'}],'image':photo}
    env = Environment(loader=FileSystemLoader(str(ROOT/'templates')),autoescape=True,undefined=StrictUndefined)
    for lang in ('zh','en'):
        view=build.art_view(build.prep_article(raw),lang)
        ctx=build.base_ctx(lang,'news','news/a-render-fallback/',title=view['title'],
                           description=view['summary'],ticker=[],
                           build={'date':'2026-11-16 MON','utc_hm':'00:00','tpe_hm':'8:00','stamp':'2026-11-16'})
        ctx['a']=view
        soup=BeautifulSoup(env.get_template('article.html').render(**ctx),'html.parser')
        figure=soup.select_one('.article-page figure')
        assert figure is not None
        assert figure.has_attr('data-image-fallback') is not has_image
        if has_image:
            assert figure.img['src'] == photo['url']
        else:
            assert 'skytical-social.png' in figure.img['src']
