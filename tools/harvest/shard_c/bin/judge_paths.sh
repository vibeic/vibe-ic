#!/usr/bin/env bash
# judge_paths.sh -- same content rule as judge.sh, but driven by an explicit list of
# checkout paths on stdin instead of `git worktree list`.
#
# Needed because `git worktree list` reports only REGISTERED worktrees. A checkout whose
# registration was pruned still holds its commits and its files; it is simply invisible to
# the enumeration the first pass trusted. Nine such checkouts were found on this host.
# Emits the same 16 columns as judge.sh so the downstream stages are unchanged.
set -uo pipefail
isnoise(){ case "$1" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;; esac; return 1; }
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
lastrepo=""
while read -r wt; do
  cdir=$(git -C "$wt" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || continue
  repo=${cdir%/.git}
  if [ "$repo" != "$lastrepo" ]; then
    export GIT_INDEX_FILE="$T/idx"; rm -f "$T/idx"
    git -C "$repo" read-tree origin/main 2>/dev/null || { echo "READTREE_FAIL $repo" >&2; continue; }
    lastrepo=$repo
  fi
  head=$(env -u GIT_INDEX_FILE git -C "$wt" rev-parse -q --verify HEAD 2>/dev/null)
  br=$(env -u GIT_INDEX_FILE git -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null || echo '(detached)')
  [ -d "$wt" ] && wtdir=present || wtdir=REMOVED
  if [ -z "$head" ]; then
    printf '%s\t%s\t%s\t-\tUNDETERMINED_NO_HEAD\t0\t0\t0\t0\t0\t0\t0\t-\t-\t-\t%s|-|-|\n' "$repo" "$wt" "$br" "$wtdir"; continue
  fi
  subj=$(git -C "$repo" log -1 --format='%s' "$head" 2>/dev/null | tr '\t\n|' '   ' | cut -c1-150)
  cdate=$(git -C "$repo" log -1 --format='%cs' "$head" 2>/dev/null)
  mb=$(git -C "$repo" merge-base "$head" origin/main 2>/dev/null)
  if [ -z "$mb" ]; then
    printf '%s\t%s\t%s\t%s\tUNDETERMINED_NO_MERGEBASE\t0\t0\t0\t0\t0\t0\t0\t-\t-\t%s\t%s|-|%s|\n' "$repo" "$wt" "$br" "$head" "$subj" "$wtdir" "$cdate"; continue
  fi
  git -C "$repo" diff --name-only "$mb" "$head" 2>/dev/null | sort > "$T/own"
  git -C "$repo" diff --name-only origin/main "$head" 2>/dev/null | sort > "$T/vsmain"
  awk 'NR==FNR{a[$0]=1;next} ($0 in a)' "$T/own" "$T/vsmain" > "$T/differ"   # not comm: comm warns and still emits a wrong result on a collation mismatch
  nown=$(grep -c '' < "$T/own"); ndiff=$(grep -c '' < "$T/differ")
  nnovel=0; nnoise=0; nsuper=0; novel_list=""; super_list=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    isnoise "$f" && { nnoise=$((nnoise+1)); continue; }
    git -C "$repo" diff "$mb" "$head" -- "$f" > "$T/f" 2>/dev/null
    if [ -s "$T/f" ] && git -C "$repo" apply --cached --check -R "$T/f" 2>/dev/null; then
      nsuper=$((nsuper+1)); [ ${#super_list} -lt 300 ] && super_list="${super_list}${super_list:+,}${f}"
    else
      nnovel=$((nnovel+1)); [ ${#novel_list} -lt 300 ] && novel_list="${novel_list}${novel_list:+,}${f}"
    fi
  done < "$T/differ"
  if [ "$wtdir" = present ]; then
    trk=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '')
    unt=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??')
    dirty=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | head -4 | cut -c1-60 | tr '\n' ';')
  else trk=0; unt=0; dirty=""; fi
  if   [ "$ndiff" -eq 0 ];                         then st=DROP_ALL_FILES_MATCH
  elif [ "$nnovel" -eq 0 ] && [ "$nsuper" -eq 0 ]; then st=DROP_VERSION_NOISE_ONLY
  elif [ "$nnovel" -eq 0 ];                        then st=KEEP_SUPERSEDED_CONTENT_DIFFERS
  else                                                  st=KEEP_NOVEL_CONTENT; fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$repo" "$wt" "$br" "$head" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$nnoise" \
    "${trk:-0}" "${unt:-0}" "$novel_list" "$super_list" "$subj" "$wtdir|-|$cdate|${dirty}"
done
