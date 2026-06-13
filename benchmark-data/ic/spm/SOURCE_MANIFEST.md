# SOURCE_MANIFEST — spm

Provenance of every RTL module in this design. Per benchmark_clean METHODOLOGY
rule 3: each module is tagged GENERATED (authored from the L-docs by spec-to-RTL)
or REUSED-IP (external source, with name + license + commit/URL + which doc it
satisfies). Doc->silicon PASS credit applies only to the GENERATED portion.

## Modules

| Module | File | Provenance | Satisfies | Notes |
|---|---|---|---|---|
| `spm` | `phase2/stage1/rtl/spm.v` | **GENERATED** | L2 (p = x*y mod 2^N), L3 (port list clk/rst/x/y/p + param size), L8 (single top module), L9 (timing/floorplan contract incl. multi-corner sign-off) | Authored from the design documents only. **CARRY-SAVE LSB-first bit-serial array** (per-stage saved sum bit + LOCAL saved carry bit; one full adder per stage with NO cross-bit carry ripple → critical path is a single FA, independent of N), synchronous active-high reset, registered serial output (latency 1). Re-architected from an earlier ripple-carry-accumulator form purely from timing analysis under the R3 freedom L2/L7 grant; the rearchitecture was authored from the L-docs, NOT by reading the upstream/reference RTL. No upstream/reference RTL read or copied at any point of authoring. |

## Physical-only additions (flow-inserted, not RTL IP)

| Item | Where | Provenance | Notes |
|---|---|---|---|
| Design-for-ECO spare-cell pool | `phase3/stage3/pnr/spare_cells.json` + DEF/netlist | **GENERATED** (flow-inserted) | 7 spare std cells (inv/nand2/nor2/mux2/aoi/dff, density 0.0232) placed by the flow's Step-18 spare-insertion path as FIXED, tied-off, `dont_touch`/`keep` instances after placement / before CTS. These are PHYSICAL-only ECO-budget cells emitted by `phase3_one_shot_runner.py --spare-density`; they are **GENERATED/flow-inserted, NOT REUSED-IP** — they carry no design logic, are unconnected/tied-off, and exist solely to provide metal-only-ECO readiness. Coverage PASS + preservation intact (removed 0). |

## Summary

- **GENERATED: 1 / 1 RTL module (100%)** (+ 1 GENERATED flow-inserted physical-only spare-cell pool)
- **REUSED-IP: 0 / 1 module (0%)**

No IP reuse. The single top module `spm` was authored from the L1-L9 design
documents. The behavioral golden used for verification was independently derived
from the L2/L7 math (`(x*y) mod 2^N`, LSB-first bit stream) and is an ORACLE,
not an input. The upstream reference RTL
(`/home/reyerchu/AI_IC_design/4th_benchmark/spm_e2e/phase2/stage1/rtl/spm.v`)
was NOT read during authoring; it is used only at the VERIFY stage as a second
oracle for cross-checking.
