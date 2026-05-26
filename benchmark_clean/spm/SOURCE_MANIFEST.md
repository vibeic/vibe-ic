# SOURCE_MANIFEST — spm

Provenance of every RTL module in this design. Per benchmark_clean METHODOLOGY
rule 3: each module is tagged GENERATED (authored from the L-docs by spec-to-RTL)
or REUSED-IP (external source, with name + license + commit/URL + which doc it
satisfies). Doc->silicon PASS credit applies only to the GENERATED portion.

## Modules

| Module | File | Provenance | Satisfies | Notes |
|---|---|---|---|---|
| `spm` | `phase2/stage1/rtl/spm.v` | **GENERATED** | L2 (p = x*y mod 2^N), L3 (port list clk/rst/x/y/p + param size), L8 (single top module), L9 (timing/floorplan contract incl. multi-corner sign-off) | Authored from the design documents only. **CARRY-SAVE LSB-first bit-serial array** (per-stage saved sum bit + LOCAL saved carry bit; one full adder per stage with NO cross-bit carry ripple → critical path is a single FA, independent of N), synchronous active-high reset, registered serial output (latency 1). Re-architected from an earlier ripple-carry-accumulator form purely from timing analysis under the R3 freedom L2/L7 grant; the rearchitecture was authored from the L-docs, NOT by reading the upstream/reference RTL. No upstream/reference RTL read or copied at any point of authoring. |

## Summary

- **GENERATED: 1 / 1 module (100%)**
- **REUSED-IP: 0 / 1 module (0%)**

No IP reuse. The single top module `spm` was authored from the L1-L9 design
documents. The behavioral golden used for verification was independently derived
from the L2/L7 math (`(x*y) mod 2^N`, LSB-first bit stream) and is an ORACLE,
not an input. The upstream reference RTL
(`/home/reyerchu/AI_IC_design/4th_benchmark/spm_e2e/phase2/stage1/rtl/spm.v`)
was NOT read during authoring; it is used only at the VERIFY stage as a second
oracle for cross-checking.
