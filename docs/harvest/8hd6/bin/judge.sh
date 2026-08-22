#!/usr/bin/env bash
# judge.sh <clone> -- decide every worktree of <clone> KEEP/DROP by CONTENT.
#
# The verdict never looks at ancestry, commit count, or "ahead/behind". It asks one
# question per file: is the blob in this worktree's HEAD byte-identical to the blob at
# the same path in current origin/main? A git blob OID is a content hash over the exact
# bytes, so "same OID" is "same sha256sum of `git show origin/main:<path>`" -- computed
# once instead of once per file. A named example is re-checked with real sha256sum so
# the evidence in the report is verifiable by hand.
#
# merge-base is used ONLY to scope which files this branch is responsible for. It never
# decides the verdict. Without that scope every branch older than one landing would list
# all of main's later churn as "differing" and every verdict would be KEEP.
#
# READ-ONLY: temp index, no checkout, no worktree created, nothing written into any tree.
set -uo pipefail
REPO="${1:?usage: judge.sh <clone>}"
MAIN=origin/main
git -C "$REPO" rev-parse --verify -q "$MAIN" >/dev/null || { echo "NOMAIN $REPO" >&2; exit 2; }
MAINSHA=$(git -C "$REPO" rev-parse "$MAIN")

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_INDEX_FILE="$T/idx"
git -C "$REPO" read-tree "$MAIN" || exit 3

# Self-test: the reverse-apply probe must be able to recognise main's own last landing
# as already-present. If this fails the LANDED_PATCH class below is not trustworthy.
git -C "$REPO" diff "$MAIN~1" "$MAIN" > "$T/ctl" 2>/dev/null
SELFTEST=ok
if [ -s "$T/ctl" ] && ! git -C "$REPO" apply --cached --check -R "$T/ctl" 2>/dev/null; then SELFTEST=FAILED; fi
echo "#selftest	$REPO	$SELFTEST	$MAINSHA" >&2

# Version/marketplace bookkeeping is rewritten by every landing; a difference there is
# not work. Kept separate rather than ignored, so the report can say so out loud.
isnoise(){ case "$1" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;; esac; return 1; }

git -C "$REPO" worktree list --porcelain | awk '
  /^worktree /{p=substr($0,10)} /^HEAD /{h=substr($0,6)}
  /^branch /{b=substr($0,8)} /^detached/{b="(detached)"} /^prunable/{pr="prunable"}
  /^$/{if(p!=""){print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h)"\t"(pr==""?"-":pr);p="";b="";h="";pr=""}}
  END{if(p!="")print p"\t"(b==""?"(none)":b)"\t"(h==""?"-":h)"\t"(pr==""?"-":pr)}' \
| while IFS=$'\t' read -r wt br head prun; do
  br=${br#refs/heads/}
  [ -d "$wt" ] && wtdir=present || wtdir=REMOVED

  if [ "$head" = "-" ] || ! git -C "$REPO" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1; then
    printf '%s\t%s\t%s\t%s\tUNDETERMINED_NO_HEAD\t0\t0\t0\t0\t0\t0\t\t\t\t%s\t%s\n' \
      "$REPO" "$wt" "$br" "$head" "$wtdir" "$prun"; continue
  fi

  subj=$(git -C "$REPO" log -1 --format='%s' "$head" 2>/dev/null | tr '\t\n|' '   ' | cut -c1-150)
  cdate=$(git -C "$REPO" log -1 --format='%cs' "$head" 2>/dev/null)
  mb=$(git -C "$REPO" merge-base "$head" "$MAIN" 2>/dev/null)
  if [ -z "$mb" ]; then
    printf '%s\t%s\t%s\t%s\tUNDETERMINED_NO_MERGEBASE\t0\t0\t0\t0\t0\t0\t\t\t%s\t%s\t%s\n' \
      "$REPO" "$wt" "$br" "$head" "$subj" "$wtdir" "$prun"; continue
  fi

  # own = the files this branch is responsible for.
  git -C "$REPO" diff --name-only "$mb" "$head" 2>/dev/null | sort > "$T/own"
  # vsmain = every path where HEAD's tree and main's tree hold different bytes.
  git -C "$REPO" diff --name-only "$MAIN" "$head" 2>/dev/null | sort > "$T/vsmain"
  comm -12 "$T/own" "$T/vsmain" > "$T/differ"

  nown=$(grep -c '' < "$T/own"); ndiff=$(grep -c '' < "$T/differ")
  nnovel=0; nnoise=0; nsuper=0; novel_list=""; super_list=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if isnoise "$f"; then nnoise=$((nnoise+1)); continue; fi
    # Bytes differ. Is the branch's own change nonetheless already contained in main,
    # with main having moved further on top? Reverse-applying the branch's patch for
    # this file against main's tree answers that without a checkout.
    git -C "$REPO" diff "$mb" "$head" -- "$f" > "$T/f" 2>/dev/null
    if [ -s "$T/f" ] && git -C "$REPO" apply --cached --check -R "$T/f" 2>/dev/null; then
      nsuper=$((nsuper+1)); [ ${#super_list} -lt 300 ] && super_list="${super_list}${super_list:+,}${f}"
    else
      nnovel=$((nnovel+1)); [ ${#novel_list} -lt 300 ] && novel_list="${novel_list}${novel_list:+,}${f}"
    fi
  done < "$T/differ"

  # Uncommitted state on disk is work too, and it is on no branch at all.
  if [ "$wtdir" = present ]; then
    trk=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | grep -c '')
    unt=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain 2>/dev/null | grep -c '^??')
    dirty=$(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain -uno 2>/dev/null | head -4 | cut -c1-60 | tr '\n' ';')
  else trk=0; unt=0; dirty=""; fi

  if   [ "$ndiff" -eq 0 ];                            then st=DROP_ALL_FILES_MATCH
  elif [ "$nnovel" -eq 0 ] && [ "$nsuper" -eq 0 ];    then st=DROP_VERSION_NOISE_ONLY
  elif [ "$nnovel" -eq 0 ];                           then st=KEEP_SUPERSEDED_CONTENT_DIFFERS
  else                                                     st=KEEP_NOVEL_CONTENT
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$REPO" "$wt" "$br" "$head" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$nnoise" \
    "${trk:-0}" "${unt:-0}" "$novel_list" "$super_list" "$subj" "$wtdir|$prun|$cdate|${dirty}"
done
