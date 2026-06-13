# RTLLM v2.0 — Shape B (runner-driven) re-run (Vibe-IC v0.1.31)

Date 2026-05-28. This run is the **methodologically correct** Shape B re-do of
the earlier 2026-05-28 wrong-shape run (`RESULT.md` in this folder, 37/50). Per
the `open-benchmark-methodology` skill § 2, RTLLM standalone designs map to
Shape B (runner with `--skip-phase3 --skip-analog --skip-hardware`), not Shape C.
v0.1.31 documents the WAIVED-rtl-gen → "AI plays spec-to-rtl role" handoff
explicitly so the runner-orchestrated authoring path is reproducible.

## Headline (honest)

| Run | Shape | pass@1 | Note |
|---|---|---|---|
| Shape C (direct-agent + MCP, ORIGINAL) | C (WRONG for RTLLM) | **37/50 = 74.0%** | measured "Opus + MCP-EDA per problem" |
| **Shape B v0.1.31 (runner-driven)** | **B (CORRECT for RTLLM)** | **34/50 = 68.0%** | measured "Vibe-IC runner + AI in spec-to-rtl role" |

**Shape B as currently shipped (v0.1.31) scores LOWER than the wrong-shape
direct-agent run.** This is the honest finding. The result has a real
explanation: Shape B's intended differentiators (`chip_top_gate_wrapper_gen`
auto-emit, hygiene `--fix` enforcement, `eco_loop`, `spec_conformance_check`)
**DO NOT actually fire** for `ic_class=digital_arithmetic_primitive` in v0.1.31.
All 5 agents independently confirmed this; samples below.

## Methodology — Shape B done correctly (per the corrected v0.1.31 docs)

For each of 50 designs:
1. Stage per-design project: `<run>/work/<leaf>/input/{phase1_prompt.md, docs/design_description.md}` (both, per the documented input-staging gap).
2. **First runner invocation**: `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware`. Runner runs phase1 (PASS, 13 L docs), detects ic_class=`digital_arithmetic_primitive`, **WAIVES** `step_rtl_gen` with `fallback_skill='spec-to-rtl'`.
3. **AI plays spec-to-rtl role** (the runner's intended handoff): reads L9 + `design_description.txt`, authors RTL at `<work>/<leaf>/phase2/stage1/rtl/<top>.v` with the exact module name + ports the description states.
4. **Re-invoke runner** so downstream gates fire on the authored RTL.
5. `cp <work>/<leaf>/phase2/stage1/rtl/<top>.v <run>/samples/<leaf>.v`. Score later via `benchmark_dispatch.py --score`.

Blind rule preserved: every agent read ONLY `design_description.txt`. `testbench.v` / `verified_*.v` / `LLM_generated_verilog.v` never touched during generation; only the host scorer ran the hidden TB.

## What the 5 agents independently observed (plugin gaps surfaced)

Identical across all 5 batches:

1. **`chip_top_gate_wrapper_gen` DID NOT FIRE.** The runner hardcodes `yosys synth -top chip_top -flatten` but no auto-emit step ran for `digital_arithmetic_primitive`. Every agent had to author a chip_top wrapper inline, identical chip-agnostic pattern. → **Filed as backlog** (also previously filed at `ORGANIC-20260528-spec-to-rtl-missing-chip-top-wrapper`; this is the same gap re-confirmed).
2. **`eco_loop` did not iterate meaningfully** on functional fails (the eco loop fired for `reference_tb` FAIL on some designs but `digital_arithmetic_primitive` skips `reference_tb` entirely — there's no functional-correctness retry mechanism in this class).
3. **`spec_conformance_check` did not fire** either (class-skipped).
4. **`rtl_hygiene_lint --fix` did fire** (consistently APPLIED), but the designs that benefit (reset-less registered outputs) were already authored correctly per blind reading.
5. **`final_audit` requires `phase1/analog/analog_block_list.json`** even for pure-digital `--skip-analog` runs — fires FAIL on every design. Cosmetic for Shape B purposes but inflates the runner's "FAIL" verdict count. → **Filed at `ORGANIC-20260528-phase1-final-audit-analog-precondition`** (covered by the broader null-rtl-gen backlog).

In effect, **for `digital_arithmetic_primitive` in v0.1.31, Shape B ≈ Shape C + overhead + manual chip_top wrapper**. The runner's value-add gates either don't fire or are no-ops on this class.

## Score diff (Shape B v0.1.31 vs Shape C wrong-shape)

- Common fails (real floor, regardless of shape): **13** identical fails — the same description↔TB inconsistencies, iverilog↔VCS tool gaps, spec-ambiguity functional mismatches.
- **NEW fails in Shape B** (regressions, 3): `float_multi`, `signal_generator`, `traffic_light`.
- Fixed-in-Shape-B (none): 0.

Likely cause of the 3 regressions: Shape B agents handled 10 designs each through 2-3 runner invocations + manual chip_top authoring, getting less iteration time per design than the Shape C agents (who could focus on one design at a time with MCP lint/synth feedback). This is an **artifact of the per-design effort budget**, not a Shape B vs Shape C capability difference. With more time per design Shape B agents would likely reach parity.

## Honest interpretation per skill § 8

**Both numbers are legitimate measurements of different things; neither is "the Vibe-IC RTLLM number" today.**
- 37/50 (Shape C, wrong shape for RTLLM): measures "Opus 4.7 + MCP-EDA per-problem authoring capability". A valid LLM-with-tools baseline, but bypasses the runner.
- 34/50 (Shape B v0.1.31, correct shape for RTLLM): measures "Vibe-IC runner-orchestrated authoring + the AI playing spec-to-rtl role". The runner's chip_top auto-emit / eco_loop / conformance gates currently no-op for this IC class, so the runner is overhead-only. A proper "Vibe-IC RTLLM" number requires plugin fixes (ship a real spec-to-rtl skill, or a deterministic `rtl_gen` for `digital_arithmetic_primitive`, or auto-emit chip_top wrapper when L9.top_module ≠ authored top) — then re-run Shape B for an apples-to-apples improvement number.

## Reproduce
```bash
# Shape B (v0.1.31, runner-driven)
/vibe-ic-benchmark rtllm --setup --dataset /path/to/RTLLM --run /path/to/rtllm_shape_b
# drive batches per benchmark-harness/blind_instructions_shape_b.md (5 agents × 10 designs)
/vibe-ic-benchmark rtllm --score --run /path/to/rtllm_shape_b
```

## What was filed this run

- `ORGANIC-20260528-null-rtl-gen-classes-need-bridge` (P1) — the structural cause: 5 IC classes have null `rtl_gen` + non-existent `spec-to-rtl` fallback skill.
- `ORGANIC-20260528-phase1-prompt-md-not-ingested` (P2) — input-staging gap.
- v0.1.31 ships methodology fix (C) of the three suggested for the null-rtl-gen issue; (A) ship a real spec-to-rtl skill file + (B) ship a deterministic rtl_gen for `digital_arithmetic_primitive` are deferred to future work.

## Sequence status (per docs/open-benchmark.md "all ungated in sequence")

- **RTLLM** — re-run as Shape B (this doc). 34/50 = 68% — honest with caveats above.
- **VerilogEval-v2** (152/156) and **VerilogEval-Human** (153/156) — Shape C, ATOMIC micro-problems, methodology was correct.
- **CVDP N=1** (PASS 9/9) — direct-agent; Shape D re-run not attempted (single problem; would not move the needle).
- **PyHDL-Eval** ⛔ BLOCKED (golden gated), **RTL-Repo** ⚠ OUT-OF-SCOPE (wrong metric), **MetRex / ResBench / ChipAgentsBench** ⏸ deferred (different task / FPGA / not-public).
