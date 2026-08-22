#!/bin/bash
# ARM A reproduces jpadsite: hold -rotation_horizontal at R0, vary -rotation_vertical.
# ARM B is the decisive second arm: hold -rotation_vertical at R0, vary
# -rotation_horizontal. If the VERTICAL rows track the HORIZONTAL argument, the
# two arguments are crossed inside make_io_sites; if neither argument moves them,
# the vertical rows are hardcoded.
set -u
ok=1
for pair in "R0 R0" "R0 R90" "R0 R180" "R0 MX" "R90 R0" "R180 R0" "MX R0"; do
  set -- $pair
  ROTH=$1; ROTV=$2
  echo "########## ROTH=$ROTH ROTV=$ROTV"
  ROTH=$ROTH ROTV=$ROTV openroad -no_init -exit /w/one.tcl 2>&1 \
    | grep -E '^#####|^  p' || ok=0
done
openroad -version
[ "$ok" = 1 ] && echo "PROBE_COMPLETE" || echo "PROBE_INCOMPLETE"
