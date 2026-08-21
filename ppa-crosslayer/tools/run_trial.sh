#!/bin/bash
# One cross-layer trial: fresh project, fresh container, the candidate RTL
# staged into the flow's own rtl dir, phase3 at the SHIPPED PnR defaults unless
# overridden. CPU + peak RSS come from the trial's OWN container cgroup.
set -u
T="$1"; VARIANT="$2"; DIE="${3:-auto}"; DENS="${4:-0.30}"; SPARE="${5:-0.02}"; RF="${6:-none}"
ROOT=/home/reyerchu/_jxlayer
P=/home/reyerchu/vibe-ic-wt-jxlayer/vibe-ic-marketplace/plugins/vibe-ic
IMG=ghcr.io/vibeic/vibeic-eda:0.3.13
PROJ=$ROOT/run/trials/$T
LOG=$ROOT/logs/trials/$T.log
CNAME=jxlayer-$T
mkdir -p "$ROOT/logs/trials" "$ROOT/run/trials" "$ROOT/records/trials/$T"

rm -rf "$PROJ"; mkdir -p "$PROJ"
cp -a "$ROOT/src2/input" "$ROOT/src2/phase1" "$ROOT/src2/phase2" "$PROJ/" || {
  echo "COPY_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; }
# stage the candidate RTL: the flow's own rtl dir is the actuator
rm -f "$PROJ"/phase2/stage1/rtl/*.v "$PROJ"/phase2/stage1/rtl/*.sv
cp "$ROOT/rtl2/$VARIANT"/*.v "$PROJ/phase2/stage1/rtl/" || {
  echo "RTL_STAGE_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; }
# synthesis-strategy lever: the ONLY actuator the shipped flow exposes is the
# design's own input/reference_flow. `none` stages nothing at all.
if [ "$RF" != "none" ]; then
  mkdir -p "$PROJ/input/reference_flow"
  cp "$ROOT/reference_flow/$RF"/* "$PROJ/input/reference_flow/" || {
    echo "RF_STAGE_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; }
fi

docker rm -f "$CNAME" >/dev/null 2>&1
CID=$(docker run -d --name "$CNAME" --user 1000 \
      -v /home/reyerchu:/home/reyerchu -v /home/reyerchu/AI_IC_design:/foss/designs \
      "$IMG" --skip sleep infinity 2>/dev/null)
if [ -z "$CID" ]; then echo "CONTAINER_START_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; fi
CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
cpu_before=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat" 2>/dev/null || echo "")

w0=$(date +%s.%N)
VIBEIC_OPENROAD_THREADS=3 timeout 3600 python3 "$P/programs/phase3_one_shot_runner.py" "$PROJ" \
   --top-name spm --pdk sky130A --container "$CNAME" \
   --die-um "$DIE" --util "$DENS" --spare-density "$SPARE" > "$LOG" 2>&1
RC=$?
w1=$(date +%s.%N)
cpu_after=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat" 2>/dev/null || echo "")
mem_peak=$(cat "$CG/memory.peak" 2>/dev/null || echo "")
docker rm -f "$CNAME" >/dev/null 2>&1

python3 - "$T" "$VARIANT" "$DIE" "$DENS" "$SPARE" "$RF" "$RC" "$w0" "$w1" "$cpu_before" "$cpu_after" "$mem_peak" <<'PY'
import json,sys,os
T,VAR,DIE,DENS,SPARE,RF,RC,w0,w1,cb,ca,mp = sys.argv[1:13]
ROOT="/home/reyerchu/_jxlayer"
out=os.path.join(ROOT,"records","trials",T); os.makedirs(out,exist_ok=True)
cost={"wall_seconds": round(float(w1)-float(w0),3)}
if cb and ca: cost["cpu_seconds"]=round((int(ca)-int(cb))/1e6,3)
else: cost["cpu_seconds"]=None; cost["cpu_seconds_reason"]="container cgroup cpu.stat unreadable"
if mp: cost["peak_rss_mb"]=round(int(mp)/1048576.0,1)
else: cost["peak_rss_mb"]=None; cost["peak_rss_mb_reason"]="container cgroup memory.peak unreadable"
json.dump({"trial":T,
           "levers":{"rtl_variant":VAR,"synthesis_strategy":RF},
           "pnr_knobs":{"die_um":DIE,"placement_density":DENS,"spare_cell_density":SPARE},
           "runner_rc":int(RC),"cost":cost},
          open(os.path.join(out,"run.json"),"w"), indent=2)
PY

python3 "$ROOT/tools/extract_area.py" "$PROJ" "$ROOT/records/trials/$T" --label "$T" >> "$LOG" 2>&1
echo "$T rc=$RC done"
