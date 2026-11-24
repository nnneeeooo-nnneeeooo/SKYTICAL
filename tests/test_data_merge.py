"""Concurrent-write guards: a data workflow must not undo edits made meanwhile."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
os.environ["AVWIRE_DATA_DIR"] = tempfile.mkdtemp(prefix="avwire-data-merge-")
sys.path.insert(0, str(ROOT / "pipeline"))

import data_merge  # noqa: E402

BATCH = "data/articles/2026-11-24T03.json"
CURATED = {"url": "https://example.gov/summit.jpg", "provider": "The White House",
           "kind": "file_photo", "curated": True}
STOCK = {"url": "https://upload.example.org/737.jpg", "provider": "Wikimedia Commons",
         "kind": "file_photo"}


def roundup():
    return {"id": "a-roundup", "articleFormat": "roundup", "roundupKind": "industry",
            "image": None, "zh": {"title": "短訊"}, "en": {"title": "Briefs"},
            "roundupItems": [{"articleId": "a-qantas", "image": None},
                             {"articleId": "a-boeing", "image": None},
                             {"articleId": "a-delta", "image": None}]}


def story(article_id="a-story", **extra):
    return {"id": article_id, "writer": "openai:auto", "image": None,
            "zh": {"title": "標題", "body": ["內文"]},
            "en": {"title": "Title", "body": ["Body"]}, **extra}


def batch(*articles):
    return {"articles": list(articles)}


def lock_item(article, article_id="a-boeing", image=CURATED):
    item = next(i for i in article["roundupItems"] if i["articleId"] == article_id)
    item.update(image=dict(image), images=[dict(image)], editorialImageLocked=True)
    article["image"] = {**article["roundupItems"][0]["image"], "roundupItemNumber": 1} \
        if article["roundupItems"][0]["image"] else {**image, "roundupItemNumber": 2}
    return article


def item(payload, article_id):
    return next(i for a in payload["articles"] for i in a.get("roundupItems") or []
                if i["articleId"] == article_id)


def article(payload, article_id):
    return next(a for a in payload["articles"] if a["id"] == article_id)


# --- merge rules -----------------------------------------------------------

def test_locked_photo_beats_the_pipeline_photo_on_the_same_item():
    base = batch(roundup())
    branch = batch(lock_item(roundup()))
    run = copy.deepcopy(base)
    item(run, "a-boeing").update(image=dict(STOCK), images=[dict(STOCK)])
    item(run, "a-delta")["image"] = dict(STOCK)
    merged, notes = data_merge.merge_batch(base, branch, run)
    assert item(merged, "a-boeing") == item(branch, "a-boeing")
    assert item(merged, "a-delta")["image"] == STOCK      # the run's other work stays
    assert merged["articles"][0]["image"] == {**CURATED, "roundupItemNumber": 2}
    assert any("a-boeing" in note for note in notes)


def test_unlocked_branch_photo_also_beats_the_pipeline_photo():
    base = batch(story())
    branch = batch(story(image=dict(CURATED)))
    run = batch(story(image=dict(STOCK), imageSelection={"status": "matched"}))
    merged, _ = data_merge.merge_batch(base, branch, run)
    assert merged["articles"][0]["image"] == CURATED
    assert "imageSelection" not in merged["articles"][0]


def test_branch_text_edit_and_pipeline_photo_both_survive():
    base = batch(story())
    branch = batch(story(archived=True, archiveReason="duplicate"))
    run = batch(story(image=dict(STOCK)))
    merged, notes = data_merge.merge_batch(base, branch, run)
    assert merged["articles"][0]["archived"] is True
    assert merged["articles"][0]["image"] == STOCK
    assert notes == []


def test_branch_text_edit_beats_a_pipeline_redraft_as_a_whole():
    base = batch(story())
    branch = batch(story(zh={"title": "人工修正", "body": ["內文"]}))
    run = batch(story(zh={"title": "模型改寫", "body": ["新內文"]},
                      en={"title": "Model rewrite", "body": ["New body"]}, revision=2))
    merged, notes = data_merge.merge_batch(base, branch, run)
    assert merged["articles"][0] == branch["articles"][0]   # no half zh, half en
    assert any("revision is dropped" in note for note in notes)


def test_articles_added_on_both_sides_are_all_kept_branch_first():
    base = batch(story("a-old"))
    branch = batch(story("a-old"), story("a-manual", writer="scheduled:Devin"))
    run = batch(story("a-old"), story("a-new"))
    merged, _ = data_merge.merge_batch(base, branch, run)
    assert [a["id"] for a in merged["articles"]] == ["a-old", "a-manual", "a-new"]


def test_article_removed_on_the_branch_is_not_resurrected():
    base = batch(story("a-old"), story("a-gone"))
    branch = batch(story("a-old"))
    run = batch(story("a-old"), story("a-gone", image=dict(STOCK)))
    merged, notes = data_merge.merge_batch(base, branch, run)
    assert [a["id"] for a in merged["articles"]] == ["a-old"]
    assert any("a-gone" in note for note in notes)


def test_without_a_common_ancestor_the_branch_copy_wins():
    # A run replaying a file it never had at its base (the 2026-11-24 reverts).
    branch = batch(lock_item(roundup()))
    run = batch(roundup(), story("a-new"))
    merged, _ = data_merge.merge_batch(None, branch, run)
    assert merged["articles"][0] == branch["articles"][0]
    assert merged["articles"][1]["id"] == "a-new"


def test_managed_articles_match_the_writer_gate():
    import write
    for meta in ({"writer": "manual:GPT"}, {"writer": "scheduled:Devin • Fable 5.2"},
                 {"editorialLocked": True}, {"scheduledNews": {"version": 1}},
                 {"writer": "openai:auto"}, {"editorialImageLocked": True}):
        assert data_merge.is_managed(meta) == write._is_editorially_managed(meta)


def test_new_flash_is_prepended_above_branch_edits():
    rows = [{"articleId": f"a-{n}", "zh": str(n)} for n in range(10)]
    branch = copy.deepcopy(rows)
    branch[0]["articleId"] = "a-retargeted"
    run = [{"articleId": "a-new", "zh": "new"}, *rows[:9]]
    merged = data_merge.merge_prepended(rows, branch, run, 10)
    assert [r["articleId"] for r in merged[:2]] == ["a-new", "a-retargeted"]
    assert len(merged) == 10


def test_model_redraft_keeps_the_reviewed_gallery_and_lock():
    import write
    from datetime import datetime, timezone
    url = "https://example.com/ana-order"
    existing = story("a-ana", image=dict(CURATED), images=[dict(CURATED)],
                     editorialImageLocked=True,
                     sources=[{"name": "Example", "url": url}])
    group = {"id": "g", "updateCandidate": True, "primarySource": "Example",
             "items": [{"title": "ANA orders eight more Embraer E190-E2 aircraft",
                        "summary": "ANA expanded the order.", "url": url,
                        "source": "Example", "publishedUtc": "2026-07-29T18:00Z"}]}
    draft = {"cat": "biz", "riskFlags": [],
             "zh": {"title": "全日空擴大E190-E2訂單", "summary": "摘要", "body": ["一"]},
             "en": {"title": "ANA expands its Embraer E190-E2 order",
                    "summary": "Summary", "body": ["One"]}}
    revised = write.build_article(draft, group, datetime(2026, 7, 30, tzinfo=timezone.utc),
                                  set(), writer="test:model", facts=[],
                                  existing_article=existing)
    assert revised["revision"] == 2
    assert revised["image"] == CURATED and revised["images"] == [CURATED]
    assert revised["editorialImageLocked"] is True


# --- the workflow's own git commands ---------------------------------------

def git(cwd, *args, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8")
    assert not check or result.returncode == 0, result.stderr
    return result


def write_json(root, name, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def read_json(root, name):
    return json.loads((root / name).read_text(encoding="utf-8"))


@pytest.fixture
def repos(tmp_path):
    """A branch with one edition; `editor` and `run` both start from its tip."""
    git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", "remote.git")
    editor, run = tmp_path / "editor", tmp_path / "run"
    for clone in (editor, run):
        git(tmp_path, "clone", "-q", "remote.git", clone.name)
        git(clone, "config", "user.name", clone.name)
        git(clone, "config", "user.email", f"{clone.name}@example.com")
    (editor / "pipeline").mkdir()
    for name in ("data_merge.py", "common.py", "roundup_images.py"):
        (editor / "pipeline" / name).write_bytes((ROOT / "pipeline" / name).read_bytes())
    (editor / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    write_json(editor, BATCH, batch(roundup(), story()))
    write_json(editor, "data/flashes.json", [{"articleId": "a-roundup", "zh": "短訊"}])
    write_json(editor, "data/incidents.json", [])
    write_json(editor, "data/usage.json", {"calls": 1})
    git(editor, "add", "-A")
    git(editor, "commit", "-qm", "base")
    git(editor, "push", "-q", "origin", "main")
    git(run, "pull", "-q", "origin", "main")
    return editor, run


def push_edit(editor, payload, name=BATCH):
    write_json(editor, name, payload)
    git(editor, "commit", "-qam", "manual edit")
    git(editor, "push", "-q", "origin", "main")


def commit_and_rebase(run, message="hourly update"):
    """hourly.yml: commit data, replay it on the tip, then run the guard."""
    git(run, "add", "data")
    git(run, "commit", "-qm", message)
    subprocess.run([sys.executable, "pipeline/data_merge.py", "install"], cwd=run, check=True)
    result = git(run, "pull", "--rebase", "-X", "theirs", "origin", "main", check=False)
    if result.returncode:
        git(run, "rebase", "--abort", check=False)
        return result, ""
    guard = subprocess.run([sys.executable, "pipeline/data_merge.py", "guard", "origin/main"],
                           cwd=run, check=True, capture_output=True, text=True)
    return result, guard.stdout


def test_rebase_keeps_a_photo_locked_while_the_run_was_drafting(repos):
    editor, run = repos
    push_edit(editor, batch(lock_item(roundup()), story()))
    payload = read_json(run, BATCH)
    item(payload, "a-boeing").update(image=dict(STOCK), images=[dict(STOCK)])
    item(payload, "a-qantas")["image"] = dict(STOCK)
    payload["articles"].append(story("a-new"))
    write_json(run, BATCH, payload)
    write_json(run, "data/flashes.json", [{"articleId": "a-new", "zh": "新"},
                                          {"articleId": "a-roundup", "zh": "短訊"}])
    result, _ = commit_and_rebase(run)
    assert result.returncode == 0, result.stderr
    merged = read_json(run, BATCH)
    assert item(merged, "a-boeing")["image"] == CURATED
    assert item(merged, "a-boeing")["editorialImageLocked"] is True
    assert item(merged, "a-qantas")["image"] == STOCK
    assert [a["id"] for a in merged["articles"]] == ["a-roundup", "a-story", "a-new"]
    assert git(run, "status", "--porcelain", "--untracked-files=no").stdout == ""
    git(run, "push", "-q", "origin", "HEAD:main")


def test_second_commit_of_the_same_run_replays_cleanly(repos):
    editor, run = repos
    payload = read_json(run, BATCH)
    item(payload, "a-boeing")["image"] = dict(STOCK)
    write_json(run, BATCH, payload)
    assert commit_and_rebase(run)[0].returncode == 0
    push_edit(editor, batch(lock_item(roundup()), story()))      # lands after the build
    payload = read_json(run, BATCH)
    article(payload, "a-story")["en"]["title"] = "Title (TPE)"
    write_json(run, BATCH, payload)
    assert commit_and_rebase(run)[0].returncode == 0
    merged = read_json(run, BATCH)
    assert item(merged, "a-boeing")["image"] == CURATED
    assert article(merged, "a-story")["en"]["title"] == "Title (TPE)"


def test_bot_owned_files_still_resolve_for_the_run(repos):
    editor, run = repos
    push_edit(editor, {"calls": 2}, "data/usage.json")
    write_json(run, "data/usage.json", {"calls": 5})
    assert commit_and_rebase(run)[0].returncode == 0
    assert read_json(run, "data/usage.json") == {"calls": 5}


def test_unparsable_batch_stops_the_rebase_and_leaves_the_branch_alone(repos):
    editor, run = repos
    push_edit(editor, batch(lock_item(roundup()), story()))
    (run / BATCH).write_text('{"articles": [', encoding="utf-8")
    result, _ = commit_and_rebase(run)
    assert result.returncode != 0
    assert read_json(editor, BATCH)["articles"][0]["roundupItems"][1]["image"] == CURATED


def test_guard_restores_a_locked_photo_a_stage_replaced(repos):
    editor, run = repos
    push_edit(editor, batch(lock_item(roundup()), story(editorialImageLocked=True,
                                                         image=dict(CURATED))))
    git(run, "pull", "-q", "origin", "main")       # the run starts after the lock
    payload = read_json(run, BATCH)
    item(payload, "a-boeing").update(image=dict(STOCK), images=[dict(STOCK)])
    item(payload, "a-boeing").pop("editorialImageLocked")
    article(payload, "a-story").update(image=None)
    article(payload, "a-story")["en"]["title"] = "Title (TPE)"
    write_json(run, BATCH, payload)
    _, report = commit_and_rebase(run)
    restored = read_json(run, BATCH)
    assert item(restored, "a-boeing") == item(read_json(editor, BATCH), "a-boeing")
    assert article(restored, "a-story")["image"] == CURATED
    assert article(restored, "a-story")["en"]["title"] == "Title (TPE)"   # text stage kept
    assert report.count("restored the locked image") == 2


def test_guard_restores_lost_articles_and_unreadable_batches(repos):
    editor, run = repos
    payload = read_json(run, BATCH)
    payload["articles"] = [a for a in payload["articles"] if a["id"] != "a-story"]
    write_json(run, BATCH, payload)
    assert any("a-story" in note for note in data_merge.guard("origin/main", root=run))
    assert [a["id"] for a in read_json(run, BATCH)["articles"]] == ["a-roundup", "a-story"]
    (run / BATCH).write_text("<<<<<<< HEAD\n", encoding="utf-8")
    assert any("unreadable" in note for note in data_merge.guard("origin/main", root=run))
    assert read_json(run, BATCH) == read_json(editor, BATCH)


def test_dropped_redraft_takes_its_flash_and_incident_with_it(repos):
    editor, run = repos
    edited = read_json(editor, BATCH)
    article(edited, "a-story")["zh"]["title"] = "人工修正"
    push_edit(editor, edited)
    payload = read_json(run, BATCH)
    article(payload, "a-story").update(zh={"title": "模型改寫", "body": ["新內文"]}, revision=2)
    payload["articles"].append(story("a-new"))
    write_json(run, BATCH, payload)
    old_flash = {"articleId": "a-roundup", "zh": "短訊"}
    write_json(run, "data/flashes.json", [{"articleId": "a-story", "zh": "模型改寫"},
                                          {"articleId": "a-new", "zh": "新"}, old_flash])
    write_json(run, "data/incidents.json", [{"articleId": "a-story", "sev": "inc"}])
    _, report = commit_and_rebase(run)
    assert article(read_json(run, BATCH), "a-story")["zh"]["title"] == "人工修正"
    assert read_json(run, "data/flashes.json") == [{"articleId": "a-new", "zh": "新"}, old_flash]
    assert read_json(run, "data/incidents.json") == []
    assert report.count("announcing a redraft that was not kept") == 2


def test_kept_redraft_keeps_its_flash(repos):
    _, run = repos
    payload = read_json(run, BATCH)
    article(payload, "a-story").update(zh={"title": "模型改寫", "body": ["新內文"]}, revision=2)
    write_json(run, BATCH, payload)
    flashes = [{"articleId": "a-story", "zh": "模型改寫"}, {"articleId": "a-roundup", "zh": "短訊"}]
    write_json(run, "data/flashes.json", flashes)
    _, report = commit_and_rebase(run)
    assert read_json(run, "data/flashes.json") == flashes
    assert "data_merge" not in report


def test_guard_leaves_ordinary_pipeline_changes_alone(repos):
    _, run = repos
    payload = read_json(run, BATCH)
    item(payload, "a-delta")["image"] = dict(STOCK)
    payload["articles"].append(story("a-new"))
    write_json(run, BATCH, payload)
    assert data_merge.guard("origin/main", root=run) == []
    assert read_json(run, BATCH) == payload


# --- wiring ----------------------------------------------------------------

@pytest.mark.parametrize("workflow", ["hourly.yml", "source-recovery.yml"])
def test_every_data_rebase_installs_the_driver_and_runs_the_guard(workflow):
    text = (ROOT / ".github/workflows" / workflow).read_text(encoding="utf-8")
    steps = [step for step in re.split(r"\n      - ", text) if "pull --rebase -X theirs" in step]
    assert steps
    for step in steps:
        rebase = step.index("pull --rebase -X theirs")
        assert "data_merge.py install" in step[:rebase]
        assert "data_merge.py guard" in step[rebase:]


def test_failed_pre_build_rebase_stops_before_the_site_is_built():
    text = (ROOT / ".github/workflows/hourly.yml").read_text(encoding="utf-8")
    step = next(step for step in re.split(r"\n      - ", text)
                if step.startswith("name: Run pipeline"))
    after_rebase = step[step.index("pull --rebase"):step.index("python pipeline/build.py")]
    assert 'if [ -z "$replayed" ]; then' in after_rebase
    assert "exit 1" in after_rebase
    assert "data/briefings" not in after_rebase      # no build from the stale snapshot


def test_gitattributes_routes_published_data_to_the_driver():
    lines = (ROOT / ".gitattributes").read_text(encoding="utf-8").split("\n")
    for pattern in ("data/articles/*.json", "data/flashes.json", "data/incidents.json"):
        assert f"{pattern} merge={data_merge.DRIVER}" in lines
