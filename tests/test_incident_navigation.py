"""Offline regression checks for weekly serious-incident navigation."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    assert build.main() == 0

    stats = json.loads(
        (ROOT / "data" / "stats.json").read_text(encoding="utf-8"))
    expected = stats["seriousThisWeek"]
    home = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    en_home = (ROOT / "site" / "en" / "index.html").read_text(encoding="utf-8")
    incidents = (ROOT / "site" / "incidents" / "index.html").read_text(encoding="utf-8")
    script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert 'href="/incidents/?filter=week"' in home
    assert 'href="/en/incidents/?filter=week"' in en_home
    assert 'data-filter-sev="week"' in incidents
    weekly_rows = re.findall(
        r'<tr data-sev="(?:acc|ser)" data-weekly-serious="true">.*?</tr>',
        incidents,
        re.DOTALL,
    )
    assert len(weekly_rows) == expected
    assert weekly_rows and all(
        'class="incident-article-link"' in row for row in weekly_rows)
    assert all('class="incident-date-link"' in row for row in weekly_rows)
    assert 'new URLSearchParams(window.location.search)' in script
    assert 'row.dataset.weeklySerious === "true"' in script

    print("test_incident_navigation: OK")


if __name__ == "__main__":
    main()
