# CVDP — v0.1.22 + MCP-EDA, agentic (N=1 runnable example)

## Scope (honest)
CVDP's full 1,500+ set is GATED (NVIDIA/Turing access). The public host copy has only the
`example_dataset` (1 problem per category), and of the `no_commercial` (Icarus-runnable) examples
just **one** is a complete agentic problem with a cocotb harness: `cvdp_agentic_fixed_arbiter_0001`
(cid003/easy). So this is an **N=1** demonstration of the agentic + MCP-EDA loop, not a pass-rate.

## Pipeline (genuinely MCP-EDA, agentic)
Agent read `docs/specification.md` + the in-context `verif/fixed_priority_arbiter_tb.sv`, wrote
`rtl/fixed_priority_arbiter.sv`, and self-verified through the **MCP-EDA toolchain**:
- `eda_lint` (Verilator 5.044): **PASS** (0 errors/0 warnings)
- `eda_simulate` (Icarus, the in-context verif TB): **PASS 7/7** test cases
- `eda_synth` (Yosys, gf180): **PASS** — 64 cells, 1633 µm², 12 DFFs, no latches
Then scored by the HIDDEN harness `src/test_fixed_priority_arbiter.py` via **MCP `eda_cocotb`** (Icarus).

## Result: hidden harness FAIL (the override-direction ambiguity)
The hidden cocotb harness failed at **Test Case 3 (priority_override)**: DUT `grant=8'b00001000`
(bit 3) vs harness-expected `8'b00010000` (bit 4). Root cause is an **ambiguous spec phrase**:

> "If `priority_override` is non-zero … the **highest-priority bit** in `priority_override` is granted."

The agent read "highest-priority bit" as the **lowest index** — consistent with the spec's own `req`
rule two lines later ("scans `req` from bit 0 to 7 … the first active request (lowest index) is
granted"). The hidden harness expects the **opposite** index for the override. So a reading that is
*internally consistent with the spec's req convention* disagrees with the harness on the override
direction. This is the same class of inconsistency the earlier `DEMO_RESULT.md` flagged for this
exact problem (spec says *synchronous* reset; reference/TB require *asynchronous*).

Per discipline, the agent was NOT iterated against the hidden harness (that would be overfitting).
The blind agentic attempt's honest verdict on this one gated example is **FAIL on the hidden
harness**, attributable to a spec ambiguity — while the MCP-EDA toolchain (lint/sim/synth/cocotb)
itself ran cleanly end-to-end, which is what this N=1 exercise validates.

## MCP-EDA infra note
The mcp-eda-server runs the tools inside the `iic-eda` Docker container, which mounts only
`/home/reyerchu/AI_IC_design → /foss/designs`. Files outside that mount are not container-visible;
RTL/harness must be staged under `AI_IC_design/` and addressed as `/foss/designs/...`. `eda_cocotb`
also requires `work_dir` ≠ the testbench's directory (else a self-`cp` errors) and `harness_library`
present in `work_dir`.
