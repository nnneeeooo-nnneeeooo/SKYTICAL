"""Regressions for headline substitution and broken factual card excerpts."""
import sys
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
import build


@pytest.mark.parametrize("title,summary,lang", [
    ("airBaltic與漢莎集團簽新濕租協議，A220機隊2027年縮減至36架",
     "airBaltic與漢莎集團簽署新的長期濕租協議，夏季最多以6架、冬季4架空中巴士A220-300含機組為漢莎營運，濕租業務與自有定期航網並行。", "zh"),
    ("A350-1000ULR創飛行紀錄",
     "空中巴士A350-1000ULR以24小時24分完成墨爾本至土魯斯12,507公里飛行，並取得飛行紀錄認證。", "zh"),
    ("David Cummins宣誓就任TSA第八任局長",
     "美國參議院通過確認案後，David Cummins已正式宣誓就任TSA第八任局長。", "zh"),
    ("Airline signs wet-lease agreement",
     "The airline will operate up to six Airbus A220-300 aircraft with crew during summer and four during winter under the new agreement.", "en"),
    ("Airline sets a record", "The flight covered 12,507 kilometres in 24 hours and 24 minutes.", "en"),
])
def test_long_summary_keeps_original_facts_instead_of_short_headline(title, summary, lang):
    assert build.notification_summary(summary, lang, title) == summary


@pytest.mark.parametrize("title,summary,lang", [
    ("航空公司增班", "航空公司增班。", "zh"),
    ("航空公司增班", "航空公司 增班！", "zh"),
    ("Airline adds flights", "AIRLINE adds flights.", "en"),
    ("標題", "", "zh"),
    ("Headline", None, "en"),
])
def test_no_summary_is_invented_from_a_headline(title, summary, lang):
    assert build.notification_summary(summary, lang, title) == ""


def test_empty_hero_keeps_a_hidden_node_for_later_carousel_summaries():
    env = Environment(loader=FileSystemLoader(str(ROOT / "templates")), autoescape=True)
    macro = env.get_template("_summary.html").module.notification_summary
    assert not BeautifulSoup(macro("", "Summary", "feed"), "html.parser").select(".summary-preview")
    hero = BeautifulSoup(macro("", "Summary", "hero"), "html.parser")
    assert hero.select_one(".summary-preview[data-summary-empty] .summary-preview__text") is not None
    visible = BeautifulSoup(macro("Flight covers 12,507 kilometres.", "Summary", "hero"), "html.parser")
    assert not visible.select("[data-summary-empty]")
    assert visible.select_one(".summary-preview__text").text == "Flight covers 12,507 kilometres."


def test_article_and_carousel_views_keep_the_editorial_summary_without_mutation():
    raw = {"id": "summary-regression", "publishedUtc": "2026-11-10T00:00Z", "cat": "ops",
           "zh": {"title": "航空公司宣布新航線", "summary": "全新航線將每週營運三班，使用空中巴士A350-1000執飛，預定下個月開始服務旅客。", "body": ["原始報導內文。"]},
           "en": {"title": "Airline announces new route", "summary": "The new route will operate three times a week using Airbus A350-1000 aircraft, with service scheduled to begin next month.", "body": ["Original report."]},
           "sources": [{"name": "Example", "url": "https://example.com/aviation"}]}
    article = build.prep_article(raw)
    for lang in ("zh", "en"):
        view = build.art_view(article, lang)
        assert view["display_summary"] == article[lang]["summary"]
        assert build.hero_rotation_view(view, lang)["summary"] == view["display_summary"]
        assert raw[lang]["summary"] == article[lang]["summary"]
