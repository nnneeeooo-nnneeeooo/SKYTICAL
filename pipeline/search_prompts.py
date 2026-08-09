"""Generate daily, article-grounded search-box prompts.

The hourly workflow calls this once per run.  A saved Taipei calendar date
keeps the LLM budget to one successful generation per day; the first run after
midnight refreshes the file.  Invalid or unavailable model output always falls
back to deterministic prompts made from published article titles.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DATA_DIR, iso_minute, load_json, now_utc, parse_iso, save_json  # noqa: E402

TPE = timezone(timedelta(hours=8), "UTC+8")
OUTPUT_NAME = "search-prompts.json"
PROMPT_COUNT = 6
MAX_CANDIDATES = 12
MAX_ZH_CHARS = 26
MAX_EN_CHARS = 58

PROMPT_SCHEMA = {
    "type": "object",
    "properties": {
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "articleId": {"type": "string"},
                    "zh": {"type": "string"},
                    "en": {"type": "string"},
                },
                "required": ["articleId", "zh", "en"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["prompts"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """You create six short search-box suggestions for SKYTICAL.
Use ONLY the supplied published articles. Pick six distinct article IDs and
return JSON matching the schema. Each suggestion must clearly reuse a named
airline, flight number, airport, city, aircraft type, registration or other
searchable entity from that article's title. Do not add facts, dates, numbers,
causes or conclusions. Traditional Chinese must use Taiwan wording and be at
most 26 characters; English must be at most 58 characters. Do not use URLs,
HTML, markdown, relative-time words such as today/yesterday, or generic prompts.
The suggestions should feel friendly and natural, not like headlines."""

_SPACE_RE = re.compile(r"\s+")
_ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{1,}")
_CJK_RE = re.compile(r"[\u3400-\u9fff]+")
_UNSAFE_RE = re.compile(
    r"https?://|<|>|reasoning_content|\b(?:today|yesterday)\b|今天|昨天",
    re.IGNORECASE,
)


def _text(value) -> str:
    return _SPACE_RE.sub(" ", str(value or "")).strip()


def _article_time(raw: dict) -> datetime | None:
    try:
        return parse_iso(str(raw.get("publishedUtc") or ""))
    except (TypeError, ValueError):
        return None


def collect_candidates(articles_dir: Path, now: datetime) -> tuple[list[dict], str]:
    """Prefer today's Taipei stories, then month-to-date, then latest."""
    rows = []
    for path in sorted(articles_dir.glob("*.json")) if articles_dir.is_dir() else []:
        payload = load_json(path, {})
        article_rows = payload.get("articles") if isinstance(payload, dict) else []
        for raw in article_rows if isinstance(article_rows, list) else []:
            if not isinstance(raw, dict) or raw.get("archived") is True:
                continue
            article_id = _text(raw.get("id"))
            published = _article_time(raw)
            if not article_id or published is None or published > now + timedelta(hours=6):
                continue
            zh = raw.get("zh") if isinstance(raw.get("zh"), dict) else {}
            en = raw.get("en") if isinstance(raw.get("en"), dict) else {}
            zh_title = _text(zh.get("title") or en.get("title"))
            en_title = _text(en.get("title") or zh.get("title"))
            if not zh_title or not en_title:
                continue
            rows.append({
                "id": article_id,
                "publishedUtc": iso_minute(published),
                "publishedTpeDate": published.astimezone(TPE).strftime("%Y-%m-%d"),
                "zhTitle": zh_title,
                "zhSummary": _text(zh.get("summary"))[:240],
                "enTitle": en_title,
                "enSummary": _text(en.get("summary"))[:320],
                "_dt": published,
            })

    by_id = {}
    for row in sorted(rows, key=lambda item: item["_dt"], reverse=True):
        by_id.setdefault(row["id"], row)
    ordered = list(by_id.values())
    today = now.astimezone(TPE).date()
    month_key = (today.year, today.month)
    today_rows = [row for row in ordered if row["_dt"].astimezone(TPE).date() == today]
    month_rows = [row for row in ordered
                  if (row["_dt"].astimezone(TPE).year,
                      row["_dt"].astimezone(TPE).month) == month_key]

    selected = []
    for pool in (today_rows, month_rows, ordered):
        for row in pool:
            if row["id"] not in {item["id"] for item in selected}:
                selected.append(row)
            if len(selected) >= MAX_CANDIDATES:
                break
        if len(selected) >= MAX_CANDIDATES:
            break

    if len(today_rows) >= PROMPT_COUNT:
        window = "today"
    elif month_rows:
        window = "month_to_date"
    else:
        window = "latest"
    for row in selected:
        row.pop("_dt", None)
    return selected, window


def _shares_anchor(prompt: str, title: str) -> bool:
    folded_prompt = prompt.casefold()
    tokens = {
        token.casefold() for token in _ASCII_TOKEN_RE.findall(title)
        if len(token) >= 3
    }
    if any(token in folded_prompt for token in tokens):
        return True
    for run in _CJK_RE.findall(title):
        if any(run[index:index + 2] in prompt
               for index in range(max(0, len(run) - 1))):
            return True
    return False


def validate_llm_prompts(draft, candidates: list[dict]) -> tuple[dict, list[str]] | None:
    rows = draft.get("prompts") if isinstance(draft, dict) else None
    if not isinstance(rows, list) or len(rows) != PROMPT_COUNT:
        return None
    source_by_id = {row["id"]: row for row in candidates}
    seen_ids, source_ids, zh_prompts, en_prompts = set(), [], [], []
    for row in rows:
        if not isinstance(row, dict):
            return None
        article_id = _text(row.get("articleId"))
        zh = _text(row.get("zh"))
        en = _text(row.get("en"))
        source = source_by_id.get(article_id)
        if source is None or article_id in seen_ids:
            return None
        if not (4 <= len(zh) <= MAX_ZH_CHARS and 8 <= len(en) <= MAX_EN_CHARS):
            return None
        if _UNSAFE_RE.search(zh) or _UNSAFE_RE.search(en):
            return None
        if not _shares_anchor(zh, source["zhTitle"]):
            return None
        if not _shares_anchor(en, source["enTitle"]):
            return None
        seen_ids.add(article_id)
        source_ids.append(article_id)
        zh_prompts.append(zh)
        en_prompts.append(en)
    if len(set(zh_prompts)) != PROMPT_COUNT or len(set(en_prompts)) != PROMPT_COUNT:
        return None
    return {"zh": zh_prompts, "en": en_prompts}, source_ids


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def deterministic_prompts(candidates: list[dict]) -> tuple[dict, list[str]]:
    zh, en, source_ids = [], [], []
    for row in candidates:
        zh_prompt = _truncate(f"搜尋：{row['zhTitle']}", MAX_ZH_CHARS)
        en_prompt = _truncate(f"Explore: {row['enTitle']}", MAX_EN_CHARS)
        if zh_prompt in zh or en_prompt in en:
            continue
        zh.append(zh_prompt)
        en.append(en_prompt)
        source_ids.append(row["id"])
        if len(zh) >= PROMPT_COUNT:
            break
    generic_zh = [
        "搜尋班號，例如 CI100", "搜尋航空公司", "搜尋機場或城市",
        "搜尋機型，例如 A350", "探索本月航空新聞", "看看最新航空動態",
    ]
    generic_en = [
        "Search a flight number, e.g. CI100", "Search an airline",
        "Search an airport or city", "Search an aircraft type, e.g. A350",
        "Explore this month's aviation news", "See the latest aviation news",
    ]
    for zh_prompt, en_prompt in zip(generic_zh, generic_en):
        if len(zh) >= PROMPT_COUNT:
            break
        if zh_prompt in zh or en_prompt in en:
            continue
        zh.append(zh_prompt)
        en.append(en_prompt)
    return {"zh": zh, "en": en}, source_ids


def _provider_limit() -> int:
    try:
        return max(1, min(int(os.environ.get("SEARCH_PROMPTS_LLM_ATTEMPTS", "3")), 5))
    except ValueError:
        return 3


def update_daily_prompts(*, data_dir: Path = DATA_DIR, now: datetime | None = None,
                         force: bool = False, providers=None,
                         record_usage: bool = True) -> bool:
    now = now or now_utc()
    output_path = data_dir / OUTPUT_NAME
    target_date = now.astimezone(TPE).strftime("%Y-%m-%d")
    existing = load_json(output_path, {})
    if not force and isinstance(existing, dict) \
            and existing.get("targetDateTpe") == target_date:
        print(f"search-prompts: {target_date} already generated")
        return False

    candidates, window = collect_candidates(data_dir / "articles", now)
    prompts, source_ids = deterministic_prompts(candidates)
    generation_mode, provider_label = "deterministic", None
    attempted = []

    if len(candidates) >= PROMPT_COUNT:
        if providers is None:
            try:
                from providers import build_providers
                providers = build_providers()
            except Exception as exc:
                print(f"search-prompts: providers unavailable ({type(exc).__name__})")
                providers = []
        digest = json.dumps(candidates, ensure_ascii=False, separators=(",", ":"))
        for provider in list(providers or [])[:_provider_limit()]:
            attempted.append(provider)
            try:
                draft = provider.draft(SYSTEM_PROMPT, digest, PROMPT_SCHEMA)
                validated = validate_llm_prompts(draft, candidates)
            except Exception as exc:
                print(f"search-prompts: {getattr(provider, 'label', '?')} failed "
                      f"({type(exc).__name__})")
                continue
            if validated is None:
                print(f"search-prompts: {getattr(provider, 'label', '?')} "
                      "returned invalid prompts")
                continue
            prompts, source_ids = validated
            generation_mode = "llm"
            provider_label = str(getattr(provider, "label", "unknown"))[:160]
            break

    if record_usage and attempted:
        try:
            import usage
            usage.record_providers(attempted)
        except Exception as exc:
            print(f"search-prompts: usage update failed ({type(exc).__name__})")

    payload = {
        "version": 1,
        "generatedUtc": iso_minute(now),
        "targetDateTpe": target_date,
        "sourceWindow": window,
        "generationMode": generation_mode,
        "provider": provider_label,
        "sourceArticleIds": source_ids,
        "prompts": prompts,
    }
    save_json(output_path, payload)
    print(f"search-prompts: wrote {PROMPT_COUNT} prompts for {target_date} "
          f"({generation_mode}, {window})")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--daily-if-due", action="store_true")
    group.add_argument("--force", action="store_true")
    args = parser.parse_args()
    update_daily_prompts(force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
