#!/bin/bash
# Whole `programs/tests/` suite, BOTH arms, on an origin/main worktree.
# xdist -n 12 (32 cores, one other lane's suite already running) and a distinct
# TMPDIR per arm so two concurrent runs cannot manufacture reds in each other.
set -x
SP=/tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad
OUT=/home/reyerchu/vibe-ic/A_foundry_handoff
REPO=/home/reyerchu/vibe-ic
: > "$OUT/regress_main.progress"

arm () {  # $1 = name, $2 = worktree path
  export TMPDIR="$SP/tmp_$1"; rm -rf "$TMPDIR"; mkdir -p "$TMPDIR"
  cd "$2/vibe-ic-marketplace/plugins/vibe-ic/programs" || exit 1
  python3 -m pytest tests/ -q -p no:randomly -n 12 > "$OUT/MAIN_$1.log" 2>&1
  echo "$1 pytest rc=$?" >> "$OUT/MAIN_$1.log"
  grep -E "^(FAILED|ERROR)" "$OUT/MAIN_$1.log" | sed 's/ - .*//' | sort -u > "$OUT/MAIN_${1}_FAILED.txt"
  { echo "== ARM $1 =="; tail -3 "$OUT/MAIN_$1.log"; } >> "$OUT/regress_main.progress"
}

# BASE arm: a clean second worktree at origin/main, untouched.
BW=$SP/mainwt_base
rm -rf "$BW"; git -C "$REPO" worktree remove --force "$BW" 2>/dev/null
git -C "$REPO" worktree add --detach "$BW" origin/main || exit 1
arm BASE "$BW"

# AFTER arm: the worktree the candidate is already applied to.
arm AFTER "$SP/mainwt"

{
  echo "=== NEW failures (AFTER - BASE) ==="
  comm -13 "$OUT/MAIN_BASE_FAILED.txt" "$OUT/MAIN_AFTER_FAILED.txt"
  echo "=== FIXED (BASE - AFTER) ==="
  comm -23 "$OUT/MAIN_BASE_FAILED.txt" "$OUT/MAIN_AFTER_FAILED.txt"
} > "$OUT/MAIN_DELTA.txt"
cat "$OUT/MAIN_DELTA.txt" >> "$OUT/regress_main.progress"
cp "$OUT/regress_main.progress" "$OUT/regress_main.done"
