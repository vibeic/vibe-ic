#!/bin/bash
# DIAGNOSTIC ONLY — quantifies the surviving F-7 for one arm. Not a flow
# artefact and never substituted for one without saying so.
# Same tool, same liberty, same SDC as the shipped power session; the only
# differences are the netlist (routed, not pre-PnR) and that a SPEF is read.
set -u
RUN="$(readlink -f "$1")"; mkdir -p "$2"; OUT="$(readlink -f "$2")"
IMG=ghcr.io/vibeic/vibeic-eda@sha256:24b5074b686386084f87a03712b5f76e475201fbf2f2583b112d6e2c3eb55f3d
NL="$RUN/phase3/stage3/pnr/spm_pnr.v"
SPEF="$RUN/phase3/stage3/extracted/spm.spef"
SDC="$RUN/phase3/stage3/pnr/constraint.sdc"
LIB=/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
for f in "$NL" "$SPEF" "$SDC"; do
  [ -f "$f" ] || { echo "[CANNOT CHECK] $f absent: no diagnostic possible" >&2; exit 2; }
done
cat > "$OUT/power_postroute.tcl" <<TCL
# The activity basis is DECLARED the way the runner's own power session declares
# it. Not a label of convenience: this script reads no VCD and no SAIF (grep
# it), so OpenSTA's activity model here is vectorless by construction.
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
read_liberty $LIB
read_verilog $NL
link_design spm
read_spef $SPEF
read_sdc $SDC
report_power
TCL
timeout 900 docker run --rm --user 1000 -v /home/reyerchu:/home/reyerchu "$IMG" --skip \
   sta -no_init -exit "$OUT/power_postroute.tcl" > "$OUT/power_postroute.rpt" 2>&1 \
   || { echo "[CANNOT CHECK] sta failed for $RUN" >&2; exit 2; }
python3 - "$OUT" <<'PY'
import sys, json, pathlib
sys.path.insert(0, "/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic/programs")
from _ppa import power as P
D = pathlib.Path(sys.argv[1])
rep = P.read_power_report(D / "power_postroute.rpt")
if rep is None:
    print("[CANNOT CHECK] diagnostic power report not parseable", file=sys.stderr)
    raise SystemExit(2)
doc = P.power_document(rep, stage="post_route_extracted", scenario="diagnostic",
                       extra_scope={"process": "tt", "voltage_v": 1.8,
                                    "temperature_c": 25.0, "mode": "functional"})
doc["_authored_by"] = (
    "cross-layer lane DIAGNOSTIC, not a flow artefact. The shipped phase-3 "
    "power session links phase2/stage2/synth/spm_synth.v and reads no SPEF, so "
    "its number is pre-place-and-route while its own report header says "
    "post-PnR. Same tool / liberty / SDC as that session; the only differences "
    "are the ROUTED netlist and that a SPEF is read.")
(D / "power_postroute_records.json").write_text(json.dumps(doc, indent=2) + "\n")
t = [r for r in doc["metrics"] if r["metric"] == "power.total_w"
     and r["scope"].get("group") == "Total"][0]
print(f"diag[{D.name}]: total={t['value']} W basis={doc['activity']['basis']}")
PY
