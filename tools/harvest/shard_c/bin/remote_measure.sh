#!/usr/bin/env bash
# remote_measure.sh -- run ON a fleet host. Reads worktree paths on stdin after a line
# containing only "---PATHS---", measures each by CONTENT against current origin/main, and
# prints one TSV row per path. Ships over `ssh .102 ssh <host> bash -s < this`.
#
# Measures only. The verdict ladder is applied back home where `gh` is authenticated, so a
# merge tip can be resolved against real PR state instead of guessed at.
#
# READ-ONLY: fetch is the only write, once per CLONE, and it writes only the tracking ref.
# No checkout, no worktree created, no prune, nothing deleted.
set -uo pipefail
OUT_SEP='---MEASUREMENTS---'
# Paths arrive as ARGUMENTS, not on stdin: this script is itself delivered on stdin to
# `bash -s`, so stdin is already spoken for. Invoke as: bash -s -- <path> <path> ...
paths=$(printf '%s\n' "$@")
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
: > "$T/fetched"

resolve_clone(){ git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null | sed 's#/\.git$##'; }

fetch_once(){ # $1 = clone dir. Once per clone, and VERIFY the ref actually moved.
  grep -qxF "$1" "$T/fetched" && return 0
  printf '%s\n' "$1" >> "$T/fetched"
  url=$(git -C "$1" config --get remote.origin.url 2>/dev/null)
  before=$(git -C "$1" rev-parse -q --verify origin/main 2>/dev/null)
  # Check the URL BEFORE fetching. If origin is a LOCAL PATH, `fetch origin main` pulls that
  # path's local BRANCH main -- which can be far behind -- and SILENTLY REWRITES a correct
  # origin/main BACKWARDS, exiting 0. On .121 that moved four clones from a00f53f2094 back
  # to f6db3e921e6. Never fetch from a local origin; go to the real remote instead.
  case "$url" in
    http*|git@*) git -C "$1" fetch origin '+refs/heads/main:refs/remotes/origin/main' >/dev/null 2>&1 ;;
    *)           git -C "$1" fetch https://github.com/vibeic/vibe-ic.git '+refs/heads/main:refs/remotes/origin/main' >/dev/null 2>&1 ;;
  esac
  sha=$(git -C "$1" rev-parse -q --verify origin/main 2>/dev/null)
  # A fetch that moved the ref BACKWARDS is worse than no fetch. Say so loudly.
  if [ -n "$before" ] && [ "$before" != "$sha" ] && git -C "$1" merge-base --is-ancestor "$sha" "$before" 2>/dev/null; then
    printf 'CLONE\t%s\t%s\t%s\tWENT_BACKWARDS_from_%s\n' "$1" "${url:-none}" "${sha:-NOMAIN}" "$before"
  else
    printf 'CLONE\t%s\t%s\t%s\n' "$1" "${url:-none}" "${sha:-NOMAIN}"
  fi
}

echo "$OUT_SEP"
printf 'HOST\t%s\n' "$(hostname)"
while IFS= read -r wt; do
  [ -n "$wt" ] || continue
  if [ ! -e "$wt/.git" ] && [ ! -d "$wt" ]; then printf 'ROW\t%s\tGONE\t-\t-\t-\t0\t0\t0\t0\t0\t0\t0\t-\t-\n' "$wt"; continue; fi
  clone=$(resolve_clone "$wt"); [ -n "$clone" ] || { printf 'ROW\t%s\tNOTAREPO\t-\t-\t-\t0\t0\t0\t0\t0\t0\t0\t-\t-\n' "$wt"; continue; }
  fetch_once "$clone" >&2
  head=$(git -C "$wt" rev-parse -q --verify HEAD 2>/dev/null)
  br=$(git -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null || echo '(detached)')
  msha=$(git -C "$clone" rev-parse -q --verify origin/main 2>/dev/null)
  [ -n "$head" ] || { printf 'ROW\t%s\tNOHEAD\t-\t%s\t%s\t0\t0\t0\t0\t0\t0\t0\t-\t-\n' "$wt" "$br" "${msha:-NOMAIN}"; continue; }
  subj=$(git -C "$clone" log -1 --format='%s' "$head" 2>/dev/null | tr '\t\n' '  ')
  mb=$(git -C "$clone" merge-base "$head" origin/main 2>/dev/null)
  [ -n "$mb" ] || { printf 'ROW\t%s\tNOMERGEBASE\t%s\t%s\t%s\t0\t0\t0\t0\t0\t0\t0\t%s\t-\n' "$wt" "$head" "$br" "$msha" "$subj"; continue; }
  git -C "$clone" diff --name-only "$mb" "$head" 2>/dev/null | sort > "$T/own"
  git -C "$clone" diff --name-only origin/main "$head" 2>/dev/null | sort > "$T/vs"
  awk 'NR==FNR{a[$0]=1;next} ($0 in a)' "$T/own" "$T/vs" > "$T/differ"   # not comm: comm warns and still emits a wrong result on a collation mismatch
  nown=$(grep -c '' < "$T/own"); ndiff=$(grep -c '' < "$T/differ")
  export GIT_INDEX_FILE="$T/idx"; rm -f "$T/idx"; git -C "$clone" read-tree origin/main 2>/dev/null
  nnovel=0; nsuper=0; nnoise=0; ex=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) nnoise=$((nnoise+1)); continue;; esac
    git -C "$clone" diff "$mb" "$head" -- "$f" > "$T/p" 2>/dev/null
    if [ -s "$T/p" ] && git -C "$clone" apply --cached --check -R "$T/p" 2>/dev/null; then nsuper=$((nsuper+1))
    else nnovel=$((nnovel+1)); [ -z "$ex" ] && ex="$f"; fi
  done < "$T/differ"
  read -r nadd ndel cadd < <(git -C "$clone" diff --numstat origin/main "$head" 2>/dev/null | awk -v OWN="$T/own" '
     BEGIN{while((getline l < OWN)>0) own[l]=1}
     { f=$3; if(!(f in own)) next; a=($1=="-"?0:$1); d=($2=="-"?0:$2); ta+=a; td+=d
       gen=(f ~ /^benchmark-data\//)||(f ~ /\.(json|html|csv|svg|lock|log|gds|def|lef|sdf|spef)$/)||(f ~ /(^|\/)(reports?|runs?|logs?|out|output|results?)\//)
       if(!gen&&a>0) ca+=a } END{printf "%d %d %d", ta+0, td+0, ca+0}')
  unset GIT_INDEX_FILE
  edits=$(git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '^[MARC]')
  # evidence: sha256 of BOTH sides of one novel file, from the COMMIT not the worktree
  esa=-; esb=-; ela=0; elb=0
  if [ -n "$ex" ]; then
    esa=$(git -C "$clone" show "$head:$ex" 2>/dev/null | sha256sum | cut -c1-16)
    ela=$(git -C "$clone" show "$head:$ex" 2>/dev/null | grep -c '')
    if git -C "$clone" rev-parse -q --verify "origin/main:$ex" >/dev/null 2>&1; then
      esb=$(git -C "$clone" show "origin/main:$ex" 2>/dev/null | sha256sum | cut -c1-16)
      elb=$(git -C "$clone" show "origin/main:$ex" 2>/dev/null | grep -c '')
    else esb=ABSENT_ON_MAIN; fi
  fi
  printf 'ROW\t%s\tOK\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$wt" "$head" "$br" "$msha" "$nown" "$ndiff" "$nnovel" "$nsuper" "$nadd" "$ndel" "$cadd" "$edits" "$subj" "${ex:--}|$esa|$esb|$ela|$elb"
done <<< "$paths"
echo "DONE"
