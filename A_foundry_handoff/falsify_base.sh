#!/bin/bash
# NEGATIVE CONTROL on the origin/main base: the identical four cases against the
# PRE-FIX programs (restored from `git show origin/main:`), every other program
# symlinked from the same worktree so nothing else differs.
set -u
SP=/tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad
B=$SP/base_farm
W=$SP/work_base
LOG=/home/reyerchu/vibe-ic/A_foundry_handoff/FALSIFY_BASE.log
: > "$LOG"
say(){ echo "$@" | tee -a "$LOG"; }
rm -rf "$W"; mkdir -p "$W"
for c in A_asis B_realgds C_hollowgds D_zerobyte; do
  cp -a $SP/work/$c "$W/$c"
  rm -rf "$W/$c/phase3/stage4/foundry_handoff" "$W/$c/reports/phase3/foundry_handoff_audit.json"
done
for CASE in A_asis B_realgds C_hollowgds D_zerobyte; do
  D="$W/$CASE"
  say "=== CASE $CASE  (PRE-FIX / origin/main e37d10e1e)"
  python3 "$B/foundry_handoff_pack_gen.py" "$D" --top spm >>"$LOG" 2>&1; say "    producer rc=$?"
  say "    handoff dir: $(ls "$D/phase3/stage4/foundry_handoff" 2>/dev/null | tr '\n' ' ')"
  python3 "$B/foundry_handoff_package_check.py" "$D" --json "$D/reports/phase3/foundry_handoff_audit.json" >>"$LOG" 2>&1; say "    gate rc=$?"
  say "    gate verdict: $(python3 -c "
import json
try:
    d=json.load(open('$D/reports/phase3/foundry_handoff_audit.json'))
    print(d.get('verdict'), [f['rule'] for f in d.get('findings',[])])
except Exception as e: print('no audit json:', e)")"
done
say DONE
