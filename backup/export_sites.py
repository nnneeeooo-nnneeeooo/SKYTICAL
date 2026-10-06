"""Export an owner-private Sites reading snapshot; never run news writers.

This is deliberately a snapshot, not a failover executor. The generated Site
keeps the primary site's canonical URLs and labels its actual capabilities.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".sites-work" / "standby"
PRIMARY = "https://skytical.tech"
PRIVATE_ASSETS = {"manual.js", "copilot.js", "copilot.css"}


def snapshot_html(content: str, timestamp: str) -> str:
    """Label both languages and prevent indexing without changing canonicals."""
    english = bool(re.search(r'<html\b[^>]*\blang=[\"\']en(?:-[^\"\']*)?[\"\']',
                             content, re.I))
    content = re.sub(r'<meta\b[^>]*\bname=[\"\']robots[\"\'][^>]*>', "",
                     content, flags=re.I)
    content = re.sub(r"</head\s*>", '<meta name="robots" content="noindex,nofollow">'
                     "</head>", content, count=1, flags=re.I)
    content = content.replace("● LIVE</span>", "● SNAPSHOT</span>")
    content = content.replace(" NEAR-LIVE ADS-B</div>", " ADS-B SNAPSHOT</div>")
    message = ("Reading snapshot · Automatic publishing and radar updates are not active. "
               if english else "閱讀快照｜自動發布與雷達更新尚未啟用。")
    label = "Backup status" if english else "備援狀態"
    primary = "Primary website" if english else "主站"
    notice = ('<aside aria-label="SKYTICAL standby" data-sites-snapshot="true" '
              'style="padding:12px 20px;background:#fff1cb;color:#35290a;'
              'font:14px/1.6 system-ui;border-bottom:1px solid #d8ba63">'
              f'{message}<time datetime="{html.escape(timestamp, quote=True)}">'
              f'{html.escape(timestamp)}</time> · <a href="/standby/">{label}</a>'
              f' · <a href="{PRIMARY}">{primary}</a></aside>')
    return re.sub(r"(<body\b[^>]*>)", lambda match: match[1] + notice,
                  content, count=1, flags=re.I)


def sanitize_snapshot(directory: Path, timestamp: str) -> int:
    """Fail on private output; omit GitHub-writing UI and domain validation."""
    for name in ("u", "m"):
        if (directory / name).exists():
            raise RuntimeError("Private dashboard/workbench must not enter a snapshot")
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if path.name in PRIVATE_ASSETS or re.fullmatch(r"google[a-f0-9]+\.html", path.name):
            path.unlink()
    pages = 0
    for path in directory.rglob("*.html"):
        path.write_text(snapshot_html(path.read_text(encoding="utf-8"), timestamp),
                        encoding="utf-8", newline="\n")
        pages += 1
    (directory / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    return pages


def main() -> int:
    # No user-selected destination: build.py clears its output directory. Reject
    # symlinks/junctions so that this cannot erase a different checkout or data.
    output = WORK / "dist"
    for path in (ROOT / ".sites-work", WORK, output):
        if path.is_symlink() or path.is_junction():
            raise RuntimeError("Snapshot output must not use links or junctions")
    if not output.resolve().is_relative_to((ROOT / ".sites-work").resolve()):
        raise RuntimeError("Snapshot output is outside the dedicated workspace")
    WORK.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((ROOT / "backup/sites/.openai/hosting.json").read_text(encoding="utf-8"))
    if not manifest.get("project_id"):
        raise RuntimeError("Persist the native Sites project ID before exporting")
    # Production secrets are unnecessary for rendering and must not create
    # private URLs in a reading snapshot. Only this Python process is changed.
    for name in ("AVWIRE_USAGE_TOKEN", "AVWIRE_MANUAL_TOKEN"):
        os.environ.pop(name, None)
    os.environ["BASE_PATH"] = ""
    os.environ["SITE_ORIGIN"] = PRIMARY
    sys.path.insert(0, str(ROOT / "pipeline"))
    import common
    common.SITE_DIR = output
    common.BASE_PATH = ""
    common.SITE_ORIGIN = PRIMARY
    import build
    build.L["zh"].update(updateBadge="備援閱讀快照", live="已發布快訊",
                         flash="快訊快照", today="營運資料快照",
                         statRadar="雷達快照", statRadarValue="SNAPSHOT")
    build.L["en"].update(updateBadge="Reading snapshot", live="PUBLISHED WIRE",
                         flash="Wire snapshot", today="Operations snapshot",
                         statRadar="Radar snapshot", statRadarValue="SNAPSHOT")
    result = build.main()
    if result:
        return result  # Never package a build that failed its render budget.
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    pages = sanitize_snapshot(output, stamp)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                       text=True).strip()
    stats = common.load_json(common.DATA_DIR / "stats.json", {})
    status = {
        "schema": 1, "mode": "read_only_snapshot", "activePublisher": "github",
        "primaryUrl": PRIMARY, "snapshotAt": stamp, "sourceCommit": revision,
        "sourceStatsUpdatedUtc": stats.get("updatedUtc") if isinstance(stats, dict) else None,
        "pages": pages, "automaticSync": False, "automaticFailover": False,
        "newsWriter": False, "briefingWriter": False, "radarUpdater": False,
        "manualPublisher": False, "privateUsageDashboard": False,
    }
    (output / "standby.json").write_text(json.dumps(status, ensure_ascii=False, indent=2)
                                          + "\n", encoding="utf-8")
    status_dir = output / "standby"
    status_dir.mkdir(exist_ok=True)
    rows = "".join(f"<tr><th>{html.escape(key)}</th><td>{html.escape(str(value))}</td></tr>"
                   for key, value in status.items())
    page = ('<!doctype html><html lang="zh-Hant-TW"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>SKYTICAL 備援狀態</title><style>body{font:16px/1.7 system-ui;'
            'max-width:900px;margin:40px auto;padding:0 20px;color:#172535}'
            'td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd;'
            'overflow-wrap:anywhere}table{width:100%}</style></head><body>'
            '<h1>SKYTICAL 備援狀態</h1><p>GitHub 仍為主站與唯一發布者。'
            '此 Sites 版本僅保存已發布內容的閱讀快照，尚未具備全系統接管能力。</p>'
            '<p>文章、雙語頁面、搜尋及既有快報可閱讀；新聞抓取、撰稿、快報產生、'
            '雷達更新、手動發布與私有用量報表尚未接通。此版本不會自動同步。</p>'
            '<p>外部圖片、地圖與來源連結仍取決於各提供者。雷達沿用過期資料隱藏規則。</p>'
            f'<p><a href="/">瀏覽備援快照</a> · <a href="{PRIMARY}">回到主站</a></p>'
            f'<table>{rows}</table></body></html>')
    (status_dir / "index.html").write_text(snapshot_html(page, stamp), encoding="utf-8")
    (WORK / ".openai").mkdir(exist_ok=True)
    manifest["static"] = {"directory": "dist"}
    (WORK / ".openai/hosting.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"Sites reading snapshot prepared: {pages} pages; backend and sync disabled")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
