#!/usr/bin/env bash
# reach2.sh -- three-way survivability, jharv3's vocabulary, adopted so a/b/c mean the same
# thing by the same word.
#
#   ON_REMOTE          reachable from a REMOTE-tracking ref. The commit is on the server;
#                      the directory, the clone and the machine can all go.
#   ON_LOCAL_REF_ONLY  on a local branch or tag but on NO remote. Survives only as long as
#                      THIS CLONE does -- and 14 whole clones were deleted during the first
#                      triage run, so that is a measured risk, not a hypothetical.
#   UNREFERENCED       on no ref at all. The worktree's own HEAD is the only pointer;
#                      deleting the directory makes the commit garbage.
#
# My earlier version collapsed the first two into "safe to delete", which is true of ON_REMOTE
# and misleading for ON_LOCAL_REF_ONLY.
set -uo pipefail
while IFS=$'\t' read -r p repo head; do
  [ -n "$head" ] && [ -d "$repo" ] || { printf '%s\tUNKNOWN\t-\n' "$p"; continue; }
  git -C "$repo" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1 || { printf '%s\tCOMMIT_ABSENT\t-\n' "$p"; continue; }
  r=$(git -C "$repo" for-each-ref --format='%(refname:short)' --contains "$head" --count=1 refs/remotes 2>/dev/null)
  [ -z "$r" ] && r=$(git -C "$repo" for-each-ref --format='%(refname:short)' --points-at "$head" --count=1 refs/remotes 2>/dev/null)
  if [ -n "$r" ]; then printf '%s\tON_REMOTE\t%s\n' "$p" "$r"; continue; fi
  l=$(git -C "$repo" for-each-ref --format='%(refname:short)' --contains "$head" --count=1 refs/heads refs/tags 2>/dev/null)
  [ -z "$l" ] && l=$(git -C "$repo" for-each-ref --format='%(refname:short)' --points-at "$head" --count=1 refs/heads refs/tags 2>/dev/null)
  if [ -n "$l" ]; then printf '%s\tON_LOCAL_REF_ONLY\t%s\n' "$p" "$l"; continue; fi
  printf '%s\tUNREFERENCED\t-\n' "$p"
done
