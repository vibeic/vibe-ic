#!/bin/bash
# Falsification harness. Writes every step's result to FALSIFY.log as it goes.
set -u
P=/tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad/mainwt/vibe-ic-marketplace/plugins/vibe-ic/programs
W=/tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad/work
LOG=/home/reyerchu/vibe-ic/A_foundry_handoff/FALSIFY.log
: > "$LOG"
say(){ echo "$@" | tee -a "$LOG"; }
run(){ say "--- \$ $*"; "$@" >>"$LOG" 2>&1; local rc=$?; say "    rc=$rc"; return $rc; }

rm -rf "$W"; mkdir -p "$W"
cp -a /tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad/spm_gf180mcuD_20260831_a1 "$W/A_asis"
cp -a "$W/A_asis" "$W/B_realgds"
cp -a "$W/A_asis" "$W/C_hollowgds"
cp -a "$W/A_asis" "$W/D_zerobyte"

# B: plant the REAL chip GDS from a converged control run (spm_rep1, same design,
#    same PDK, PnR converged) at the canonical stream-out path. NOTHING is
#    hand-authored: this is the flow's own artefact from its own converged run.
mkdir -p "$W/B_realgds/phase3/stage4/gds"
cp /tmp/claude-1000/-home-reyerchu-vibe-ic/38974ecc-f59b-42fb-8024-2d37c19573f3/scratchpad/rep1/spm_rep1/phase3/stage4/gds/spm.gds \
   "$W/B_realgds/phase3/stage4/gds/spm.gds"

# C: a HOLLOW GDS — a structurally valid GDSII stream (HEADER..ENDLIB, a named
#    top structure) carrying ZERO geometry records. This is the launderable
#    artefact the directive names.
python3 - "$W/C_hollowgds/phase3/stage4/gds/spm.gds" <<'PY'
import struct, sys, os, pathlib
out = pathlib.Path(sys.argv[1]); out.parent.mkdir(parents=True, exist_ok=True)
def rec(rtype, dtype, payload=b""):
    if len(payload) % 2: payload += b"\x00"
    return struct.pack(">HBB", len(payload)+4, rtype, dtype) + payload
b  = rec(0x00,0x02, struct.pack(">h",600))                    # HEADER
b += rec(0x01,0x02, struct.pack(">12h", *([2026,8,31,0,0,0]*2)))  # BGNLIB
b += rec(0x02,0x06, b"spm.db")                                 # LIBNAME
b += rec(0x03,0x05, struct.pack(">dd", 1e-3, 1e-9))            # UNITS
b += rec(0x05,0x02, struct.pack(">12h", *([2026,8,31,0,0,0]*2)))  # BGNSTR
b += rec(0x06,0x06, b"spm")                                    # STRNAME
b += rec(0x07,0x00)                                            # ENDSTR
b += rec(0x04,0x00)                                            # ENDLIB
out.write_bytes(b)
print("hollow gds bytes:", len(b))
PY

# D: a 0-byte GDS at the same path.
mkdir -p "$W/D_zerobyte/phase3/stage4/gds"; : > "$W/D_zerobyte/phase3/stage4/gds/spm.gds"

for CASE in A_asis B_realgds C_hollowgds D_zerobyte; do
  say ""; say "=========================================================="
  say "CASE $CASE"
  say "=========================================================="
  D="$W/$CASE"
  # wipe the kit the FAILED run already left, so we measure the PRODUCER
  rm -rf "$D/phase3/stage4/foundry_handoff" "$D/reports/phase3/foundry_handoff_audit.json"
  say "[producer] foundry_handoff_pack_gen"
  run python3 "$P/foundry_handoff_pack_gen.py" "$D" --top spm
  say "    handoff dir now: $(ls "$D/phase3/stage4/foundry_handoff" 2>/dev/null | tr '\n' ' ')"
  say "[gate] foundry_handoff_package_check"
  run python3 "$P/foundry_handoff_package_check.py" "$D" --json "$D/reports/phase3/foundry_handoff_audit.json"
  say "    gate verdict: $(python3 -c "
import json,sys
try:
    d=json.load(open('$D/reports/phase3/foundry_handoff_audit.json'))
    print(d.get('verdict'), [f['rule'] for f in d.get('findings',[])])
except Exception as e: print('no audit json:', e)")"
done
say ""; say "DONE"
