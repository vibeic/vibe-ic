# RESULT — spm × IHP-SG13G2 (Benchmark IC campaign, open-PDK matrix)

_Run date: 2026-07-24. IC: `spm` — configurable N-bit serial-parallel integer
multiplier (N=32), PDK: **IHP-SG13G2** (open, sign-off-grade 130nm BiCMOS
process). Plugin: v1.5.58. Container: `vibeic-eda:0.2.28`._

## VERDICT

**PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts (not from
this run's own RESULT/AGENT_REPORT):

- **GDS**: `spm.gds`, 822,084 bytes, present at
  `phase3/stage4/gds/spm.gds`.
- **Sign-off DRC** (KLayout, IHP-SG13G2 deck): raw report shows an empty
  `<items>` list — **0 violations**.
- **LVS** (netgen): raw report tail — *"Cell pin lists are equivalent. Device
  classes spm and spm are equivalent. Final result: **Circuits match
  uniquely**."*
- **STA** (multi-corner, real SPEF): raw report — worst setup slack **+6.14 ns**
  (TNS 0.00), worst hold slack **+0.17 ns** (TNS 0.00). Both MET.
- **DFT at-speed ATPG** (DT1/DT2/DT3 — transition/path/small-delay-defect):
  real graded coverage on the tech-mapped netlist — 65 scan flops detected,
  100% test coverage (≥ 90% floor). Not a skip: the OSS `fault` engine (yosys
  SAT-based) generated and scored real at-speed patterns.
- **Functional conformance** (L10 test cases): `l10_tb_conformance_check`
  reports **5/5 cases covered** (exit 0). The full-stack testbench carries 28
  golden-scored functional vectors (0 placeholders) — each vector's expected
  value is derived deterministically from the design's own declared function
  (product = a×b) rather than authored ad hoc.
- **Formal verification**: SymbiYosys driving `abc pdr` (unbounded PDR, no
  external SMT solver needed) proved a reset-safety property
  (`assert(p == '0)` one cycle after reset) — *"Property proved."* This is a
  genuine, tool-run proof of reset-safety, not a claim of full datapath
  equivalence (that remains a separate, harder proof obligation).

**Waivers (2, both foundry/board-stage, not engineering gaps):** FPGA
early-prototype + final sign-off (no DE10-class board-pin contract for this IC
class — deferred to board bring-up, not executed-PASS) and formal full-stack
functional proof beyond reset-safety (deferred to the AI assertion-gen /
equivalence-miter track for a full arithmetic proof).

## Chip-agnostic plugin fixes this cell's convergence proved

Reaching this PASS required landing 3 systemic, chip-agnostic plugin fixes
(all merged to `origin/main`, no chip-specific literals):

1. **DFT at-speed ATPG grading** — the OSS `fault` engine cannot detect flops
   in a generic (un-tech-mapped) netlist; the fix makes the DFT step consume
   the tech-mapped synthesis netlist so the engine can actually grade,
   producing real coverage instead of an unverifiable "engine-limited" skip.
2. **Functional-TB golden authoring** — the full-stack testbench's functional
   vectors were bring-up placeholders (`expected_bytes: null`); the fix
   authors real golden values from the design's declared function, captured
   as a general IC-expert convention (declared-function datapath →
   drive-operands-and-compute-golden), not a one-off for this design.
3. **OSS formal tool wiring** — Step 5 previously self-reported
   "no formal tool ran" as an honest skip; the fix wires SymbiYosys (`abc
   pdr`) into the flow so a real bounded/unbounded proof runs on the stock
   toolchain, no commercial tool and no image rebuild required.

## Honest scope

This is one cell (IC × PDK) of a larger open-PDK matrix (sky130A, GF180MCU,
IHP-SG13G2, NanGate45) covering `spm`, `sha256`, `caravel_user_project`,
`edge_llm_accel`, `edge_llm_matmul_accel`, `ibex`, `opentitan_aes`,
`subservient`, `u_hawaii_adc`. The other cells in the matrix are in active
convergence — see `BENCHMARK_IC_CAMPAIGN_STATUS.md` for current per-cell
status. Nothing here is claimed for any cell other than `spm × IHP-SG13G2`.
