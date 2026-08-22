#!/bin/bash
# READ-ONLY: `git hash-object` without -w never writes. No index is touched, nothing is fetched.
# Question: is the directory's on-disk content (tracked + untracked, excluding ignored) exactly HEAD's tree?
while IFS=$'\t' read -r p rest; do
  [ -z "$p" ] && continue
  [ -d "$p" ] || { echo -e "$p\tGONE"; continue; }
  cd "$p" || continue
  head=$(git rev-parse HEAD)
  git ls-tree -r --full-tree HEAD | awk -F'\t' '{split($1,a," "); if(a[2]=="blob") print $2 "\t" a[3]}' | sort > /tmp/_A_$$
  git ls-files --cached --others --exclude-standard | sort -u > /tmp/_L_$$
  : > /tmp/_B_$$
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    printf '%s\t%s\n' "$f" "$(git hash-object -- "$f" 2>/dev/null)" >> /tmp/_B_$$
  done < /tmp/_L_$$
  sort -o /tmp/_B_$$ /tmp/_B_$$
  onlyhead=$(comm -23 /tmp/_A_$$ /tmp/_B_$$ | wc -l)
  onlydisk=$(comm -13 /tmp/_A_$$ /tmp/_B_$$ | wc -l)
  ex=$(comm -13 /tmp/_A_$$ /tmp/_B_$$ | head -3 | cut -f1 | tr '\n' '|')
  exh=$(comm -23 /tmp/_A_$$ /tmp/_B_$$ | head -3 | cut -f1 | tr '\n' '|')
  if [ "$onlyhead" -eq 0 ] && [ "$onlydisk" -eq 0 ]; then v=DISK_EQUALS_HEAD_TREE; else v=DISK_DIFFERS; fi
  echo -e "$p\t$head\t$v\thead_blobs=$(wc -l < /tmp/_A_$$)\tdisk_blobs=$(wc -l < /tmp/_B_$$)\tonly_in_head=$onlyhead\tonly_on_disk=$onlydisk\tdisk_only_eg=$ex\thead_only_eg=$exh"
  rm -f /tmp/_A_$$ /tmp/_L_$$ /tmp/_B_$$
done
