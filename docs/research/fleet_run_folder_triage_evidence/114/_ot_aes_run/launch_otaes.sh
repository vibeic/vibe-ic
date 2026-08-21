#!/usr/bin/env bash
# launch_otaes.sh — wait for the pinned image, create a dedicated container,
# and launch vibe_ic_one_shot_runner.py fully detached (setsid) so it
# survives the SSH session that started it. Runs on 192.168.1.114.
set -uo pipefail

IMAGE="ghcr.io/vibeic/vibeic-eda:0.2.76"
CONTAINER="vibeic-eda-otaes3"
RUNDIR="/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808"
PLUGIN="/home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-ic/1.10.2"

echo "WAITING_FOR_IMAGE $IMAGE"
tries=0
until docker images "$IMAGE" --format '{{.Repository}}:{{.Tag}}' | grep -qx "$IMAGE"; do
  sleep 10
  tries=$((tries+1))
  if [ "$tries" -gt 240 ]; then
    echo "FATAL: image never appeared after 40 min"
    exit 1
  fi
done
echo "IMAGE_READY $IMAGE"

docker rm -f "$CONTAINER" >/dev/null 2>&1 || true

docker run -d --name "$CONTAINER" \
  -v /home/reyerchu:/home/reyerchu \
  -v /home/reyerchu/AI_IC_design:/foss/designs \
  "$IMAGE" --skip sleep infinity
rc=$?
echo "CONTAINER_CREATE rc=$rc"
if [ "$rc" -ne 0 ]; then
  echo "FATAL: docker run failed"
  exit 1
fi

sleep 5
docker ps --filter "name=^${CONTAINER}\$" --format 'RUNNING: {{.Names}} {{.Image}} {{.Status}}'

if [ ! -d "$RUNDIR" ]; then
  echo "FATAL: run dir missing: $RUNDIR"
  exit 1
fi
if [ ! -f "$PLUGIN/programs/vibe_ic_one_shot_runner.py" ]; then
  echo "FATAL: plugin runner missing: $PLUGIN"
  exit 1
fi

cd "$RUNDIR" || exit 1

setsid nohup python3 "$PLUGIN/programs/vibe_ic_one_shot_runner.py" \
  "$RUNDIR" --container "$CONTAINER" --require-image "$IMAGE" \
  --pdk sky130A --ic-name opentitan_aes --top-name chip_top --no-dashboard \
  > "$RUNDIR/runner_r1.log" 2>&1 < /dev/null &
disown
RPID=$!
echo "RUNNER_LAUNCHED pid=$RPID"

sleep 30
if kill -0 "$RPID" 2>/dev/null; then
  echo "ALIVE $RPID"
  tail -15 "$RUNDIR/runner_r1.log"
else
  echo "DIED — log tail:"
  tail -40 "$RUNDIR/runner_r1.log"
fi
