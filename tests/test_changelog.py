"""Offline checks for the bilingual, source-traceable site changelog."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import build  # noqa: E402


def main() -> None:
    raw = json.loads(
        (ROOT / "config" / "changelog.json").read_text(encoding="utf-8"))
    assert raw["schemaVersion"] == 1
    assert raw["historyStart"] == "2026-07-26"
    assert raw["updatedThrough"] == "2026-07-30"
    assert len(raw["entries"]) == 53

    historical = [row["commit"] for row in raw["entries"]
                  if row["commit"] is not None]
    assert len(historical) == 51
    assert len(set(historical)) == len(historical)
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in historical)
    assert sum(row["commit"] is None for row in raw["entries"]) == 2
    rendered_copy = "\n".join(
        f"{row['zh']}\n{row['en']}" for row in raw["entries"])
    assert "免費" not in rendered_copy
    assert "free keyless" not in rendered_copy.lower()
    assert "free no-api" not in rendered_copy.lower()
    assert not any(term in rendered_copy for term in (
        "補上", "跑馬燈", "杜撰偵測防線", "機器強制",
        "機器審核", "完整性檢查淘汰", "消化編輯拒絕",
    ))

    dates = [row["date"] for row in raw["entries"]]
    assert dates == sorted(dates, reverse=True)
    assert {row["kind"] for row in raw["entries"]} \
        <= build._CHANGELOG_KINDS
    assert all(row["zh"].strip() and row["en"].strip()
               for row in raw["entries"])

    zh = build.changelog_view(
        raw, "zh", build.L["zh"]["changeKinds"])
    en = build.changelog_view(
        raw, "en", build.L["en"]["changeKinds"])
    assert zh["count"] == en["count"] == 53
    assert [group["date"] for group in zh["groups"]] \
        == ["2026-07-30", "2026-07-28", "2026-07-27", "2026-07-26"]
    assert zh["groups"][0]["entries"][0]["title"] \
        == "私人 API 用量頁新增模型失敗、備援切換、各階段耗時與最近 30 天執行紀錄。"
    assert en["groups"][-1]["entries"][-1]["title"].startswith(
        "Created AVWIRE")
    linked = [entry for group in en["groups"] for entry in group["entries"]
              if entry["commit"]]
    assert all(entry["url"] ==
               f"{build._CHANGELOG_REPOSITORY}/commit/{entry['commit']}"
               for entry in linked)

    malformed = {
        "entries": [
            {"date": "not-a-date", "kind": "feature", "commit": None,
             "zh": "bad", "en": "bad"},
            {"date": "2026-07-28", "kind": "unknown", "commit": None,
             "zh": "bad", "en": "bad"},
            {"date": "2026-07-28", "kind": "feature",
             "commit": "javascript:alert(1)", "zh": "bad", "en": "bad"},
            {"date": "2026-07-28", "kind": "feature",
             "commit": historical[0], "zh": "ok", "en": "ok"},
            {"date": "2026-07-28", "kind": "feature",
             "commit": historical[0], "zh": "duplicate", "en": "duplicate"},
        ]
    }
    safe = build.changelog_view(
        malformed, "zh", build.L["zh"]["changeKinds"])
    assert safe["count"] == 1
    assert safe["groups"][0]["entries"][0]["title"] == "ok"

    env = Environment(
        loader=FileSystemLoader(str(ROOT / "templates")),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    fake_build = {
        "date": "2026-07-28 TUE", "utc_hm": "14:00",
        "tpe_hm": "22:00", "stamp": "2026-07-28 14:00",
    }
    for lang, view in (("zh", zh), ("en", en)):
        t = build.L[lang]
        ctx = build.base_ctx(
            lang, "changelog", "changelog/",
            title=f"{t['siteName']} — {t['changeTitle']}",
            description=t["changeSub"], ticker=[], build=fake_build)
        ctx["changelog"] = view
        html = env.get_template("changelog.html").render(**ctx)
        expected_path = ("/avwire/changelog/" if lang == "zh"
                         else "/avwire/en/changelog/")
        assert f'href="{expected_path}"' in html
        assert t["footerChangelog"] in html
        assert t["changeNotice"] in html
        assert len(re.findall(r'class="changelog-entry"', html)) == 53
        assert "javascript:alert" not in html

    print("test_changelog: OK")


if __name__ == "__main__":
    main()
