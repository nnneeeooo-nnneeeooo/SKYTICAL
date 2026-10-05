"""Offline regression checks for the bounded briefing writer.

Run with ``python tests/test_briefing_writer.py`` from the repository root.
"""
from __future__ import annotations

import copy
import os
import sys
import tempfile
import types
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_old_data_dir = os.environ.get("AVWIRE_DATA_DIR")
_tmp = tempfile.TemporaryDirectory(prefix="avwire-briefing-writer-")
os.environ["AVWIRE_DATA_DIR"] = _tmp.name
sys.path.insert(0, str(REPO / "pipeline"))
import briefing_writer as writer  # noqa: E402
from providers import ProviderAuthError, ProviderQuotaError  # noqa: E402

CHECKS = FAILED = 0


def check(name, condition):
    global CHECKS, FAILED
    CHECKS += 1
    if condition:
        print("PASS " + name)
    else:
        FAILED += 1
        print("FAIL " + name)


def make_input():
    article = {
        "id": "art-1",
        "zh": {"title": "航空公司公布波音 787 新航線", "summary": "公司公告新航線。",
               "body": ["航空公司宣布波音 787 將於 2026 年 10 月 6 日開航。",
                        "新航線每日一班。"]},
        "en": {"title": "Carrier announces Boeing 787 route", "summary": "The carrier announced a route.",
               "body": ["The carrier says its Boeing 787 route starts on October 6, 2026."]},
    }
    briefing = {"window_start": "2026-10-05T00:00:00+08:00",
                "window_end": "2026-10-06T00:00:00+08:00",
                "sections": {"international_aviation": [{
                    "article_id": "art-1", "headline": "原始標題", "headline_en": "Original",
                }]}, "warnings": [], "status": "complete"}
    return briefing, [article]


def valid_row(article_id="art-1", **changes):
    row = {"article_id": article_id, "headline_zh": "航空公司公布波音 787 新航線",
           "summary_zh": "航空公司宣布波音 787 將於 2026 年 10 月 6 日開航。",
           "keyword_zh": "波音 787 新航線", "headline_en": "Carrier announces Boeing 787 route",
           "summary_en": "The carrier says its Boeing 787 route starts on October 6, 2026.",
           "keyword_en": "Boeing 787 route", "evidence": [0]}
    row.update(changes)
    return row


class FakeProvider:
    model = "gpt-6-luna"

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def available(self):
        return True

    def _responses_call(self, system, prompt, schema, repair=False):
        self.calls.append({"system": system, "prompt": prompt,
                           "schema": schema, "repair": repair})
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def encoded(rows):
    import json
    return json.dumps({"items": rows}, ensure_ascii=False)


def run_with(provider, briefing=None, articles=None, old=None):
    briefing, articles = briefing or make_input()[0], articles or make_input()[1]
    original = writer.make_provider
    writer.make_provider = lambda: provider
    try:
        result = writer.write_briefing(briefing, articles, old)
    finally:
        writer.make_provider = original
    return result, briefing


# A valid batch writes every article after one medium-effort provider call.
provider = FakeProvider([encoded([valid_row()])])
brief, articles = make_input()
ok = run_with(provider, brief, articles)[0]
written = brief["sections"]["international_aviation"][0]
check("valid output writes headline, summary, bilingual keywords and evidence",
      ok and written["headline"] == "航空公司公布波音 787 新航線"
      and written["summary"].startswith("航空公司宣布")
      and written["keyword_zh"] == "波音 787 新航線"
      and written["writer_evidence"] == [0])
check("valid output is a single initial medium-effort batch",
      len(provider.calls) == 1 and provider.calls[0]["repair"] is False
      and provider.calls[0]["schema"] == writer.SCHEMA)

# Punctuation-only defects are normalized in one batch and summaries retain
# their valid semicolon punctuation.
punctuation_row = valid_row(
    headline_zh="航空公司；公布波音 787 新航線",
    summary_zh="航空公司宣布波音 787 將於 2026 年 10 月 6 日開航；航線每日一班。")
punctuation_provider = FakeProvider([encoded([punctuation_row])])
punctuation_brief, punctuation_articles = make_input()
punctuation_ok = run_with(punctuation_provider, punctuation_brief,
                          punctuation_articles)[0]
punctuation_item = punctuation_brief["sections"]["international_aviation"][0]
check("new headline semicolon is normalized in one batch and summary is preserved",
      punctuation_ok and len(punctuation_provider.calls) == 1
      and punctuation_provider.calls[0]["repair"] is False
      and punctuation_item["headline"] == "航空公司 公布波音 787 新航線"
      and punctuation_item["summary"] == punctuation_row["summary_zh"])

# Image fields do not enter the digest; cache reuse preserves the saved labels.
old = copy.deepcopy(brief)
old["sections"]["international_aviation"][0]["keyword_zh"] = "已保存關鍵字"
image_changed = copy.deepcopy(articles)
image_changed[0]["image"] = "https://images.example/new.jpg"
provider2 = FakeProvider([])
cached_brief, cached_articles = make_input()
cached_brief["sections"]["international_aviation"][0]["image"] = "new"
cached_ok = run_with(provider2, cached_brief, image_changed, old)[0]
check("image-only change reuses writer cache and saved keyword without a call",
      cached_ok and not provider2.calls
      and cached_brief["sections"]["international_aviation"][0]["keyword_zh"] == "已保存關鍵字")

# Headline punctuation is normalized without touching valid summary punctuation.
cached_semicolon = copy.deepcopy(old)
cached_semicolon_item = cached_semicolon["sections"]["international_aviation"][0]
cached_semicolon_item["headline"] = "航空公司；公布波音 787 新航線"
cached_semicolon_item["summary"] = "航空公司宣布波音 787 開航；新航線每日一班。"
provider_semicolon_cache = FakeProvider([])
semicolon_cache_brief, semicolon_cache_articles = make_input()
semicolon_cache_ok = run_with(provider_semicolon_cache, semicolon_cache_brief,
                              semicolon_cache_articles,
                              cached_semicolon)[0]
semicolon_cache_item = semicolon_cache_brief["sections"]["international_aviation"][0]
check("cached headline semicolon is normalized without a provider call",
      semicolon_cache_ok and not provider_semicolon_cache.calls
      and semicolon_cache_item["headline"] == "航空公司 公布波音 787 新航線"
      and semicolon_cache_item["summary"] == cached_semicolon_item["summary"])

# A cached opaque title cannot bypass the guard; a failed repair falls back to
# the verified article copy instead of reusing the rejected cached headline.
cached_opaque = copy.deepcopy(old)
cached_opaque["sections"]["international_aviation"][0]["headline"] = (
    "航空公司波音787換志願者")
provider_cache_failure = FakeProvider([ProviderAuthError("offline test")])
opaque_cache_brief, opaque_cache_articles = make_input()
opaque_cache_ok = run_with(provider_cache_failure, opaque_cache_brief,
                           opaque_cache_articles, cached_opaque)[0]
opaque_cache_item = opaque_cache_brief["sections"]["international_aviation"][0]
check("opaque cached headline triggers bounded regeneration and source fallback",
      not opaque_cache_ok and len(provider_cache_failure.calls) == 1
      and opaque_cache_item["headline"] == "原始標題"
      and "換志願者" not in opaque_cache_item["headline"])

# Invalid batch gets one low-effort repair; a still-invalid response falls back.
malformed = encoded([valid_row(evidence=[99])])
provider3 = FakeProvider([malformed, encoded([valid_row()])])
brief3, articles3 = make_input()
check("malformed output receives one low-effort repair then succeeds",
      run_with(provider3, brief3, articles3)[0]
      and len(provider3.calls) == 2 and provider3.calls[1]["repair"] is True)

# An opaque but otherwise well-formed headline receives the existing single
# low-effort correction; its summary remains unchanged, including semicolons.
opaque_row = valid_row(
    headline_zh="男子持假登機證拒離機清艙",
    summary_zh="航空公司宣布波音 787 將於 2026 年 10 月 6 日開航；新航線每日一班。")
corrected_row = valid_row(
    headline_zh="航空公司宣布波音 787 新航線將於 2026 年 10 月 6 日開航並每日一班",
    summary_zh=opaque_row["summary_zh"])
provider_opaque = FakeProvider([
    encoded([opaque_row]), encoded([corrected_row])])
brief_opaque, articles_opaque = make_input()
opaque_ok = run_with(provider_opaque, brief_opaque, articles_opaque)[0]
opaque_item = brief_opaque["sections"]["international_aviation"][0]
check("opaque briefing headline receives one bounded low-effort correction",
      opaque_ok and len(provider_opaque.calls) == 2
      and provider_opaque.calls[1]["repair"] is True
      and opaque_item["headline"] == corrected_row["headline_zh"]
      and opaque_item["summary"] == opaque_row["summary_zh"])
provider4 = FakeProvider([malformed, malformed])
brief4, articles4 = make_input()
fallback_ok = run_with(provider4, brief4, articles4)[0]
fallback_item = brief4["sections"]["international_aviation"][0]
check("two invalid responses fall back to a complete source paragraph and partial status",
      not fallback_ok and len(provider4.calls) == 2 and brief4["status"] == "partial"
      and fallback_item["summary"] == articles4[0]["zh"]["body"][0])

# The structural validator rejects claims that are not supported by input text.
from providers import extract_json  # noqa: E402
evidence = {"art-1": writer._evidence(articles[0])}
for label, row in (
        ("unsupported number", valid_row(summary_zh="航空公司稱 99 架波音 787 將於 2026 年 10 月 6 日開航。")),
        ("untrusted URL", valid_row(summary_en="https://fake.example/ Boeing 787 route starts October 6, 2026.")),
        ("reasoning trace", valid_row(summary_en="<think>private reasoning</think> Boeing 787 route starts October 6, 2026.")),
        ("unknown article ID", valid_row(article_id="other")),
        ("invalid evidence index", valid_row(evidence=[24])),
):
    try:
        writer._validate({"items": [row]}, evidence, "2026-10-05")
        rejected = False
    except ValueError:
        rejected = True
    check(label + " rejected by evidence validation", rejected)

# An earlier event date in the evidence must survive in the Chinese summary.
old_article = copy.deepcopy(articles[0])
old_article["zh"]["body"] = ["2024年3月2日，航空公司發生事故；本期公布調查結果及後續處置，相關單位已完成初步調查並說明後續處理方式，並確認所有相關程序已依規定完成。"]
old_evidence = {"art-1": writer._evidence(old_article)}
try:
    writer._validate({"items": [valid_row(summary_zh="航空公司公布調查結果及後續處置。",
                                            summary_en="The carrier published investigation results and follow-up.")]},
                     old_evidence, "2026-10-05")
    old_date_rejected = False
except ValueError:
    old_date_rejected = True
check("old-event lead date is required in the generated summary", old_date_rejected)
check("publisher and publication-date lead-in is removed from extracted copy",
      writer.clean_copy("Simple Flying於2026年10月3日報導，航空公司宣布新航線。")
      == "航空公司宣布新航線。")

# Auth and quota errors are terminal and never trigger a second paid attempt.
for label, exc in (("auth", ProviderAuthError("unauthorized")),
                   ("quota", ProviderQuotaError("quota"))):
    auth_provider = FakeProvider([exc])
    auth_brief, auth_articles = make_input()
    run_with(auth_provider, auth_brief, auth_articles)
    check(label + " failure is not retried", len(auth_provider.calls) == 1)

# Fallback keywords retain aircraft identifiers rather than slicing their tail.
keyword = writer.fallback_keyword("波音 787-9 新航線")
check("short fallback keyword keeps complete aircraft identifier",
      "787-9" in keyword and "7879" not in keyword and "…" not in keyword)

if _old_data_dir is None:
    os.environ.pop("AVWIRE_DATA_DIR", None)
else:
    os.environ["AVWIRE_DATA_DIR"] = _old_data_dir
_tmp.cleanup()
print(f"\n{CHECKS - FAILED}/{CHECKS} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
