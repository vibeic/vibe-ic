#!/usr/bin/env bash
# classify.sh -- for each checkout path on stdin, say which clone owns it and which repo it is.
# `git worktree list` only reports REGISTERED worktrees; a checkout whose registration was
# pruned, or which is its own clone, is invisible to it and was missed by the first pass.
set -uo pipefail
while read -r p; do
  cd "$p" 2>/dev/null || { printf '%s\tUNREADABLE\t-\t-\n' "$p"; continue; }
  cdir=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || { printf '%s\tNOT_A_REPO\t-\t-\n' "$p"; continue; }
  url=$(git config --get remote.origin.url 2>/dev/null)
  head=$(git rev-parse -q --verify HEAD 2>/dev/null)
  reg=no
  # registered with its owning clone?
  if git -C "$cdir" worktree list --porcelain 2>/dev/null | grep -qxF "worktree $p"; then reg=yes; fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$p" "$cdir" "${url:-(no origin)}" "${head:0:9}" "registered=$reg"
done
