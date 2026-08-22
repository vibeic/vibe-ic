#!/bin/bash
# The SAME gate, the SAME relation, the SAME engine — a longer time budget.
# `equiv_induct` on a candidate that changes the accumulator's STATE ENCODING
# needs to unroll far enough for the two state spaces to be forced together;
# the default 1800 s stopped it mid-way at induction step ~19.  Raising the
# budget does not weaken the check: an unproven point stays unproven.
set -u
V="$1"; TMO="${2:-21600}"
ROOT=/home/reyerchu/_jxlayer
P=/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic
IMG=ghcr.io/vibeic/vibeic-eda:0.3.13
CN=jxeqL-$V
PROJ=$ROOT/equivL/$V
mkdir -p "$PROJ"; cp -a "$ROOT/src2/phase1" "$PROJ/" 2>/dev/null
docker rm -f "$CN" >/dev/null 2>&1
docker run -d --name "$CN" --user 1000 -v /home/reyerchu:/home/reyerchu \
   -v /home/reyerchu/AI_IC_design:/foss/designs "$IMG" --skip sleep infinity >/dev/null 2>&1
timeout $((TMO+600)) python3 "$P/programs/crosslayer_rewrite_equivalence.py" "$PROJ" \
   --baseline-rtl-dir "$ROOT/rtl2/base" --candidate-rtl-dir "$ROOT/rtl2/$V" \
   --top spm --container "$CN" --timeout "$TMO" \
   --json "reports/equiv_$V.json" > "$ROOT/logs/equivL_$V.log" 2>&1
echo "L:$V rc=$?" >> "$ROOT/logs/equiv_summary.txt"
docker rm -f "$CN" >/dev/null 2>&1
