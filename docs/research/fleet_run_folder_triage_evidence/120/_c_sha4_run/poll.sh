#!/bin/bash
# Bounded blocking poll (compact). $1 = seconds to block, under the 10-min Bash cap.
BUDGET=${1:-480}; RR=/home/reyerchu/_c_sha4_run; RC=$RR/f1.rc
END=$((SECONDS+BUDGET))
while [ $SECONDS -lt $END ]; do
  [ -f "$RC" ] && { echo "=== TERMINAL ==="; cat "$RC"; exit 0; }
  sleep 10
done
echo "STILL RUNNING (blocked ${BUDGET}s) @ $(date +%H:%M:%S)"
pgrep -f "_one_shot_runner.py $RR/f1" >/dev/null || echo "!! RUNNER GONE AND NO f1.rc -- INVESTIGATE"
echo "runner pids: $(pgrep -f "_one_shot_runner.py $RR/f1" | tr '\n' ' ')"
echo "heartbeat  : $(tail -1 $RR/f1.heartbeat)"
echo "log tail   : $(tail -1 $RR/runF.log | cut -c1-160)"
echo "newest     : $(find $RR/f1 -newermt '-12 minutes' -type f -printf '%TT %p\n' 2>/dev/null | sort | tail -3 | cut -c1-120 | tr '\n' '|')"
echo "load       : $(uptime | sed 's/.*load average/load/')"
P=$(pgrep -x openroad | head -1); [ -n "$P" ] && echo "openroad   : core-hours=$(awk '{printf "%.2f",($14+$15)/100/3600}' /proc/$P/stat) threads=$(awk '/^Threads/{print $2}' /proc/$P/status)"
