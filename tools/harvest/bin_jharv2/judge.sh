#!/usr/bin/env bash
# judge.sh <clone> <checkout>... -- decide each checkout KEEP/DROP by CONTENT.
#
# The verdict never looks at ancestry, commit count, "ahead/behind", or `git status`
# alone. It asks one question per file: are the bytes at this path identical to the
# bytes at the same path in current origin/main? A git blob OID is a content hash over
# the exact bytes, so "same OID" is "same sha256sum of `git show origin/main:<path>`",
# computed once per tree instead of once per file. Named examples are re-hashed with
# real sha256sum by evidence.sh so the report is checkable by hand.
#
# merge-base is used ONLY to scope which files this branch is responsible for. It never
# decides the verdict. Without that scope, every branch older than one landing would list
# all of main's later churn as "differing" and every verdict would be KEEP.
#
# Method adopted from jharv3's shard-C judge so the shards are comparable, with one
# deliberate difference: UNCOMMITTED state (modified tracked files, and non-ignored
# untracked files) forces KEEP here. A wrong DROP is unrecoverable and that content is
# on no branch at all.
#
# READ-ONLY: temp index, no checkout, no worktree created, nothing written into any tree.
set -uo pipefail
REPO="${1:?usage: judge.sh <clone> <checkout>...}"; shift
MAIN=origin/main
MAINSHA=$(git -C "$REPO" rev-parse -q --verify "$MAIN") || { echo "NOMAIN $REPO" >&2; exit 2; }

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
export GIT_INDEX_FILE="$T/idx"
git -C "$REPO" read-tree "$MAIN" || exit 3

# Self-test: the reverse-apply probe must recognise main's own last landing as already
# present. If this fails, the SUPERSEDED class below is not trustworthy and says so.
git -C "$REPO" diff "$MAIN~1" "$MAIN" > "$T/ctl" 2>/dev/null
SELFTEST=ok
if [ -s "$T/ctl" ] && ! git -C "$REPO" apply --cached --check -R "$T/ctl" 2>/dev/null; then SELFTEST=FAILED; fi
echo "#selftest	$REPO	$SELFTEST	${MAINSHA:0:11}" >&2

# Version/marketplace bookkeeping is rewritten by every landing; a difference there is
# not work. Counted separately rather than ignored, so the report can say so out loud.
isnoise(){ case "$1" in *.claude-plugin/plugin.json|*marketplace.json|*/VERSION|VERSION|*CHANGELOG.md) return 0;; esac; return 1; }

for wt in "$@"; do
  [ -d "$wt" ] || { printf '%s\t%s\t(gone)\t-\tUNDETERMINED_DIR_GONE\t0\t0\t0\t0\t0\t0\t0\t\t\t\t\n' "$REPO" "$wt"; continue; }
  head=$(env -u GIT_INDEX_FILE git -C "$wt" rev-parse -q --verify HEAD 2>/dev/null)
  br=$(env -u GIT_INDEX_FILE git -C "$wt" symbolic-ref -q --short HEAD 2>/dev/null); br=${br:-(detached)}
  if [ -z "$head" ] || ! git -C "$REPO" rev-parse -q --verify "$head^{commit}" >/dev/null 2>&1; then
    printf '%s\t%s\t%s\t%s\tUNDETERMINED_NO_HEAD\t0\t0\t0\t0\t0\t0\t0\t\t\t\t\n' "$REPO" "$wt" "$br" "${head:--}"; continue
  fi
  subj=$(git -C "$REPO" log -1 --format='%s' "$head" 2>/dev/null | tr '\t\n|' '   ' | cut -c1-140)
  cdate=$(git -C "$REPO" log -1 --format='%cs' "$head" 2>/dev/null)
  mb=$(git -C "$REPO" merge-base "$head" "$MAIN" 2>/dev/null)
  if [ -z "$mb" ]; then
    printf '%s\t%s\t%s\t%s\tUNDETERMINED_NO_MERGEBASE\t0\t0\t0\t0\t0\t0\t0\t\t\t%s\t%s\n' "$REPO" "$wt" "$br" "$head" "$subj" "$cdate"; continue
  fi

  git -C "$REPO" diff --name-only "$mb" "$head" 2>/dev/null | sort > "$T/own"
  git -C "$REPO" diff --name-only "$MAIN" "$head" 2>/dev/null | sort > "$T/vsmain"
  # awk set-intersection, never `comm`. comm requires both inputs in the collation order IT
  # expects; on a mismatch it warns and STILL EMITS a result, usually EMPTY -- and an empty differ
  # set is precisely what produces DROP/LANDED. jharv3 lost a number to exactly this with comm's
  # stderr discarded. awk has no such precondition.
  awk 'NR==FNR{a[$0]=1;next} ($0 in a)' "$T/own" "$T/vsmain" > "$T/differ"
  nown=$(grep -c '' < "$T/own"); ndiff=$(grep -c '' < "$T/differ")
  nnovel=0; nnoise=0; nsuper=0; novel_list=""; super_list=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if isnoise "$f"; then nnoise=$((nnoise+1)); continue; fi
    git -C "$REPO" diff "$mb" "$head" -- "$f" > "$T/f" 2>/dev/null
    if [ -s "$T/f" ] && git -C "$REPO" apply --cached --check -R "$T/f" 2>/dev/null; then
      nsuper=$((nsuper+1)); [ ${#super_list} -lt 260 ] && super_list="${super_list}${super_list:+,}${f}"
    else
      nnovel=$((nnovel+1)); [ ${#novel_list} -lt 260 ] && novel_list="${novel_list}${novel_list:+,}${f}"
    fi
  done < "$T/differ"

  # Uncommitted state is work too, and it is on no branch at all. Hash the on-disk /
  # staged bytes and compare to origin/main's blob at the same path.
  dmod=0; dnew=0; ddel=0; dsame=0; dlist=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    xy=${line:0:2}; f=${line:3}
    case "$f" in *' -> '*) f=${f##* -> };; esac
    f=${f%\"}; f=${f#\"}
    case "$xy" in 'D '|' D'|'DD') ddel=$((ddel+1)); continue;; esac
    if [ "${xy:0:1}" != " " ] && [ "${xy:0:1}" != "?" ]; then
      a=$(env -u GIT_INDEX_FILE git -C "$wt" rev-parse -q --verify ":$f" 2>/dev/null)
    else
      a=$(env -u GIT_INDEX_FILE git -C "$wt" hash-object -- "$f" 2>/dev/null)
    fi
    [ -n "$a" ] || { ddel=$((ddel+1)); continue; }
    b=$(git -C "$REPO" rev-parse -q --verify "$MAIN:$f" 2>/dev/null)
    if   [ -z "$b" ];     then dnew=$((dnew+1));  [ ${#dlist} -lt 260 ] && dlist="${dlist}${dlist:+,}NEW:$f"
    elif [ "$a" = "$b" ]; then dsame=$((dsame+1))
    else                       dmod=$((dmod+1));  [ ${#dlist} -lt 260 ] && dlist="${dlist}${dlist:+,}MOD:$f"; fi
  done < <(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain 2>/dev/null)

  if   [ "$nnovel" -gt 0 ];                            then st=KEEP_NOVEL_CONTENT
  elif [ "$nsuper" -gt 0 ];                            then st=KEEP_SUPERSEDED_CONTENT_DIFFERS
  elif [ $((dmod+dnew)) -gt 0 ];                       then st=KEEP_UNCOMMITTED_ONLY
  elif [ "$ndiff" -eq 0 ] && [ "$ddel" -eq 0 ];        then st=DROP_ALL_FILES_MATCH
  elif [ "$ndiff" -eq 0 ];                             then st=DROP_ALL_FILES_MATCH_DELETIONS_ONLY
  elif [ "$nnovel" -eq 0 ] && [ "$nsuper" -eq 0 ];     then st=DROP_VERSION_NOISE_ONLY
  else                                                      st=UNDETERMINED_UNCLASSIFIED
  fi

  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$REPO" "$wt" "$br" "$head" "$st" "$nown" "$ndiff" "$nnovel" "$nsuper" "$nnoise" \
    "$dmod" "$dnew" "$novel_list" "$super_list$( [ -n "$dlist" ] && echo "  UNCOMMITTED[$dlist]")" "$subj" "$cdate"
done
