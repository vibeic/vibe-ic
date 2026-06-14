# Benchmark IC #7 — caravel_user_project — Clean-Room Run r2 (round 2)

Plugin under test: **root tree v0.3.37** (#643 TB-gen + #644 phase1 power-port
split both landed). Project: `_bench7_caravel_v1034_cleanroom/caravel_r2v`.

## Shape
**Shape A / D — full runner, SoC integration.** Driven through the root-tree
`vibe_ic_one_shot_runner.py` (NOT the installed cache, NOT `/vibe-ic-*` slash
commands). Design = stock upstream Caravel `user_project_wrapper` +
`user_proj_example` + counter (Wishbone / LA / GPIO). Value = Caravel SoC
integration + OpenLane PnR + sign-off, not the trivial counter.

## Run command (root-tree runner, cwd = repo root)
```
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
    _bench7_caravel_v1034_cleanroom/caravel_r2v \
    --pdk sky130A --ic-name caravel_user_project \
    --top-name user_project_wrapper --die-um 2920x3520
```
RTL authored into the runner's expected path
`phase2/stage1/rtl/` (stock upstream `user_project_wrapper.v` +
`user_proj_example.v` + a self-contained `defines.v` for the caravel-harness
`MPRJ_IO_PADS` constant) per the `spec-to-rtl`/`catalog-glue-author` handoff,
then re-invoked so gates fire. Blind: no spm_pilot checkout, no reference GDS.

## #643 audit — VERDICT: **RESOLVED**
Audited the runner's OWN generated full-stack TB
(`phase2/stage1/sim_full_stack/tb_USE_POWER_PINS_full.v`, the first emit; later
`tb_user_project_wrapper_full.v` after data recovery — both audited):

| Check | Round-1 (broken) | Round-2 v0.3.37 | Evidence |
|---|---|---|---|
| (a) illegal identifiers | `wire vccd1_/_vssd1;` (`/` in ident) | **none** | only `/` is in legal `` `timescale 1ns / 1ps `` comment; grep for `_/_`, `[A-Za-z]/[A-Za-z]` in idents = empty |
| (b) multi-bit port widths | every bus declared 1-bit | **correct `[msb:lsb]`** | `reg [3:0] wbs_sel_i`, `[31:0] wbs_dat_i`, `[127:0] la_data_in`, `[37:0] io_in`, `[28:0] analog_io`, `[2:0] user_irq` — all match L9 |
| (c) power-pin tie | driven as `*_drive` stimulus | **TIED** | line 33-38: `// v0.3.36 (#643) — supply pin tied` `wire vccd1; assign vccd1 = 1'b1;` / `wire vssd1; assign vssd1 = 1'b0;` |
| (d) iverilog compile | rc=9 | **rc=0** | `iverilog -g2012 tb...full.v upp_stub.v` in `hpretl/iic-osic-tools:latest` → `IVERILOG_RC=0` |

The round-1 root cause (illegal-ident leak + ignored width + POWER-pin
stimulus drive) is **fully fixed**. The chain now advances past that point.

## SOLE ACCEPTANCE CRITERION — verdict (verbatim, this run)
```
Steps: 59 total (4/48 executed PASS, 1 DEFERRED via waiver)
  PASS=3  FAIL=6  MISSING=38 (25 blocked-by-upstream of step 3)  WAIVED-DEFERRED=1  SKIPPED=10  VACUOUS-PASS=1
Overall: FAIL  (strict=True)
```
- executed PASS = 3/48 (same headline number as round 1) but the chain
  progressed *structurally further* and the blocker moved through three NEW
  root causes down to an irreducible plugin-internal contradiction.

## How far the chain progressed vs round 1 (was 3/48, halted at TB-gen defect)
| Step | r1 | r2 | Note |
|---|---|---|---|
| phase1_precheck | PASS | PASS | 24/13 L docs |
| detect_ic_class | PASS | PASS | `bus_peripheral` |
| rtl_gen | WAIVED | WAIVED | `bus_peripheral` rtl_gen=null → spec-to-rtl handoff (intended) |
| full_stack_tb_gen | FAIL (uncompilable TB) | **SKIP (clean skeleton)** | #643 fix: connectivity-only skeleton emitted, no illegal idents/widths |
| Step 1 Spec-to-RTL | PASS | **PASS** | RTL authored into runner path |
| Step 2 Lint | PASS | **PASS** | RTL clean |
| yosys_synth | PASS | **PASS** | 189 cells, top=user_project_wrapper |
| Step 9 Synthesis | PASS | **PASS** | mapped netlist |
| reference_tb | FAIL (illegal TB) | **FAIL (new root cause)** | now: TB vs RTL structural mismatch; ultimately `-DUSE_POWER_PINS` not passed |
| Steps 3-6, 39 | FAIL/MISSING | FAIL/MISSING | cascade from reference_tb gate |
| Steps 7-38 PnR/DRC/LVS/STA/sign-off | MISSING | MISSING | blocked-by-upstream(step 3) |

**Net:** #643 RESOLVED; the chain advanced from "halts on an uncompilable TB"
to "halts on a 2-error TB↔RTL port mismatch that is a plugin-internal
USE_POWER_PINS inconsistency", with three intermediate phase1-extraction gaps
uncovered and recovered along the way.

## Close-loop recovery (AI judgment applied to project DATA, not the plugin)
The reference_tb FAIL was peeled in three steps, each surfacing a distinct
chip-AGNOSTIC gap (captured below), recovering the project DATA each time:

1. `iverilog rc=3: Unknown module type: USE_POWER_PINS` → L1.ic_name and
   L9.top_module were mis-extracted as the macro `USE_POWER_PINS`
   (`l1_ic_name_fallback`). Recovered DATA: top_module = `user_project_wrapper`
   (the L1 "Top deliverable"). → gap 1.
2. `iverilog rc=29: port io_in20..io_in26 not a port of u_dut` → L9.top_ports
   carried 27 phantom scalar ports `io_in0..io_in26` (width=None, no evidence)
   "promoted from L1.pin_table", none of which exist in any input doc.
   Recovered DATA: stripped the 27 phantoms (48→21 ports = the real interface).
   → gap 2.
3. `iverilog rc=2: port vccd1/vssd1 not a port of u_dut` → the real RTL gates
   those ports behind `` `ifdef USE_POWER_PINS ``; the runner's reference_tb
   compile never defines it. **PROVEN**: identical files compile **rc=0 WITH
   `-DUSE_POWER_PINS`, rc=2 WITHOUT**. This is a plugin-internal contradiction
   (the #643 TB-gen emits the power connections; the compile half hides the
   ports) → **irreducible in-flow** (cannot be fixed in project DATA). → gap 3.

Gaps 1+2 are real phase1-extraction defects recovered in the project DATA to
prove they were the sole intermediate blockers; gap 3 is the controlling plugin
defect and is the reason the in-flow runner cannot legitimately pass
reference_tb on this IC class without a plugin fix.

## NEW chip-AGNOSTIC file-worthy gap candidates (all Bucket A — deterministic)
1. **L1 ic_name accepts an HDL/PDK conditional-compile macro as the chip name.**
   Step: phase1 / L1 datasheet-gen ic_name pick. Symptom: `ic_name=USE_POWER_PINS`
   though L1 declares `**Project name:** caravel_user_project` /
   `**Top deliverable:** user_project_wrapper`; the all-caps validator
   `tok.isupper() and len>=2` accepts the macro. why_systematic: every
   sky130/Caravel/OpenLane SoC mentions `USE_POWER_PINS` (+ SYNTHESIS/FORMAL/GL/
   SIM/FUNCTIONAL/MPRJ_IO_PADS); all pass the validator. fix_area:
   `phase1_doc_one_shot_runner.py` — add an HDL/PDK-macro stoplist family AND a
   natural-language `**Project name:**`/`**Top deliverable:**` explicit-declaration
   tier (today only YAML frontmatter `ic:`/`ic_name:`/`chip:` is honoured).
   severity: HIGH (cascades to L9.top_module → reference_tb rc=3).
2. **phase1 fabricates per-bit scalar ports from a bus, then L9 promotes them.**
   Step: phase1 / L1.pin_table → L9.top_ports promotion. Symptom: 27 phantom
   `io_in0..io_in26` (width=None, no evidence) in pin_table & top_ports; no
   input doc contains them; L3 has one `io_in | 38` row. TB then wires
   nonexistent ports → rc=29. why_systematic: any packed bus with bit-indexing
   text can trigger spurious scalar expansion (la_data_in[127:0],
   wbs_dat_i[31:0], any AXI/Wishbone bus). fix_area:
   `phase1_doc_one_shot_runner.py` — never emit scalar `<bus><digits>` when a
   packed `<bus>` (width>1) already exists; reject width=None+no-evidence rows;
   cardinality post-check L3-table vs top_ports. severity: HIGH (21→48 inflation).
3. **reference_tb compile omits `-DUSE_POWER_PINS` while #643 TB-gen connects
   the power pins — plugin-internal contradiction.** Step: phase2 /
   reference_tb compile (`_reference_tb_generic_full_stack`, ~line 2919) vs
   `step_full_stack_tb_gen` (#643). Symptom: `port vccd1/vssd1 not a port of
   u_dut`, rc=2; proven rc=0 WITH `-DUSE_POWER_PINS`, rc=2 WITHOUT.
   why_systematic: power-pin gating behind `USE_POWER_PINS` is the universal
   sky130/Caravel/OpenLane convention; every such top reproduces it. fix_area:
   `phase2_one_shot_runner.py` — add `-DUSE_POWER_PINS` to the reference_tb (and
   oracle) iverilog/sv2v commands when the TB connects io=POWER/GROUND ports or
   the RTL contains `` `ifdef USE_POWER_PINS ``; or `` `ifdef ``-guard the power
   connections in `step_full_stack_tb_gen` to keep the two halves consistent.
   severity: HIGH (gating step; FAIL cascades to 25 blocked-by-upstream steps;
   NOT recoverable in project DATA — it is the plugin's own compile command).

Structured records: `_runlogs/recoveries_r2.json` (3 records, all Bucket A).

## Environment-only blockers (tool/PDK/docker) — separated from plugin gaps
- iverilog is not on the container's default `$PATH`; lives at
  `/foss/tools/iverilog/bin/iverilog` (needs `export PATH=/foss/tools/iverilog/bin:$PATH`
  with `--entrypoint bash`). Environment-only; the runner handles this internally
  via `shutil.which` inside its own container invocation. NOT a plugin gap.
- No commercial sim/synth available → iverilog (Icarus) for sim, yosys for synth
  — standard Vibe-IC open-tool substitution. NOT a plugin gap.
- No DE10-Lite board attached → Step 6 FPGA early / Step 39 FPGA final cannot run
  on-board (BFM-only). Environment-only for a pure-digital SoC. NOT a plugin gap.
- Phase 3 PnR/DRC/LVS never reached (blocked-by-upstream at step 3), so no
  phase3 step was time-boxed; the run completed in ~31 s with no hanging step.

## Tool substitutions (disclosed)
- EDA in docker `hpretl/iic-osic-tools:latest` (`--entrypoint bash`, PATH export).
- iverilog (Icarus) substitutes for a commercial simulator; yosys for synthesis.

## Residual triage (A–H rubric, open-benchmark-methodology §4)
- **Cat C (tool/runner gap), chip-AGNOSTIC, file-worthy** — gap 3, the
  `reference_tb` ↔ `step_full_stack_tb_gen` `USE_POWER_PINS` contradiction. The
  controlling residual; reproduces on every USE_POWER_PINS-gated SoC.
- **Cat C (extraction gap), chip-AGNOSTIC, file-worthy** — gap 1 (macro token
  wins ic_name) + gap 2 (fabricated per-bit scalar ports). Both reproduce on any
  SoC datasheet that mentions an all-caps HDL/PDK macro or shows bus bit-indexing.
- **NOT FAIL-of-design / not agent-fixable-RTL** — the design RTL is correct:
  `yosys_synth` PASS (189 cells), standalone `iverilog` of the RTL = rc=0, and
  the TB+RTL compile rc=0 the moment `-DUSE_POWER_PINS` is supplied. Every FAIL
  is a runner/extractor defect, not a spec-to-RTL miss.
- **#643 (round-1 root cause)** — RESOLVED, not a residual.
- **WAIVED-DEFERRED (1)** — `L5_ADI_SPEC` analog stub, legitimately N/A for a
  pure-digital SoC; deferred, not a defect.
- **Bucket D (discard)** — none. (`MPRJ_IO_PADS` self-contained `defines.v` is
  design-input authoring, a caravel-harness constant, not a systematic gap;
  handled as input authoring, not filed.)

## Capture / role boundary
3 chip-AGNOSTIC Bucket-A recovery candidates recorded at
`_runlogs/recoveries_r2.json`. Per benchmark-agent role + this task's hard
rules: **captured + reported only** — NOT self-applied to the plugin, NO GitHub
issue filed. The Core Agent absorbs them (chip-AGNOSTIC) and the number is
re-confirmed on a fresh clean-room round.

## Verdict summary
`Overall: FAIL (strict=True)`, executed PASS = 3/48. **#643 RESOLVED** (the
round-1 uncompilable-TB root cause is gone; Spec-to-RTL/Lint/Synthesis now
PASS). The chain is now blocked at a *new, deeper* irreducible plugin gap — the
`reference_tb` compile omits `-DUSE_POWER_PINS` while the #643 TB-gen connects
the power pins — behind which two phase1-extraction gaps (macro-as-ic_name,
fabricated scalar bus ports) were also uncovered. The loop has NOT converged: a
fresh clean-room re-run still surfaces 3 plugin fixes. Re-run round 3 after they
land to confirm reference_tb passes and the chain reaches Phase-3 PnR/sign-off.
