# Step 12 — Post-DFT optimization / buffering

## What we ran
- Post-scan re-synthesis/opt on OUR netlist: yosys `synth -flatten; dfflibmap; abc
  -liberty; opt; stat` (the same flow that produces the mapped netlist, exercised after
  the scan-flop enumeration of step 11).
- Compared to REF's stored post-DFT artifacts (`phase2/stage2/synth/post_dft_netlist.v`,
  `phase2/stage2/dft/scan_netlist.v`).

## OUR result
- After scan-flop mapping the design is still **64 flops + ~222 combinational cells**;
  `opt` finds nothing further to remove (`Finished fast OPT passes. There is nothing
  left to do.`). The carry-save core has no redundant logic to buffer away. No timing
  violations to fix (step 10 STA already MET at all corners with large margin), so no
  buffer/sizing ECO is required post-scan.
- The scan chain adds the scan-enable mux into each flop (sdf* cell) — a fixed
  per-flop area increment, no new critical path (scan path is timed only in shift mode).

## REF result
- REF produced `post_dft_netlist.v` and `scan_netlist.v` (the scan-stitched + post-opt
  netlists). REF's flow is the same yosys+Fault open-source path. REF reports atpg_exit
  0 and timing closure carried into phase3.

## Honest note
This step is light for spm: a 286-cell combinational-heavy carry-save core with no
timing pressure needs no post-DFT buffering/resizing ECO. We confirmed `opt` is a no-op
and STA is already met; we did not author a new buffered post-DFT netlist because none
is warranted. REF likewise carries its scan netlist forward unchanged into PnR.

## Verdict: EQUIVALENT (no post-DFT opt needed)
Both OUR and REF require no functional post-DFT buffering — scan stitching adds the
per-flop scan mux only, timing stays met. EQUIVALENT.
