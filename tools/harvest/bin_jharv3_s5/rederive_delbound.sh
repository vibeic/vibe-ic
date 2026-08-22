#!/usr/bin/env bash
# Independent re-derivation of the deletion-bound shard-C rows, by CONTENT.
#
# A worktree holds work that is NOT on main iff some path's content at its HEAD
# differs from BOTH main's tip AND the merge-base. (Differing from main alone is
# not evidence: main may simply have moved on past a file this old checkout still
# carries unchanged.)  Ancestry is never consulted for the verdict.
#
# Usage: rederive_delbound.sh <clone> <main_sha> <head_sha> <label>
set -u
CLONE=$1; MAIN=$2; HEAD=$3; LABEL=$4
cd "$CLONE" 2>/dev/null || { echo -e "$LABEL\tERROR\tclone $CLONE unreadable"; exit 0; }
git cat-file -e "${HEAD}^{commit}" 2>/dev/null || { echo -e "$LABEL\tERROR\thead $HEAD absent from $CLONE"; exit 0; }
B=$(git merge-base "$MAIN" "$HEAD" 2>/dev/null) || B=""
[ -z "$B" ] && { echo -e "$LABEL\tERROR\tno merge-base with main"; exit 0; }
own=0; landed=0; div=0; divlist=""
while IFS= read -r p; do
  [ -z "$p" ] && continue
  own=$((own+1))
  hb=$(git rev-parse --quiet --verify "$HEAD:$p" 2>/dev/null || echo ABSENT)
  mb=$(git rev-parse --quiet --verify "$MAIN:$p" 2>/dev/null || echo ABSENT)
  if [ "$hb" = "$mb" ]; then landed=$((landed+1)); else
    # deleted by this branch and still absent from main is not content it holds
    if [ "$hb" = ABSENT ] && [ "$mb" != ABSENT ]; then landed=$((landed+1)); continue; fi
    div=$((div+1)); divlist="$divlist $p"
  fi
done < <(git diff --name-only "$B" "$HEAD" 2>/dev/null)
if [ "$div" -eq 0 ]; then
  echo -e "$LABEL\tCONTENT_ON_MAIN\tmerge-base $B; $own paths this head changed relative to the merge-base, all $landed byte-identical to main $MAIN (or deleted here and absent there); 0 divergent"
else
  echo -e "$LABEL\tHOLDS_CONTENT\tmerge-base $B; $own changed paths, $div differ from BOTH main $MAIN and the merge-base:$divlist"
fi
