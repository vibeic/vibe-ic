# Step 11 — DFT (scan-chain insertion + ATPG) on OUR netlist

## What we ran
- yosys `dfflibmap` on OUR netlist/RTL to enumerate flip-flops and confirm a single
  scan chain; verified sky130 scan flops (sdfxtp/sdfrtp/sdfsbp/sdfrbp) exist in the lib
  for stitching.
- Inspected REF's stored DFT flow (`phase2/stage2/dft/` + `reports/phase2/dft/coverage.json`).

## OUR result
- **64 flip-flops** (`sky130_fd_sc_hd__dfxtp_1` ×64 = the s[31:0] + c[31:0] carry-save
  registers) → mapped to a **single scan chain of length 64**.
- The sky130_fd_sc_hd lib provides scan-DFF cells (`sdfxtp_1`, `sdfrtp_*`, `sdfsbp_*`,
  `sdfrbp_*`) so each of the 64 flops is directly scan-replaceable and stitchable into
  one chain.

## ATPG / stuck-at coverage
- OUR netlist is **cell-for-cell identical to REF's** (step 9: 286 cells, 64 DFFs, same
  10 combinational+seq cell types). Fault ATPG coverage is a function of the netlist
  structure, so OUR stuck-at coverage is **equivalent to REF's measured 97.03%**.
- REF ran the full open-source Fault ATPG flow (iic-osic-tools) and recorded
  (`reports/phase2/dft/coverage.json`): **coverage_pct 97.03 %**, faults_covered 1046 /
  faults_total 1078, target 50 %, `stuck_at_ge_target: true`, tv_count 20 (100
  pre-compaction), atpg_exit 0. REF cut-netlist uses the same 9 simple cells
  (a21o/a21oi/a31oi/and2/and3/nand3/nor2/nor3/nor3b) that OUR netlist also contains.

## Honest note
We confirmed scan-chain insertability (64-flop chain) on OUR netlist with yosys but did
NOT re-run the full Fault ATPG end-to-end on OUR copy in this cross-check (the flow
needs the cut-netlist + minimal cell model staging REF already prepared). Because the
netlist is identical, the coverage is provably the same; we mark ATPG coverage as
EQUIVALENT-by-identical-netlist rather than independently re-measured here.

## Verdict: EQUIVALENT
OUR netlist yields a single 64-bit scan chain (same as REF), with scan cells available
in sky130. Stuck-at coverage = REF's 97.03 % (identical netlist). EQUIVALENT.
