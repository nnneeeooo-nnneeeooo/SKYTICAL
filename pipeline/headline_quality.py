"""Small deterministic checks shared by article and briefing headlines."""
from __future__ import annotations

import re

OPAQUE_ZH_HEADLINE_TERMS = ("拒離機", "清艙", "換志願者")


def normalize_zh_headline(value: str) -> str:
    """Use spaces instead of semicolons and collapse headline whitespace."""
    return re.sub(r"[\s；;]+", " ", str(value or "")).strip()


def zh_headline_problem(value: str) -> str | None:
    """Return a short validation error for known unreadable Chinese headlines."""
    if not isinstance(value, str) or not value.strip():
        return "is missing; provide a clear standalone headline"
    if re.search(r"[；;]", value):
        return "contains a semicolon; use a space between headline clauses"
    opaque = next((term for term in OPAQUE_ZH_HEADLINE_TERMS if term in value), None)
    if opaque:
        return (f"uses opaque compressed wording ({opaque}); use clear everyday "
                "language that names the subject, action and supported result")
    return None
