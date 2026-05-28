# RTLLM v0.1.44 — asyn_fifo close-loop under Verilator (honest verdict)

## Headline

| Metric | v0.1.43 | v0.1.44 (Verilator-verified) | Δ |
|---|---|---|---|
| RTLLM pass@3 close-loop | 48/48 = 100.0% (2 scorer-gap excluded; raw 48/50 = 96.0%) | **49/50 = 98.0% raw** (no exclusion) | +1 pp honesty |
| RTLLM PASS designs | 48 + 2 SKIP | 49 PASS, 1 FAIL | — |

## What changed

The v0.1.43 RTLLM scoring excluded 2 designs as `scorer_substitution_gap` (TB used SV-2012 features iverilog 12 doesn't support: array-literal init in `ring_counter`, `break;` in `asyn_fifo`). v0.1.44 re-ran both under Verilator 5.020 to verify the claim per `open-benchmark-methodology` § 4 triage rubric.

- **ring_counter** → Verilator binary stdout `=========== Your Design Passed ===========`. Real gap, recovered to PASS. Sample unchanged.
- **asyn_fifo** → Verilator binary stdout `===========Error===========`. The TB compiles cleanly under Verilator; the prior v0.1.37 sample is a REAL functional fail. The gap claim was wrong.

## asyn_fifo close-loop attempt (3 retries, blind contract)

Per `open-benchmark-methodology` § 3 blind contract, the close-loop agent could read only `design_description.txt` + the prior failing sample + Verilator stdout PASS/FAIL. Hidden `testbench.v`, `verified_*.v`, and the oracle `.txt` data files were refused.

| Attempt | Verdict | What changed | Result |
|---|---|---|---|
| 0 (v0.1.37 baseline) | FAIL | Registered RAM read on rclk, registered wfull/rempty | TB Error |
| 1 | FAIL | Cummings-style top-2-bit-inverted full-check, RAM read still registered | Same FAIL — `rdata=0x00` then `0x01, 0xab, ...` confirmed stale-by-1 read |
| 2 | FAIL | Kept synchronous RAM read inside posedge rclk always block | Same stale-by-1 pattern via DEBUG_FIFO trace |
| 3 | FAIL | RAM read changed to combinational (`always @(*) if (renc) rdata = mem[raddr]`) | **Data path now correct** — 16/16 byte readback matches writes. But TB still Errors → residual must be in `wfull`/`rempty` flag sample timing. |
| 4 (extra) | FAIL | wfull/rempty also changed to combinational (`assign`) | TB still Errors. Cannot further bisect without inspecting `testbench.v` or oracle `.txt` files (refused per § 3 blind contract). |

## Captured Bucket-B patterns (in `agents/ic-expert-agent.md`)

1. **async-FIFO readback — zero-cycle RAM read aligns with TB sample timing.** Standard Cummings async-FIFO knowledge. Combinational RAM read recovers byte-perfect readback.

2. **async-FIFO TB sample-timing limits blind close-loop.** Past the data-path fix, full/empty flag sample-timing requires oracle/TB inspection that the blind contract forbids. Honest verdict: report residual as a real fail, not a tooling artifact.

## Honest path forward

asyn_fifo is recorded as a real RTLLM FAIL in v0.1.44. Recovery would require either:
- A Verilator-trace-based diagnostic that infers TB timing from the FAIL pattern (legitimate; the diff signal is the AI's own observation), OR
- A close-loop run that explicitly opens the blind contract (no longer pass@3 in the academic sense), OR
- A future RTLLM dataset revision that documents the TB's flag sample timing in the prompt.

The 49/50 = 98.0% figure stands as the honest v0.1.44 baseline.

## Tool substitution disclosure (per § 3)

- Verilator 5.020 (Debian 5.020-1) — `--timing --binary --Wno-fatal`
- cwd = design_dir for `$readmemh` resolution
- iverilog 12 retained as primary scorer; Verilator used only for the 2 designs flagged as scorer_substitution_gap candidates in v0.1.37
- Substitution verified per § 4 triage rubric: a gap claim is only defensible if a tool supporting the missing feature confirms PASS. ring_counter's claim held; asyn_fifo's did not.
