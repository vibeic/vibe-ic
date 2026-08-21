#!/usr/bin/env bash
# Graceful wind-down: let the in-flight TDF ATPG step finish, then stop the
# runner BEFORE it dispatches the next step. No mid-solve kill.
ATPG_PID=1734459      # transition_fault_atpg_run.py (current step)
RUNNER=3984702        # vibe_ic_one_shot_runner.py
PH3=1394370           # phase3_one_shot_runner.py
LOG=/home/reyerchu/_ot_aes_run/clean_run_v1.10.2_sky130A_20260808/winddown.log
{
  echo "winddown armed $(date -Is): waiting for ATPG pid $ATPG_PID to finish"
  while kill -0 "$ATPG_PID" 2>/dev/null; do sleep 5; done
  echo "ATPG step finished $(date -Is) — stopping runner before next step"
  kill -TERM "$PH3" 2>/dev/null && echo "SIGTERM -> phase3 $PH3"
  sleep 3
  kill -TERM "$RUNNER" 2>/dev/null && echo "SIGTERM -> runner $RUNNER"
  sleep 10
  kill -0 "$RUNNER" 2>/dev/null && echo "runner still up after TERM (left alone; no SIGKILL)" || echo "runner exited cleanly"
  echo "winddown done $(date -Is)"
} >> "$LOG" 2>&1
