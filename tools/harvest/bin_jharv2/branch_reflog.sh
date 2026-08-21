#!/usr/bin/env bash
# branch_reflog.sh -- read CLONE paths. Both of us swept per-worktree logs/HEAD. The CLONE also
# keeps logs/refs/heads/<branch>: every rebase, amend, reset and force-update leaves the old tip
# there, unreachable the instant the branch moves, and expiring at the reflog default.
# jharv3's find. Counted per CLONE, never per worktree.
#
# Honest framing, theirs and kept here: most of these are INTERMEDIATE states of work that later
# landed — a branch rebased twenty times leaves twenty old tips, each "differing from main", all
# superseded. This counts what is at risk; it does not claim each holds unique work.
set -uo pipefail
LIVE="${LIVE:?}"; PULLS="${PULLS:?}"
[ -s "$LIVE" ] && [ -s "$PULLS" ] || { echo "REFUSING: empty authority" >&2; exit 2; }
while read -r c; do
  [ -n "$c" ] || continue
  git -C "$c" rev-parse --git-dir >/dev/null 2>&1 || { printf '%s\tNOT_A_REPO\n' "$c"; continue; }
  gd=$(git -C "$c" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || continue
  [ -d "$gd/logs/refs/heads" ] || { printf '%s\tno-branch-reflogs\n' "$c"; continue; }
  tot=0; risk=0
  while read -r sha; do
    [ -n "$sha" ] || continue
    tot=$((tot+1))
    git -C "$c" for-each-ref --contains "$sha" --count=1 --format='x' refs/heads refs/tags refs/remotes 2>/dev/null | grep -q x && continue
    grep -qxF "$sha" "$PULLS" && continue
    hit=""
    while read -r r; do [ "$r" = "origin/HEAD" ] && continue; grep -qxF "${r#origin/}" "$LIVE" && { hit=1; break; }; done < <(git -C "$c" for-each-ref --format='%(refname:short)' --contains "$sha" refs/remotes/origin 2>/dev/null)
    [ -n "$hit" ] && continue
    risk=$((risk+1)); printf '%s\t%s\n' "$c" "$sha"
  done < <(find "$gd/logs/refs/heads" -type f -print0 2>/dev/null | xargs -0 -r awk '{print $2}' 2>/dev/null | sort -u)
  printf '#%s\tscanned=%s\tat_risk=%s\n' "$c" "$tot" "$risk" >&2
done
