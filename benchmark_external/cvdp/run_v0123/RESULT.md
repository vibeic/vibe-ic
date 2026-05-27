# CVDP — v0.1.23 + MCP-EDA, agentic (N=1)

## Scope
CVDP's full set is gated (NVIDIA/Turing). The only runnable public agentic example with a cocotb
harness is `cvdp_agentic_fixed_arbiter_0001` (cid003/easy). This is an N=1 demonstration of the
agentic + MCP-EDA loop, not a pass-rate.

## Pipeline (fresh blind agent, MCP-EDA)
Agent read `docs/specification.md` + the in-context `verif/fixed_priority_arbiter_tb.sv`, authored
`work/rtl/fixed_priority_arbiter.sv` blind, and self-verified:
- `eda_lint` (Verilator 5.044): **PASS** (0 err / 0 warn)
- `eda_simulate` (in-context TB, Icarus): **PASS 7/7**
- `eda_synth` (Yosys gf180): **PASS** — 71 cells, 12 DFFs, 0 latches, ~1677 µm²

## Result: hidden harness FAIL (1 pass / 8 fail of 9)
Scored by the HIDDEN `score/src/test_fixed_priority_arbiter.py` via MCP `eda_cocotb` (Icarus).
Dominant failure: **Test Case 8 — "grant should be zero after reset"** (DUT `grant=8'b00001000`).

Root cause = **spec ambiguity** (same class as the v0.1.22 N=1 run):
- The spec Port table literally says *"Active-high **synchronous** reset (clears all outputs)"*. The
  agent implemented synchronous reset faithfully; the harness's reset timing requires `grant` to
  clear the way an **asynchronous** reset would, so most cases (each preceded by a reset) cascade-fail.
- `priority_override` "highest-priority bit" direction is also under-specified (agent read lowest set
  index, internally consistent with the spec's own req-scan rule).

This fresh sample picked the **sync-reset** reading (8/9 fail); the v0.1.22 sample picked async (only
the override case failed). Both are honest blind readings of the same ambiguous spec. Per discipline,
the agent was **not** iterated against the hidden harness (no overfit). Toolchain (lint / in-context
sim / synth) was clean end-to-end — the failure is spec-side, not plugin/toolchain-side.
