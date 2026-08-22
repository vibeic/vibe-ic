#!/usr/bin/env bash
# predelete_guard.sh -- the last check before a worktree is deleted. Reads `path` lines, and for
# each one re-measures CONTENT against origin/main on the machine actually holding it.
#
# Exit 0 only if every path was measured AND holds nothing that differs from main.
#
# FAILS CLOSED. A path that cannot be measured -- absent, unreadable, no HEAD, or in a clone whose
# origin/main is not the ref you are judging against -- REFUSES. An unmeasured worktree and a clean
# one are otherwise byte-identical in the output, and that equivalence is how content gets deleted.
#
# Pass the expected origin/main as $1. The guard refuses if the clone disagrees, because a stale or
# divergent origin/main manufactures a false LANDED: content that matches an OLD main and differs
# from the current one reads as "already landed" and is deleted. Measured on .112, whose clone held
# a divergent d3f261f734b -- not an ancestor of live main -- while two rows were judged against it.
set -uo pipefail
EXPECT=${1:-}
[ -n "$EXPECT" ] || { echo "usage: predelete_guard.sh <expected-origin-main-sha> < paths"; exit 2; }
rc=0; ok=0; refused=0
while IFS= read -r wt; do
  [ -n "$wt" ] || continue
  if [ ! -d "$wt" ]; then printf 'REFUSE\t%s\tnot present on this host -- unmeasured, not clean\n' "$wt"; refused=$((refused+1)); rc=1; continue; fi
  repo=$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || repo=""
  [ -n "$repo" ] || { printf 'REFUSE\t%s\tno git dir\n' "$wt"; refused=$((refused+1)); rc=1; continue; }
  om=$(git -C "$repo" rev-parse -q --verify origin/main 2>/dev/null)
  if [ "${om:0:${#EXPECT}}" != "$EXPECT" ]; then
    printf 'REFUSE\t%s\tclone origin/main=%s expected=%s -- a stale or divergent ref manufactures a false LANDED\n' "$wt" "${om:0:11}" "$EXPECT"; refused=$((refused+1)); rc=1; continue
  fi
  head=$(git -C "$wt" rev-parse -q --verify HEAD 2>/dev/null)
  [ -n "$head" ] || { printf 'REFUSE\t%s\tno HEAD (pruned registration) -- cannot scope owned files\n' "$wt"; refused=$((refused+1)); rc=1; continue; }
  mb=$(git -C "$repo" merge-base "$head" origin/main 2>/dev/null)
  [ -n "$mb" ] || { printf 'REFUSE\t%s\tno merge-base with origin/main\n' "$wt"; refused=$((refused+1)); rc=1; continue; }
  n=0; ex=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    a=$(git -C "$repo" rev-parse -q --verify "$head:$f" 2>/dev/null)
    b=$(git -C "$repo" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
    [ "$a" = "$b" ] && continue
    n=$((n+1)); [ -z "$ex" ] && ex="$f"
  done < <(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null)
  m=0; dex=""
  # --untracked-files=all, never `normal`: `normal` collapses an untracked DIRECTORY to one entry
  # and the [ -f ] test below drops it, so a worktree whose only content is in a directory reads 0.
  while IFS= read -r line; do
    [ -n "$line" ] || continue; xy=${line:0:2}; f=${line:3}
    case "$f" in *' -> '*) f=${f##* -> };; esac; f=${f%\"}; f=${f#\"}
    case "$xy" in 'D '|' D'|'DD') continue;; esac
    [ -f "$wt/$f" ] || continue
    a=$(git -C "$repo" hash-object -- "$wt/$f" 2>/dev/null) || continue
    b=$(git -C "$repo" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
    [ "$a" = "$b" ] && continue
    m=$((m+1)); [ -z "$dex" ] && dex="$f"
  done < <(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null)
  if [ $((n+m)) -gt 0 ]; then
    printf 'REFUSE\t%s\tcommitted_differing=%s uncommitted_differing=%s first=%s\n' "$wt" "$n" "$m" "${ex:-$dex}"; refused=$((refused+1)); rc=1
  else
    printf 'ALLOW\t%s\tcommitted_differing=0 uncommitted_differing=0 vs %s\n' "$wt" "$EXPECT"; ok=$((ok+1))
  fi
done
printf '# allow=%s refuse=%s\n' "$ok" "$refused"
exit $rc
