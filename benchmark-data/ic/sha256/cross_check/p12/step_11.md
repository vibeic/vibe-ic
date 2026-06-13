# Step 11 — DFT scan-chain insertion + ATPG coverage on OURS vs REF

**Verdict: BETTER-THAN-REF** (OURS 94.09 % stuck-at; REF stored 0 % DESIGN_DEFICIT)

## What ran
`eda_dft` (Fault open-source, MCP, pdk=sky130) on OUR netlist
(`synth/ours_netlist.v`): internal scan-chain stitch + boundary scan + ATPG,
clock=clk, reset=reset_n (active-low), tv_count=200.

## Result (OURS)
- Internal scan chain successfully constructed — length **1584** (all FFs).
- Boundary scan cells chained — length 75.
- **Total scan-chain length: 1659.**
- Fault sites: 35182 in 8879 gates + 3176 ports.
- **Stuck-at coverage: 94.085 %.**
- Test vectors: 200 generated → compacted to **60** (70 % compaction), 31 essential.

## REF comparison
REF's stored `reports/phase2/dft/coverage.json`:
- `scan_inserted: false`, `stuck_at_coverage_percent: 0.0`,
  `deficit_class: DESIGN_DEFICIT` — "yosys flow did not stitch scan chain;
  sequential ATPG cannot initialise state … Re-run after proper scan stitch".

## Finding
OURS is **strictly better** than REF on DFT. On OUR netlist the Fault scan
stitch + ATPG flow completed and reached **94 % stuck-at coverage** (well above
the 50 % target and the practical 85 % bar), with a clean 1659-cell scan chain.
REF's archived run never stitched a chain (0 %, flow-config gap). Same
open-source toolchain (Fault), same PDK — the difference is that the scan
insertion completed cleanly here. This is a real, reproduced positive result.
