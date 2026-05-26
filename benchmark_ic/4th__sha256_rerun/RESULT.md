# Vibe-IC Full-Flow Result — sha256 (4th__sha256_rerun)

- **Project**: `/home/reyerchu/vibe-ic/benchmark_ic/4th__sha256_rerun`
- **IC**: `sha256` — pure-digital NIST FIPS-180-4 SHA-256 hash accelerator (memory-mapped register interface)
- **Date**: 2026-05-26
- **Container**: `iic-eda`
- **Detected IC class**: `digital_arithmetic_primitive`

## Final verdict: **BLOCKED**

`overall verdict = FAIL, halted_at = phase2`. Classified **BLOCKED** (not plain FAIL)
because the blocker is an **irreducible plugin class-handling gap**, not broken RTL or a
missing toolchain. The generated RTL is real and synthesizes/compiles/simulates cleanly;
Phase 2 cannot pass only because its strict-structural gate suite is hard-coded for
protocol/analog IC classes and has no path for a pure-digital arithmetic primitive.
Honest convergence would require either fabricating analog/protocol spec data (forbidden)
or changing plugin code.

## halted_at + reason

- **halted_at**: `phase2` (so `analog` and `phase3` were SKIPPED — never reached).
- **Reason**: Phase 2 final verdict FAIL. Functional steps PASS, but the strict-structural
  compliance gate fails on 12 protocol/analog-class checkers that are inapplicable to a
  `digital_arithmetic_primitive`. Plus the reference-TB step selects a protocol-class TB
  (`aid_class_reference_tb.v`) that expects an `id_bus` port the hash core does not have.

## Per-phase status

### Phase 1 — PASS (after close-loop fix)
- **14/14 L docs** in `phase1/generated_docs/L*.json` (L1-L13 + L8_TIMING_WAVEFORM).
- 100% extraction coverage, 0 `__TODO__` stubs, 38 evidence entries.
- Real extractions from vendor Markdown (digest width 256 bits, K constants, clk 38.6 MHz).
- `ic_name` reported as UNKNOWN_IC — honest: the vendor docs do not state an explicit IC name.

### Phase 2 — FAIL (functional artifacts produced; structural gate blocks)
- **RTL files (5)** in `phase2/stage1/rtl/`:
  - `sha256.v`, `sha256_core.v` (554 LOC, real round logic), `sha256_w_mem.v`,
    `sha256_k_constants.v` (all 64 K constants) — pulled from secworks/sha256
    (BSD-2-Clause, git_clone, SHA256-attested in `plugin_output/declaration.json`).
  - `chip_top.v` — AI-authored integration wrapper (catalog-glue-author skill),
    8-port pass-through matching the L3 spec, attribution comments + SPDX.
- **SOF**: YES — `phase2/stage1/fpga/output_files/chip_top.sof` (3.2 MB, real Quartus build).
- **Synth netlist**: YES — `phase2/stage2/synth/netlist_yosys.v` (2.5 MB, 23082 cells).
- **Reference sim**: PASS — `phase2/stage1/sim/pass.flag` + `results.xml` verdict PASS.
- Phase2 step verdicts: phase1_precheck PASS, detect_ic_class PASS, full_stack_tb_gen PASS,
  rtl_gen WAIVED→catalog-glue-author, **yosys_synth PASS, qsf_gen PASS, sdc_gen PASS,
  fpga_compile PASS**, reference_tb FAIL (wrong TB class), fpga_burn FAIL (structural gate),
  final_audit FAIL.

### Analog — SKIPPED (never reached; also genuinely N/A — L6 states pure-digital, no analog)
### Phase 3 — SKIPPED (never reached: synth/PnR/GDS/DRC/LVS not run)
- netlist: n/a (phase3) · DEF: NO · GDS: NO · DRC: NO · LVS: NO

## Key artifact paths (exist)
- `phase1/generated_docs/L1_DATASHEET.json` … `L13_LAB_CALIBRATION.json` (14 files)
- `phase2/stage1/rtl/{sha256.v,sha256_core.v,sha256_w_mem.v,sha256_k_constants.v,chip_top.v}`
- `phase2/stage2/synth/netlist_yosys.v` + `phase2/stage2/synth/yosys.log`
- `phase2/stage1/fpga/output_files/chip_top.sof` + `phase2/stage1/fpga/compile.log`
- `phase2/stage1/fpga/{chip_top.qsf,chip_top.sdc}`
- `phase2/stage1/sim/{pass.flag,results.xml}`
- `plugin_output/declaration.json` (rtl_strategy=catalog_lookup_plus_ai_glue, license audit BSD-2-Clause)
- `reports/orchestrator/{vibe_ic_one_shot.json,phase2_one_shot.json}`
- `reports/audit/flow_compliance_check.log`
- `/home/reyerchu/vibe-ic/community/backlogs/ORGANIC-20260526-digital-arith-primitive-gate-class-path.yaml`

## EDA tools exercised (inside iic-eda) + errors
- **Yosys 0.33** — synth chip_top → 23082 cells (1807 DFF, 12718 NAND, 6215 NOR, 2342 NOT).
  Exit clean ("End of script", CPU 3.98s). **No errors.**
- **Quartus Prime 23.1std Lite** — full FPGA compile, generated 3.2 MB SOF. **No errors.**
- **iverilog** — reference_tb: elaboration **error** on `aid_class_reference_tb.v:84:
  port 'id_bus' is not a port of u_dut` (wrong protocol-class TB selected; not an RTL fault).
  The design's own full-stack reference sim verdict = PASS.
- KLayout / OpenROAD / Netgen — **NOT exercised** (phase3 never reached).

## Close-loop actions taken (honest, no fabrication)
1. **Phase1 was SKIPPED by the orchestrator** for the vendor-docs-only Path B, leaving 0 L
   docs (phase2 precheck failed). Diagnosed two orchestration bugs; worked around by running
   `phase1_one_shot_runner.py --mode docs` explicitly → 14 L docs (doc-extraction track).
2. **rtl_gen WAIVED** with `fallback_skill=catalog-glue-author` and an IP match
   (crypto/sha256_core). Invoked the skill: pulled the secworks SHA256 core via
   `ip_catalog_pull.py` (BSD-2-Clause, permissive) and authored `chip_top.v`. Verified with
   `iverilog -g2012 -t null` (exit 0, host + container). This unblocked synth/compile/sim.
3. **l9_rtl_pin_consistency FAIL** (RTL has cs/we not in L9): backfilled cs/we into L9
   top_ports from the L3 interface table (L3 tabulates both verbatim) → gate now PASS.
   Spec-backed, not fabrication.
4. **l8_clock_domains_typed FAIL** (shallow `L9.clocks` clk stub): enriched it with the
   38.6 MHz / period 25.9 ns / role=primary that L1 already states → gate now PASS.
5. **L5 false analog blocks** (dac/esd): corrected to `no_analog=true`. L6 explicitly says
   "sha256 為純數位 ... 無 analog / mixed-signal 內容"; the dac/esd were keyword false
   positives from negated mentions ("Plugin 不需...DAC", "❌ ESD strategy"). This exposed
   the analog keyword-detect-vs-emit **deadlock** (see below).

## Honest assessment
- The RTL is genuine and high-quality: a battle-tested open-source SHA-256 core + a thin,
  spec-faithful wrapper. It synthesizes to ~23k cells, compiles to a real FPGA bitstream,
  and its reference simulation passes. Nothing was stubbed or faked to force a green.
- The remaining 12 Phase-2 structural-gate failures are **all plugin class-handling bugs**
  for `digital_arithmetic_primitive`, in two clusters:
  - **Analog false-positive deadlock (6 gates)**: analog_content_detected_must_emit_l5 +
    analog_block_coverage/hardmacro/mixed_signal_cosim/flow_compliance/digital_interface.
    The detector counts NEGATED/❌-excluded "ESD"/"DAC" mentions as analog content; declaring
    analog blocks forces the full analog flow, declaring none triggers a contradiction error.
    No honest state passes.
  - **Protocol/typed-depth cluster (5 gates + reference_tb)**:
    protocol_ip_simulation_required, l3_opcode_argument_constraints, l1_electrical_specs_typed_depth,
    l12_behavioral_sequences_steps_typed, l_doc_structured_field_count — all demand
    opcode/electrical/protocol-step data a memory-mapped digital primitive legitimately lacks;
    and the reference-TB step picks a protocol-class TB.
  - Plus provenance_output_hash_completeness (1 provenance fault).
- These cannot be cleared without fabricating spec data (forbidden) or patching plugin code,
  so the result is **BLOCKED**, and a chip-agnostic enhancement was filed to the community
  backlog (sanitize check PASS, 0 violations). NOT auto-submitted to GitHub — awaiting user
  consent.
