#!/usr/bin/env bash
# wt_classify3.sh <repo> [main-ref]  -- CONTENT-based vibe-ic worktree triage.
# READ-ONLY: never writes to the repo. Tier 2 uses a temp index (GIT_INDEX_FILE)
# read from the main ref, so no worktree/checkout is created.
#
# vibe-ic lands everything as a SQUASH, so a landed branch is never an ancestor of
# main -- merge-base --is-ancestor / branch --merged / rev-list origin/main..HEAD
# all call landed work unlanded. Content is the only separator.
#   tier1 every changed file byte-identical to main            -> LANDED_FILE
#   tier2 every non-identical file's hunks already in main
#         (its patch reverse-applies to main's tree)           -> LANDED_PATCH
#   only version-manifest churn left                           -> LANDED_VERONLY
#   else                                                       -> UNLANDED
# TSV: path branch head state nfiles ndiffer nnovel dirty subject topdirs novelfiles
set -uo pipefail
REPO="${1:?usage: wt_classify3.sh <repo> [main-ref]}"
MAIN="${2:-origin/main}"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
cd "$REPO" || exit 1
git rev-parse --verify -q "$MAIN" >/dev/null || { echo "NO_SUCH_REF $MAIN in $REPO" >&2; exit 2; }
export GIT_INDEX_FILE="$T/idx"
git read-tree "$MAIN" || { echo "READ_TREE_FAIL $REPO" >&2; exit 3; }

# self-test: a patch known to be in main MUST reverse-apply, else the tool is broken
git diff "$MAIN~1" "$MAIN" > "$T/ctl.patch" 2>/dev/null
if [ -s "$T/ctl.patch" ] && ! git apply --cached --check -R "$T/ctl.patch" 2>/dev/null; then
  echo "SELFTEST_FAIL $REPO: known-landed patch did not reverse-apply" >&2; exit 4
fi

is_version_noise() {
  case "$1" in
    *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;;
  esac; return 1
}

git worktree list --porcelain | awk '
  /^worktree /{p=substr($0,10)} /^HEAD /{h=substr($0,6)}
  /^branch /{b=substr($0,8)} /^detached/{b="(detached)"}
  /^$/{if(p!=""){print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h); p="";b="";h=""}}
  END{if(p!="")print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h)}' \
| while IFS=$'\t' read -r wt br head; do
  br=${br#refs/heads/}
  if [ ! -d "$wt" ]; then printf '%s\t%s\t%s\tGONE\t0\t0\t0\t-\t\t\t\n' "$wt" "$br" "$head"; continue; fi
  if [ "$head" = "-" ]; then printf '%s\t%s\t%s\tNOHEAD\t0\t0\t0\t-\t\t\t\n' "$wt" "$br" "$head"; continue; fi
  subj=$(git log -1 --format='%s' "$head" 2>/dev/null | tr '\t|' '  ' | cut -c1-160)
  mb=$(git merge-base "$head" "$MAIN" 2>/dev/null)
  if [ -z "$mb" ]; then printf '%s\t%s\t%s\tNOMERGEBASE\t0\t0\t0\t-\t%s\t\t\n' "$wt" "$br" "$head" "$subj"; continue; fi
  mapfile -t files < <(git diff --name-only "$mb" "$head" 2>/dev/null)
  n=${#files[@]}; differ=0; novel=0; nlist=""; vernoise=0
  for f in "${files[@]}"; do
    [ -n "$f" ] || continue
    a=$(git rev-parse -q --verify "$head:$f" 2>/dev/null)
    b=$(git rev-parse -q --verify "$MAIN:$f" 2>/dev/null)
    [ "$a" = "$b" ] && continue
    differ=$((differ+1))
    if is_version_noise "$f"; then vernoise=$((vernoise+1)); continue; fi
    git diff "$mb" "$head" -- "$f" > "$T/f.patch" 2>/dev/null
    if [ -s "$T/f.patch" ] && git apply --cached --check -R "$T/f.patch" 2>/dev/null; then continue; fi
    novel=$((novel+1)); [ ${#nlist} -lt 500 ] && nlist="${nlist}${nlist:+,}${f}"
  done
  if   [ "$differ" -eq 0 ]; then state=LANDED_FILE
  elif [ "$novel" -eq 0 ] && [ "$vernoise" -gt 0 ]; then state=LANDED_VERONLY
  elif [ "$novel" -eq 0 ]; then state=LANDED_PATCH
  else state=UNLANDED; fi
  # NB: env -u GIT_INDEX_FILE -- the temp index used by the --cached tier-2 test
  # must NOT leak here, or status compares the worktree against main's index and
  # calls almost every file modified (measured: 18083 false positives).
  dt=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '')
  du=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??')
  if [ "${dt:-0}" -gt 0 ]; then dirty="dirty:$dt/u$du"; elif [ "${du:-0}" -gt 0 ]; then dirty="untracked:$du"; else dirty="clean"; fi
  topdirs=$(printf '%s\n' "${files[@]}" | grep -v '^$' | cut -d/ -f1-2 | sort -u | head -6 | paste -sd, -)
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$wt" "$br" "$head" "$state" "$n" "$differ" "$novel" "$dirty" "$subj" "$topdirs" "$nlist"
done
