#!/bin/bash
BPID=$(cat /home/reyerchu/_c_car14_scratch/runB.pid)
CPID=$(cat /home/reyerchu/_c_car14_scratch/control.pid)
deadline=$(( $(date +%s) + 3300 ))   # 55 min cap
while :; do
  b_alive=0; c_alive=0
  kill -0 "$BPID" 2>/dev/null && b_alive=1
  kill -0 "$CPID" 2>/dev/null && c_alive=1
  if [ $b_alive -eq 0 ] && [ $c_alive -eq 0 ]; then
    echo "BOTH_DONE"
    break
  fi
  if [ $(date +%s) -ge $deadline ]; then
    echo "SUPERVISOR_TIMEOUT b_alive=$b_alive c_alive=$c_alive"
    break
  fi
  sleep 30
done
echo "===== runB (skip-boundary=auto) tail ====="
tail -25 /home/reyerchu/_c_car14_scratch/runB.log
echo "===== control (boundary=off) tail ====="
tail -25 /home/reyerchu/_c_car14_scratch/control.log
