#!/usr/bin/env bash
# stash_sweep.sh -- read CLONE paths on stdin. A stash entry is a commit on no branch holding
# work that was never committed: invisible to a worktree sweep, invisible to `git status` (the
# files are gone from the tree), and a row in nobody's shard.
#
# Two traps, both of which jharv3 hit and named:
#  1. `git stash list` reads the CLONE-WIDE refs/stash. Counting it per WORKTREE multiplies one
#     stash by however many worktrees share the clone. Count per clone.
#  2. refs/stash points at the TOP entry only. stash@{1}, stash@{2}... exist solely in the stash
#     REFLOG and survive only until it expires. Walk the reflog, not the ref.
# And refuse on a path that is not a repository, rather than counting it as zero.
set -uo pipefail
LIVE="${LIVE:?}"; PULLS="${PULLS:?}"
[ -s "$LIVE" ] && [ -s "$PULLS" ] || { echo "REFUSING: empty authority" >&2; exit 2; }
while read -r c; do
  [ -n "$c" ] || continue
  if ! git -C "$c" rev-parse --git-dir >/dev/null 2>&1; then printf '%s\tNOT_A_REPO\t-\t-\t-\n' "$c"; continue; fi
  n=0
  while read -r sha; do
    [ -n "$sha" ] || continue
    n=$((n+1))
    mb=$(git -C "$c" merge-base "$sha" origin/main 2>/dev/null) || continue
    d=0; t=0
    while read -r f; do
      [ -n "$f" ] || continue
      a=$(git -C "$c" show "$sha:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      b=$(git -C "$c" show "origin/main:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      t=$((t+1)); [ "$a" = "$b" ] || d=$((d+1))
    done < <(git -C "$c" diff --name-only "$mb" "$sha" 2>/dev/null)
    held=""
    grep -qxF "$sha" "$PULLS" && held="PR_REF"
    if [ -z "$held" ]; then
      while read -r r; do [ "$r" = "origin/HEAD" ] && continue; grep -qxF "${r#origin/}" "$LIVE" && { held="$r"; break; }; done < <(git -C "$c" for-each-ref --format='%(refname:short)' --contains "$sha" refs/remotes/origin 2>/dev/null)
    fi
    printf '%s\t%s\t%s\towned=%s\tdiffer=%s\theld=%s\n' "$c" "stash@{$((n-1))}" "$sha" "$t" "$d" "${held:-NOTHING}"
  done < <(git -C "$c" reflog --format='%H' refs/stash 2>/dev/null)
  [ "$n" -eq 0 ] && printf '%s\tno-stash\t-\t-\t-\t-\n' "$c"
done
