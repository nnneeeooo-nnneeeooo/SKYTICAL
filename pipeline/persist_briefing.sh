#!/usr/bin/env bash
# Persist only briefing state while keeping other pipeline data untouched.
set -euo pipefail

edition="${1:-unknown}"
git config user.name "skytical-bot"
git config user.email "bot@users.noreply.github.com"
git add -- data/briefings
if [ -f data/usage.json ]; then
  git add -- data/usage.json
fi
if git diff --cached --quiet; then
  echo "no changes to commit; current main already contains the state"
  echo "persisted=true" >> "$GITHUB_OUTPUT"
  exit 0
fi

git commit -m "briefing ${edition} $(date -u +%FT%H:%M)"
# The paid-budget sync and other generators may change tracked files outside
# this commit. Report the paths, but never discard or accidentally push them.
git status --short --untracked-files=no

# Rebase and push from a clean, isolated worktree. A rebase in the runner's
# working directory would fail on those unrelated unstaged changes.
worktree="$(mktemp -d)"
cleanup() {
  git worktree remove --force "$worktree" 2>/dev/null || true
  rmdir "$worktree" 2>/dev/null || true
}
trap cleanup EXIT
git worktree add --quiet --detach "$worktree" HEAD

pushed=""
for attempt in 1 2 3; do
  if ! git -C "$worktree" fetch origin main; then
    echo "fetch failed on attempt $attempt"
  elif ! git -C "$worktree" rebase -X theirs origin/main; then
    git -C "$worktree" rebase --abort || true
    echo "rebase failed on attempt $attempt"
  elif git -C "$worktree" push origin HEAD:main; then
    pushed=yes
    break
  else
    echo "push failed on attempt $attempt"
  fi
  if [ "$attempt" -lt 3 ]; then
    sleep "${BRIEFING_PERSIST_RETRY_DELAY:-5}"
  fi
done
if [ -z "$pushed" ]; then
  echo "::error::briefing data could not be persisted after 3 attempts"
  exit 1
fi
echo "persisted=true" >> "$GITHUB_OUTPUT"
