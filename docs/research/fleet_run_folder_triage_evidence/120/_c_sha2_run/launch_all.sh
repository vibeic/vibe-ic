#!/bin/bash
cd /home/reyerchu/_c_sha2_run
./launch_d0.sh > d0.log 2>&1 &
./launch_d1.sh > d1.log 2>&1 &
./launch_d2.sh > d2.log 2>&1 &
wait
echo "ALL_THREE_ARMS_FINISHED"
for a in d0 d1 d2; do echo "=== $a tail ==="; tail -5 $a.log; done
