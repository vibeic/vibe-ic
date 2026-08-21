#!/usr/bin/env bash
# reach.sh -- read `path<TAB>repo<TAB>head` and answer the question an EXECUTOR actually has:
# if this directory is deleted, is the work still there?
#
# Removing a worktree directory does NOT remove its commits. If the head is reachable from any
# ref in the clone, deleting the directory reclaims disk and loses nothing -- `git checkout` it
# back. If it is reachable from NO ref, the worktree's own HEAD is the only thing holding it and
# deleting the directory makes it garbage: recoverable from the reflog for a while, then gone.
# That is the difference between "reclaim disk" and "lose work", and it is not the same question
# as RECOVER-vs-LANDED.
set -uo pipefail
while IFS=$'\t' read -r p repo head; do
  [ -n "$head" ] && [ -d "$repo" ] || { printf '%s\tUNKNOWN\t-\n' "$p"; continue; }
  git -C "$repo" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1 || { printf '%s\tCOMMIT_ABSENT\t-\n' "$p"; continue; }
  at=$(git -C "$repo" for-each-ref --format='%(refname:short)' --points-at "$head" --count=1 2>/dev/null)
  if [ -n "$at" ]; then printf '%s\tON_REF\t%s\n' "$p" "$at"; continue; fi
  con=$(git -C "$repo" for-each-ref --format='%(refname:short)' --contains "$head" --count=1 2>/dev/null)
  if [ -n "$con" ]; then printf '%s\tREACHABLE_FROM\t%s\n' "$p" "$con"; continue; fi
  printf '%s\tUNREFERENCED\t-\n' "$p"
done
