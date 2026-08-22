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
# COMMITTED content is judged by REVERSE-APPLYING the branch's own diff (merge-base..head) onto
# main, NOT by comparing blobs. "differs from origin/main" is not "holds work not in main": a
# worktree whose change is already contained in main still differs from it on every file main has
# touched since, because it holds an OLDER copy of what main already has. Measured: a blob compare
# refused all 29 of my ABANDON rows; reverse-apply showed all 29 CONTAINED_IN_MAIN and the two real
# losses still NOT_CONTAINED. A guard that refuses everything protects nothing.
#
# LIMITATION, measured 2026-08-22: reverse-apply against the CURRENT main reports not_contained for
# a change that DID land and whose files main modified afterwards -- the hunk no longer applies even
# though nothing is missing. Three rows read "not contained" against live main and CONTAINED against
# the main they were judged at, one of them with 678 files. When a row cites a judged main, test
# BOTH before believing a refusal. A refusal is still the safe direction; it is not proof of loss.
#
# SECOND LIMITATION, measured 2026-08-22: this compares against main's TIP. A squash-merge lands
# content and main then moves on, so the tip no longer matches while nothing is missing. A peer
# flipped 12 rows to LANDED on exactly that basis and was right: every differing file's blob is in
# main's HISTORY at the same path. When this refuses, check history before believing loss --
# `git log --full-history <ref> -- <path>` and compare blobs, WITHOUT a head limit: a 200-commit cap
# missed one at commit 204 of 226 and would have reported a correct verdict as unlanded work.
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
  nfiles=$(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null | grep -c '')
  n=0; ex=""
  if [ "$nfiles" -gt 0 ]; then
    idx=$(mktemp); rm -f "$idx"
    if ! GIT_INDEX_FILE="$idx" git -C "$repo" read-tree origin/main 2>/dev/null; then
      printf 'REFUSE\t%s\tcannot build a main index to test containment\n' "$wt"; refused=$((refused+1)); rc=1; rm -f "$idx"; continue
    fi
    if git -C "$repo" diff --binary "$mb" "$head" 2>/dev/null | GIT_INDEX_FILE="$idx" git -C "$repo" apply -R --cached --check - 2>/dev/null; then
      n=0
    else
      n=$nfiles; ex=$(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null | head -1)
    fi
    rm -f "$idx"
  fi
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
    printf 'REFUSE\t%s\tnot_contained_in_main=%s uncommitted_differing=%s first=%s\n' "$wt" "$n" "$m" "${ex:-$dex}"; refused=$((refused+1)); rc=1
  else
    printf 'ALLOW\t%s\tchange_contained_in_main uncommitted_differing=0 vs %s\n' "$wt" "$EXPECT"; ok=$((ok+1))
  fi
done
printf '# allow=%s refuse=%s\n' "$ok" "$refused"
exit $rc
