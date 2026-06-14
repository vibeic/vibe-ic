# RESULT_r9 — caravel_user_project (7th benchmark IC), Round 9 clean-room (convergence round)

- **Date:** 2026-06-14
- **Plugin:** v1.0.57 (PUBLIC tree, PUSHED) — `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/`
- **IC:** caravel_user_project | top=`user_project_wrapper` | PDK=sky130A | die=2920x3520 um
- **Run dir:** `_bench7_caravel_v1034_cleanroom/caravel_r9`
- **Shape:** A (full runner) + D (RTL recovery if WAIVED)
- **Blind:** no reference GDS / spm_pilot / host-scorer
- **In-flight field-verify:** #692 (sparse-die PERC/latchup/metal-fill consistency), #693 (drc_signoff provenance stamp), #694 (pvt single-corner stance)
- **Round-8 baseline:** flow_compliance_check Overall=FAIL, 25/31 executed PASS, 3 DEFERRED, 6 FAILs (P0 phase1-depth, Step7 PVT, Step28 PERC ZERO_TAPS, Step31 provenance, Step34 metal-fill, Step38 foundry-handoff).

## Fix-presence pre-check (v1.0.57 code, before run)
- **#692**: `metal_fill_density_check.py` reads `sparse_die_skip.json` → `_sparse_die_fill_skip_attested` (lines 129-161). `latchup_esd_spacing_check.py` reads `sparse_die_skip.json` → `WELLTAP_SPARSE_DIE_DEFERRED` / `ZERO_TAPS_SPARSE_DIE_ATTESTED` (lines 258-347). [The ZERO_TAPS/PERC well-tap gate lives in latchup_esd_spacing_check.py, not perc_signoff_check.py.]
- **#693**: `phase3_one_shot_runner.py` lines 7755-7773 write `reports/phase3/drc_signoff.rpt` AND append provenance entry (`("reports/phase3/drc_signoff.rpt", "klayout", ...)` line 6881).
- **#694**: `pvt_matrix_check.py` lines 44-107 load `single_corner_stance.json` → `SINGLE_CORNER_STANCE_DISCLOSED` (exit 0, review_required).

## Setup
- caravel_r9 created from `caravel/input` ONLY (clean-room). design_src/verilog/rtl has: defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v (+ uprj_netlists.v — NOT staged for RTL recovery).

## Progress log

### [23:09] First runner pass — WAIVED rtl_gen (expected, Shape D)
- IC class detected: `bus_peripheral` (rtl_gen=null) → runner WAIVES, recommends skill `spec-to-rtl`.
- eco_loop 3 iters, all FAIL `reference_tb: rtl/ missing`. phase1 PASS, phase2 FAIL (halted, rtl/ missing). duration 3.7s.

### [23:09] RTL recovery (Shape D handoff)
- Staged 4 synthesizable sources into `phase2/stage1/rtl/`: defines.v, user_defines.v, user_proj_example.v, user_project_wrapper.v. uprj_netlists.v deliberately NOT staged.
- Re-invoked runner (PID 225243).

### [23:10] Phase 2 PASS_WITH_WAIVERS (RTL recovery worked)
- `yosys_synth PASS cells=189 synth_top=user_project_wrapper frontend=read_verilog_v2005`. sdc_gen PASS. detect_ic_class=bus_peripheral. complexity tier=SMALL.
- rtl_gen / reference_tb WAIVED (bus_peripheral generic_full_stack) — expected.

### [23:12-23:15] Phase 3 — ALL BACKEND STEPS EXECUTED (faster than r8: ~135s vs 336s, PDK cache warm)
- **synth PASS**, **pnr PASS** (routed.def COMPONENTS=648, met1-met5 multi-layer route).
- **drc PASS violations=0** (drc.rpt). **lvs PASS** "Circuits match uniquely."
- **canonicalize_artefacts**: emitted single_corner_stance.json (#694) + 42 canonical artefacts.
- **GDS** = 92,967,798 bytes (89MB, MB-scale), present in pnr + stage4/gds + foundry_handoff.
- one-shot overall: FAIL halted=phase3 (completion-audit only — NO executed step regressed).

## IN-FLOW FIELD-VERIFY (fresh THIS-run evidence)

### #692 SPARSE-DIE SIGN-OFF CONSISTENCY (PERC + latch-up + metal-fill) — **RESOLVED**
- `reports/phase3/sparse_die_skip.json` PRESENT: `tapcell_skipped=true, fill_skipped=true, tapcell_core_util_pct=0.022%, fill_core_util_pct=0.034%, threshold_pct=5.0` — the attestation the gates now read.
- **PERC / latch-up gate** (`latchup_esd_spacing_check.py` on routed.def): `status=WELLTAP_SPARSE_DIE_DEFERRED`, `reason=ZERO_TAPS_SPARSE_DIE_ATTESTED`, `any_conclusive_gap=false`, **exit=0** (was hard FAIL ZERO_TAPS in r8). Reads sparse_die_skip.json.
- **metal_fill gate** (`metal_fill_density_check.py`): `summary.pass=true`, fill skip attested via `_sparse_die_fill_skip_attested` reading sparse_die_skip.json (was FAIL FILL_NO_SUBSTANCE in r8).
- **flow_compliance:** Step 28 (PERC/Reliability sign-off) = **PASS**; Step 34 (Metal Fill) = **PASS**. Both were FAIL in r8.

### #693 drc_signoff PROVENANCE STAMP — **RESOLVED**
- `provenance.jsonl` now has 6 entries (was 5 in r8). Entry #6: `{"tool":"klayout","command":"klayout -b -r drc (sign-off DRC) (phase3_one_shot_runner)","exit_code":0,"outputs":{"reports/phase3/drc_signoff.rpt":"sha256:a9010b1c..."}}` — drc_signoff.rpt is now provenance-declared.
- The r8 Step-31 provenance_check FAIL ("no entry declares drc_signoff.rpt") is GONE.

### #694 PVT SINGLE-CORNER STANCE — **RESOLVED**
- `reports/phase3/single_corner_stance.json` PRESENT: `stance=SINGLE_CORNER_DISCLOSED, corner_count=0, primary_corner=TT, multi_corner_claimed=false, review_required=true`, rationale per #442/#694.
- **flow_compliance:** Step 7 (Constraint setup SDC+PVT matrix) = **PASS** (was FAIL corner_count=0 in r8). pvt_matrix_check now → SINGLE_CORNER_STANCE_DISCLOSED (exit 0).

## SOLE ACCEPTANCE CRITERION (flow_compliance_check --strict) — verbatim
- **`Overall: FAIL  (strict=True)`** (exit 1)
- **`Steps: 59 total (28/31 executed PASS, 3 DEFERRED via waiver)`**
- **`PASS=27  FAIL=3  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=25  VACUOUS-PASS=1`**
- Completed WITHOUT hanging. **Round-8 was 25/31; round-9 is 28/31 (+3 = exactly #692/#693/#694).**

### The 3 FAILs (classified) — down from 6 in round-8
1. **Step P0** — `l_doc_structured_field_count_check`: 3 L docs carry fewer typed structured fields than required (Wave 31/32). PRE-EXISTING phase1 L-doc field-DEPTH gap on sparse vendor docs. KNOWN, not new.
2. **Step 31 (PV)** — `erc_density_check FAIL ERC_DIRTY: floating nets=3`. **NEWLY SURFACED** (was masked behind #693 provenance failure in r8). The 3 "floating nets" = **VGND + VPWR (power/ground specialnets) + zero_ (yosys hilomap constant-tie net)**; the 15 "floating pins" = all `spare_*` (design-for-ECO pool, intentionally tied-off by Step 18). ZERO real functional signal nets float. → NEW chip-AGNOSTIC plugin gap (see below). NOTE: DRC=0, LVS unique — Step 37 GDSII still PASSed.
3. **Step 38 (Foundry Handoff)** — `foundry_handoff_package_check FAIL`: mask spec / WAT plan / scribe / corner test kit incomplete. KNOWN roadmap hold (foundry-handoff kit assembler not shipped).

### DEFERRED (3, not FAIL) + cap-gaps
- Step 4 (Sim): WAIVED-DEFERRED cpu_functional_oracle_waiver (#651).
- Step 6 + Step 39 (FPGA early + final): ENV_UNAVAILABLE cap:fpga_board_prototype (no DE10 / no Quartus). environment-only.
- Step 29/30 (post-layout gate-sim SDF + SPICE correlation): SKIPPED-CONDITION cap:#430. open-tool cap-gaps.
- Step 14: VACUOUS-PASS (yosys_hilomap / script_template input-not-applicable).

## NEW CHIP-AGNOSTIC FILE-WORTHY GAP (ranked)

### CANDIDATE 1 (HIGH) — ERC sub-check (Step 31) counts power/tie/spare nets as floating-net FAILs (no false-positive allow-list)
- `erc_density_check.py` parses OpenROAD `report_floating_nets` raw count (3) and emits hard `ERROR ERC_DIRTY` treating them as "real electrical-rule failures." But ALL 3 are universally-known false-positive classes:
  - **VPWR / VGND** — power/ground nets driven as DEF SPECIALNETS, not regular signal nets; OpenROAD's report_floating_nets always flags these.
  - **zero_** — the yosys hilomap constant-0 tie net (CLAUDE.md rule #4); a tie net, not a floating signal.
  - The 15 floating *pins* are all `spare_*` cells — the design-for-ECO spare-cell pool, which is BY DESIGN tied-off/unconnected (that is what spare cells are; inserted by Step 18 which itself PASSed).
- Neither `erc_density_check.py` nor the ERC-report generator in `phase3_one_shot_runner.py` filters VPWR/VGND/VDD/VSS power nets, the hilomap `zero_`/`one_` constant-tie nets, or the deliberately-floating `spare_*` ECO-pool pins before counting.
- CHIP-AGNOSTIC: ANY sky130/open-flow digital P&R (which uses VPWR/VGND specialnets + yosys hilomap + a design-for-ECO spare pool) hits this exact false-positive set — not caravel-specific. Fix: teach the ERC screen to exclude (a) PDK power/ground net names, (b) hilomap constant-tie nets, (c) spare-cell-pool instance pins, before declaring ERC_DIRTY — so genuine functional floating nets still FAIL but these known-benign classes do not. Symmetric with how #692 taught PERC/metal-fill to read sparse-die attestation and how Step 18 already KNOWS the spare pool is tied off. DRC=0 + LVS-unique + Step-37 GDSII PASS all confirm the layout is otherwise clean.

## CONVERGENCE / KNOWN-HOLD GAPS (NOT new plugin bugs — do not file)
- **Step P0 phase1 L-doc field-depth** — pre-existing, known on this IC class (sparse vendor docs). Not new.
- **Step 38 foundry-handoff package** — known roadmap hold (kit assembler not shipped).
- **Step 6/39 FPGA** — cap:fpga_board_prototype (no DE10 board / no Quartus). environment-only.
- **Step 29/30 SDF gate-sim + SPICE correlation** — cap:#430 open-tool chain. environment-only.

## CONCLUSION
- #692 / #693 / #694 all **RESOLVED in-flow** with fresh THIS-run evidence. Step 7, Step 28, Step 34 PASS; provenance.jsonl declares drc_signoff.rpt.
- flow_compliance --strict: **Overall: FAIL** | **28/31 executed PASS (+3 vs r8's 25/31), 3 DEFERRED**, FAILs down 6→3.
- Full doc→GDS→tapeout chain GREEN: PnR(met1-met5) → CTS → hold-fix → SPEF → post-route STA → IR/EM/antenna/SI → PERC → ECO → Power → Metal-Fill → DFM → Tapeout-checklist → GDSII(89MB). DRC=0, LVS unique.
- **NOT fully converged:** one NEW chip-AGNOSTIC plugin gap surfaced (ERC floating-net false-positive allow-list, CANDIDATE 1) that was masked in r8 by the #693 provenance failure. The other 2 FAILs are known holds (phase1-depth, foundry-handoff). A round-10 after the ERC fix should confirm convergence.
- NO GitHub issues filed; NO plugin/MCP edits. Capture + report only per mandate.

<!-- APPEND after each major step -->
