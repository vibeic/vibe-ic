#!/usr/bin/env bash
# landed_form.sh -- read `path<TAB>repo<TAB>head` and say WHICH KIND of LANDED this is, plus
# what the worktree held BEFORE.
#
# jharv3's generalisation of the _landppa case: "head == main" is too narrow. Any head that is an
# ANCESTOR of main collapses `own` to empty, so every content check passes trivially. The row is
# then TRUE and uninformative, and — the part that matters — the work the directory used to hold
# has quietly become somebody else's problem.
#
#   STRONG   it owns files and every one is byte-identical to main. Says something.
#   EMPTY    it owns nothing because its head is already contained in main. Says nothing about
#            what was there before, so the reflog is asked.
# For every distinct PRIOR head in the worktree's reflog: how many files it owned differ from
# main, and whether any live origin ref contains it. A prior head owning differing files and on
# no ref is unpreserved work sitting behind a LANDED row.
set -uo pipefail
LIVE="${LIVE:?set LIVE to a file of live origin branch names}"
while IFS=$'\t' read -r p repo head; do
  [ -n "$head" ] && [ -d "$repo" ] || { printf '%s\tNO_INPUT\t-\t-\n' "$p"; continue; }
  git -C "$repo" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1 || { printf '%s\tHEAD_ABSENT\t-\t-\n' "$p"; continue; }
  mb=$(git -C "$repo" merge-base "$head" origin/main 2>/dev/null)
  nown=$(git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null | grep -c '')
  if [ "$nown" -gt 0 ]; then form=STRONG_owns_$nown; else
    if [ "$(git -C "$repo" rev-parse "$head")" = "$(git -C "$repo" rev-parse origin/main)" ]; then form=EMPTY_head_IS_main
    else form=EMPTY_head_ancestor_of_main; fi
  fi
  prior=""
  if [ -d "$p" ]; then
    while read -r ph; do
      [ -n "$ph" ] || continue
      [ "$ph" = "$head" ] && continue
      git -C "$repo" rev-parse -q --verify "$ph^{commit}" >/dev/null 2>&1 || continue
      pmb=$(git -C "$repo" merge-base "$ph" origin/main 2>/dev/null)
      d=0; n=0
      while read -r f; do
        [ -n "$f" ] || continue
        a=$(git -C "$repo" show "$ph:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
        b=$(git -C "$repo" show "origin/main:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
        n=$((n+1)); [ "$a" = "$b" ] || d=$((d+1))
      done < <(git -C "$repo" diff --name-only "$pmb" "$ph" 2>/dev/null)
      ref=$(git -C "$repo" for-each-ref --format='%(refname:short)' --contains "$ph" refs/remotes/origin 2>/dev/null \
              | grep -v '^origin/HEAD$' | while read -r c; do grep -qxF "${c#origin/}" "$LIVE" && { echo "$c"; break; }; done)
      if [ "$d" -gt 0 ] && [ -z "$ref" ]; then tag='**ORPHANED_WORK**'; elif [ "$d" -gt 0 ]; then tag="differs_but_on:$ref"; else tag="all_${n}_match_main"; fi
      prior="${prior}${prior:+; }${ph:0:11}(owned=$n differ=$d $tag)"
    done < <(env -u GIT_INDEX_FILE git -C "$p" reflog --format='%H' 2>/dev/null | sort -u | head -8)
  fi
  printf '%s\t%s\t%s\t%s\n' "$p" "$form" "${nown}" "${prior:-no-prior-heads-recorded}"
done
