#!/usr/bin/env bash
# A duplicate-justified ABANDON is safe only if the TWIN still exists, still holds identical
# content, and is itself KEPT. Two defensible arbitrations can otherwise close both members of a
# pair and the content goes with them.
set -uo pipefail
while IFS=$'\t' read -r a b; do
  [ -n "$a" ] || continue
  if [ ! -d "$a" ]; then echo -e "$a\t$b\tABANDONED_SIDE_ABSENT_HERE"; continue; fi
  if [ ! -d "$b" ]; then echo -e "$a\t$b\t*** TWIN MISSING ON THIS HOST ***"; continue; fi
  ra=$(git -C "$a" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  ha=$(git -C "$a" rev-parse -q --verify HEAD 2>/dev/null); hb=$(git -C "$b" rev-parse -q --verify HEAD 2>/dev/null)
  # compare INDEXES (works even if a HEAD object has been gc'd)
  fa=$(env -u GIT_INDEX_FILE git -C "$a" ls-files -s 2>/dev/null | awk '{print $2"\t"$4}' | sort | md5sum | cut -c1-32)
  fb=$(env -u GIT_INDEX_FILE git -C "$b" ls-files -s 2>/dev/null | awk '{print $2"\t"$4}' | sort | md5sum | cut -c1-32)
  na=$(env -u GIT_INDEX_FILE git -C "$a" ls-files 2>/dev/null | wc -l)
  # REFRESH FIRST. `git diff-files` compares the index's STAT data to the working tree, so after a
  # copy or a checkout that rewrites mtimes every entry reads dirty even when content is identical.
  # Measured: wt-j63x8c read 4728 changed files before refresh and 0 after; base-mml read 6368
  # before, 1640 after, and only 122 differ by CONTENT. The error is one-directional -- it
  # over-reports -- so a 0 here is trustworthy and a non-zero means nothing until content is checked.
  env -u GIT_INDEX_FILE git -C "$a" update-index --refresh >/dev/null 2>&1
  env -u GIT_INDEX_FILE git -C "$b" update-index --refresh >/dev/null 2>&1
  da=$(env -u GIT_INDEX_FILE git -C "$a" diff-files --name-only 2>/dev/null | wc -l)
  db=$(env -u GIT_INDEX_FILE git -C "$b" diff-files --name-only 2>/dev/null | wc -l)
  st=IDENTICAL; [ "$fa" != "$fb" ] && st='*** TWINS DIFFER ***'
  echo -e "$a\t$b\t$st\tindex_files=$na\tdirty_a=$da\tdirty_b=$db\thead_a=${ha:0:11}\thead_b=${hb:0:11}"
done
