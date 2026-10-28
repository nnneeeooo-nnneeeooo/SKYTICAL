"""Offline checks for the bilingual, source-traceable site changelog."""
from __future__ import annotations

import copy
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
    assert raw["repository"] == "https://github.com/nnneeeooo-nnneeeooo/SKYTICAL"
    assert raw["historyStart"] == "2026-07-26"
    assert raw["updatedThrough"] == "2026-10-28"
    assert len(raw["entries"]) == 114

    historical = [row["commit"] for row in raw["entries"]
                  if row["commit"] is not None]
    archive = json.loads(
        (ROOT / "config" / "commit-records.json").read_text(encoding="utf-8"))
    assert archive["schemaVersion"] == 2
    assert set(archive["commits"]) == set(historical)
    commit_records = build.commit_records_view(archive, historical)
    assert all(commit_records[sha]["sha"] == sha for sha in historical)
    expected_by_sha = {row["commit"]: row for row in raw["entries"]
                       if row["commit"]}
    for sha, record in commit_records.items():
        assert set(record) == {"sha", "date", "summary", "stats", "redacted"}
        assert record["date"] == expected_by_sha[sha]["date"]
        assert record["summary"] == {
            lang: expected_by_sha[sha][lang] for lang in ("zh", "en")}
        assert record["redacted"] is True
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["date"])
    public_copy = json.dumps(archive, ensure_ascii=False)
    assert not re.search(r"T\d{2}:\d{2}|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", public_copy)
    assert not any(term in public_copy for term in (
        "AVWIRE_", "usage.json", "private usage", "manual-jobs",
        "copilot-jobs", "diffLines", "created_at", "filename", "email"))

    # A legacy archive or reintroduced sensitive field must stop publication.
    for changed in (
        {"schemaVersion": 1},
        {"extra": "unexpected"},
        {"record": {"author": {"email": "person@example.com"}}},
        {"record": {"date": "2026-07-28T14:00:00Z"}},
        {"record": {"date": "2026-02-30"}},
        {"record": {"diffLines": ["private settings"]}},
        {"record": {"redacted": False}},
        {"record": {"summary": {"zh": "person@example.com", "en": "Summary"}}},
        {"record": {"summary": {"zh": "摘要", "en": "2026-07-28T14:00Z"}}},
        {"record": {"summary": {"zh": "摘要", "en": "AVWIRE_PRIVATE_SETTING"}}},
        {"record": {"stats": {"files": True, "additions": 1, "deletions": 0}}},
    ):
        unsafe = copy.deepcopy(archive)
        if "record" in changed:
            unsafe["commits"][historical[0]].update(changed["record"])
        else:
            unsafe.update(changed)
        try:
            build.commit_records_view(unsafe, historical)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe public archive accepted: {changed}")
    assert len(historical) == 113
    assert len(set(historical)) == len(historical)
    assert all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in historical)
    assert sum(row["commit"] is None for row in raw["entries"]) == 1
    assert next(row for row in raw["entries"] if row["commit"] is None) == {
        "date": "2026-10-19", "kind": "feature", "commit": None,
        "zh": "新增彩蛋。",
        "en": "Added an Easter egg.",
    }
    assert [row["commit"] for row in raw["entries"][:5]] == [
        "1b055b72d11b691df28fa991d9c5c91fc8cf0171",
        "820dd9df4bef609ee6df249c8eb733ba101fe4d2",
        "1845d973244de1de2b59a89fad30efcb007f2451",
        "664f41408c35309f459d6ff8fa5fb5cd5378a3aa",
        "9d898aaa48f316ce77944a9a68987e45e0e5167b",
    ]
    assert {
        sha: expected_by_sha[sha]["date"] for sha in (
            "5a583102f2088b4a54058c87a97d7aeea4b9a410",
            "f4760026bbcea265b523824ff54bdc6f5bbe66ea",
            "4e0483122d1246556b7520ac15d4ccab15971d43",
            "6c66ad9e4fdbedc2aefa0070d57508fd92aa12d7",
            "bef6dec80650df07395ef3188b05494dda631c88",
        )
    } == {
        "5a583102f2088b4a54058c87a97d7aeea4b9a410": "2026-10-24",
        "f4760026bbcea265b523824ff54bdc6f5bbe66ea": "2026-10-23",
        "4e0483122d1246556b7520ac15d4ccab15971d43": "2026-10-23",
        "6c66ad9e4fdbedc2aefa0070d57508fd92aa12d7": "2026-10-22",
        "bef6dec80650df07395ef3188b05494dda631c88": "2026-10-20",
    }
    assert {
        sha: expected_by_sha[sha]["date"] for sha in (
            "10eafb38be69447d39ea888df819e4b694e41ced",
            "eaa85e006fbfb9bbe0992e0a0afdba6f6063c625",
            "1b525576bf182fbf18ec4698918136bccf03fdf0",
            "a8bbd76a65adb780e6f6cd9c8c28474d17b597a6",
        )
    } == {
        "10eafb38be69447d39ea888df819e4b694e41ced": "2026-10-18",
        "eaa85e006fbfb9bbe0992e0a0afdba6f6063c625": "2026-10-18",
        "a8bbd76a65adb780e6f6cd9c8c28474d17b597a6": "2026-10-13",
        "1b525576bf182fbf18ec4698918136bccf03fdf0": "2026-10-13",
    }
    rendered_copy = "\n".join(
        f"{row['zh']}\n{row['en']}" for row in raw["entries"])
    assert "免費" not in rendered_copy
    assert "free keyless" not in rendered_copy.lower()
    assert "free no-api" not in rendered_copy.lower()
    assert not any(term in rendered_copy for term in (
        "補上", "跑馬燈", "杜撰偵測防線", "機器強制",
        "機器審核", "完整性檢查淘汰", "消化編輯拒絕",
    ))
    assert not any(term in rendered_copy.lower() for term in (
        "私人", "人工撰稿工作台", "private authoring workbench",
        "private manual", "private usage", "usage dashboard",
        "reference-cost dashboard", "人工新聞部署流程",
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
    assert zh["count"] == en["count"] == 114
    assert [group["date"] for group in zh["groups"]] \
        == sorted(set(dates), reverse=True)
    assert zh["groups"][0]["entries"][0]["title"].startswith(
        "修正首頁過期置頂文章")
    assert en["groups"][0]["entries"][0]["title"].startswith(
        "Fixed stale pinned stories")
    assert en["groups"][-1]["entries"][-1]["title"].startswith(
        "Created SKYTICAL")
    linked = [entry for group in en["groups"] for entry in group["entries"]
              if entry["commit"]]
    assert len(linked) == len(historical)
    assert all(entry["url"] == build.page_url(
               "en", f"changelog/commits/{entry['commit']}/")
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
        expected_path = ("/changelog/" if lang == "zh"
                         else "/en/changelog/")
        assert f'href="{expected_path}"' in html
        assert t["footerChangelog"] in html
        assert t["changeNotice"] in html
        assert len(re.findall(r'class="changelog-entry"', html)) == 114
        assert len(re.findall(r'class="changelog-commit"', html)) == 113
        assert 'href="https://github.com/nnneeeooo-nnneeeooo/SKYTICAL/commit/' not in html
        assert "javascript:alert" not in html

        sha = historical[0]
        record = commit_records[sha]
        sub = f"changelog/commits/{sha}/"
        record_ctx = build.base_ctx(
            lang, "changelog", sub,
            title=f"{sha[:7]}｜{t['commitRecordTitle']}｜{t['siteName']}",
            description=t["changeNotice"], ticker=[], build=fake_build)
        record_ctx["commit_record"] = record
        record_ctx["raw_record_url"] = f"{build.BASE_PATH}/commit-records/{sha}.json"
        record_html = env.get_template("commit_record.html").render(**record_ctx)
        assert sha in record_html
        assert f'href="{build.BASE_PATH}/commit-records/{sha}.json"' in record_html
        assert record["summary"][lang] in record_html
        assert record["date"] in record_html
        assert "commit-record-diff" not in record_html
        assert "@" not in record_html.split('<main class="commit-record-page">')[1].split("</main>")[0]
        assert not any(term in record_html for term in (
            "AVWIRE_", "diff --git", "data/usage.json"))
        assert 'href="https://github.com/nnneeeooo-nnneeeooo/SKYTICAL/commit/' not in record_html

    print("test_changelog: OK")


if __name__ == "__main__":
    main()
