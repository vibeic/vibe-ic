# RESULT_r8 — caravel_user_project (7th benchmark IC), Round 8 clean-room

- **Date:** 2026-06-14
- **Plugin:** v1.0.54 (PUBLIC tree, PUSHED) — `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/`
- **IC:** caravel_user_project | top=`user_project_wrapper` | PDK=sky130A | die=2920x3520 um
- **Run dir:** `_bench7_caravel_v1034_cleanroom/caravel_r8`
- **Shape:** A (full runner) + D (RTL recovery if WAIVED)
- **Blind:** no reference GDS / spm_pilot / host-scorer
- **In-flight field-verify:** #691 (routing), #685 (LVS port-recovery), #684 (fill)
- **Round-7 baseline:** halted at PnR global route (GRT-0229 / met1-met1 restriction)

## Setup
- caravel_r8 created from `caravel/input` ONLY (clean-room). design_src/verilog/rtl has: defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v (+ uprj_netlists.v — NOT staged for RTL recovery).
- Via-analyzer tests: 12 passed (routing_layer_upper_bound present at _pdk_via_analyzer.py:224).

## Progress log
<!-- APPEND after each major step -->

### [22:15] First runner pass — WAIVED rtl_gen (expected, Shape D)
- IC class detected: `bus_peripheral` (rtl_gen=null) → runner WAIVES, recommends skill `spec-to-rtl`.
- eco_loop tried 3 iters, all FAIL `reference_tb: rtl/ missing` → `yosys_synth: rtl/ missing`.
- phase1: PASS. phase2: FAIL (halted, rtl/ missing). analog/phase3: SKIPPED. duration 3.6s.

### [22:16] RTL recovery (Shape D handoff)
- Staged 4 synthesizable sources into `phase2/stage1/rtl/`: defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v. uprj_netlists.v deliberately NOT staged.
- Re-invoked runner (PID 96650).

### [22:17] Phase 2 PASS_WITH_WAIVERS (RTL recovery worked)
- `yosys_synth PASS cells=189 synth_top=user_project_wrapper`. sdc_gen PASS. detect_ic_class=bus_peripheral.
- rtl_gen / reference_tb WAIVED (bus_peripheral, generic_full_stack track) — expected for this class.

### [22:19-22:22] Phase 3 — ALL BACKEND STEPS EXECUTED PASS (huge jump past round-7)
Round-7 halted at PnR **global route**. Round-8 reached GDS + tapeout checklist + LVS clean.
- **synth PASS**, **pnr PASS** (def + sta + spares=7, target_d=0.02 actual_d=0.021277 dist_ok=True)
- **gds PASS** size=92967798 (89MB) — klayout streamout, grid-snapped 0.005µm (#600), klayout-native per-layer merge (#601)
- **drc PASS violations=0** (drc.rpt)
- **lvs PASS** — "Final result: Circuits match uniquely."
- phase3 orchestrator verdict: FAIL only on completion-audit (missing canonical steps), NOT on any executed step.
- overall one-shot: FAIL, halted=phase3, duration 336.4s.

## IN-FLOW FIELD-VERIFY (fresh evidence, THIS run)

### #691 ROUTING — **RESOLVED**
- `pnr.tcl`: **NO routing_layer directive at all** (grep -ni "routing_layer" → empty). Unrestricted routing.
- **NO `set_routing_layers -signal met1-met1`**. **No GRT-0229** anywhere in phase3 logs.
- routed.def: NETS 749; metal layers used = met1(96912) met2(187647) met3(186651) met4(12765) met5(178) — multi-layer route, met1-met1 restriction GONE.
- PnR status: global + detailed route COMPLETE → routed.def + GDS produced.

### #685 LVS PORT-RECOVERY — **RESOLVED**
- `reports/phase3/lvs.rpt`: "Netlists match uniquely." / "Final result: Circuits match uniquely."
- io_out[N] ↔ io_out[N] and la_data_out[M] ↔ la_data_out[M] matched 1:1 ("Cell pin lists are equivalent").
- Extracted netlist has **74 RWALIAS** shared-internal-net port-recovery aliases (RWALIAS0..RWALIAS73, e.g. `RWALIAS0 io_oeb[7] io_oeb[0] 0`).
- No residual io_out↔la_data_out mismatch. LVS verdict = PASS.

### #684 FILL / die scale — **RESOLVED (component+GDS)**
- routed.def COMPONENTS = 648 (hundreds). GDS = 92,967,798 bytes = 89MB (MB-scale).
- NOTE: #684 sparse-die guard (core_util ~0.02%) also intentionally SKIPS full-die tapcell + decap/fill tiling — see new gap candidate below.

## SOLE ACCEPTANCE CRITERION (flow_compliance_check --strict) — verbatim
- **`Overall: FAIL  (strict=True)`**
- **`Steps: 59 total (25/31 executed PASS, 3 DEFERRED via waiver)`**
- Counts (this run): PASS=24 step-lines, FAIL=6, WAIVED-DEFERRED=7(lines)/3(steps), VACUOUS-PASS=2, SKIPPED-CONDITION=27.
- Completed WITHOUT hanging (round-7 hang fixed). Exit 0.

### The 6 FAILs (classified)
1. **Step P0 (structural-RTL gates)** — `l_doc_structured_field_count_check`: 3 L docs carry fewer typed structured fields than required (Wave 31/32). CHIP-SPECIFIC-ish: caravel input docs are sparse vendor docs; phase1 ingested 24/13 L docs but field DEPTH below floor. Pre-existing phase1-depth gap (already known on this IC class).
2. **Step 7 (Constraint setup PVT)** — `pvt_matrix_check FAIL corner_count=0`: "corners empty — discover >=2 Liberty corners or document single-corner explicitly (#442)". CHIP-AGNOSTIC plugin gap candidate: sdc_gen emits SDC but no PVT corner matrix; single-corner not auto-documented for sky130A.
3. **Step 28 (PERC ZERO_TAPS)** — `perc_signoff_check FAIL`: "359 placed std cells but 0 valid well/substrate-tap cells". ROOT: pnr.tcl SPARSE_DIE_TAPCELL_SKIPPED fired (core_util=0.022% < 5.0% guard #684). CHIP-AGNOSTIC plugin-CONSISTENCY gap: tapcell-skip guard and PERC gate disagree (see ranked candidate #1).
4. **Step 31 (PV provenance)** — `provenance_check FAIL`: drc_signoff.rpt EXISTS (22520B) but "no entry in provenance.jsonl declares reports/phase3/drc_signoff.rpt as an output" (provenance.jsonl has 5 entries, drc_signoff.rpt not among them). CHIP-AGNOSTIC plugin gap: sign-off DRC report not provenance-stamped.
5. **Step 34 (Metal Fill)** — `metal_fill_density_check FAIL`: filled.def (37553108B) == routed.def (37553108B), 0 fillers, FILL_NO_SUBSTANCE (#445). ROOT: SPARSE_DIE_FILL_SKIPPED fired (core_util=0.034% < 5.0%). CHIP-AGNOSTIC plugin-CONSISTENCY gap: same sparse-die guard vs metal-fill gate disagreement.
6. **Step 38 (Foundry Handoff)** — `foundry_handoff_package_check FAIL`: mask spec / WAT plan / scribe / corner test kit package incomplete. CHIP-AGNOSTIC plugin gap: handoff package generator does not emit required artifacts for digital-only sky130A.

### Step 39 FPGA — WAIVED-DEFERRED (ENV_UNAVAILABLE, cap:fpga_board_prototype) — environment-only, NOT a plugin bug.
### Steps 29/30 (post-layout gate-sim + SPICE correlation) — SKIPPED-CONDITION, cap:sdf_annotated_gatelevel_sim / cap:post_layout_spice_correlation (#430) — open-tool cap-gaps, NOT plugin bugs.

## NEW CHIP-AGNOSTIC FILE-WORTHY GAP CANDIDATES (ranked)

### CANDIDATE 1 (HIGH) — sparse-die guard vs sign-off gates are INCONSISTENT (PERC + metal-fill)
- The runner (`phase3_one_shot_runner.py`) deliberately emits `SPARSE_DIE_TAPCELL_SKIPPED` and `SPARSE_DIE_FILL_SKIPPED` when `core_util < 5.0%` (#684 guard) — correct engineering for an empty fixed wrapper (latch-up ties / decap only needed where active wells exist).
- BUT two downstream sign-off gates have NO sparse-die awareness and FAIL categorically:
  - `perc_signoff_check.py` → ZERO_TAPS FAIL (grep: no `core_util`/`sparse` handling at all).
  - `metal_fill_density_check.py` → FILL_NO_SUBSTANCE FAIL (treats `core_utilization_pct` as metadata to exclude, but has no WAIVE/VACUOUS path when fill was legitimately skipped on sub-5% util).
- CHIP-AGNOSTIC: any sub-5%-util fixed wrapper / harness-style top (extremely common SoC integration pattern, not caravel-specific) hits this exact contradiction. The fix is to teach PERC + metal-fill gates to read the same sparse-die signal the runner already emits and downgrade ZERO_TAPS / FILL_NO_SUBSTANCE to VACUOUS-PASS (input-not-applicable) when the runner attests a documented sparse-die skip — symmetric with how Step 14 already VACUOUS-PASSes.

### CANDIDATE 2 (MED) — sign-off DRC report not provenance-stamped (Step 31 PV)
- `drc_signoff.rpt` is produced (22520B) but `provenance.jsonl` (5 entries) does not declare it as an output → `provenance_check` FAILs Step 31 even though DRC itself is clean (violations=0) and LVS matches uniquely.
- CHIP-AGNOSTIC: the sign-off-DRC emitter writes the report but does not append a provenance entry; affects every IC. Fix: stamp `reports/phase3/drc_signoff.rpt` into provenance.jsonl at emit time.

### CANDIDATE 3 (MED) — PVT matrix empty for single-corner sky130A (Step 7)
- `pvt_matrix_check` FAIL corner_count=0: "discover >=2 Liberty corners or document single-corner explicitly (#442)". sdc_gen emits SDC but no corner matrix and no single-corner attestation.
- CHIP-AGNOSTIC: any sky130A digital run that uses the nominal corner only trips this; fix is to auto-document the single-corner stance (sky130A ships nom tt by default in the open flow) so the gate VACUOUS/PASSes instead of FAIL.

### CANDIDATE 4 (LOW) — foundry-handoff package incomplete for digital-only sky130A (Step 38)
- `foundry_handoff_package_check` FAIL: mask spec / WAT plan / scribe / corner test kit not emitted. Likely a generator-coverage gap for the open-source sky130A digital handoff (no commercial PDK handoff template). Needs confirmation it is plugin-side (generator) vs cap-gap (no sky130A WAT/scribe data available) before filing — lean toward generator gap since the package step ran but emitted an incomplete audit.

## ENVIRONMENT-ONLY BLOCKERS (NOT plugin bugs — do not file)
- **Step 39 FPGA final sign-off** — ENV_UNAVAILABLE waiver, cap:fpga_board_prototype. No DE10-class board-pin contract for bus_peripheral + no Quartus/.sof on host. Correctly DEFERRED.
- **Step 29 post-layout gate-level sim (SDF)** — cap:sdf_annotated_gatelevel_sim (#430): open-tool chain does not implement SDF-annotated gate sim yet.
- **Step 30 post-layout SPICE correlation** — cap:post_layout_spice_correlation (#430): not implemented in open-tool chain.

## CONCLUSION
- #691 / #685 / #684 all **RESOLVED in-flow** with fresh THIS-run evidence.
- Chain reached MUCH further than round-7 (which halted at PnR global route): completed PnR → routing(met1-met5) → CTS → hold-fix → SPEF → post-route STA → IR/EM/antenna/SI → ECO → GDS(89MB) → tapeout-checklist(PASS) → DFM(PASS). LVS PASSed (circuits match uniquely). GDS streamout (Step 37) PASS.
- `flow_compliance_check --strict`: **Overall: FAIL** | **Steps: 59 total (25/31 executed PASS, 3 DEFERRED via waiver)**, 6 FAILs.
- Remaining FAILs are NOT blocked on PnR/route/LVS (all green) — they are (a) the sparse-die-guard/sign-off-gate inconsistency cluster (PERC+metal-fill), (b) a provenance-stamp miss, (c) PVT single-corner doc, (d) foundry-handoff package coverage, (e) pre-existing phase1 L-doc field-depth. Ranked candidates above.
- NO GitHub issues filed; NO plugin/MCP edits. Capture + report only per mandate.
