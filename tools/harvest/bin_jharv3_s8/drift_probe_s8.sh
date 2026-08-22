#!/bin/bash
# READ-ONLY drift probe. Reads path<TAB>judged_head on stdin, one row per line.
# Writes nothing anywhere and never fetches. Reports what a deletion would face
# TODAY, which is not what the verdict was measured on.
while IFS=$'\t' read -r p h; do
  [ -z "$p" ] && continue
  if [ ! -d "$p" ]; then echo -e "$p\t$h\tGONE\t-\t-\t-\t-"; continue; fi
  cur=$(git -C "$p" rev-parse HEAD 2>/dev/null) || { echo -e "$p\t$h\tNOT_A_GIT_CHECKOUT\t-\t-\t-\t-"; continue; }
  [ "$cur" = "$h" ] && d=HEAD_SAME || d=HEAD_MOVED
  s=$(git -C "$p" status --porcelain=v1 --untracked-files=all 2>/dev/null)
  mod=$(printf '%s\n' "$s" | grep -v '^??' | grep -c .)
  unt=$(printf '%s\n' "$s" | grep -c '^??')
  tree=$(git -C "$p" rev-parse HEAD^{tree} 2>/dev/null)
  echo -e "$p\t$h\t$d\t$cur\t$tree\tmod=$mod\tuntracked=$unt"
done
