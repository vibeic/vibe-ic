#!/bin/bash
# EVIDENCE (vibe-ic#1293): the harness run behind prob093_kmap_proof.py.
# Candidate = the K-map read literally off the prompt under the ONLY physically
# meaningful index mapping (4-to-1 mux select {a,b} -> binary input index).
# ORACLE-FOR-RCA: declared.
set -e
DS=/home/reyerchu/verilog-eval/dataset_code-complete-iccad2023
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
cat > "$W/cand.sv" <<'SV'
module TopModule (
  input c,
  input d,
  output [3:0] mux_in
);
  assign mux_in[0] = c | d;      // printed column ab=00
  assign mux_in[1] = 1'b0;       // printed column ab=01
  assign mux_in[2] = c | ~d;     // printed column ab=10
  assign mux_in[3] = c & d;      // printed column ab=11
endmodule
SV
cd "$W"
iverilog -Wall -Winfloop -Wno-timescale -g2012 -s tb -o sim \
    "$DS/Prob093_ece241_2014_q3_test.sv" "$DS/Prob093_ece241_2014_q3_ref.sv" cand.sv 2>&1 | sed 's/^/[compile] /'
vvp -n sim 2>&1 | grep -Ev "^VCD|dumpfile" | tail -20
