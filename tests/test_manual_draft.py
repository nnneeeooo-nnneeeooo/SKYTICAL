"""Offline contract tests for the encrypted private manual-drafting desk."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402
import manual_draft  # noqa: E402
import write  # noqa: E402
from model_config import (  # noqa: E402
    MODEL_DISPLAY_NAMES,
    MODEL_ORDER,
    OPENCODE_MODEL_ORDER,
    OPENROUTER_MODEL_ORDER,
    manual_reasoning_profile,
)
from providers import ProviderError  # noqa: E402

passed = 0
failed = 0


def check(condition, label):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


def sample_payload():
    return {
        "articleType": "incident",
        "language": "bilingual",
        "reasoningTier": "deep",
        "model": "auto",
        "sourceUrls": ["https://8.8.8.8/source"],
        "sourceText": "Official source text with enough evidence.",
        "articleSummary": "Use this as the expansion outline.",
        "instruction": "Keep the authority name in English.",
        "conversation": [{"role": "user", "text": "Focus on chronology."}],
        "publicationMode": "auto",
        "publicationTimeUtc": "",
        "sortMode": "publication",
        "sortTimeUtc": "",
        "previousDraft": None,
        "images": [],
    }


def test_encryption_round_trip():
    token = "A" * 43
    job_id = "0123456789abcdef0123456789abcdef"
    value = {"sourceText": "未公開來源", "images": ["secret"]}
    envelope = manual_draft.encrypt_json(value, token, job_id)
    encoded = json.dumps(envelope, ensure_ascii=False)
    check(set(envelope) == {"version", "alg", "iv", "ciphertext"},
          "encrypted envelope has ciphertext-only contract")
    check("未公開來源" not in encoded and "secret" not in encoded,
          "plaintext never appears in the repository envelope")
    check(manual_draft.decrypt_json(envelope, token, job_id) == value,
          "AES-GCM envelope round-trips")
    try:
        manual_draft.decrypt_json(envelope, "B" * 43, job_id)
        check(False, "wrong private URL token must not decrypt")
    except Exception:
        check(True, "wrong private URL token is rejected")


def test_payload_limits_and_ssrf():
    payload = manual_draft.validate_payload(sample_payload())
    check(payload["articleType"] == "incident"
          and payload["reasoningTier"] == "deep"
          and payload["articleSummary"]
          == "Use this as the expansion outline.",
          "manual selection contract validates")
    automatic = sample_payload()
    automatic["articleType"] = "auto"
    check(manual_draft.validate_payload(automatic)["articleType"] == "auto",
          "article type can be detected automatically")
    manual_time = sample_payload()
    manual_time["publicationMode"] = "manual"
    manual_time["publicationTimeUtc"] = "2026-07-30T12:34:56Z"
    check(
        manual_draft.validate_payload(manual_time)["publicationTimeUtc"]
        == "2026-07-30T12:34:00Z",
        "manual publication time is normalized to minute precision")
    manual_sort = sample_payload()
    manual_sort["sortMode"] = "manual"
    manual_sort["sortTimeUtc"] = "2026-07-29T09:45:59Z"
    check(
        manual_draft.validate_payload(manual_sort)["sortTimeUtc"]
        == "2026-07-29T09:45:00Z",
        "manual website-order time is normalized to minute precision")
    credits = sample_payload()
    credits["writerModels"] = [
        "GPT 5.6 Sol", "Gemini 3.6 Flash", "Nemotron 3 Ultra"]
    check(
        manual_draft.validate_payload(credits)["writerModels"]
        == credits["writerModels"],
        "up to five owner-supplied writer model labels are preserved")
    custom = sample_payload()
    custom["model"] = "custom"
    custom["customModel"] = "openrouter:example/model:free"
    custom_payload = manual_draft.validate_payload(custom)
    check(custom_payload["model"] == "openrouter:example/model:free",
          "confirmation stage accepts a provider-prefixed custom model")
    try:
        manual_draft._public_url("http://127.0.0.1/private")
        check(False, "loopback URL must be blocked")
    except ValueError:
        check(True, "loopback URL is blocked")
    check(manual_draft._public_url("https://8.8.8.8/source")
          == "https://8.8.8.8/source",
          "global HTTPS address is accepted")
    bad = sample_payload()
    bad["model"] = "nvidia:not-a-real-model"
    try:
        manual_draft.validate_payload(bad)
        check(False, "unknown model must be rejected")
    except ValueError:
        check(True, "unknown model is rejected")


def test_publication_detection_prompt_and_bundle():
    soup = manual_draft.BeautifulSoup(
        '<html><head><meta property="article:published_time" '
        'content="2026-07-30T10:11:12+08:00"></head></html>',
        "html.parser",
    )
    check(
        manual_draft._html_publication_time(soup)
        == "2026-07-30T02:11:12Z",
        "source metadata publication time is normalized to UTC seconds")

    payload = manual_draft.validate_payload({
        **sample_payload(),
        "articleType": "auto",
        "sortMode": "manual",
        "sortTimeUtc": "2026-07-29T12:00:00Z",
    })
    group = {
        "id": "manual-test",
        "primarySource": "Official aviation authority",
        "items": [{
            "source": "Official aviation authority",
            "title": "Airport and airline operational update",
            "summary": "Aircraft operations continue at the airport.",
            "fulltext": (
                "The aviation authority said the airline and airport "
                "continued aircraft operations."
            ),
            "url": "https://8.8.8.8/source",
            "publishedUtc": "2026-07-30T02:11:12Z",
            "dateInferred": False,
        }],
    }
    prompt = manual_draft._manual_prompt(payload, group)
    check(
        "Use this as the expansion outline." in prompt
        and "NEVER evidence" in prompt,
        "operator summary is supplied as an outline but prohibited as evidence")

    draft = {
        "status": "publish",
        "decisionReason": "",
        "cat": "ops",
        "zh": {
            "title": "機場與航空公司營運更新",
            "summary": "主管機關說明航空公司與機場的最新營運狀況。",
            "body": ["航空主管機關公布最新營運說明。" * 12
                     for _ in range(write.MIN_BODY_PARAGRAPHS)],
        },
        "en": {
            "title": "Airport and airline operations update",
            "summary": (
                "The authority provided an update on airline and airport "
                "operations."
            ),
            "body": [
                ("The aviation authority said airline and airport operations "
                 "continued while aircraft movements remained under regular "
                 "monitoring and established operational procedures. " * 4)
                for _ in range(write.MIN_BODY_PARAGRAPHS)
            ],
        },
        "flash": {
            "zh": "主管機關公布航空營運更新。",
            "en": "The authority published an aviation operations update.",
            "hot": False,
        },
        "incident": None,
        "facts": [{
            "factId": "F1",
            "claim": "Operations continued.",
            "sourceQuote": "continued aircraft operations",
        }],
        "headlineSupportedBy": ["F1"],
        "summarySupportedBy": ["F1"],
        "entities": {key: [] for key in write.ENTITY_KEYS},
        "eventStatus": "confirmed",
        "riskFlags": [],
        "requiresHumanReview": False,
    }
    check(write.validate_draft(draft) is None,
          "publication fixture satisfies the editorial draft contract")
    bundle = manual_draft._publication_bundle(
        "0123456789abcdef0123456789abcdef",
        payload,
        group,
        draft,
        SimpleNamespace(label="gemini:gemini-3.6-flash"),
        "airport",
        "",
        datetime(2026, 7, 31, 1, 2, 3, tzinfo=timezone.utc),
    )
    check(
        bundle["articleType"] == "airport"
        and bundle["publicationTimeUtc"] == "2026-07-30T02:11:12Z"
        and bundle["publicationTimeSource"] == "source_metadata",
        "auto type and source publication time reach the publish bundle")
    check(
        bundle["articlePath"]
        == "data/articles/manual-0123456789abcdef0123456789abcdef.json"
        and bundle["article"]["publishedUtc"] == "2026-07-30T02:11:12Z"
        and bundle["article"]["sortUtc"] == "2026-07-29T12:00:00Z"
        and bundle["flash"]["timeUtc"] == "2026-07-29T12:00:00Z"
        and bundle["flash"]["articleId"] == bundle["article"]["id"],
        "publish bundle links article and flash with independent sort time")


def test_manual_translation_bundle():
    payload = manual_draft.validate_payload({
        **sample_payload(),
        "translationOnly": True,
        "articleType": "airline",
        "language": "bilingual",
        "publicationMode": "manual",
        "publicationTimeUtc": "2026-07-30T12:00:00Z",
        "sortMode": "manual",
        "sortTimeUtc": "2026-07-29T12:00:00Z",
        "writerModels": ["GPT 5.6 Sol", "Gemini 3.6 Flash"],
        "manualArticle": {
            "title": "航空公司公布營運更新",
            "summary": "航空公司公布最新營運消息。",
            "body": ["第一段內容。", "第二段內容。"],
        },
    })
    draft = manual_draft._operator_draft(payload, {
        "title": "Airline publishes operational update",
        "summary": "The airline published its latest operational update.",
        "body": ["First paragraph.", "Second paragraph."],
    })
    group = {
        "primarySource": "example.com",
        "items": [{
            "source": "example.com",
            "url": "https://example.com/source",
        }],
    }
    bundle = manual_draft._operator_publication_bundle(
        "0123456789abcdef0123456789abcdef",
        payload,
        group,
        draft,
        "",
        datetime(2026, 7, 31, 1, 2, tzinfo=timezone.utc),
    )
    check(
        draft["zh"] == payload["manualArticle"]
        and bundle["article"]["en"]["body"]
        == ["First paragraph.", "Second paragraph."]
        and bundle["article"]["writerModels"]
        == ["GPT 5.6 Sol", "Gemini 3.6 Flash"]
        and bundle["article"]["sortUtc"] == "2026-07-29T12:00:00Z"
        and bundle["flash"]["timeUtc"] == "2026-07-29T12:00:00Z",
        "background translation preserves Chinese and publication metadata")


def test_operator_authored_auto_source_time():
    source_article = {
        "title": "航空公司公布營運更新",
        "summary": "航空公司公布最新營運消息。",
        "body": ["第一段內容。", "第二段內容。"],
    }
    payload = manual_draft.validate_payload({
        **sample_payload(),
        "operatorAuthored": True,
        "translationOnly": False,
        "articleType": "airline",
        "language": "zh",
        "publicationMode": "auto",
        "publicationTimeUtc": "",
        "writerModels": ["GPT 5.6 Sol"],
        "manualArticle": source_article,
    })
    group = {
        "primarySource": "example.com",
        "items": [{
            "source": "example.com",
            "url": "https://example.com/source",
            "publishedUtc": "2026-07-30T13:45:00Z",
            "dateInferred": False,
        }],
    }
    draft = manual_draft._operator_draft(payload, {})
    bundle = manual_draft._operator_publication_bundle(
        "0123456789abcdef0123456789abcdef",
        payload,
        group,
        draft,
        "",
        datetime(2026, 7, 31, 1, 2, tzinfo=timezone.utc),
    )
    check(
        bundle["publicationTimeUtc"] == "2026-07-30T13:45:00Z"
        and bundle["publicationTimeSource"] == "source_metadata"
        and bundle["article"]["publishedUtc"]
        == bundle["article"]["sortUtc"]
        and bundle["article"]["zh"] == source_article
        and bundle["article"]["en"]["body"] == []
        and bundle["article"]["availableLanguages"] == ["zh"],
        "manual article auto-detects source metadata without rewriting copy")


def test_reasoning_tiers():
    check(manual_reasoning_profile(
        "gemini", "gemini-3.6-flash", "deep")["wire"]
        == {"thinkingConfig": {"thinkingLevel": "high"}},
        "Gemini deep maps to thinkingLevel high")
    check(manual_reasoning_profile(
        "nvidia", "nvidia/nemotron-3-ultra-550b-a55b", "deep")["wire"]
        == {"reasoning_effort": "max"},
        "Nemotron Ultra deep maps to maximum reasoning")
    check(manual_reasoning_profile(
        "nvidia", "z-ai/glm-5.2", "deep")["effective"]
        == "provider_default",
        "GLM reports provider-default when no control exists")
    check(manual_reasoning_profile(
        "nvidia", "qwen/qwen3.5-397b-a17b", "fast")["wire"]
        == {"chat_template_kwargs": {"enable_thinking": False}},
        "Qwen fast disables thinking")
    check(manual_reasoning_profile(
        "openrouter", "openai/gpt-oss-20b:free", "deep")["wire"]
        == {"reasoning": {"effort": "high", "exclude": True}},
        "OpenRouter deep uses high reasoning without returning its trace")


def test_openrouter_manual_provider_order():
    saved = {
        key: os.environ.get(key)
        for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY",
                    "OPENROUTER_API_KEY", "OPENCODE_API_KEY")
    }
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ.pop("NVIDIA_API_KEY", None)
    os.environ.pop("OPENCODE_API_KEY", None)
    os.environ["OPENROUTER_API_KEY"] = "test-not-a-real-key"
    try:
        rows = manual_draft._providers_for(
            manual_draft.validate_payload(sample_payload()))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check([row.label for row in rows] == list(OPENROUTER_MODEL_ORDER),
          "manual fallback exposes all OpenRouter models in owner order")
    check(all(row.reasoning_tier == "deep" for row in rows),
          "manual reasoning tier reaches every OpenRouter model")


def test_opencode_manual_provider_order():
    saved = {
        key: os.environ.get(key)
        for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY",
                    "OPENROUTER_API_KEY", "OPENCODE_API_KEY")
    }
    for key in ("GEMINI_API_KEY", "NVIDIA_API_KEY", "OPENROUTER_API_KEY"):
        os.environ.pop(key, None)
    os.environ["OPENCODE_API_KEY"] = "oc_sk_test-not-a-real-key"
    try:
        rows = manual_draft._providers_for(
            manual_draft.validate_payload(sample_payload()))
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    check([row.label for row in rows] == list(OPENCODE_MODEL_ORDER),
          "manual fallback exposes all OpenCode models in owner order")
    check(all(row.reasoning_tier == "deep" for row in rows),
          "manual reasoning tier reaches every OpenCode model")


class FakeProvider:
    def __init__(self, label, answer):
        self.label = label
        self.name, _ = label.split(":", 1)
        self.answer = answer
        self.reasoning_effective = "test"
        self.http_calls = 1
        self.repair_calls = 0
        self.usage = {"inputTokens": 10, "outputTokens": 20}
        self.request_log = [{
            "status": 429 if isinstance(answer, Exception) else 200,
            "durationMs": 1,
            "headers": {"x-ratelimit-remaining": "0"}
            if isinstance(answer, Exception) else {},
        }]

    def draft(self, system, user, schema):
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def test_fallback_and_telemetry():
    first = FakeProvider(
        MODEL_ORDER[0], ProviderError("HTTP 429 per-minute rate limit"))
    second = FakeProvider(MODEL_ORDER[1], {"status": "reject"})
    originals = (
        manual_draft._providers_for,
        manual_draft._build_group,
        manual_draft.usage_ledger.record_providers,
        manual_draft.usage_ledger.record_run,
    )
    recorded_runs = []
    manual_draft._providers_for = lambda payload: [first, second]
    manual_draft._build_group = lambda job, payload, log: {
        "id": f"manual-{job}",
        "primarySource": "official",
        "items": [{
            "source": "official",
            "title": "Source",
            "summary": "Source material",
            "fulltext": "Source material",
            "url": "https://8.8.8.8/source",
        }],
    }
    manual_draft.usage_ledger.record_providers = lambda rows: None
    manual_draft.usage_ledger.record_run = recorded_runs.append
    try:
        result = manual_draft.generate(
            "0123456789abcdef0123456789abcdef",
            manual_draft.validate_payload(sample_payload()))
    finally:
        (manual_draft._providers_for,
         manual_draft._build_group,
         manual_draft.usage_ledger.record_providers,
         manual_draft.usage_ledger.record_run) = originals
    check(result["fallbackUsed"] is True
          and result["finalModel"] == MODEL_ORDER[1],
          "failed first model falls back in configured order")
    check(result["attempts"][0]["failureClass"] == "rate_limit"
          and result["attempts"][0]["requests"][0]["headers"]
          ["x-ratelimit-remaining"] == "0",
          "safe rate-limit and failure telemetry reach encrypted result")
    check(
        len(recorded_runs[0]["resourceUsage"]["models"]) == 2
        and sum(row["outputTokens"] for row in
                recorded_runs[0]["resourceUsage"]["models"]) == 40,
        "private AI drafting records per-model token resources")


def test_translation_generate_path():
    provider = FakeProvider("gemini:gemini-3.6-flash", {
        "title": "Airline publishes operational update",
        "summary": "The airline published an operational update.",
        "body": ["First paragraph.", "Second paragraph."],
        "detectedPublishedUtc": "2026-07-30T08:15:00Z",
        "timeEvidenceQuote": "Published July 30, 2026 at 8:15 UTC.",
        "timeEvidenceUrl": "https://example.com/source",
    })
    payload = manual_draft.validate_payload({
        **sample_payload(),
        "translationOnly": True,
        "articleType": "airline",
        "language": "bilingual",
        "publicationMode": "auto",
        "publicationTimeUtc": "",
        "writerModels": ["GPT 5.6 Sol", "Gemini 3.6 Flash"],
        "manualArticle": {
            "title": "航空公司公布營運更新",
            "summary": "航空公司公布營運更新。",
            "body": ["第一段內容。", "第二段內容。"],
        },
    })
    originals = (
        manual_draft._providers_for,
        manual_draft._build_group,
        manual_draft.usage_ledger.record_providers,
        manual_draft.usage_ledger.record_run,
    )
    manual_draft._providers_for = lambda request: [provider]
    manual_draft._build_group = lambda job, request, log: {
        "primarySource": "example.com",
        "items": [{
            "source": "example.com",
            "url": "https://example.com/source",
            "fulltext": "Published July 30, 2026 at 8:15 UTC.",
        }],
    }
    manual_draft.usage_ledger.record_providers = lambda rows: None
    manual_draft.usage_ledger.record_run = lambda row: None
    try:
        result = manual_draft.generate(
            "0123456789abcdef0123456789abcdef", payload)
    finally:
        (manual_draft._providers_for,
         manual_draft._build_group,
         manual_draft.usage_ledger.record_providers,
         manual_draft.usage_ledger.record_run) = originals
    check(
        result["status"] == "success"
        and result["translationOnly"] is True
        and result["operatorAuthored"] is True
        and result["publicationTimeUtc"] == "2026-07-30T08:15:00Z"
        and result["publicationTimeSource"] == "model_source_text"
        and result["publication"]["article"]["zh"]["title"]
        == "航空公司公布營運更新"
        and result["publication"]["article"]["en"]["title"]
        == "Airline publishes operational update",
        "translation job uses provider fallback and returns publishable bundle")


def test_manual_time_detection_generate_path():
    provider = FakeProvider("gemini:gemini-3.6-flash", {
        "detectedPublishedUtc": "2026-07-29T04:30:00Z",
        "timeEvidenceQuote": (
            "The notice was published on July 29, 2026."),
        "timeEvidenceUrl": "https://example.com/source",
    })
    source_article = {
        "title": "Airport operational notice",
        "summary": "The airport published an operational notice.",
        "body": ["Operator-authored English copy."],
    }
    payload = manual_draft.validate_payload({
        **sample_payload(),
        "operatorAuthored": True,
        "articleType": "airport",
        "language": "en",
        "publicationMode": "auto",
        "manualArticle": source_article,
        "writerModels": ["GPT 5.6 Sol"],
    })
    originals = (
        manual_draft._providers_for,
        manual_draft._build_group,
        manual_draft.usage_ledger.record_providers,
        manual_draft.usage_ledger.record_run,
    )
    manual_draft._providers_for = lambda request: [provider]
    manual_draft._build_group = lambda job, request, log: {
        "primarySource": "example.com",
        "items": [{
            "source": "example.com",
            "url": "https://example.com/source",
            "fulltext": "The notice was published on July 29, 2026.",
            "publishedUtc": "",
            "dateInferred": True,
        }],
    }
    manual_draft.usage_ledger.record_providers = lambda rows: None
    manual_draft.usage_ledger.record_run = lambda row: None
    try:
        result = manual_draft.generate(
            "0123456789abcdef0123456789abcdef", payload)
    finally:
        (manual_draft._providers_for,
         manual_draft._build_group,
         manual_draft.usage_ledger.record_providers,
         manual_draft.usage_ledger.record_run) = originals
    check(
        result["status"] == "success"
        and result["operatorAuthored"] is True
        and result["translationOnly"] is False
        and result["publicationTimeUtc"] == "2026-07-29T04:30:00Z"
        and result["publication"]["article"]["en"] == source_article
        and result["publication"]["article"]["zh"]["body"] == [],
        "manual English copy uses source-time model without rewriting content")
    forged = {
        "detectedPublishedUtc": "2026-07-28T00:00:00Z",
        "timeEvidenceQuote": "This sentence is not in the source.",
        "timeEvidenceUrl": "https://example.com/source",
    }
    check(
        manual_draft._verified_detected_time(
            forged,
            {"items": [{
                "url": "https://example.com/source",
                "fulltext": "The notice was published on July 29, 2026.",
            }]},
        ) == "",
        "model time is rejected when its verbatim evidence is absent")


def test_private_page_render_contract():
    captured = []
    original_render = build.render
    original_token = os.environ.get("AVWIRE_MANUAL_TOKEN")
    build.render = lambda env, template, out, ctx: captured.append(
        (template, out, ctx))
    try:
        os.environ.pop("AVWIRE_MANUAL_TOKEN", None)
        check(build.render_manual_workbench(None, {}) == 0,
              "manual page is absent without its secret")
        os.environ["AVWIRE_MANUAL_TOKEN"] = "x" * 43
        check(build.render_manual_workbench(None, {}) == 1,
              "manual page renders with a valid secret")
    finally:
        build.render = original_render
        if original_token is None:
            os.environ.pop("AVWIRE_MANUAL_TOKEN", None)
        else:
            os.environ["AVWIRE_MANUAL_TOKEN"] = original_token
    template, out, ctx = captured[0]
    check(template == "manual.html" and out == f"m/{'x' * 43}/index.html",
          "private route embeds the unguessable token")
    check([row["id"] for row in ctx["models"]] == list(MODEL_ORDER)
          and [row["name"] for row in ctx["models"]]
          == [MODEL_DISPLAY_NAMES[item] for item in MODEL_ORDER],
          "UI exposes every model in exact fallback order")


def test_manual_article_render_contract():
    raw = {
        "id": "a-20260731-1200-manual-test",
        "publishedUtc": "2026-07-31T12:00:00Z",
        "sortUtc": "2026-07-29T12:00:00Z",
        "cat": "ops",
        "primarySource": "example.com",
        "zh": {
            "title": "手動撰寫的航空新聞",
            "summary": "手動摘要",
            "body": ["手動文章內容。"],
        },
        "en": {"title": "", "summary": "", "body": []},
        "sources": [{
            "name": "example.com",
            "url": "https://example.com/source",
        }],
        "writer": "manual:GPT 5.6 Sol",
        "writerModels": ["GPT 5.6 Sol", "Gemini 3.6 Flash"],
        "availableLanguages": ["zh"],
    }
    article = build.prep_article(raw)
    check(article is not None
          and article["available_languages"] == ["zh"]
          and article["writer_model"] == "GPT 5.6 Sol、Gemini 3.6 Flash"
          and article["dt"]
          == datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
          and article["meta_ts"] == "2026-07-31 8:00 PM UTC+8",
          "manual sort time controls placement without changing display time")
    legacy = dict(raw)
    legacy.pop("sortUtc")
    legacy_article = build.prep_article(legacy)
    check(
        legacy_article["dt"]
        == datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        "articles without sortUtc retain published-time ordering")
    flashes = build.prep_flashes([{
        "timeUtc": "2026-07-31T12:00:00Z",
        "zh": "繁中快訊",
        "en": "English fallback",
        "articleId": raw["id"],
        "availableLanguages": ["zh"],
    }], {raw["id"]})
    check(len(build.flash_view(flashes, "zh")) == 1
          and build.flash_view(flashes, "en") == [],
          "single-language manual flash never links to a missing language page")


def test_static_security_contract():
    html = (ROOT / "templates" / "manual.html").read_text(encoding="utf-8")
    js = (ROOT / "static" / "manual.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "manual.css").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    radar_js = (ROOT / "static" / "radar.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows"
                / "manual-draft.yml").read_text(encoding="utf-8")
    hourly = (ROOT / ".github" / "workflows"
              / "hourly.yml").read_text(encoding="utf-8")
    briefing = (ROOT / ".github" / "workflows"
                / "briefing.yml").read_text(encoding="utf-8")
    check("noindex,nofollow,noarchive,nosnippet" in html
          and "Content-Security-Policy" in html,
          "private page is noindex and has a restrictive CSP")
    check('<option value="deep" selected>' in html
          and '<option value="standard" selected>' not in html,
          "private page defaults to the highest reasoning tier")
    model_select = html.split('<select id="model">', 1)[1].split(
        "</select>", 1)[0]
    check(
        '<option value="{{ model.id }}"{% if loop.first %} selected{% endif %}>'
        in model_select and '<option value="auto" selected>' not in model_select,
        "private page selects the first configured model by default")
    check(
        '<option value="auto" selected>自動偵測</option>' in html
        and 'id="article-summary"' in html
        and 'id="publication-date"' in html
        and 'id="publication-hour"' in html
        and 'id="publication-minute"' in html
        and 'id="publication-period"' in html
        and '<label>文章時間' in html
        and '<option value="auto" selected>自動偵測來源時間</option>'
        in html
        and 'id="manual-order-panel"' in html
        and 'id="sort-follow-publication"' in html
        and 'id="sort-date"' in html
        and 'id="sort-hour"' in html
        and 'id="sort-minute"' in html
        and 'id="sort-period"' in html
        and 'id="manual-time-panel" class="manual-time-panel"' in html
        and 'type="date"' in html
        and 'type="datetime-local"' not in html
        and 'second: "2-digit"' not in js
        and 'hour12: true' in js,
        "workbench exposes auto type, summary and 12-hour minute controls")
    check(
        "publishedUtc: publicationTime" in js
        and "sortUtc: sortTime" in js
        and "function manualSortUtc()" in js
        and "網站排序時間跟隨文章時間" in html,
        "true manual mode saves independent article and website-order times")
    check(
        html.count("一鍵送出並發布到網站") == 1
        and "await publishArticle();" in js
        and 'sortMode: (' in js
        and 'sortTimeUtc: (' in js
        and "等待人工確認" not in js,
        "AI mode generates, validates and publishes from one action")
    check(
        build.clock_12(datetime(2026, 7, 31, 21, 0, tzinfo=timezone.utc))
        == "9:00 PM"
        and 'hour12: true' in app_js
        and 'hour12: true' in radar_js
        and 'second: "2-digit"' not in radar_js,
        "site clocks use 12-hour time without seconds")
    check(
        'id="review-panel"' in html
        and 'id="confirm-model"' in html
        and 'id="custom-model"' in html
        and 'id="publish"' in html,
        "review stage supports built-in and custom model selection plus publish")
    check(
        'id="mode-ai"' in html and 'id="mode-manual"' in html
        and 'id="manual-title-primary"' in html
        and 'id="manual-content-primary"' in html
        and 'id="manual-english-mode"' in html
        and '由後台模型忠實翻譯（預設）' in html
        and 'id="writer-model-{{ slot }}"' in html
        and "range(1, 6)" in html
        and "prepareAndPublishManualArticle" in js
        and "manualNeedsPreparation" in js
        and "operatorAuthored: true" in js,
        "manual mode supports source-time detection, translation and credits")
    check(
        'id="activity-indicator"' in html
        and 'id="pipeline-steps"' in html
        and "@keyframes activity-bounce" in css
        and "@keyframes step-pulse" in css,
        "both modes expose animated live workflow telemetry")
    check(
        "PAT_VAULT_CONTEXT" in js
        and "encryptPat" in js and "decryptPat" in js
        and "localStorage.setItem(PAT_STORAGE_KEY, JSON.stringify(envelope))"
        in js
        and "sessionStorage" not in js,
        "PAT is stored only as URL-token-bound AES-GCM ciphertext")
    check(
        "await restorePat()" in js
        and "localStorage.removeItem(PAT_STORAGE_KEY)" in js,
        "encrypted PAT is automatically restored and can be cleared")
    check(
        'els["github-token"].addEventListener("input", savePatOnInput)' in js
        and "expectedRevision !== patInputRevision" in js
        and "PAT 已加密記憶" in js,
        "a pasted PAT is saved immediately without waiting for generation")
    check("AES-GCM" in js and "data/manual-jobs/inbox/" in js,
          "browser encrypts before writing a job")
    check(
        "async function publishArticle()" in js
        and "async function publishManualArticle()" in js
        and "writeRepoJson(" in js
        and "data\\/articles\\/manual-" in js
        and "data/flashes.json" in js
        and "data/incidents.json" in js
        and ".github/deploy-trigger" in js
        and "data/usage.json" in js
        and "waitForPublishedArticle" in js
        and "previousDraft" in js,
        "AI and true-manual drafts back up data, usage and verify Pages")
    check(
        "manualUsageModels" in js
        and "estimated: true" in js
        and "manual_workbench" in js
        and "actualUsd: 0" in js,
        "true manual mode records estimated tokens with zero actual API spend")
    check("secrets.AVWIRE_MANUAL_TOKEN" in workflow
          and "secrets.OPENROUTER_API_KEY" in workflow
          and "secrets.OPENCODE_API_KEY" in workflow
          and "secrets.DeepSeekV4Flash_API" in workflow
          and "WECHAT_API_KEY" in workflow
          and "encrypted envelopes only" in workflow
          and "data/manual-jobs/outbox 2>/dev/null || true" in workflow,
          "Actions uses Secrets, checks ciphertext and tolerates empty queues")
    configured_order = f"AVWIRE_PROVIDER_ORDER: {','.join(MODEL_ORDER)}"
    check(configured_order in hourly and configured_order in briefing,
          "automatic workflows use the complete shared fallback order")
    check("secrets.OPENROUTER_API_KEY" in hourly
          and "secrets.OPENROUTER_API_KEY" in briefing
          and "sk-or-v1-" in hourly and "sk-or-v1-" in briefing,
          "automatic workflows receive and scan for the OpenRouter secret")
    check("secrets.OPENCODE_API_KEY" in hourly
          and "secrets.OPENCODE_API_KEY" in briefing
          and "oc_sk_" in hourly and "oc_sk_" in briefing,
          "automatic workflows receive and scan for the OpenCode secret")


def main():
    for test in (
        test_encryption_round_trip,
        test_payload_limits_and_ssrf,
        test_publication_detection_prompt_and_bundle,
        test_manual_translation_bundle,
        test_operator_authored_auto_source_time,
        test_reasoning_tiers,
        test_openrouter_manual_provider_order,
        test_opencode_manual_provider_order,
        test_fallback_and_telemetry,
        test_translation_generate_path,
        test_manual_time_detection_generate_path,
        test_private_page_render_contract,
        test_manual_article_render_contract,
        test_static_security_contract,
    ):
        test()
    print(f"{passed} checks passed, {failed} failed")
    if failed:
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":
    main()
