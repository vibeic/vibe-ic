#!/usr/bin/env bash
# reflog_blind.sh -- read checkout paths; report which have NO reflog at all.
# The displaced-prior-head sweep reads `git reflog` in each worktree. Where logs/HEAD is absent
# the sweep is structurally BLIND: it did not find nothing, it could not look. jharv3's point,
# and it must be a stated limit rather than folded into a clean count.
set -uo pipefail
b=0; ok=0
while read -r p; do
  [ -n "$p" ] || continue
  if [ ! -d "$p" ]; then echo "GONE $p"; continue; fi
  n=$(env -u GIT_INDEX_FILE git -C "$p" reflog --format='%H' 2>/dev/null | grep -c '' || echo 0)
  if [ "$n" -eq 0 ]; then b=$((b+1)); echo "NO_REFLOG $p"; else ok=$((ok+1)); fi
done
echo "with_reflog=$ok no_reflog=$b"
