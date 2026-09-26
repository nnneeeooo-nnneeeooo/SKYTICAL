#!/usr/bin/env python3
"""Compare SKYTICAL's current full-text extractor with optional alternatives.

This benchmark is intentionally isolated from the production pipeline. It uses
one fetched HTML payload per URL, feeds the exact same payload to every
extractor, records timing/quality heuristics, and writes JSON + Markdown
reports suitable for a GitHub Actions artifact.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline"
if str(PIPELINE) not in sys.path:
    sys.path.insert(0, str(PIPELINE))

import fulltext  # noqa: E402

DEFAULT_LIMIT = 30
MIN_SUCCESS_CHARS = 200
RESULT_DIR = ROOT / "benchmark-results" / "fulltext"
BOILERPLATE_TERMS = (
    "cookie", "privacy policy", "terms of use", "subscribe", "newsletter",
    "sign in", "log in", "accept all", "manage preferences", "advertisement",
    "related articles", "recommended", "follow us", "share this article",
)


@dataclass
class MethodResult:
    method: str
    ok: bool
    elapsed_ms: float
    chars: int
    lines: int
    duplicate_line_ratio: float
    boilerplate_hits: int
    published: str | None = None
    authors: list[str] | None = None
    error: str | None = None


@dataclass
class PageResult:
    url: str
    host: str
    fetch_ms: float
    html_bytes: int
    methods: list[MethodResult]
    fetch_error: str | None = None


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _normalise_lines(text: str) -> list[str]:
    return [_clean_text(line) for line in (text or "").splitlines()
            if _clean_text(line)]


def _quality(text: str) -> tuple[int, int, float, int]:
    lines = _normalise_lines(text)
    if lines:
        duplicate_ratio = 1 - (len(set(lines)) / len(lines))
    else:
        duplicate_ratio = 0.0
    lowered = (text or "").casefold()
    boilerplate_hits = sum(lowered.count(term) for term in BOILERPLATE_TERMS)
    return len(text or ""), len(lines), round(duplicate_ratio, 4), boilerplate_hits


def _method_result(
    method: str,
    started: float,
    text: str | None,
    published: str | None = None,
    authors: Iterable[str] | None = None,
    error: str | None = None,
) -> MethodResult:
    chars, lines, duplicate_ratio, boilerplate_hits = _quality(text or "")
    return MethodResult(
        method=method,
        ok=chars >= MIN_SUCCESS_CHARS and not error,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        chars=chars,
        lines=lines,
        duplicate_line_ratio=duplicate_ratio,
        boilerplate_hits=boilerplate_hits,
        published=published,
        authors=[str(a) for a in (authors or []) if str(a).strip()] or None,
        error=error,
    )


def current_extract(
    html: str, url: str
) -> tuple[str | None, str | None, list[str] | None]:
    return fulltext.extract_text(html), None, None


def trafilatura_extract(
    html: str, url: str
) -> tuple[str | None, str | None, list[str] | None]:
    import trafilatura

    text = trafilatura.extract(
        html,
        url=url,
        output_format="txt",
        include_comments=False,
        include_tables=False,
        favor_precision=True,
    )
    published = None
    authors = None
    try:
        metadata = trafilatura.extract_metadata(html, default_url=url)
        if metadata is not None:
            published = str(getattr(metadata, "date", None) or "") or None
            author_value = getattr(metadata, "author", None)
            if author_value:
                authors = [
                    a.strip()
                    for a in str(author_value).split(";")
                    if a.strip()
                ]
    except Exception:
        pass
    return text, published, authors


def newspaper_extract(
    html: str, url: str
) -> tuple[str | None, str | None, list[str] | None]:
    from newspaper import Article

    article = Article(url)
    article.download(input_html=html)
    article.parse()
    published = article.publish_date.isoformat() if article.publish_date else None
    return article.text, published, list(article.authors or [])


def _available_methods() -> list[
    tuple[
        str,
        Callable[
            [str, str],
            tuple[str | None, str | None, list[str] | None],
        ],
    ]
]:
    methods = [("current", current_extract)]
    try:
        import trafilatura  # noqa: F401
    except ImportError:
        pass
    else:
        methods.append(("trafilatura", trafilatura_extract))
    try:
        import newspaper  # noqa: F401
    except ImportError:
        pass
    else:
        methods.append(("newspaper4k", newspaper_extract))
    return methods


def _article_urls(limit: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    article_dir = ROOT / "data" / "articles"
    for path in sorted(article_dir.glob("*.json"), reverse=True):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for article in payload.get("articles") or []:
            for source in article.get("sources") or []:
                url = str(source.get("url") or "").strip()
                host = urlsplit(url).netloc.lower()
                if not url or host not in fulltext.ALLOWED_HOSTS:
                    continue
                key = fulltext.norm_url(url)
                if key in seen:
                    continue
                seen.add(key)
                urls.append(url)
                if len(urls) >= limit:
                    return urls
    return urls


def _fetch_html(url: str) -> tuple[str | None, float, int, str | None]:
    if urlsplit(url).netloc.lower() not in fulltext.ALLOWED_HOSTS:
        return None, 0.0, 0, "host-not-allowlisted"
    if not fulltext.robots_allows(url):
        return None, 0.0, 0, "robots-denied-or-unreachable"
    started = time.perf_counter()
    try:
        response = requests.get(
            url,
            headers=fulltext.HEADERS,
            timeout=fulltext.TIMEOUT,
        )
    except requests.RequestException as exc:
        return (
            None,
            round((time.perf_counter() - started) * 1000, 2),
            0,
            type(exc).__name__,
        )
    elapsed = round((time.perf_counter() - started) * 1000, 2)
    if response.status_code != 200:
        return (
            None,
            elapsed,
            len(response.content or b""),
            f"http-{response.status_code}",
        )
    final_url = str(getattr(response, "url", "") or url)
    if urlsplit(final_url).netloc.lower() not in fulltext.ALLOWED_HOSTS:
        return (
            None,
            elapsed,
            len(response.content or b""),
            "redirect-host-not-allowlisted",
        )
    if not fulltext.robots_allows(final_url):
        return (
            None,
            elapsed,
            len(response.content or b""),
            "redirect-robots-denied",
        )
    response.encoding = response.encoding or response.apparent_encoding
    return response.text, elapsed, len(response.content or b""), None


def run(urls: list[str]) -> list[PageResult]:
    methods = _available_methods()
    if len(methods) == 1:
        print(
            "warning: optional extractors unavailable; install "
            "benchmarks/requirements-fulltext.txt",
            file=sys.stderr,
        )
    results: list[PageResult] = []
    for index, url in enumerate(urls, start=1):
        host = urlsplit(url).netloc.lower()
        print(f"[{index}/{len(urls)}] {host} {url}")
        html, fetch_ms, html_bytes, fetch_error = _fetch_html(url)
        page = PageResult(
            url=url,
            host=host,
            fetch_ms=fetch_ms,
            html_bytes=html_bytes,
            methods=[],
            fetch_error=fetch_error,
        )
        if html is not None:
            for name, extractor in methods:
                started = time.perf_counter()
                try:
                    text, published, authors = extractor(html, url)
                    page.methods.append(
                        _method_result(
                            name,
                            started,
                            text,
                            published,
                            authors,
                        )
                    )
                except Exception as exc:
                    page.methods.append(
                        _method_result(
                            name,
                            started,
                            None,
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    )
        results.append(page)
    return results


def _summary(results: list[PageResult]) -> dict:
    methods = sorted({m.method for page in results for m in page.methods})
    summary: dict[str, dict] = {}
    fetched = sum(1 for page in results if not page.fetch_error)
    for method in methods:
        rows = [
            m
            for page in results
            for m in page.methods
            if m.method == method
        ]
        ok_rows = [m for m in rows if m.ok]
        summary[method] = {
            "attempted": len(rows),
            "successes": len(ok_rows),
            "success_rate": round(
                (len(ok_rows) / len(rows)) * 100,
                1,
            ) if rows else 0.0,
            "avg_chars_success": round(
                sum(m.chars for m in ok_rows) / len(ok_rows),
                1,
            ) if ok_rows else 0.0,
            "avg_elapsed_ms": round(
                sum(m.elapsed_ms for m in rows) / len(rows),
                2,
            ) if rows else 0.0,
            "avg_duplicate_line_ratio": round(
                sum(m.duplicate_line_ratio for m in ok_rows) / len(ok_rows),
                4,
            ) if ok_rows else 0.0,
            "avg_boilerplate_hits": round(
                sum(m.boilerplate_hits for m in ok_rows) / len(ok_rows),
                2,
            ) if ok_rows else 0.0,
            "published_metadata": sum(1 for m in ok_rows if m.published),
            "author_metadata": sum(1 for m in ok_rows if m.authors),
        }
    return {
        "pages_requested": len(results),
        "pages_fetched": fetched,
        "methods": summary,
    }


def _markdown(summary: dict, results: list[PageResult]) -> str:
    lines = [
        "# SKYTICAL Full-text Extraction Benchmark",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Pages requested: {summary['pages_requested']}",
        f"Pages fetched: {summary['pages_fetched']}",
        "",
        "## Summary",
        "",
        "| Method | Success | Avg chars | Avg ms | Duplicate lines | "
        "Boilerplate hits | Published metadata | Author metadata |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method, row in summary["methods"].items():
        lines.append(
            f"| {method} | {row['successes']}/{row['attempted']} "
            f"({row['success_rate']}%) | {row['avg_chars_success']} | "
            f"{row['avg_elapsed_ms']} | "
            f"{row['avg_duplicate_line_ratio']} | "
            f"{row['avg_boilerplate_hits']} | "
            f"{row['published_metadata']} | {row['author_metadata']} |"
        )
    failures = [page for page in results if page.fetch_error]
    if failures:
        lines.extend(["", "## Fetch failures", ""])
        for page in failures:
            lines.append(
                f"- `{page.host}` — {page.fetch_error}: {page.url}"
            )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "These metrics are screening signals, not a ground-truth quality score. "
        "A production change should only follow a manual review of representative "
        "pages and must preserve SKYTICAL's allowlist, robots handling, redirect "
        "validation, quote traceability, and prompt-size caps.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="maximum recent allowlisted source URLs to benchmark",
    )
    parser.add_argument(
        "--url",
        action="append",
        default=[],
        help="explicit URL to benchmark; may be supplied multiple times",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=RESULT_DIR,
    )
    args = parser.parse_args()

    urls = (
        [u.strip() for u in args.url if u.strip()]
        or _article_urls(max(1, args.limit))
    )
    if not urls:
        print("no eligible URLs found", file=sys.stderr)
        return 2

    results = run(urls[: max(1, args.limit)])
    summary = _summary(results)
    payload = {
        "generatedUtc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "pages": [asdict(page) for page in results],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "results.json"
    md_path = args.output_dir / "summary.md"
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(
        _markdown(summary, results),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
