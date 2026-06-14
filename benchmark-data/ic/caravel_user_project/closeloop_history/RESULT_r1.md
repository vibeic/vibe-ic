# Benchmark IC #7 — caravel_user_project — Clean-Room Run r1 (round 1)

## Shape
**Shape A / D — full runner, SoC integration.** Driven through the root-tree
`vibe_ic_one_shot_runner.py` (NOT the installed cache, NOT `/vibe-ic-*` slash
commands). Design = stock upstream Caravel `user_project_wrapper` +
`user_proj_example` + `counter` (Wishbone / LA / GPIO counter). Value is the
Caravel SoC integration + OpenLane PnR + sign-off, not the trivial counter.

## Run command
```
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
    _bench7_caravel_v1034_cleanroom/caravel \
    --pdk sky130A --ic-name caravel_user_project \
    --top-name user_project_wrapper --die-um 2920x3520
```

## SOLE ACCEPTANCE CRITERION — verdict (verbatim, this run)
```
Steps: 59 total (4/48 executed PASS, 1 DEFERRED via waiver)
  PASS=3  FAIL=6  MISSING=38 (25 blocked-by-upstream of step 3)  WAIVED-DEFERRED=1  SKIPPED=10  VACUOUS-PASS=1
Overall: FAIL  (strict=True)
```
- executed PASS = 3 / 48 applicable
- FAIL = 6, MISSING = 38 (25 cascaded from the single Step-3 root cause)
- WAIVED-DEFERRED = 1 (L5_ADI_SPEC stub, analog, N/A for pure-digital SoC)

## What ran / passed / failed per step
| Step | Verdict | Note |
|---|---|---|
| Phase 1 (24/13 L docs) | PASS (precheck) | 24 L docs present, 100% coverage |
| detect_ic_class | PASS | `bus_peripheral` (Wishbone register peripheral) |
| step_rtl_gen | **WAIVED** | `rtl_gen=null` for `bus_peripheral` → AI invokes `spec-to-rtl` (runner's intended path) |
| Step 1 Spec-to-RTL | **PASS** | RTL authored into `phase2/stage1/rtl/` (stock upstream wrapper + example + self-contained `defines.v` for `MPRJ_IO_PADS`) |
| Step 2 Lint | **PASS** | RTL clean |
| yosys_synth | **PASS** | netlist 189 cells, synth_top=user_project_wrapper, frontend=read_verilog_v2005 |
| Step 9 Synthesis | **PASS** | mapped netlist |
| reference_tb | **FAIL** | runner-generated `tb_caravel_full.v` does not compile (iverilog rc=9) — ROOT CAUSE |
| eco_loop | FAIL_ECO_INERT | no remediable signature; byte-identical RTL across iters |
| Step 3 CDC/RDC | FAIL | no CDC report — pipeline halted before producing it |
| Step 4 Sim / Step 5 Formal / Step 6 FPGA | FAIL | artifacts never produced (chain halted at reference_tb) |
| Steps 7–39 (PnR / DRC / LVS / STA / sign-off) | MISSING | blocked-by-upstream(step 3) |
| Analog A6 / M1–M4 / Step 40–44 | MISSING / SKIPPED-CONDITION | N/A pure-digital SoC; no silicon |

## Root cause (single)
`reference_tb` FAILed because the **runner's own** `step_full_stack_tb_gen`
emitted an **uncompilable** TB (`tb_caravel_full.v`), which halted the rest of
the Phase 2/3 chain. The defect is NOT in the authored design RTL.

Proof the design RTL is clean:
- `yosys_synth` PASS (189 cells, top = user_project_wrapper).
- Standalone `iverilog -g2012 defines.v user_proj_example.v user_project_wrapper.v`
  inside `hpretl/iic-osic-tools:latest` → **RC=0**.

The generated TB (`phase2/stage1/sim_full_stack/tb_caravel_full.v`) fails at
lines 32–34:
```verilog
wire vccd1_/_vssd1;                      // illegal Verilog identifier ('/')
reg vccd1_/_vssd1_drive = 1'bz;
assign vccd1_/_vssd1 = vccd1_/_vssd1_drive;
```
plus every multi-bit port is declared 1-bit (`reg wbs_dat_i = 0;` for a
`[31:0]` port; same for `la_data_in[127:0]`, `io_in[37:0]`, `wbs_sel_i[3:0]`).

## Generator defect site
`vibe-ic-marketplace/plugins/vibe-ic/programs/phase2_one_shot_runner.py`,
`step_full_stack_tb_gen`, lines ~1855–1880:
- `nm = (p.get("name") ...)` used verbatim — no identifier sanitization.
- `reg {nm} = 0;` / `wire {nm};` — never reads `p['width']/msb/lsb` (L9
  carries them correctly, e.g. `wbs_sel_i` width 4, `la_data_in` width 128).
- `direction == "inout"` always builds a `*_drive` stimulus net, even for
  `io:"POWER"` pins that should be tied.

## Tool substitutions (disclosed)
- EDA in docker `hpretl/iic-osic-tools:latest` (entrypoint needs `--skip`/
  `--entrypoint bash`).
- iverilog (Icarus) substitutes for a commercial sim; yosys for synth. No
  commercial tool available; standard Vibe-IC open-tool substitution.

## Residual triage (A–H rubric, open-benchmark-methodology §4)
- **Cat C (tool/runner gap), chip-AGNOSTIC, file-worthy** — the
  `step_full_stack_tb_gen` defect (illegal-identifier leak + ignored width +
  POWER-pin stimulus). Hits ANY SoC-class IC: every Caravel user_project_wrapper
  has 8 power pins, a 31-bit Wishbone data bus, a 127-bit LA bus, and a 37-bit
  IO bus. Any APB/AXI-Lite/Wishbone register-peripheral with buses + power pins
  in L9 reproduces it. → captured as gap #2 below.
- **Cat C (extraction gap), chip-AGNOSTIC, file-worthy** — phase1 interface-
  table extraction merging a power-pair row (`vccd1 / vssd1`) into one port name
  with a literal `/`. Any datasheet whose power table uses `A / B` pairing
  reproduces it. → captured as gap #1 below.
- **NOT FAIL-of-design / not agent-fixable-RTL** — the design RTL is correct
  (synth PASS, standalone compile RC=0). The FAIL is a runner-TB-generator
  defect, not a spec-to-RTL miss. No design-side close-loop can fix a broken
  TB generator without editing the plugin (out of my role).
- **WAIVED-DEFERRED (1)**: `L5_ADI_SPEC` analog stub — legitimately N/A for a
  pure-digital SoC; deferred, not a defect.

## Chip-specific one-offs (NOT in the file-list — noted here only)
- `MPRJ_IO_PADS` macro was not in the project's `user_defines.v`; I authored a
  self-contained `phase2/stage1/rtl/defines.v` (38 pads) so the wrapper
  synthesizes standalone. This is a caravel-harness-specific constant, not a
  systematic plugin gap — handled as design-input authoring, not filed.

## Capture
Structured recovery candidates recorded at
`_bench7_caravel_v1034_cleanroom/_runlogs/recoveries_r1.json`. Both classified
**Bucket A** (deterministic, no LLM judgment). Per role boundary, NOT
self-applied — filed for the Core Agent loop.

## Verdict summary
`Overall: FAIL (strict=True)` — blocked at a single runner-side root cause
(`step_full_stack_tb_gen` emits uncompilable TB). Design RTL is clean and
synthesizes; the chain cannot advance past `reference_tb` until the plugin's TB
generator is fixed (Core Agent). Re-run after the fix lands to confirm the chain
proceeds to Phase 3 PnR / sign-off.
