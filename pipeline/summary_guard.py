"""Repair the manual-desk 180-character fallback when it cuts a sentence.

The manual drafting desk historically used ``body[0][:180]`` whenever an
operator-authored article had no summary.  That fallback can end in the middle
of a sentence.  This publishing guard is deliberately narrow: it only changes
a summary when it exactly matches that legacy 180-character prefix and the
prefix does not end at a sentence boundary.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ARTICLES_DIR, load_json, save_json  # noqa: E402

SOFT_LIMIT = 180
HARD_LIMIT = 260
_CLOSERS = '"\'”’）)]』」》'
_SENTENCE_END_RE = re.compile(
    rf"(?:[。！？!?]|\.(?=(?:[{re.escape(_CLOSERS)}]|\s|$)))"
    rf"[{re.escape(_CLOSERS)}]*"
)


def _ends_sentence(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(str(text or '').rstrip())
                and _SENTENCE_END_RE.search(str(text or '').rstrip()).end()
                == len(str(text or '').rstrip()))


def sentence_safe_fallback(text: str) -> str:
    """Return a compact summary without exposing an accidental hard cut."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= SOFT_LIMIT:
        return clean

    boundaries = [
        match.end() for match in _SENTENCE_END_RE.finditer(clean[:HARD_LIMIT])
    ]
    after_soft = next((end for end in boundaries if end >= SOFT_LIMIT), None)
    if after_soft is not None:
        return clean[:after_soft].strip()

    before_soft = [end for end in boundaries if end < SOFT_LIMIT]
    if before_soft:
        return clean[:before_soft[-1]].strip()

    prefix = clean[:SOFT_LIMIT].rstrip()
    word_cut = max(prefix.rfind(" "), prefix.rfind("　"))
    if word_cut >= SOFT_LIMIT // 2:
        prefix = prefix[:word_cut].rstrip()
    return prefix.rstrip("，,；;：:") + "…"


def repair_article(article: dict) -> bool:
    changed = False
    for lang in ("zh", "en"):
        block = article.get(lang)
        if not isinstance(block, dict):
            continue
        body = block.get("body")
        if not isinstance(body, list) or not body:
            continue
        first = str(body[0] or "").strip()
        summary = str(block.get("summary") or "").strip()
        if (len(first) > SOFT_LIMIT
                and summary == first[:SOFT_LIMIT]
                and not _ends_sentence(summary)):
            repaired = sentence_safe_fallback(first)
            if repaired and repaired != summary:
                block["summary"] = repaired
                changed = True
    return changed


def main() -> int:
    if not ARTICLES_DIR.is_dir():
        print("summary_guard: no articles yet")
        return 0

    updated_articles = 0
    updated_files = 0
    for path in sorted(ARTICLES_DIR.glob("*.json")):
        batch = load_json(path, None)
        if not isinstance(batch, dict):
            continue
        file_changed = False
        for article in batch.get("articles") or []:
            if isinstance(article, dict) and repair_article(article):
                updated_articles += 1
                file_changed = True
        if file_changed:
            save_json(path, batch)
            updated_files += 1

    print(
        f"summary_guard: repaired {updated_articles} article(s) "
        f"in {updated_files} file(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
