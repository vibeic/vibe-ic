#!/usr/bin/env bash
# prior_sweep.sh -- read `path<TAB>repo<TAB>head` and report every PRIOR head in the worktree's
# reflog that owns files differing from main and is held by no live origin ref and no PR ref.
#
# jharv3's correction: I ran this only over LANDED rows, because that is where the example came
# from. The reasoning has nothing to do with the verdict — ANY worktree whose head moved leaves
# its previous head behind, and a RECOVER row displaces work just as readily. Scoping a general
# check to the population the example came from is the population being chosen by where I was
# looking rather than by what the check is about.
set -uo pipefail
LIVE="${LIVE:?}"; PULLS="${PULLS:?}"
[ -s "$LIVE" ]  || { echo "REFUSING: empty live authority" >&2; exit 2; }
[ -s "$PULLS" ] || { echo "REFUSING: empty pull authority" >&2; exit 2; }
while IFS=$'\t' read -r p repo head; do
  [ -d "$p" ] && [ -d "$repo" ] || continue
  while read -r ph; do
    [ -n "$ph" ] || continue
    [ "$ph" = "$head" ] && continue
    git -C "$repo" rev-parse -q --verify "$ph^{commit}" >/dev/null 2>&1 || continue
    grep -qxF "$ph" "$PULLS" && continue
    hit=""
    while read -r c; do
      [ "$c" = "origin/HEAD" ] && continue
      grep -qxF "${c#origin/}" "$LIVE" && { hit="$c"; break; }
    done < <(git -C "$repo" for-each-ref --format='%(refname:short)' --contains "$ph" refs/remotes/origin 2>/dev/null)
    [ -n "$hit" ] && continue
    pmb=$(git -C "$repo" merge-base "$ph" origin/main 2>/dev/null) || continue
    n=0; d=0
    while read -r f; do
      [ -n "$f" ] || continue
      a=$(git -C "$repo" show "$ph:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      b=$(git -C "$repo" show "origin/main:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
      n=$((n+1)); [ "$a" = "$b" ] || d=$((d+1))
    done < <(git -C "$repo" diff --name-only "$pmb" "$ph" 2>/dev/null)
    [ "$d" -gt 0 ] && printf '%s\t%s\t%s\towned=%s\tdiffer=%s\n' "$p" "$repo" "$ph" "$n" "$d"
  done < <(env -u GIT_INDEX_FILE git -C "$p" reflog --format='%H' 2>/dev/null | sort -u | head -12)
done
