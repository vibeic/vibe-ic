#!/bin/bash
# One rewrite-fidelity check: candidate RTL == BASELINE RTL, through the shipped
# gate.  Its verdict is the gate's, not this script's.
set -u
V="$1"; OFFSET="${2:-0}"; EVID="${3:-}"
ROOT=/home/reyerchu/_jxlayer
P=/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic
IMG=ghcr.io/vibeic/vibeic-eda:0.3.13
CN=jxeq-$V
PROJ=$ROOT/equiv2/$V
mkdir -p "$PROJ"
cp -a "$ROOT/src2/phase1" "$PROJ/" 2>/dev/null
docker rm -f "$CN" >/dev/null 2>&1
docker run -d --name "$CN" --user 1000 -v /home/reyerchu:/home/reyerchu \
   -v /home/reyerchu/AI_IC_design:/foss/designs "$IMG" --skip sleep infinity >/dev/null 2>&1
ARGS=(--baseline-rtl-dir "$ROOT/rtl2/base" --candidate-rtl-dir "$ROOT/rtl2/$V"
      --top spm --container "$CN" --json "reports/equiv_$V.json")
if [ "$OFFSET" != "0" ]; then
  ARGS+=(--latency-offset "$OFFSET" --latency-free-evidence "$EVID" --reset rst --clock clk)
fi
timeout 2400 python3 "$P/programs/crosslayer_rewrite_equivalence.py" "$PROJ" "${ARGS[@]}" \
   > "$ROOT/logs/equiv_$V.log" 2>&1
echo "$V rc=$?" >> "$ROOT/logs/equiv_summary.txt"
docker rm -f "$CN" >/dev/null 2>&1
