#!/usr/bin/env bash
# untracked_all.sh -- read `path<TAB>repo`. jharv3 measured cleanliness with `-uno`, which EXCLUDES
# untracked files, and deletion destroys untracked bytes. My judges never used -uno (grepped: zero
# occurrences), but my EVIDENCE never says so, and a reader cannot verify a question they cannot
# see was asked. So: measure with --untracked-files=ALL, the widest setting, and hash every
# modified/untracked path against origin/main so "clean" is a content statement.
set -uo pipefail
while IFS=$'\t' read -r wt repo; do
  [ -d "$wt" ] || { printf '%s\tGONE\t-\n' "$wt"; continue; }
  n=0; mod=0; new=0; ex=""
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    n=$((n+1)); xy=${line:0:2}; f=${line:3}
    case "$f" in *' -> '*) f=${f##* -> };; esac; f=${f%\"}; f=${f#\"}
    case "$xy" in 'D '|' D'|'DD') continue;; esac
    [ -f "$wt/$f" ] || continue
    a=$(git -C "$repo" hash-object -- "$wt/$f" 2>/dev/null) || continue
    b=$(git -C "$repo" rev-parse -q --verify "origin/main:$f" 2>/dev/null)
    if [ -z "$b" ]; then new=$((new+1)); [ -z "$ex" ] && ex="NEW:$f"
    elif [ "$a" != "$b" ]; then mod=$((mod+1)); [ -z "$ex" ] && ex="MOD:$f"; fi
  done < <(env -u GIT_INDEX_FILE git -C "$wt" status --porcelain --untracked-files=all 2>/dev/null)
  st=CLEAN; [ $((mod+new)) -gt 0 ] && st='**HOLDS_CONTENT_NOT_ON_MAIN**'
  printf '%s\t%s\tstatus_lines=%s modified=%s untracked_new=%s\t%s\n' "$wt" "$st" "$n" "$mod" "$new" "$ex"
done
