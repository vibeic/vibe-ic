#!/bin/bash
# READ-ONLY probe: for each deletion-bound row, report existence, HEAD drift, and dirt.
# Writes nothing anywhere; never fetches.
while IFS=$'\t' read -r p v h; do
  [ -z "$p" ] && continue
  if [ ! -d "$p" ]; then echo -e "$p\t$v\t$h\tGONE\t-\t-\t-"; continue; fi
  cur=$(git -C "$p" rev-parse HEAD 2>/dev/null) || { echo -e "$p\t$v\t$h\tNOT_A_GIT_CHECKOUT\t-\t-\t-"; continue; }
  if [ "$cur" = "$h" ]; then drift=HEAD_SAME; else drift=HEAD_MOVED; fi
  mod=$(git -C "$p" status --porcelain=v1 --untracked-files=all 2>/dev/null | grep -vc '^??' )
  unt=$(git -C "$p" status --porcelain=v1 --untracked-files=all 2>/dev/null | grep -c '^??' )
  echo -e "$p\t$v\t$h\t$drift\t$cur\tmod=$mod\tuntracked=$unt"
done
