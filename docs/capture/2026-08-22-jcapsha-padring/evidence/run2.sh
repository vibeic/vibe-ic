#!/bin/bash
set -u
ok=1
for pair in "R0 R0" "R90 R0" "R0 R90"; do
  set -- $pair
  echo "########## ROTH=$1 ROTV=$2"
  ROTH=$1 ROTV=$2 openroad -no_init -exit /w/loc.tcl 2>&1 | grep -E '^#####|^  p' || ok=0
done
[ "$ok" = 1 ] && echo "PROBE_COMPLETE" || echo "PROBE_INCOMPLETE"
