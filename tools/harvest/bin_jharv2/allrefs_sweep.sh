#!/usr/bin/env bash
# allrefs_sweep.sh -- read CLONE paths. The superset of everything swept so far.
#
# The sweeps to date each took one route: worktree HEADs, worktree reflogs, branch reflogs,
# stashes, pruned files. Each was found by someone noticing a route the other had not taken.
# This asks the general question instead: is there ANY ref in this clone -- branch, tag, note,
# any namespace -- whose commit origin does not have? Plus the in-progress states that hold
# commits on no ref at all: an interrupted rebase, a half-finished cherry-pick or merge.
set -uo pipefail
LIVE="${LIVE:?}"; PULLS="${PULLS:?}"
[ -s "$LIVE" ] && [ -s "$PULLS" ] || { echo "REFUSING: empty authority" >&2; exit 2; }
while read -r c; do
  [ -n "$c" ] || continue
  git -C "$c" rev-parse --git-dir >/dev/null 2>&1 || continue
  gd=$(git -C "$c" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || continue
  # every local ref, excluding remote-tracking (which is a cache of origin, not content of ours)
  while read -r name sha; do
    [ -n "$sha" ] || continue
    case "$name" in refs/remotes/*) continue;; esac
    grep -qxF "$sha" "$PULLS" && continue
    hit=""
    while read -r r; do [ "$r" = "origin/HEAD" ] && continue; grep -qxF "${r#origin/}" "$LIVE" && { hit=1; break; }; done < <(git -C "$c" for-each-ref --format='%(refname:short)' --contains "$sha" refs/remotes/origin 2>/dev/null)
    [ -n "$hit" ] && continue
    printf 'REF\t%s\t%s\t%s\n' "$c" "$name" "$sha"
  done < <(git -C "$c" for-each-ref --format='%(refname) %(objectname)' 2>/dev/null)
  # in-progress operations: commits that exist and are on no ref by construction
  for d in rebase-merge rebase-apply; do
    [ -d "$gd/$d" ] || continue
    for f in orig-head head onto; do
      [ -f "$gd/$d/$f" ] || continue
      s=$(tr -d ' \n' < "$gd/$d/$f" 2>/dev/null)
      case "$s" in [0-9a-f]*) git -C "$c" rev-parse -q --verify "$s^{commit}" >/dev/null 2>&1 && printf 'INPROGRESS\t%s\t%s/%s\t%s\n' "$c" "$d" "$f" "$s";; esac
    done
  done
  for f in MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD BISECT_EXPECTED_REV; do
    [ -f "$gd/$f" ] || continue
    s=$(tr -d ' \n' < "$gd/$f" 2>/dev/null)
    case "$s" in [0-9a-f]*) git -C "$c" rev-parse -q --verify "$s^{commit}" >/dev/null 2>&1 && printf 'INPROGRESS\t%s\t%s\t%s\n' "$c" "$f" "$s";; esac
  done
done
