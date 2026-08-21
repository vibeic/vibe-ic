#!/bin/bash
# Round-4 sha256 x sky130A launcher.
# The runner is executed in the FOREGROUND of this script; this script itself is
# what gets detached with setsid.  Its whole job is to guarantee that a terminal
# record (RUNNER_RC) is written no matter how the runner ends -- round 3 lost a
# verdict because the guard line never ran.
set -u

RUN_ROOT=/home/reyerchu/_c_sha4_run
PROJ=$RUN_ROOT/f1
export CLAUDE_PLUGIN_ROOT=/home/reyerchu/_c_sha4_scratch/plugin_f/vibe-ic-marketplace/plugins/vibe-ic
export PDK_ROOT=/foss/pdks
export OMP_NUM_THREADS=6
export PYTHONUNBUFFERED=1

RC_FILE=$RUN_ROOT/f1.rc
HB=$RUN_ROOT/f1.heartbeat
rm -f "$RC_FILE"

# Terminal record on ANY exit path: normal return, SIGTERM, SIGINT, SIGHUP.
_stamp() {
  local rc=$1 how=$2
  printf 'RUNNER_RC=%s\nHOW=%s\nAT=%s\n' "$rc" "$how" "$(date -Is)" > "$RC_FILE"
}
trap '_stamp 143 SIGTERM; kill -TERM $CHILD 2>/dev/null; exit 143' TERM
trap '_stamp 130 SIGINT;  kill -TERM $CHILD 2>/dev/null; exit 130' INT
trap '' HUP

printf 'START %s\npid %s\n' "$(date -Is)" "$$" > "$HB"
( while kill -0 $$ 2>/dev/null; do
    printf 'ALIVE %s supervisor_pid=%s\n' "$(date -Is)" "$$" >> "$HB"
    sleep 60
  done ) &
HBPID=$!

cd "$PROJ"
nice -n 5 python3 "$CLAUDE_PLUGIN_ROOT/programs/vibe_ic_one_shot_runner.py" \
  "$PROJ" \
  --pdk sky130A --ic-name sha256 \
  --container vibeic-eda-f256 \
  --require-image ghcr.io/vibeic/vibeic-eda:0.2.51 \
  --no-dashboard &
CHILD=$!
wait $CHILD
RC=$?
kill $HBPID 2>/dev/null
_stamp "$RC" normal
exit $RC
