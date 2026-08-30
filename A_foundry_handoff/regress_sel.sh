#!/bin/bash
# TARGETED regression, both arms on origin/main worktrees. Selection, stated:
# every test file naming foundry_handoff / the shared geometry parser / the
# hardmacro gate that shares it, PLUS the hygiene gates that react to a new
# test file, a new program import, and a new module-level function.
# (The whole-suite run is ~3.5h per arm on this host with another lane's suite
#  competing; it runs separately, see regress_main.sh.)
set -x
SP=/tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad
OUT=/home/reyerchu/vibe-ic/A_foundry_handoff
SEL=$(cat $SP/sel.txt | tr '\n' ' ')
arm () {
  export TMPDIR="$SP/tmpsel_$1"; rm -rf "$TMPDIR"; mkdir -p "$TMPDIR"
  cd "$2/vibe-ic-marketplace/plugins/vibe-ic/programs" || exit 1
  python3 -m pytest $3 -q -p no:randomly -n 8 > "$OUT/SEL_$1.log" 2>&1
  echo "$1 pytest rc=$?" >> "$OUT/SEL_$1.log"
  grep -E "^(FAILED|ERROR)" "$OUT/SEL_$1.log" | sed 's/ - .*//' | sort -u > "$OUT/SEL_${1}_FAILED.txt"
}
# BASE: the same selection minus the new file (it does not exist on main).
BASESEL=$(echo $SEL | tr ' ' '\n' | grep -v absent_or_hollow_die | tr '\n' ' ')
[ -f "$OUT/SEL_BASE_FAILED.txt" ] || arm BASE  "$SP/mainwt_base" "$BASESEL"
arm AFTER "$SP/mainwt"      "$SEL"
{
  echo "SELECTION ($(echo $SEL | wc -w) files)"; echo
  echo "=== BASE  ==="; tail -2 "$OUT/SEL_BASE.log"
  echo "=== AFTER ==="; tail -2 "$OUT/SEL_AFTER.log"
  echo "=== NEW failures (AFTER - BASE) ==="; comm -13 "$OUT/SEL_BASE_FAILED.txt" "$OUT/SEL_AFTER_FAILED.txt"
  echo "=== FIXED (BASE - AFTER) ==="; comm -23 "$OUT/SEL_BASE_FAILED.txt" "$OUT/SEL_AFTER_FAILED.txt"
} > "$OUT/SEL_DELTA.txt"
cp "$OUT/SEL_DELTA.txt" "$OUT/regress_sel.done"
