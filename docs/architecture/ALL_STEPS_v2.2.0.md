# Vibe-IC — ALL Phases / Stages / Steps (v2.2.0, exhaustive)

**Plugin 0.2.2.** Complete enumeration of every phase, stage, and step. There are **two coexisting
views**: **(A)** the runner ground-truth markers (`[N/15]` / `def step_*`) that the code actually
prints, and **(B)** the 33-step Stage model (sign-off view). Both are listed in full below; the
companion `CANONICAL_FLOW_v2.2.0.md` is the narrative. Source of truth = the runners.

---

## 0. Entry + orchestrator + pre-flight

| ID | Item | Where |
|---|---|---|
| P0 | Pre-flight (env / PDK / tool availability) | `mcp_server_health_check`, `eda_doctor` |
| — | Path A: NL prompt / dialogue → Phase 1 | `phase1_doc_one_shot_runner.py` |
| — | Path B: vendor docs → Phase 1 (docs mode) | same |
| — | Orchestrator: Phase 1 → Phase 2(=2a+2b) → Analog (after P2) → Phase 3 | `vibe_ic_one_shot_runner.py` |

---

## A. RUNNER-MARKER VIEW (ground truth)

**ONE continuous global step number across the sequential flow Phase 1 → 2 → 3** (Phase 3 does
**NOT** restart at 1 — it is global 50-55). Analog A1-A8 / Mixed M1-M4 run **parallel** to Phase 2
and keep their native A*/M* ids. Auto-generated live in `FLOW_STEPS_GENERATED.md` (regenerate with
`flow_doc_emit.py`). § B below is the orthogonal 33-step silicon-flow model (its own 1→33).

### A.1 Phase 1 — global steps 1-34 (15 main markers + 19 sub-steps, `phase1_doc_one_shot_runner.py`)

| Marker | Step |
|---|---|
| `[1/15]` | Text extraction (input/docs → input_doc; 2 MB scan cap, v0.1.91) |
| `[2/15]` | L1_DATASHEET |
| `[3/15]` | L2_FRS |
| `[4/15]` | L3_CMD_PROTOCOL |
| `[5/15]` | L4_REGMAP |
| `[6/15]` | L5_ADI_SPEC |
| `[7/15]` | L6_CONTROL_LOGIC |
| `[8/15]` | L7_TEST_DEBUG |
| `[9/15]` | L8_RTL_CONSTANTS |
| `[10/15]` | L9_INTEGRATION_SPEC |
| `[11/15]` | L10_TEST_CASES |
| `[12/15]` | L11_OTP_CONTENT |
| `[13/15]` | L12_BEHAVIORAL_SEQUENCES |
| `[14/15]` | L13_LAB_CALIBRATION |
| `[14b/15]` | L8_TIMING_WAVEFORM |
| `[14b2/15]` | L8 protocol-width extract (R19) |
| `[14b3/15]` | L8 encoding-table overlay (R41) |
| `[14b4/15]` | L6 FSM / control-logic overlay (R42) |
| `[14b5/15]` | L12 behavioral-sequences overlay (R43) |
| `[14b6/15]` | L17/L18/L8_TIMING/L9 batch synth (R46) — DEPRECATED → 14c3 |
| `[14b7/15]` | L8_RTL_CONSTANTS universal protocol constants (R48) |
| `[14c/15]` | L14-L18 protocol spec extract |
| `[14c0/15]` | L9 integration_spec overlay (R40) |
| `[14c1/15]` | L1 protocol metadata overlay (R23) |
| `[14c1b/15]` | L17 handshake_pairs overlay (R27) |
| `[14c2/15]` | L3 protocol mirror from L14-L18 (R21) |
| `[14c3/15]` | L17/L18/L8_TIMING/L9 batch synth (R46 relocated) |
| `[14c4/15]` | L1/L2/L6/L7/L12 universal protocol doc facts (R50) |
| `[14c5/15]` | L4/L5/L10/L14/L15 residual cleanup (R52) |
| `[14d/15]` | L19-L23 skeleton emit |
| `[14e/15]` | serial_peripheral_protocol class synth (R53/R54/R55) — **81-protocol detector→synth dispatch** |
| `[14e2/15]` | bus_interconnect_protocol Tier-2 synth (TileLink/Wishbone/Avalon/OCP/AXI-Stream) |
| `[14e3/15]` | Universal packet/PDU L10↔L3 opcode-consistency sweep |
| `[15/15]` | Coverage / parity report |

→ **34 distinct Phase-1 markers** (15 main + 19 sub/overlay/dispatch).

### A.2 Phase 2 — step functions (`phase2_one_shot_runner.py`) — **global steps 35-49**

> Continuous global numbering (does NOT restart at 1; continues from Phase 1's 34 markers).
> Auto-generated live in `FLOW_STEPS_GENERATED.md`.

| # | Step | Note |
|---|---|---|
| 35 | `step_phase1` | re-run/ingest Phase 1 if needed |
| 36 | `step_rig_topology_skeleton` | topology scaffold |
| 37 | `step_rtl_gen` | WAIVE for `rtl_gen=null` ic_class → `spec-to-rtl` role; `phase2_scaffold_gen.py` emits top/regs/fsm/tb/soc_wrap/cocotb |
| 38 | `step_full_stack_tb_gen` | self-checking TB |
| 39 | `step_reference_tb` | reference-TB conformance (eco_loop ≤3 retries) |
| 40 | `step_yosys_synth` | gate-level synth |
| 41 | `step_qsf_gen` | FPGA project |
| 42 | `step_sdc_gen` | constraints |
| 43 | `step_otp_image_check` | OTP image (if any) |
| 44 | `step_fpga_compile` | FPGA build → `.sof` |
| 45 | `step_fpga_burn` | program board |
| 46 | `step_usb_hid_tester_verify` | host protocol-tester acceptance |
| 47 | `step_emit_phase2_manifests` | manifests |
| 48 | `step_final_audit` | aggregate audit |
| 49 | `step_phase3` | chains into Phase 3 when run end-to-end |

Surrounding gates: `rtl_hygiene_lint --fix`, `spec_conformance_check`, `chip_top_gate_wrapper_gen`,
MCP `eda_lint`/`eda_synth`/`eda_cocotb`.

### A.3 Phase 3 — step functions (`phase3_one_shot_runner.py`) — **global steps 50-55 (NOT 1-6)**

> Phase 3 is the back-end; its step functions continue the global count — they do **not** restart at 1.

| # | Step | Tool (open-source) |
|---|---|---|
| 50 | `step_synth` | yosys (+ tie-cell pass: `setundef -zero; hilomap; splitnets; clean`) |
| 51 | `step_pnr` | OpenROAD (floorplan→PDN→place→CTS→route) |
| 52 | `step_gds` | KLayout (`def2gds`) |
| 53 | `step_drc` | KLayout sky130 deck |
| 54 | `step_lvs` | netgen / yosys_equiv — the LVS sign-off chain (§ C) |
| 55 | `step_canonicalize_artefacts` | normalize outputs (+ the § D sign-off emitters) |

### A.4 Analog A1–A8 (`analog_one_shot_runner.py`, parallel to Phase 2)

| Step | Name | Output |
|---|---|---|
| A1 | spec_extract | `analog/<block>/A1_spec.json` |
| A2 | topology_select | `A2_topology.json` |
| A3 | netlist_gen | `<block>.sp` |
| A4 | corner_sweep | `A4_corners.json` |
| A5 | layout (Magic) | `A5_layout.json` (needs DRC-clean + LVS-match flags) |
| A6 | post_layout_resim | `A6_postsim.json` |
| A7 | hardmacro_gen | `{.lef,.lib,.gds,.v}` → feeds Phase 3 |
| A8 | hw_verify (HIL) | `A8_hw_verify.json` |

### A.5 Mixed-signal M1–M4 (skill-level, no dedicated runner)

| Step | Name | Where |
|---|---|---|
| M1 | top merge | `mixed_signal_m1_top_merge_check.py` + skill `mixed-signal-cosim` |
| M2 | co-sim setup | skill `mixed-signal-cosim` |
| M3 | co-sim run | skill `mixed-signal-cosim` |
| M4 | integration verify | skill `mixed-signal-cosim` |

---

## B. 33-STEP STAGE MODEL — ALL 33 STEPS, CONTIGUOUS (sign-off view, `33_step_flow_overview.md`)

**Every step 1→33, no gaps.** Stage is a column (S1 RTL+verify / S2 synth+DFT / S3 physical+sign-off
/ S4 output+validation). (§ A is the runner-marker view; § D below is a *subset* — only the
sign-off checks with a known open-source gap.)

| # | Stage | Step | Tool/Skill | Gate |
|---|---|---|---|---|
| 1 | S1 | Spec-to-RTL | `spec-to-rtl` | L1-L9 present + RTL emitted |
| 2 | S1 | Lint | `eda_lint` + Phase-2a gates + polluter check | Verilator 0 errors |
| 3 | S1 | CDC / RDC check | `cdc-check` | CDC paths synchronised |
| 4 | S1 | Simulation | `testbench-gen` + `eda_simulate` + coverage | all tb PASS + coverage |
| 5 | S1 | Formal verification | `formal-verify` + `assertion-gen` | k-induction proved (informational waiver if no model) |
| 6 | S1 | FPGA early prototype | `fpga-test-harness` + `eda_fpga_compile/program` + on-board BIST | `.sof` + BIST PASS |
| 7 | S2 | Constraint setup | `constraint-gen` | `*.sdc` + 3-corner `pvt_matrix.json` |
| 8 | S2 | SDC validation | SDC lint | all clock/IO constraints present |
| 9 | S2 | Synthesis (Yosys) | `eda_synth` + `synth-doctor` (+ tie-cell pass) | mapped netlist + cell count |
| 10 | S2 | Pre-layout STA | `eda_sta_mcorner` (SS/TT/FF) | WNS/WHS all corners |
| 11 | S2 | DFT insertion (scan + ATPG) | `dft-insert` + `atpg` + `eda_dft` | scan chain + stuck-at ≥85% |
| 12 | S2 | Post-DFT optimization | resynth / buffering | timing held |
| 13 | S2 | Equivalence check | `equivalence-check` + Yosys `equiv` | RTL ≡ post-DFT netlist |
| 14 | S3 | Floorplan + PDN | `eda_pnr` (init) | area / utilization |
| 15 | S3 | Clock planning | clock-planning skill | clock-buffer list |
| 16 | S3 | Placement (global + detailed) | `eda_pnr` | placement legal |
| 17 | S3 | CTS | `eda_pnr enable_cts=true` | clock skew |
| 18 | S3 | Post-CTS hold fixing | `repair_timing -hold` | WHS > 0 |
| 19 | S3 | Routing (global + detailed) | `eda_pnr enable_detailed_route=true` + `def_stage_progression_check` | 0 overflow + DEF SHA differs |
| 20 | S3 | Parasitic Extraction (RC→SPEF) | `eda_extraction` (OpenRCX) | `spef_extraction_check` (sky130 = no captable → ENV-BLOCKED) |
| 21 | S3 | Post-route STA (MMMC) | `eda_sta_mcorner` | 3-corner pass |
| 22 | S3 | IR Drop | OpenROAD PSM `analyze_power_grid` | `ir_drop_report_check` (FIXED v0.2.4) |
| 23 | S3 | EM check | PSM `-enable_em` | `em_report_check` (FIXED v0.2.4) |
| 24 | S3 | Antenna check | OpenROAD `check_antennas` | 0 violation (report-path FIXED v0.2.4) |
| 25 | S3 | Signal Integrity (crosstalk/noise) | SI screen (decoupled-C) | `si_crosstalk_check` (screen; full needs SPEF) |
| 26 | S3 | Post-Layout Gate-Level Sim (+SDF) | `eda_simulate` | `post_layout_sim_check` PASS |
| 27 | S3 | Physical Verification | `eda_drc_klayout` + `eda_lvs` + ERC | DRC=0 / LVS device-exact / ERC floating-net |
| 28 | S3 | ECO repair loop | `eco-plan` | `eco_loop_audit` PASS |
| 29 | S4 | Power analysis | pre + post layout | meets spec |
| 30 | S4 | Metal Fill (density fill) | OpenROAD `filler_placement` → `filled.def` | `metal_fill_density_check` (FIXED v0.2.4) |
| 31 | S4 | Tapeout checklist | `tapeout-checklist` + `signoff_audit` | 4/4 strict |
| 32 | S4 | GDSII output | `eda_gds` + `def2gds` | only if step 27 clean |
| 33 | S4 | FPGA final sign-off | recompile + on-board test + `fpga_on_board_attestation_check` | bitstream hash + hw evidence |

> **Numbering caveat:** the Stage-3 sign-off checks ALSO carry a sign-off-audit numbering used in
> § D (SPEF 22 / STA 23 / IR 24 / EM 25 / Antenna 26 / SI 27 / DRC-LVS-ERC 30 / fill 33), which
> differs from THIS 33-step numbering above (SPEF 20 / STA 21 / IR 22 / EM 23 / Antenna 24 / SI 25 /
> PV 27 / fill 30). Same checks, two ID schemes; to be unified by `flow_doc_emit.py`.

---

## C. The LVS sign-off chain (under Phase-3 `step_lvs`, NEW v0.1.96→v0.2.2)

| Layer | What | Tool |
|---|---|---|
| 1 | Structural LEC (default) | `eda_lvs mode=yosys_equiv` (equiv_simple + equiv_induct) — SAT-model unproven = Category-D gap |
| 2 | Device-level coverage | `eda_extraction` (magic ext2spice) + `eda_lvs mode=netgen` + `lvs_netgen_setup_emit.py` |
| 3 | Powered-netlist closure | OpenROAD `write_verilog -include_pwr_gnd` (after global_connect) |
| 4 | Top-level port labels | Route A `magic_port_extract_emit.py` (port makeall) / Route B `lvs_def_port_seed.py` (DEF seed) |
| 5 | Sign-off guard (MANDATORY) | `lvs_signoff_guard.py` — RAISES on a portless / vacuous match |

---

## D. Phase-3 sign-off checks — gap status (SUBSET; sign-off-audit numbering)

> **This is a SUBSET, not the full step list** — only the Phase-3 sign-off checks that had an
> open-source gap (which is why 14-21 / 28 / 29 / 31 / 32 are absent *here*: they had no gap).
> The complete contiguous 1→33 list is **§ B**. Status as of v0.2.4 (fixes shipped — see backlog
> `ORGANIC-20260531-phase3-signoff-chain-open-source-gaps`):

| Step | Check | Status (v0.2.4) | Severity |
|---|---|---|---|
| 22 | SPEF (OpenRCX) | **WORKS** (prior "ENV-BLOCKED" was a false negative) — sky130A **does** ship the OpenRCX captable at `/foss/pdks/sky130A/libs.tech/openlane/rules.openrcx.sky130A.{min,nom,max}.magic`; `extract_parasitics -ext_model_file <…nom.magic>` + `write_spef` extracts on a real routed DEF (spm: 1370 rc segments, 330 nets, 1700 caps). The earlier RCX-0107 "0 segments" was an EMPTY (routing-less) DEF, not a missing captable. | 🟢 works |
| 23 | Post-route STA (MMMC) | passes; pilots report slack +X ns MET | 🟢 none |
| 24 | IR drop (PSM) | cascading-missing on SPEF | 🔶 medium |
| 24 | IR drop | **FIXED** — OpenROAD PSM `analyze_power_grid` (walks DEF SPECIALNETS directly; no SPEF needed — the cascade premise was wrong) → `reports/phase3/ir_drop.{rpt,json}` | 🟢 fixed |
| 25 | EM | **FIXED** — PSM `-enable_em` → `em.{rpt,json}` | 🟢 fixed |
| 26 | Antenna | **FIXED** — `check_antennas` re-emitted to `antenna.{rpt,json}` (report-path) | 🟢 fixed |
| 27 | SI (crosstalk) | **PARTIAL** — decoupled-C SCREEN_PASS now emitted; full coupling-cap SI still needs SPEF (env-blocked) | 🔶 screen |
| 30 | DRC / LVS / ERC | **PARTIAL** — KLayout sky130 DRC + Magic floating-net ERC + device-level LVS (§ C) all wired/passing; full Calibre PERC (latch-up/ESD) env-deferred | 🔶 partial |
| 33 | Metal fill | **FIXED** — OpenROAD `filler_placement` → `phase3/stage3/pnr/filled.def` + `density.{rpt,json}` | 🟢 fixed |
| 18 | Spare cells | **FIXED** — `spare_cells.json` now has `rows[]` (derived from existing placement; placement unchanged) | 🟢 fixed |
| 5 | Formal | confirmed INFORMATIONAL waiver (altsyncram no model) — no code change | 🟢 none |

**None is a circuit-design error** — all script-ordering / cascading / environment / report-schema.
Actionable fixes tracked in `ORGANIC-20260531-phase3-signoff-chain-open-source-gaps`.

---

## E. Totals

| View | Count |
|---|---|
| Phase 1 runner markers | 34 (15 main + 19 sub) |
| Phase 2 step functions | 14 (+1 phase3 hook) |
| Phase 3 step functions | 6 |
| Analog | A1–A8 (8) |
| Mixed-signal | M1–M4 (4) |
| 33-step Stage model | 33 (Stage 1:6 / 2:7 / 3:15 / 4:5) |
| LVS sign-off chain layers | 5 |
| Phase-3 sign-off checks | 10 |

---

## F. Keep current

This is a **derived** enumeration. The §A runner-marker tables are now auto-generated by
**`programs/flow_doc_emit.py`** (shipped v0.2.3) into **`FLOW_STEPS_GENERATED.md`** — run
`python3 flow_doc_emit.py` after any runner change; `flow_doc_emit.py --check`
(`tests/test_flow_doc_emit.py`) fails CI on drift. The §B 33-step Stage model, §C LVS chain,
and §D sign-off table remain hand-curated (not derivable from markers); unifying the two
Stage-3 numberings into the generator is the remaining follow-up.
