#!/usr/bin/env bash
# dirty.sh <worktree> -- decide whether the UNCOMMITTED state of a worktree holds
# content that is not already at the same path in origin/main.
#
# Scope = only the paths git reports as changed relative to that worktree's own HEAD,
# so main's later churn cannot inflate the answer. For each such path the on-disk /
# staged bytes are hashed with git hash-object (identical to sha256sum modulo git's
# blob header, and the same function that produced main's OIDs) and compared to
# origin/main's blob at that path.
set -uo pipefail
WT="${1:?}"
cd "$WT" || exit 1
same=0; diff=0; absent_on_main=0; deleted=0; list=""
while IFS= read -r line; do
  [ -n "$line" ] || continue
  xy=${line:0:2}; f=${line:3}
  case "$f" in *' -> '*) f=${f##* -> };; esac
  f=${f%\"}; f=${f#\"}
  case "$xy" in
    'D '|' D'|'DD') deleted=$((deleted+1)); continue;;
  esac
  # staged bytes if the index differs, else the file on disk
  if [ "${xy:0:1}" != " " ] && [ "${xy:0:1}" != "?" ]; then
    a=$(git rev-parse -q --verify ":$f" 2>/dev/null)
  else
    a=$(git hash-object -- "$f" 2>/dev/null)
  fi
  [ -n "$a" ] || { deleted=$((deleted+1)); continue; }
  b=$(git rev-parse -q --verify "origin/main:$f" 2>/dev/null)
  if   [ -z "$b" ];      then absent_on_main=$((absent_on_main+1)); [ ${#list} -lt 400 ] && list="${list}${list:+, }NEW:$f"
  elif [ "$a" = "$b" ];  then same=$((same+1))
  else                        diff=$((diff+1)); [ ${#list} -lt 400 ] && list="${list}${list:+, }MOD:$f"
  fi
done < <(git status --porcelain 2>/dev/null)
printf '%s\tsame_as_main=%d\tdiffers=%d\tnew_paths=%d\tdeletions=%d\t%s\n' \
  "$WT" "$same" "$diff" "$absent_on_main" "$deleted" "$list"
