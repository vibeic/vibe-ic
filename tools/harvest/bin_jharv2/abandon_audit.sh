#!/usr/bin/env bash
# abandon_audit.sh -- jharv3's point applied to my extras: LANDED and ABANDON are claims about a
# DIRECTORY. Tree identity, merge-base, reverse-apply and per-file sha256 of owned files all
# describe COMMITTED history only. None of them can see an uncommitted edit or an untracked file,
# and that is exactly the content that exists in one place.
# Reads `path<TAB>repo`. Reports the working tree with --untracked-files=ALL -- never `normal`,
# which collapses an untracked DIRECTORY to one entry and lets the [ -f ] test below drop it, so a
# worktree whose only uncommitted content lives in a directory reports new=0 and is certified CLEAN.
# CLEAN on an ABANDON row authorises deletion. See test_abandon_audit_untracked_collapse.sh.
set -uo pipefail
while IFS=$'\t' read -r wt repo; do
  [ -d "$wt" ] || { printf '%s\tGONE\t-\t-\n' "$wt"; continue; }
  n=0; diff=0; new=0; ex=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    n=$((n+1)); xy=${line:0:2}; f=${line:3}
    case "$f" in *' -> '*) f=${f##* -> };; esac; f=${f%\"}; f=${f#\"}
    case "$xy" in 'D '|' D'|'DD') continue;; esac
    [ -f "$wt/$f" ] || continue
    a=$(git -C "$repo" hash-object -- "$wt/$f" 2>/dev/null) || continue
    b=$(git -C "$repo" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
    if [ -z "$b" ]; then new=$((new+1)); [ -z "$ex" ] && ex="NEW:$f"
    elif [ "$a" != "$b" ]; then diff=$((diff+1)); [ -z "$ex" ] && ex="MOD:$f"; fi
  done < <(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null)
  st=CLEAN; [ $((diff+new)) -gt 0 ] && st='**DIRTY_WITH_CONTENT_NOT_ON_MAIN**'
  printf '%s\t%s\tstatus_lines=%s modified=%s new=%s\t%s\n' "$wt" "$st" "$n" "$diff" "$new" "$ex"
done
