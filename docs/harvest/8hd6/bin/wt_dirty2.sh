#!/usr/bin/env bash
# wt_dirty2.sh <repo> -- split uncommitted state into REAL edits vs an EMPTIED tree.
# TSV: path  n_mod  n_del  n_untracked  n_files_on_disk
# A worktree whose status is entirely `D` has had its files removed from disk; the
# registration and index survive but there is nothing in it to recover. Counting
# those deletions as "uncommitted edits" put empty shells at the TOP of RECOVER.
set -uo pipefail
cd "${1:?}" || exit 1
git worktree list --porcelain | awk '/^worktree /{print substr($0,10)}' | while read -r wt; do
  [ -d "$wt" ] || { printf '%s\t-\t-\t-\t-\n' "$wt"; continue; }
  s=$(git -C "$wt" status --porcelain -uno 2>/dev/null)
  m=$(printf '%s\n' "$s" | grep -c '^[MARC?]' || true)
  d=$(printf '%s\n' "$s" | grep -c '^.\?D' || true)
  u=$(git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??' || true)
  n=$(find "$wt" -maxdepth 2 -type f -not -path '*/.git/*' 2>/dev/null | head -200 | grep -c '' || true)
  printf '%s\t%s\t%s\t%s\t%s\n' "$wt" "${m:-0}" "${d:-0}" "${u:-0}" "${n:-0}"
done
