"""Keep edits that reached the branch while a data workflow was running.

`git pull --rebase -X theirs` settles overlapping lines for the run, which
silently replaced a reviewed photo whenever an image stage touched the same
article.  Two guards replace that for published data:

* ``merge`` is a git merge driver (see .gitattributes).  It merges an article
  batch by article ID and field group instead of by line: whatever the branch
  changed since the run started stays, the run keeps what the branch left alone.
* ``guard`` runs after the rebase and restores, from the branch tip, any locked
  image, article or batch the run's working tree no longer carries.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from common import MAX_FLASHES, MAX_INCIDENTS, save_json
from roundup_images import cover_image, is_industry

ROOT = Path(__file__).resolve().parent.parent
IMAGE_FIELDS = ("image", "images", "imageSelection", "editorialImageLocked")
PREPEND_CAPS = {"data/flashes.json": MAX_FLASHES, "data/incidents.json": MAX_INCIDENTS}
DRIVER = "skytical-data"


def is_managed(article) -> bool:
    """Same articles write.py refuses to redraft."""
    return isinstance(article, dict) and (
        article.get("editorialLocked") is True
        or isinstance(article.get("scheduledNews"), dict)
        or str(article.get("writer") or "").startswith(("manual:", "scheduled:")))


def image_locked(row) -> bool:
    return isinstance(row, dict) and row.get("editorialImageLocked") is True


def _split(row):
    row = row if isinstance(row, dict) else {}
    images = {k: row[k] for k in IMAGE_FIELDS if k in row}
    content = {k: v for k, v in row.items()
               if k not in IMAGE_FIELDS and k != "roundupItems"}
    return images, content


def _items(row):
    rows = row.get("roundupItems") if isinstance(row, dict) else None
    return rows if isinstance(rows, list) else None


def _key(item, index):
    return str(item.get("articleId") or f"#{index}") if isinstance(item, dict) else f"#{index}"


def merge_row(base, branch, run, notes, label, *, managed=False, locked=False):
    """Merge one article or roundup item; the branch wins what it changed."""
    if run == base or run == branch:
        return branch
    base_images, base_content = _split(base)
    branch_images, branch_content = _split(branch)
    run_images, run_content = _split(run)
    keep_images = (locked or image_locked(branch) or base is None
                   or branch_images != base_images)
    keep_content = (managed or is_managed(branch) or base is None
                    or branch_content != base_content)
    if keep_images and run_images not in (branch_images, base_images):
        notes.append(f"{label}: kept the branch image")
    if keep_content and run_content not in (branch_content, base_content):
        notes.append(f"{label}: kept the branch text; the run's revision is dropped")
    images = branch_images if keep_images else run_images
    content = branch_content if keep_content else run_content
    branch_items, run_items = _items(branch), _items(run)
    merged = {}
    for key in [*branch, *(k for k in run if k not in branch)]:
        if key == "roundupItems":
            if branch_items is None or run_items is None or locked or image_locked(branch):
                source = branch if "roundupItems" in branch else run
                merged[key] = source["roundupItems"]
            else:
                merged[key] = _merge_items(_items(base) or [], branch_items,
                                           run_items, notes, label)
        elif key in IMAGE_FIELDS:
            if key in images:
                merged[key] = images[key]
        elif key in content:
            merged[key] = content[key]
    if is_industry(merged) and _items(merged) is not None:
        merged["image"] = cover_image(merged["roundupItems"])
    return merged


def _merge_items(base, branch, run, notes, label):
    base_by = {_key(item, i): item for i, item in enumerate(base)}
    run_by = {_key(item, i): item for i, item in enumerate(run)}
    merged = []
    for index, item in enumerate(branch):
        key = _key(item, index)
        if key in run_by and isinstance(item, dict) and isinstance(run_by[key], dict):
            item = merge_row(base_by.get(key), item, run_by[key], notes,
                             f"{label} item {key}")
        merged.append(item)
    seen = {_key(item, i) for i, item in enumerate(branch)}
    merged += [item for i, item in enumerate(run)
               if _key(item, i) not in seen and _key(item, i) not in base_by]
    return merged


def _articles(batch, name):
    rows = batch.get("articles") if isinstance(batch, dict) else None
    if not isinstance(rows, list) or not all(
            isinstance(row, dict) and row.get("id") for row in rows):
        raise ValueError(f"{name} is not an article batch")
    return rows


def merge_batch(base, branch, run):
    """Return (merged batch, notes).  ``base`` is None when git has no ancestor."""
    notes = []
    base_by = {row["id"]: row for row in _articles(base, "base")} if base else {}
    run_rows = _articles(run, "run")
    run_by = {row["id"]: row for row in run_rows}
    merged, seen = [], set()
    for row in _articles(branch, "branch"):
        seen.add(row["id"])
        if row["id"] in run_by:
            row = merge_row(base_by.get(row["id"]) if base else None, row,
                            run_by[row["id"]], notes, row["id"])
        merged.append(row)
    for row in run_rows:
        if row["id"] in seen:
            continue
        if row["id"] in base_by:
            notes.append(f"{row['id']}: removed on the branch; not restored")
        else:
            merged.append(row)
    return {**run, **branch, "articles": merged}, notes


def merge_prepended(base, branch, run, cap):
    """The run only prepends rows; keep the branch's rows below them."""
    if not all(isinstance(rows, list) for rows in (branch, run)):
        raise ValueError("not a row list")
    old = base if isinstance(base, list) else []
    new = [row for row in run if row not in old and row not in branch]
    return (new + branch)[:cap]


def _load(path):
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text) if text.strip() else None


def merge_driver(base_path, branch_path, run_path, name) -> int:
    try:
        base, branch, run = _load(base_path), _load(branch_path), _load(run_path)
        if name in PREPEND_CAPS:
            merged, notes = merge_prepended(base, branch, run, PREPEND_CAPS[name]), []
        else:
            merged, notes = merge_batch(base, branch, run)
    except (OSError, ValueError) as exc:
        # Leave the conflict for git: the rebase stops and the branch is untouched.
        print(f"data_merge: {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    save_json(Path(branch_path), merged)
    for note in notes:
        print(f"::warning::data_merge: {name}: {note}", file=sys.stderr)
    return 0


def _git(*args, root=ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout


def install(root=ROOT) -> None:
    command = f'"{sys.executable}" pipeline/data_merge.py merge %O %A %B %P'
    _git("config", f"merge.{DRIVER}.name", "SKYTICAL article-aware data merge", root=root)
    _git("config", f"merge.{DRIVER}.driver", command, root=root)


def _restore_images(tip, row, notes, label, *, locked=False) -> bool:
    changed = False
    if (locked or image_locked(tip)) and _split(row)[0] != _split(tip)[0]:
        restored = {key: (tip if key in IMAGE_FIELDS else row)[key]
                    for key in [*tip, *(k for k in row if k not in tip)]
                    if key in (tip if key in IMAGE_FIELDS else row)}
        row.clear()
        row.update(restored)
        notes.append(f"{label}: restored the locked image")
        changed = True
    tip_items, items = _items(tip), _items(row)
    if tip_items is None:
        return changed
    if items is None or [_key(i, n) for n, i in enumerate(items)][:len(tip_items)] != [
            _key(i, n) for n, i in enumerate(tip_items)]:
        if any(image_locked(item) for item in tip_items) or image_locked(tip):
            row["roundupItems"] = tip_items
            notes.append(f"{label}: restored the roundup items")
            changed = True
    else:
        for index, tip_item in enumerate(tip_items):
            changed |= _restore_images(tip_item, items[index], notes,
                                       f"{label} item {_key(tip_item, index)}",
                                       locked=locked or image_locked(tip))
    if changed and is_industry(row):
        row["image"] = cover_image(row["roundupItems"])
    return changed


def guard(rev: str, root=ROOT) -> list[str]:
    """Restore what ``rev`` protects and the working tree changed or lost."""
    notes = []
    listing = _git("diff", "--name-status", "--no-renames", rev, "--",
                   "data/articles", root=root)
    for line in listing.splitlines():
        status, name = line.split("\t", 1)
        if status == "A" or not name.endswith(".json"):
            continue
        tip = json.loads(_git("show", f"{rev}:{name}", root=root))
        path = Path(root) / name
        try:
            batch = _load(path)
            rows = _articles(batch, name)
        except (OSError, ValueError):
            save_json(path, tip)
            notes.append(f"{name}: unreadable batch replaced with the branch copy")
            continue
        by_id = {row["id"]: row for row in rows}
        changed = False
        for row in _articles(tip, name):
            if row["id"] not in by_id:
                rows.append(row)
                notes.append(f"{row['id']}: restored the missing article")
                changed = True
            else:
                changed |= _restore_images(row, by_id[row["id"]], notes, row["id"])
        if changed:
            save_json(path, batch)
    return notes


def main(argv) -> int:
    if argv[:1] == ["merge"] and len(argv) == 5:
        return merge_driver(*argv[1:])
    if argv == ["install"]:
        install()
        return 0
    if argv[:1] == ["guard"] and len(argv) == 2:
        for note in guard(argv[1]):
            print(f"::warning::data_merge: {note}")
        return 0
    print("usage: data_merge.py install | guard <rev> | merge <base> <branch> <run> <path>",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
