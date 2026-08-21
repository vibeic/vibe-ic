#!/bin/bash
# One search trial: fresh project, fresh container, phase3 with the trial knobs,
# then extraction. CPU + peak RSS come from the trial's OWN container cgroup, so
# the cost figures are that trial's and nobody else's.
set -u
IDX="$1"; DIE="$2"; DENS="$3"; SPARE="$4"
ROOT=/home/reyerchu/_jppae2e
P=$ROOT/wt/vibe-ic-marketplace/plugins/vibe-ic
SRC=/home/reyerchu/campaign_pdk/spm/cell_gf180mcuD_20260722
IMG=ghcr.io/vibeic/vibeic-eda:0.3.13
T=$(printf 't%03d' "$IDX")
PROJ=$ROOT/run/trials/$T
LOG=$ROOT/logs/trials/$T.log
CNAME=jppae2e-$T
mkdir -p "$ROOT/logs/trials" "$ROOT/run/trials" "$ROOT/records/trials/$T"

rm -rf "$PROJ"; mkdir -p "$PROJ"
cp -a "$SRC/input" "$SRC/phase1" "$SRC/phase2" "$PROJ/" || { echo "COPY_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; }

docker rm -f "$CNAME" >/dev/null 2>&1
CID=$(docker run -d --name "$CNAME" --user 1000 \
      -v /home/reyerchu:/home/reyerchu -v /home/reyerchu/AI_IC_design:/foss/designs \
      "$IMG" --skip sleep infinity 2>/dev/null)
if [ -z "$CID" ]; then echo "CONTAINER_START_FAILED" > "$ROOT/records/trials/$T/fatal"; exit 3; fi
CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
cpu_before=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat" 2>/dev/null || echo "")

w0=$(date +%s.%N)
if [ "$DIE" = "auto" ]; then DIEARG="auto"; else DIEARG="$DIE"; fi
VIBEIC_OPENROAD_THREADS=3 timeout 3600 python3 "$P/programs/phase3_one_shot_runner.py" "$PROJ" \
   --top-name spm --pdk sky130A --container "$CNAME" \
   --die-um "$DIEARG" --util "$DENS" --spare-density "$SPARE" > "$LOG" 2>&1
RC=$?
w1=$(date +%s.%N)
cpu_after=$(awk '/^usage_usec/{print $2}' "$CG/cpu.stat" 2>/dev/null || echo "")
mem_peak=$(cat "$CG/memory.peak" 2>/dev/null || echo "")
docker rm -f "$CNAME" >/dev/null 2>&1

python3 - "$T" "$IDX" "$DIE" "$DENS" "$SPARE" "$RC" "$w0" "$w1" "$cpu_before" "$cpu_after" "$mem_peak" <<'PY'
import json,sys,os
T,IDX,DIE,DENS,SPARE,RC,w0,w1,cb,ca,mp = sys.argv[1:12]
ROOT="/home/reyerchu/_jppae2e"
out=os.path.join(ROOT,"records","trials",T)
cost={"wall_seconds": round(float(w1)-float(w0),3)}
if cb and ca: cost["cpu_seconds"]=round((int(ca)-int(cb))/1e6,3)
else: cost["cpu_seconds"]=None; cost["cpu_seconds_reason"]="container cgroup cpu.stat unreadable"
if mp: cost["peak_rss_mb"]=round(int(mp)/1048576.0,1)
else: cost["peak_rss_mb"]=None; cost["peak_rss_mb_reason"]="container cgroup memory.peak unreadable"
json.dump({"trial":T,"index":int(IDX),
           "knobs":{"die_um":DIE,"placement_density":DENS,"spare_cell_density":SPARE},
           "runner_rc":int(RC),"cost":cost},
          open(os.path.join(out,"run.json"),"w"), indent=2)
PY

python3 "$ROOT/tools/extract_run.py" "$PROJ" "$ROOT/records/trials/$T" --label "$T" >> "$LOG" 2>&1
echo "$T rc=$RC done"
