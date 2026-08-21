#!/bin/bash
# DIAGNOSTIC ONLY -- quantifies RESULT.md F-7 for one arm. Not a flow artefact.
# Same tool, same liberty, same SDC as the shipped power session; the only
# differences are the netlist (routed, not pre-PnR) and that a SPEF is read.
set -u
RUN="$(readlink -f "$1")"; OUT="$(mkdir -p "$2"; readlink -f "$2")"; CNAME="${3:-vibeic-eda-jppae2e}"
mkdir -p "$OUT"
NL="$RUN/phase3/stage3/pnr/spm_pnr.v"
SPEF="$RUN/phase3/stage3/extracted/spm.spef"
SDC="$RUN/phase3/stage3/pnr/constraint.sdc"
LIB=/foss/pdks/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
for f in "$NL" "$SPEF" "$SDC"; do
  [ -f "$f" ] || { echo "[CANNOT CHECK] $f absent: no diagnostic possible" >&2; exit 2; }
done
cat > "$OUT/power_postroute.tcl" <<EOF
# The activity basis is DECLARED the same way the runner's own power session
# declares it. Not a label of convenience: this script reads no VCD and no SAIF
# (grep it), so OpenSTA's activity model here is vectorless by construction.
puts "POWER_ANALYSIS_MODE: vectorless_sdc"
read_liberty $LIB
read_verilog $NL
link_design spm
read_spef $SPEF
read_sdc $SDC
report_power
EOF
timeout 900 docker exec "$CNAME" bash -lc "sta -no_init -exit $OUT/power_postroute.tcl" \
  > "$OUT/power_postroute.rpt" 2>&1 || { echo "[CANNOT CHECK] sta failed" >&2; exit 2; }
python3 - "$OUT" <<'PY'
import sys, json, pathlib
sys.path.insert(0,"/home/reyerchu/_jppae2e/wt/vibe-ic-marketplace/plugins/vibe-ic/programs")
from _ppa import power as P
D=pathlib.Path(sys.argv[1])
rep=P.read_power_report(D/"power_postroute.rpt")
if rep is None:
    print("[CANNOT CHECK] diagnostic power report not parseable", file=sys.stderr); raise SystemExit(2)
doc=P.power_document(rep, stage="post_route_extracted", scenario="diagnostic",
                     extra_scope={"process":"tt","voltage_v":1.8,
                                  "temperature_c":25.0,"mode":"functional"})
doc["_authored_by"]=("jppae2e lane DIAGNOSTIC, not a flow artefact (RESULT.md F-7). "
                     "Same tool/liberty/SDC as the shipped power session; the only "
                     "differences are the routed netlist and that a SPEF is read.")
(D/"power_postroute_records.json").write_text(json.dumps(doc,indent=2)+"\n")
t=[r for r in doc["metrics"] if r["metric"]=="power.total_w" and r["scope"].get("group")=="Total"][0]
print(f"diag[{D.name}]: total={t['value']} W basis={doc['activity']['basis']}")
PY
