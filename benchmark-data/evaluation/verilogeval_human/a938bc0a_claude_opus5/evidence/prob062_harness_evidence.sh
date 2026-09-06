#!/bin/bash
# EVIDENCE (vibe-ic#1293): Prob062_bugs_mux2 is a TRUE_FLOOR (A2 prompt/oracle
# contradiction).  Run the benchmark's OWN harness (hidden testbench + hidden
# golden ref) against the SPEC-FAITHFUL repair derived from the prompt's own
# embedded reference expression, and record the mismatch count.
# ORACLE-FOR-RCA: declared.  Not an authoring path.
set -e
DS=/home/reyerchu/verilog-eval/dataset_code-complete-iccad2023
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
# The candidate: the prompt's embedded expression  (~sel & a) | (sel & b)
# repaired ONLY for the declared width bug (`output out` -> `output [7:0] out`),
# which is the single defect the prompt's own text admits.
cat > "$W/cand.sv" <<'SV'
module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);
    assign out = ({8{~sel}} & a) | ({8{sel}} & b);
endmodule
SV
cd "$W"
iverilog -Wall -Winfloop -Wno-timescale -g2012 -s tb -o sim \
    "$DS/Prob062_bugs_mux2_test.sv" "$DS/Prob062_bugs_mux2_ref.sv" cand.sv 2>&1 | sed 's/^/[compile] /'
vvp -n sim 2>&1 | grep -Ev "^VCD|dumpfile" | tail -20
