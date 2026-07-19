# SOURCE_MANIFEST — edge_llm_accel

Provenance of every RTL module in this design. Per benchmark_clean METHODOLOGY
rule 3: each module is tagged GENERATED (authored from the design intent /
L-docs by the IC Expert Agent) or REUSED-IP (external source, with name +
license + commit/URL). Doc→silicon PASS credit applies only to the GENERATED
portion.

## Modules

| Module | File | Provenance | Satisfies | Notes |
|---|---|---|---|---|
| `edge_llm_accel` (top) | `phase2/stage1/rtl/edge_llm_accel.v` | **GENERATED** | L2 (INT4 GEMM + fused dequant contract), L3 (port list), L4 (scratchpad layout + start/busy/done), L8 (20× fakeram45_2048x39 integration), L9 (unsigned ports, 100 MHz) | Streaming controller + 20-bank scratchpad mux + 64-way fused dequant (saturating `(acc×scale)>>>shift` → INT16). Authored by the vibe-IC IC Expert Agent (Claude) from its own design intent on 2026-07-18 (prior session of the same campaign); the L1–L9 input docs formalize that same intent, and the RTL was verified against the docs in this session's Phase 2. Architecture concepts referenced from public literature (Gemmini arXiv:1911.09925, OpenGeMM, NVDLA) — **concept-level only, no external code read or copied**. |
| `int4_systolic`, `pe` | `phase2/stage1/rtl/int4_systolic.v` | **GENERATED** | L2 (4096 INT4 MAC/cycle capacity; R3 dataflow freedom exercised as weight-stationary systolic) | Parametric ROWS×COLS weight-stationary systolic INT4 MAC array (TPU-MXU style), ACCW=20 accumulators. Same authorship as above. |

## Hard-macro / platform assets (NOT RTL IP, disclosed per L8)

| Item | Where | Provenance | Notes |
|---|---|---|---|
| `fakeram45_2048x39` LEF + Liberty | `input/pdk_local/fakeram45/` | **PLATFORM ASSET** — OpenROAD-flow-scripts Nangate45 platform (v3.0), BSD-3-Clause | Abstract SRAM macro (no transistor GDS — FakeRAM placeholder standard to all Nangate45 flows, incl. the Kimi K3 demo). 20 instances. |
| `fakeram45_2048x39.v` behavioral model | `input/pdk_local/fakeram45/` | **GENERATED** (this session) | Simulation-only behavioral model written to the macro's LEF pin list + L8 datasheet contract (1-cycle sync read, bit-masked write). Modeled on the FakeRAM interface convention; not used by synthesis (Liberty blackbox) nor PnR. |
| NangateOpenCellLibrary (std cells) | container `/foss/pdks/nangate45/` | **PLATFORM ASSET** — Si2/NanGate FreePDK45 Open Cell Library, Apache-2.0 | Staged from the OpenROAD-flow-scripts nangate45 platform into the open_pdks `libs.ref/` layout (see RESULT.md environment section). |

## Summary

- **GENERATED: 3 / 3 RTL modules (100%)** — top + systolic array + PE
- **REUSED-IP: 0 / 3 modules (0%)** — no external RTL read or copied
- SRAM macros are abstract platform assets (disclosed above), not RTL IP.

Honest ordering disclosure: this is a SELF-DESIGNED benchmark IC (no upstream
reference implementation exists). The RTL was first authored from the design
intent in the prior session of this same campaign (2026-07-18), before these
input docs were written down; the docs formalize the identical intent and the
Phase-2 gates + L7 verification in THIS clean-run are what bind RTL ↔ docs.
The golden model used in verification is independently derived from the L2
math and is an ORACLE, not an authoring input.
