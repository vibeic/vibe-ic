#!/usr/bin/env bash
# Enumerate every distinct git common-dir (clone) among the checkouts under $HOME.
# One clone may own many worktrees; we must fetch once per CLONE, not per worktree.
set -uo pipefail
for d in "$HOME"/*/ ; do
  [ -e "$d/.git" ] || continue
  git -C "$d" rev-parse --path-format=absolute --git-common-dir 2>/dev/null
done | sort -u
