# Vibe-IC Field-Agent Run — RESULT

- **Project:** `/home/reyerchu/vibe-ic/benchmark_ic/4th__spm`
- **IC:** `spm` — N-bit serial-parallel multiplier (`p = (x × y) mod 2^N`, default size=32). Path B (digital, vendor docs).
- **Date:** 2026-05-26
- **Container:** `iic-eda` (hpretl/iic-osic-tools)

## Final verdict: **BLOCKED**

- **halted_at:** `phase2` (step `reference_tb`)
- **Reason (irreducible plugin gap):** The IC is correctly classified as `digital_arithmetic_primitive` (registry entry exists, `rtl_gen: null`, `fallback_skill: spec-to-rtl`). The deterministic phase2 verification gate `step_reference_tb` is **hardwired** to the AID-class half-duplex *protocol* testbench `tools/protocol_tb/aid_class_reference_tb.v`, which instantiates the DUT as `<top>(.clk, .reset_n, .id_bus)`. SPM's ports are `clk/rst/x/y/p`, so the TB **cannot even elaborate**:
  ```
  aid_class_reference_tb.v:84: error: port `reset_n' is not a port of u_dut.
  aid_class_reference_tb.v:84: error: port `id_bus' is not a port of u_dut.
  ```
  There is no datapath/arithmetic reference-TB path, no `tb_kind` switch, and no skip for this class. Therefore reference_tb can NEVER pass for a pure-datapath IC, regardless of RTL correctness → ECO loop exhausts → phase2 FAIL → orchestrator halts before phase3. Faking the `PROTOCOL_REFERENCE_TB_PASS` token or stubbing the protocol ports would be fabrication (forbidden). **Blocker is in the plugin, not the design.**

## Per-phase status

| Phase | Status | Notes |
|---|---|---|
| **phase1** | PASS | 14 L-docs in `phase1/generated_docs/` (L1-L13 + L8_TIMING_WAVEFORM), 100% extraction coverage, 0 `__TODO__`, 28 evidence entries. Required manual `--mode docs` (see close-loop #1). |
| **phase2** | FAIL → BLOCKED | RTL authored + verified (see below); SOF = **NO** (FPGA never compiled — reference_tb gate FAIL upstream). yosys netlist = **YES**. |
| **analog** | SKIPPED | L5 emitted 2 *low_confidence* false-positive stubs (dac, esd) from NEGATED doc mentions; SPM is pure digital — `--skip-analog` was evidence-justified. |
| **phase3** | NOT REACHED | netlist=n/a (orchestrator halts at phase2), DEF=NO, GDS=NO, DRC=NO, LVS=NO. |

## Key artifacts (existing, real)

- `phase1/generated_docs/L1..L13.json` (+ `L8_TIMING_WAVEFORM.json`) — 14 files
- `phase2/stage1/rtl/spm.v` — **authored, spec-derived SPM RTL** (shift-and-add bit-serial, NOT stubbed, NOT copied from a reference netlist)
- `phase2/stage1/rtl/tb_spm_golden.v` — self-checking golden TB
- `phase2/stage2/synth/netlist_yosys.v` — gate-level netlist `module spm(clk,rst,x,y,p)`, 304 cells (incl. 33 flops = 32-bit acc + 1-bit p)
- `phase2/stage2/synth/yosys.log`
- `plugin_output/declaration.json` — spec-required declaration (bit_order=LSB_first, reset=active_high, latency=1, size=32, encoding=signed_2c)
- `reports/orchestrator/{vibe_ic_one_shot,phase2_one_shot}.json`, `reports/phase1_one_shot.json`, `reports/final_summary.md`
- `run.log`, `phase1_run.log`, `phase2_rerun.log`

## RTL correctness — PROVEN (honest, not faked)

The authored SPM RTL was independently verified inside `iic-eda`:
- **Functional:** `SPM_GOLDEN_TB_PASS errors=0` over **5008 vectors** — all L7 corner cases (`x=0`, `y=0`, MAX_POS, MIN_NEG, `-1*-1`, `7*6`, etc.) + 5000 random — vs software golden `(x*y) mod 2^32`, LSB-first.
- **Synthesis:** yosys `synth -top spm` → exit 0, "Found and reported 0 problems", 304 cells, 33 flip-flops. Gate-level netlist emitted.

So a correct, synthesizable, simulation-proven design is still reported FAIL purely because of the wrong reference-TB template.

## EDA tools exercised inside iic-eda

| Tool | Ran? | Exit / result |
|---|---|---|
| **iverilog** | Yes | golden TB compile OK; protocol reference_tb FAIL (rc=2, port mismatch — see above) |
| **vvp** | Yes | golden sim PASS (5008 vectors) |
| **yosys** | Yes | synth PASS, exit 0, netlist emitted |
| openroad | No | phase3 not reached |
| klayout / magic | No | phase3 not reached (DRC) |
| netgen | No | phase3 not reached (LVS) |

## Close-loop actions taken (3 / max 3)

1. **Orchestrator skipped phase1** for the vendor-docs-only entry → phase2 `phase1_precheck` FAIL (0/13 L docs). **Fix:** ran `phase1_one_shot_runner.py . --mode docs` → 14 L docs @ 100% coverage. (Plugin defect: orchestrator `_need_phase1` returns False for Path B and never auto-runs phase1.)
2. **rtl_gen WAIVED** (`fallback_skill=spec-to-rtl`) → authored real SPM RTL from L1-L13 spec into `phase2/stage1/rtl/spm.v`, verified via golden TB (5008 vectors PASS) + yosys synth (PASS). NOT stubbed.
3. **reference_tb FAIL** (protocol-TB port mismatch). Diagnosed as irreducible plugin gap. Did NOT fabricate/stub. Recorded a corroborating reproduction on the existing ORGANIC backlog `ORGANIC-20260526-digital-arith-primitive-gate-class-path.yaml` (this exact gap was already filed from prior hash-core/CPU sessions; my SPM run is an independent third reproduction strengthening fix-(c): the class needs a non-protocol clk/rst/data reference TB).

## Honest assessment

The SPM design itself is sound and verifiably correct. The flow is blocked by a **registered-but-incomplete IC class**: `digital_arithmetic_primitive` waives RTL generation to the AI but provides no datapath verification TB and no class-aware gate skip-set, so phase2 hard-fails on the protocol testbench. This is a plugin-side gap (already tracked in the community backlog), not a design or toolchain failure. No phase3 backend (PnR/GDS/DRC/LVS) was produced because the orchestrator correctly halts at phase2. Marking **BLOCKED** rather than forcing a false PASS.
