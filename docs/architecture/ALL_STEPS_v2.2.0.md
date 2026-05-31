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

### A.1 Phase 1 — 15 main steps + every sub-step (`phase1_doc_one_shot_runner.py`)

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

### A.2 Phase 2 — step functions (`phase2_one_shot_runner.py`, logical order)

| # | Step | Note |
|---|---|---|
| 1 | `step_phase1` | re-run/ingest Phase 1 if needed |
| 2 | `step_rig_topology_skeleton` | topology scaffold |
| 3 | `step_rtl_gen` | WAIVE for `rtl_gen=null` ic_class → `spec-to-rtl` role; `phase2_scaffold_gen.py` emits top/regs/fsm/tb/soc_wrap/cocotb |
| 4 | `step_full_stack_tb_gen` | self-checking TB |
| 5 | `step_reference_tb` | reference-TB conformance (eco_loop ≤3 retries) |
| 6 | `step_yosys_synth` | gate-level synth |
| 7 | `step_qsf_gen` | FPGA project |
| 8 | `step_sdc_gen` | constraints |
| 9 | `step_otp_image_check` | OTP image (if any) |
| 10 | `step_fpga_compile` | FPGA build → `.sof` |
| 11 | `step_fpga_burn` | program board |
| 12 | `step_usb_hid_tester_verify` | host protocol-tester acceptance |
| 13 | `step_emit_phase2_manifests` | manifests |
| 14 | `step_final_audit` | aggregate audit |
| (hook) | `step_phase3` | chains into Phase 3 when run end-to-end |

Surrounding gates: `rtl_hygiene_lint --fix`, `spec_conformance_check`, `chip_top_gate_wrapper_gen`,
MCP `eda_lint`/`eda_synth`/`eda_cocotb`.

### A.3 Phase 3 — step functions (`phase3_one_shot_runner.py`)

| # | Step | Tool (open-source) |
|---|---|---|
| 1 | `step_synth` | yosys (+ tie-cell pass: `setundef -zero; hilomap; splitnets; clean`) |
| 2 | `step_pnr` | OpenROAD (floorplan→PDN→place→CTS→route) |
| 3 | `step_gds` | KLayout (`def2gds`) |
| 4 | `step_drc` | KLayout sky130 deck |
| 5 | `step_lvs` | netgen / yosys_equiv — the LVS sign-off chain (§ D) |
| 6 | `step_canonicalize_artefacts` | normalize outputs |

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

## B. 33-STEP STAGE MODEL (sign-off view, `33_step_flow_overview.md`)

### Stage 1 — RTL Generation + Verification (steps 1-6)
| # | Step | Tool/Skill | Gate |
|---|---|---|---|
| 1 | Spec-to-RTL | `spec-to-rtl` | L1-L9 present + RTL emitted |
| 2 | Lint | `eda_lint` + Phase-2a gates + polluter check | Verilator 0 errors |
| 3 | CDC / RDC check | `cdc-check` | CDC paths synchronised |
| 4 | Simulation | `testbench-gen` + `eda_simulate` + coverage | all tb PASS + coverage |
| 5 | Formal verification | `formal-verify` + `assertion-gen` | k-induction proved |
| 6 | FPGA early prototype | `fpga-test-harness` + `eda_fpga_compile/program` + on-board BIST | `.sof` + BIST PASS |

### Stage 2 — Synthesis + DFT (steps 7-13)
| # | Step | Tool/Skill | Gate |
|---|---|---|---|
| 7 | Constraint setup | `constraint-gen` | `*.sdc` + 3-corner `pvt_matrix.json` |
| 8 | SDC validation | SDC lint | all clock/IO constraints present |
| 9 | Synthesis (Yosys) | `eda_synth` + `synth-doctor` | mapped netlist + cell count |
| 10 | Pre-layout STA | `eda_sta_mcorner` (SS/TT/FF) | WNS/WHS all corners |
| 11 | DFT insertion (scan + ATPG) | `dft-insert` + `atpg` + `eda_dft` | scan chain + stuck-at ≥85% |
| 12 | Post-DFT optimization | resynth / buffering | timing held |
| 13 | Equivalence check | `equivalence-check` + Yosys `equiv` | RTL ≡ post-DFT netlist |

### Stage 3 — Physical Design + Sign-off (steps 14-28)
| # | Step | Tool/Skill | Gate |
|---|---|---|---|
| 14 | Floorplan + PDN | `eda_pnr` (init) | area / utilization |
| 15 | Clock planning | clock-planning skill | clock-buffer list |
| 16 | Placement (global + detailed) | `eda_pnr` | placement legal |
| 17 | CTS | `eda_pnr enable_cts=true` | clock skew |
| 18 | Post-CTS hold fixing | `repair_timing -hold` | WHS > 0 |
| 19 | Routing (global + detailed) | `eda_pnr enable_detailed_route=true` + `def_stage_progression_check` | 0 overflow + DEF SHA differs |
| 20 | Parasitic Extraction (RC→SPEF) | `eda_extraction` | `spef_extraction_check` PASS |
| 21 | Post-route STA (MMMC) | `eda_sta_mcorner` | 3-corner pass |
| 22 | IR Drop | `eda_ir_drop` | static + dynamic |
| 23 | EM check | electromigration | lifetime ≥ 10 yr |
| 24 | Antenna check | OpenROAD antenna | 0 violation |
| 25 | Signal Integrity (crosstalk/noise) | SI analysis | `si_crosstalk_check` PASS |
| 26 | Post-Layout Gate-Level Sim (+SDF) | `eda_simulate` | `post_layout_sim_check` PASS |
| 27 | Physical Verification | `eda_drc_klayout` + `eda_lvs` + ERC + Density | DRC=0 / LVS match / ERC=0 |
| 28 | ECO repair loop | `eco-plan` | `eco_loop_audit` PASS |

### Stage 4 — Output + Validation (steps 29-33)
| # | Step | Tool/Skill | Gate |
|---|---|---|---|
| 29 | Power analysis | pre + post layout | meets spec |
| 30 | Metal Fill (density fill) | `eda_pnr` | `metal_fill_density_check` PASS |
| 31 | Tapeout checklist | `tapeout-checklist` + `signoff_audit` | 4/4 strict |
| 32 | GDSII output | `eda_gds` + `def2gds` | only if step 27 clean |
| 33 | FPGA final sign-off | recompile + on-board test + `fpga_on_board_attestation_check` | bitstream hash + hw evidence |

> **Numbering caveat:** the Stage-3 sign-off checks have a SECOND numbering in the sign-off-audit
> scheme used in § D (SPEF 22 / STA 23 / IR 24 / EM 25 / Antenna 26 / SI 27 / DRC-LVS-ERC 30 /
> fill 33), which differs from this 33-step doc (SPEF 20 / STA 21 / IR 22 / EM 23 / Antenna 24 /
> SI 25 / PV 27 / fill 30). To be unified by `flow_doc_emit.py` (below).

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

## D. Phase-3 sign-off checks — gap status (sign-off-audit numbering)

| Step | Check | Open-source status | Severity |
|---|---|---|---|
| 22 | SPEF (OpenRCX) | `extract.tcl` must `global_route` + `set_wire_rc` first | 🔶 medium |
| 23 | Post-route STA (MMMC) | runs once SPEF exists; pilots report slack +X ns MET | 🟢 none (passes) |
| 24 | IR drop (PSM) | cascading-missing on SPEF | 🔶 medium |
| 25 | EM | cascading-missing on SPEF | 🔶 medium |
| 26 | Antenna | router runs it; report not on audit path | 🟢 low |
| 27 | SI (crosstalk) | cascading-missing on SPEF | 🔶 medium |
| 30 | DRC / LVS / ERC | sky130 ships only Calibre decks; open decks need wiring (LVS chain = § C) | 🔴 high (env) |
| 33 | Metal fill | runner lacks the fill stage → no `filled.def` | 🔶 medium |
| 18 | Spare cells | 30 placed; `spare_cells.json` missing `rows[]` | 🟢 low (schema) |
| 5 | Formal | `altsyncram` no formal model → INFORMATIONAL waiver | 🟢 none |

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
