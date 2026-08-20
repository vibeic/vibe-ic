# Vibe-IC — All Steps: Phase → Stage → Step

Every step of the full flow, organised as **Phase → Stage → Step** with a
**single continuous numbering 1 → 44** (starting from Stage 1's Spec-to-RTL).
Phase 1's document-generation steps are labelled **D1–D5** (pre-flow, not
counted in 1→44); two parallel tracks — **Analog A1–A9** and **Mixed-signal
M1–M4** — run alongside.

**Phase → Stage map**

- **Phase 1** — Specification & documents: two entries (**Agent path** ·
  **doc-gen path D1–D5**) + optional architecture-exploration front-ends
- **Phase 2** — RTL → synthesis: Stage 1 (RTL+verification) · Stage 2
  (constraints+synthesis+DFT+handoff gate)
- **Phase 3** — Physical → Tapeout: Stage 3 (physical+sign-off) · Stage 4
  (output+tapeout) · Stage 5 (manufacturing & test)
- **Parallel** — Analog A1–A9 · Mixed-signal M1–M4

**Two exit paths.** The numbered 1→44 sequence is common to both; five
path-specific steps are not, and they carry an `ip`/`ic` suffix instead of a
number because they are not part of the sequential count.

- **Which path** — decided at **0.5ic** (submission template ingest): a slot
  template from a shuttle operator puts the design on the chip/IC path; a
  stated `NO_TEMPLATE.txt` puts it on the cell/IP path.
- **cell/IP path** — the deliverable is a block somebody else places. It
  terminates at **37.5ip** (Digital Hardmacro Generation: LEF + Liberty + GDS +
  Verilog). It does **not** continue to Step 38 or into Stage 5.
- **chip/IC path** — the deliverable is a submittable die. It adds **15.5ic**
  (pad ring), **26.5ic** (die finishing: seal ring + die identification) and
  **37.5ic** (shuttle precheck), then continues through Step 38 and Stage 5.

Steps 1–38 on their own build a **bare die**: no pad ring, no seal ring, no die
identification. That is correct for an IP hand-off and is not a submittable
chip.

---

## Phase 1 — Specification & documents

Two entries; both produce the same L-series design documents that feed Phase 2:

- `phase1/input_prompt/` — free text / natural language → **Agent path**
- `phase1/input_doc/` — existing documents / structured YAML → **doc-gen path** (D1–D5)

### Agent path (free-text input)

| Agent | What it does |
|---|---|
| **IC Expert Agent** | The single Phase-1 front door: faces the user directly in plain language, turns natural-language requirements into design facts (one plain-language question per gap), then reviews every layer with silicon expertise, fills sensible defaults, and runs cross-layer consistency checks. |

Flow: user free text → IC Expert Agent → finalised L-series documents.

### doc-gen path D1–D5 (existing-document input)

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| D1 | Doc extraction → L1–L13 | Ingest prompt/docs into `input_doc/` and deterministically extract the core design layers. | user docs / prompt | `L1`–`L13` JSON | deterministic extractors | `phase1_all_l_docs_present_check`<br>skills: `phase1` |
| D2 | Core design-layer docs L1–L13 | Deterministic extraction of datasheet, FRS, register map, etc. | D1 plain text | `L1_DATASHEET` … `L13` | deterministic extractors | — |
| D3 | Extended docs L14–L27 | Protocol, timing, power intent (L21), skeletons. | L1–L13 | `L14`–`L27` JSON | overlay extractor | — |
| D4 | Protocol-class synthesis | Detect the IC's protocol class (86 classes) and synthesise class facts. | full input text | `ic_class` + protocol facts | is_<proto> + <proto>_synth | — |
| D5 | Coverage report | Verify the input documents landed completely in the L docs. | input docs + L docs | parity / coverage report | parity reporter | — |

### Tape-out route selection (chip/IC path)

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 0.5ic | Submission template ingest (route selection) | Fetch and stage the shuttle operator's published project template — the slot geometry, the die-identification fixtures and that slot's pad list. This is the step that picks the route: a slot template puts the design on the chip/IC path (15.5ic · 26.5ic · 37.5ic); a stated `NO_TEMPLATE.txt` puts it on the cell/IP path (37.5ip). Declared external and unprobed, because it is fetched rather than produced — so the flow stays able to state it was never fetched. | the operator's published project template (external) | `input/submission_template/slots/*.yaml` (or a stated `NO_TEMPLATE.txt`) · `submission_template.json` | — (reads files; no EDA tool) | `submission_template_ingest`・`submission_template_check` |

### Architecture-exploration front-ends (optional, feed Step 1)

| Front-end | What it does | Input | Output |
|---|---|---|---|
| architecture-explore | Design-space exploration (pipeline depth / parallelism / memory vs PPA, Pareto filter). | L docs + perf targets | architecture decisions (feed Step 1) |
| hls-c2rtl | C/C++/SystemC → RTL via HLS (open-source XLS, etc.). | C/SystemC model | RTL (verified from Step 2 onward) |
| SpinalHDL/Chisel front-end | `eda_spinalhdl_gen` emits Verilog from Scala HDL. | SpinalHDL source | Verilog RTL |

Front-end precedence (**artifact-driven**): existing RTL > C/SystemC model (hls-c2rtl) > SpinalHDL/Chisel > prompt-only (Step 1 spec-to-RTL). The available artifacts decide the path — never pick one speculatively.

---

## Phase 2 — RTL → synthesis

### Stage 1 — RTL generation & verification

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 1 | Spec-to-RTL | Author synthesizable RTL from the L-series docs (SoC/CPU classes may take the IP-catalog reuse + glue path, e.g. Caravel-class harness platforms). | L1–L27 docs | `rtl/*.v(.sv)` · coverage report | — (AI-authored from L docs; SoC via IP-catalog) | skills: `spec-to-rtl` |
| 2 | 🔁 Lint (RTL hygiene) | Static RTL style/bug checks; auto-fixable issues fixed first. | RTL | lint reports (hygiene / ROM-init) | Verilator lint | `rtl_hygiene_lint`・`rom_init_lint`・`rtl_bug_report_schema_check`・`internal_vs_external_timing_check`…<br>skills: `rtl-review` |
| 3 | 🔁 CDC / RDC check | Clock-domain / reset-domain crossing safety. | RTL | CDC/RDC reports (crossing / async / reset-dep) | in-house CDC/RDC scan | `cdc_crossing_check`・`cdc_async_input_check`・`reset_dependency_check` |
| 4 | 🔁 Simulation (testbench + coverage) | Per-IC oracle testbench functional simulation (golden compares) + coverage measurement; when L21 declares power domains, the TB should cover power-state transition scenarios (no open-source UPF-aware sim — structural verification stays with M2). | RTL · L10 test cases | sim logs · results.xml · coverage report | iverilog/vvp · Verilator coverage<br>`eda_simulate` | `testbench_gen`・`coverage_closure`・`l10_tb_conformance_check`・`l12_tb_coverage_check`…<br>skills: `testbench-gen` |
| 5 | 🔁 Formal verification (assertions) | Prove key properties hold: safety invariants proved unbounded and functional properties bounded-model-checked with the bound disclosed (`all_proved` requires the .sby + SymbiYosys evidence chain). | RTL · L3 constraints | `.sby` · formal results · full-stack TB results | SymbiYosys (ABC pdr / bmc3)<br>`eda_formal` | `formal_property_run`・`assertion_property_check`・`bit_level_full_stack_tb_check`・`formal_proof_evidence_check`<br>skills: `formal-verify` |
| 6 | FPGA early prototype | Pre-synthesis behavioral prototype on FPGA. | RTL · board constraints | `.sof` · map report · FPGA verification audit | Quartus<br>`eda_synth` | `fpga_test_harness_gen`・`debug_first_pass`・`quartus_map_audit`・`fpga_verification_audit` |

### Stage 2 — Constraints, synthesis, DFT & handoff gate

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 7 | Constraint setup (SDC + PVT matrix) | Author timing constraints (SDC) + PVT corner matrix; power intent modelled via L21 and rendered to UPF (handoff artifact — open-source tools do not consume UPF; structural verification stays with M2). | L8 timing · L21 · PDK liberty | `*.sdc` · `pvt_matrix.json` · `<top>.upf` (optional, when L21 declares power domains) | — (UPF emitted by the `l21_to_upf_emit` script, not an EDA engine) | `sdc_syntax_check`・`pvt_matrix_check`・`l21_to_upf_emit`・`upf_syntax_check` |
| 8 | 🔁 SDC validation (incl. derived-clock guard) | Validate constraint correctness, completeness, and exception (false_path/multicycle) justification; manual ICG / register-divided clocks must declare a matching `create_generated_clock` (vacuous PASS without derived clocks — i.e. it passes automatically when the condition does not apply: no divided clocks in the design means the check self-skips). | SDC · L8 · RTL | SDC check report · `derived_clock_sdc.json` | — | `sdc_syntax_check`・`sdc_validator_check`・`sdc_exception_correlation_check`・`derived_clock_sdc_required_check` |
| 9 | Synthesis (Yosys → mapped netlist) | Synthesize RTL and technology-map (dfflibmap + abc -liberty) to the standard-cell netlist. | RTL · SDC · liberty | `synth/netlist.v` · area stats | Yosys + abc<br>`eda_synth` | `synth_wrapper_gen`・`synth_netlist_check`・`provenance_check`<br>skills: `synth-doctor` |
| 10 | 🔁 Pre-layout STA (multi-corner) | Pre-layout static timing analysis (SS/TT/FF) + post-synth power preview (gate-level vectorless, default toggle rate, disclosed via `analysis_mode`; a different accuracy tier from Step 33's post-layout, optionally VCD-vector, analysis). | netlist · SDC · liberty | pre-PnR timing report + summary · `pre_pnr_power_preview.rpt` | OpenSTA<br>`eda_sta` | `sta_report_check`<br>skills: `sta-review` |
| 11 | DFT insertion (scan chain + ATPG) | Insert scan chains + generate patterns (open-source Fault: scan + stuck-at ATPG + TAP; MBIST/LBIST/compression out of open-source scope). | netlist | scan netlist · ATPG coverage report | Fault (scan+ATPG+TAP)<br>`eda_dft` | `fault_atpg_run`・`dft_atpg_coverage_check` |
| 12 | Post-DFT optimization (resynth / buffering) | Re-optimise timing/area after DFT insertion; the emitted netlist must genuinely retain the scan chain — not merely resolve to a path (2026-08-08: closed a matrix_63x8 dimension-2 gap where an empty file, the pre-DFT netlist copied over, or a netlist whose scan chain silently vanished all satisfied the old files_exist-only gate; Step 13's LEC does not catch scan-chain loss, since scan insertion is designed to be functionally transparent). | scan netlist | `post_dft_netlist.v` | Yosys resynth | `dft_post_optimization_scan_survival_check`<br>skills: `synth-doctor` |
| FS1 | ISO-26262 FMEDA diagnostic-coverage (safety designs only) | Fault-injection on a declared safety mechanism (ECC/parity): inject stuck-at faults on the protected path and measure diagnostic coverage against the ASIL floor. Not applicable for non-safety designs. | RTL · declared safety mechanism · ASIL | fmeda_coverage report (measured DC) | iverilog fault-injection | `fmeda_fault_injection_coverage`・`fmeda_coverage_check` |
| DT1 | Transition-delay-fault (at-speed LOC) ATPG | Generate launch-capture 2-patterns for transition faults on a 2-time-frame launch-on-capture unroll of the scan-cut netlist, and grade the transition test coverage. Not applicable for combinational / no-scan designs. | scan-cut netlist · clock | transition coverage report | Yosys SAT (`sat -prove`) | `transition_fault_atpg_run`・`transition_coverage_check` |
| DT2 | Path-delay-fault (at-speed, timing-graded) ATPG | Report the K longest launch-on-capture paths from the routed netlist with real post-layout timing, then generate and grade a launch-capture 2-pattern per path (robust and non-robust); a path with no possible pattern is excluded, never counted. Not applicable before the routed netlist and parasitics exist. | routed netlist · SPEF · SDC · scan cut | path-delay coverage report | OpenSTA + Yosys SAT (`sat -prove`) | `path_delay_fault_atpg_run`・`path_delay_coverage_check` |
| DT3 | Small-delay-defect (SDD) at-speed grade | Grade each timing-critical path fault by its real post-layout slack: a defect is caught at-speed only when the detecting path's margin is tight, so detection through a low-slack path is a strong catch and through a slacky path is weak. A slack-rich design honestly scores low (its margin masks small delays). Descriptive grade, no floor. Not applicable before the path-delay and transition coverage exist. | path-delay coverage · transition coverage · SDC | SDD coverage report | OpenSTA + Yosys SAT (`sat -prove`) | `sdd_atpg_run`・`sdd_coverage_check` |
| 13 | 🔁 Equivalence check (RTL ≡ netlist) | Formally prove gate-level netlist ≡ RTL (LEC). | RTL · post-DFT netlist | LEC report | Yosys equiv | `lec_equivalence_check`<br>skills: `equivalence-check` |
| 14 | 🔁 Synthesis handoff gate (pre-PnR Yosys audit) | Synthesis→PnR handoff QA: synth script + netlist audit (**open-source-Yosys specific**; the synthesis stage's closing gate). | synth script · netlist | handoff audit reports | Yosys script/netlist audit | `yosys_hilomap_required_check`・`yosys_script_template_check` |

---

## Phase 3 — Physical design → Tapeout

### Stage 3 — Physical design & sign-off

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 15 | Floorplan + PDN | Chip floorplan + power delivery network; tapcell insertion (latch-up well-ties, SKY130 14 µm rule). | netlist · hardmacro LEFs (`pdk_local/` auto-included, via the IP integration check: LEF/GDS/Liberty alignment + corner coverage + L21 supply consistency; macro LEFs should carry obstruction layers) | `floorplan.def` · PDN | OpenROAD (init_floorplan+pdngen+tapcell)<br>`eda_pnr` | `phase3_backend_step`・`floorplan_pdn_check`・`ip_integration_check` |
| 15.5ic | Pad ring (chip/IC path only) | Place the I/O pad ring around the core so the die has bond-out. Not run on the cell/IP path. | `floorplan.def` | `padring.def` · `padring.json` | OpenROAD / PDK I/O library | `pad_ring_gen`・`pad_ring_check` |
| 16 | Clock planning | Clock-tree distribution strategy. | floorplan | `clock_plan.json` | OpenROAD CTS planning | `clock_plan_check` |
| 17 | Placement (global + detailed) | Place standard cells. | floorplan · netlist | `placed.def` | OpenROAD (global+detailed place)<br>`eda_pnr` | `placement_legality_check` |
| 18 | Spare-cell + ECO-prep insertion | Pre-place spare cells / ECO readiness so later fixes are metal-only (paired with Step 32 ECO: provisioned here, consumed there). | placed.def | `spare_cells.json` · coverage report | OpenROAD<br>`eda_pnr` | `spare_cell_coverage_check` (preservation is audited at Step 34, after the passes a spare must survive) |
| 19 | CTS (clock tree synthesis) | Build and balance the clock tree. | placed.def · clock plan | `post_cts.def` · clock-tree report | OpenROAD CTS<br>`eda_pnr` | `cts_quality_check` |
| 20 | 🔁 Post-CTS hold fixing | Repair hold violations after CTS (the runner repeats hold repair post-global-route). | post_cts.def | `post_hold.def` | OpenROAD repair_timing -hold | `hold_closure_check`<br>skills: `hold-fix` |
| 21 | Routing (global + detailed) | Complete all signal routing. | post_hold.def | `routed.def` · router DRC report | OpenROAD TritonRoute<br>`eda_pnr` | `drc_report_check`・`def_stage_progression_check`・`provenance_check` |
| 22 | Parasitic extraction (SPEF) | Extract post-route parasitics; when the PDK ships no coupling captable, lateral coupling caps are added analytically from the routed geometry with a disclosed generic dielectric. | routed.def · tech LEF | SPEF (coupling-aware) | OpenRCX<br>`eda_extraction` | `spef_extraction_check`・`provenance_check` |
| 23 | 🔁 Post-route STA (multi-corner sign-off) | Sign-off timing with real parasitics (MMMC = per-corner loop, one report per corner). | netlist · SPEF · SDC · multi-corner liberty | post-route timing report · `per_corner/` | OpenSTA (per-corner loop)<br>`eda_sta` | `sta_report_check`<br>skills: `sta-review` |
| 24 | 🔁 IR drop (static + dynamic) | Power-grid voltage-drop analysis vs budget: static, plus VCD-vectored dynamic IR (activity-weighted droop under a real switching VCD). | routed.def (PSM) · VCD | static + dynamic IR reports | OpenROAD PSM (`read_vcd`) | `ir_drop_report_check`・`dynamic_ir_drop_check`<br>skills: `ir-drop-triage` |
| 25 | 🔁 EM check (electromigration) | Current-density / metal-lifetime screen. | routed.def (PSM -enable_em) | EM report + per-segment currents | OpenROAD PSM -enable_em | `em_report_check` |
| 26 | 🔁 Antenna check | Detect + repair process-antenna violations. | routed.def | antenna report | OpenROAD check_antennas/repair | `antenna_report_check` |
| 26.5ic | Die finishing — seal ring + die identification (chip/IC path only) | Add the PDK's own seal ring and the shuttle's die-identification cells. Placed **after** the antenna check and **before** physical verification, so the die that Step 31 signs off is the die that ships. Not run on the cell/IP path. | `routed.def` | `die_finished.def` (or a stated `die_finishing.SKIPPED.txt`) · `die_finishing.json` | PDK seal-ring generator (KLayout/Magic), called — never reimplemented | `die_finishing_gen`・`die_finishing_check` |
| 27 | 🔁 Signal integrity (crosstalk) | Crosstalk/noise screen (SPEF coupling-cap; advisory tier explicitly named). | SPEF | SI report (incl. >0.9 coupling watch-list) | in-house SPEF coupling screen (OpenSTA window advisory) | `si_crosstalk_check` |
| 28 | 🔁 PERC / Reliability sign-off (ESD + latch-up + cross-domain) | Enforced sign-off: ESD pad-ring + discharge topology, latch-up well-tap, cross-voltage-domain protection; maps to the four PERC categories — netlist checks + netlist-driven layout checks (automated), current density + P2P resistance (named manual-review). Manual review is signed off by a senior physical-design / reliability engineer; criteria live in `perc_equivalent.json` (categories[].status=MANUAL_REVIEW + `review_criteria`: PDK Jmax tables, foundry ESD discharge-path P2P limit, Vhold>Vdd, L21 cross-domain contract), results back-filled into checklist[].confirmed. | gate netlist · routed.def · L21 power intent · L3 ESD spec · step-24–27 reports | `perc_equivalent.json` · PERC memo · gate verdict | in-house PERC-equivalent (DEF-driven) | `perc_signoff_check` |
| 29 | Post-layout gate-level simulation (SDF) | Gate-level sim with SDF delays to confirm post-layout function (honest SKIP when no SDF re-sim ran). | gate netlist · SDF · TB | post-sim results | iverilog + SDF<br>`eda_simulate` | `post_layout_sim_check` |
| 30 | Post-layout SPICE verification | Transistor-level ngspice correlation vs the Liberty timing: a representative cell plus the top-N STA critical paths, one worst path per distinct endpoint (extracted subckts stitched stage by stage with real net cap; SPICE vs STA path delay per path, aggregated). | SPICE decks · SPEF · STA paths | cell + top-N path SPICE correlation reports | ngspice + OpenSTA<br>`eda_spice` | `spice_correlation_check`<br>skills: `ams-sim` |
| 31 | 🔁 Physical verification (DRC + LVS + ERC + density) | Sign-off physical rules; density here is **RULE COMPLIANCE** (KLayout per-layer CMP-window deck; execution verification → Step 34, optimization advisory → Step 35); LVS = Magic extraction + real netgen compare (macro-bearing designs — e.g. Caravel-class harnesses — may blackbox macros: Magic `lef write -hide` masks the macro to its interface shell, a netgen supplementary setup compares it as a same-name blackbox; the waiver basis = device-level match + KLayout cross-check, written by `signoff_waiver_emit` into the project's `waivers.json`, cross-referenced as reviewer to-dos by the Step 36 checklist's open_waivers). | GDS · gate netlist · PDK decks | sign-off DRC · LVS · ERC reports | KLayout DRC · Magic ext2spice + netgen LVS · OpenROAD ERC<br>`eda_drc_klayout`・`eda_lvs` | `erc_density_check`<br>skills: `drc-fix`・`lvs-triage` |
| 32 | 🔁 Post-route timing repair pass | Multi-corner `repair_design` + `repair_timing -setup`, then a FULL `global_route` + `detailed_route` on the routed DEF. NOT an ECO: it re-routes the whole design rather than preserving the implementation, and there is no released revision for a change order to act on. **It does NOT consume the Step 18 spare cells** — measured: zero spare-cell references in the 180-line generator, and no `dont_touch`/`preserve`. Renamed 2026-07-31. | sign-off reports | ECO log or no-ECO flag | OpenROAD ECO | `eco_loop_audit`<br>skills: `eco-plan` |

### Stage 4 — Output & Tapeout

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 33 | Power analysis (post-layout) | Full-chip power sign-off (post-layout vectorless OpenSTA report_power; optional VCD vector mode). | netlist · SDC · liberty (+ optional VCD) | power report (leakage+dynamic, analysis_mode) | OpenSTA report_power (+ optional VCD) | `power_report_check` |
| 34 | Metal fill (density fill insertion) | Std-cell-row filler placement (white-space); density here is **EXECUTION VERIFICATION** (the `metal_fill_density_check` gate owns the density verdict; rule compliance → Step 31, optimization advisory → Step 35). | routed.def | `filled.def` · density report | OpenROAD filler_placement<br>`eda_pnr` | `metal_fill_density_check`・`spare_cell_preservation_check` |
| 35 | DFM screen (manufacturability) | Manufacturability screen: redundant-via ratio (single-cut fraction advisory) + density **OPTIMIZATION ADVISORY** (cross-references the Step 34 gate result only — never a duplicate FAIL); OPC/RET/SRAF/PSM as FOUNDRY_SIDE disclosure items (escalated to DESIGNER_COLLAB_REVIEW at ≤28nm; the node is derived by `dfm_screen_check` from the `input/pdk/liberty` filenames and recorded in the same `dfm_screen.json` — process_nm / advanced_node / foundry_side fields). | routed.def · density report | `dfm_screen.json` (via stats + foundry-side list) | in-house DEF via statistics + density cross-ref | `dfm_screen_check` |
| 36 | Tapeout checklist (final sign-off) | Item-by-item final confirmation (substance checks: DRC counts, evidence chains). | all sign-off reports | `tapeout_checklist.json` | — (inventory aggregation) | `tapeout_signoff_check`<br>skills: `tapeout-checklist` |
| 37 | GDSII output | Stream the foundry-deliverable GDSII (only when Step 31 PV is fully clean). | routed.def · merged GDS | sign-off `*.gds` | Magic/KLayout stream-out<br>`eda_gds` | `gds_size_check`・`provenance_check` |
| 37.5ip | Digital hardmacro generation (cell/IP path TERMINAL) | Package the signed-off block as a reusable hardmacro. **This is where the cell/IP path ends** — no Step 38, no Stage 5. | sign-off `*.gds` | `hardmacro/*.lef` · `*.lib` · `*.gds` · `*.v` | abstract + Liberty + stream-out | `digital_hardmacro_gen`・`digital_hardmacro_check` |
| 37.5ic | Tape-out precheck — our general ladder, plus the operator's own refusal where the PDK ships one (chip/IC path only) | TWO ARMS on the same GDS. Our general ladder runs on every design that reaches this step. The shuttle operator's published precheck runs IN ADDITION whenever the PDK ships one and that operator's template was fetched — an external authority, not our own bar. A PDK with no shuttle precheck is this same step with one fewer arm, not a different route; registry-says-yes-and-nothing-fetched is `NOT_DETERMINED`, never a silent skip. Where the two arms disagree the step refuses and names both verdicts, rather than preferring one. | sign-off `*.gds` · `tapeout_declaration.json` | `tapeout_precheck.json` · `general_precheck.json` · `shuttle_precheck.json` · `SIGNOFF_*.html` · `BRIEF_*.html` | shuttle operator's precheck container (second arm only) | `tapeout_precheck` → `general_precheck` + `tapeout_readiness_check` |
| 38 | Foundry handoff (mask spec + WAT + scribe + corner vectors) | Foundry physical mask kit: mask spec + WAT plan + scribe PCM + corner ATE vectors (chip-specific; foundry-supplied fields named `PENDING_FOUNDRY_*` — tracked in the Step 36 checklist and back-filled after the foundry replies). | GDS · netlist stats · L10 cases | `mask_spec.json` · `wat_plan.json` · scribe · `corner_test_vectors.json` | — (pack generator) | `foundry_handoff_package_check`<br>skills: `tapeout-checklist` |
| 39 | FPGA final sign-off (on-board test) | Final FPGA recompile + on-board attestation with hardware evidence. | RTL · board | final `.sof` · `on_board_pass.json` | Quartus + on-board measurement | `bringup_plan_gen`・`fpga_on_board_attestation_check` |

### Stage 5 — Manufacturing & test (post-fab; triggers on silicon receipt)

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| 40 | Fabrication (foundry, external) | Foundry mask-set + wafer fab (OPC/RET are foundry-side mask synthesis). | foundry handoff kit | mask/wafer intake attestations | external foundry | `manufacturing_fab_intake_check` |
| 41 | Wafer sort / probe test | Wafer probing, good-die selection; yield independently re-derived vs target. | wafer lot · probe card | `wafer_sort_yield.json` · `wafer_map.csv` | ATE + probe card (external) | `wafer_sort_yield_check` |
| 42 | Packaging (assembly) | wirebond / FC-CSP / WLCSP assembly. | good dies | `packaging_log.json` | assembly house (external) | `packaging_intake_check` |
| 43 | Final test (ATE + burn-in) | Post-package final test (functional + parametric + burn-in infant-mortality screen). | packaged units · ATE patterns | `final_test_yield.json` · `burn_in_results.json` | ATE (external) | `final_test_attestation_check` |
| 44 | Reliability qualification (HTOL / FIT) | Long-duration HTOL qual (device-hours / failures / FIT attestation; required for automotive/medical grades; consumer MPW may stay dormant = DEFERRED, never blocks tapeout). | HTOL chamber results | `htol_results.json` verdict | HTOL chamber (external) | `htol_attestation_check` |

> Out-of-flow lab steps (unnumbered): PFA/EFA (destructive FIB/SEM/EMMI
> failure analysis) and silicon characterization (shmoo) — data originates
> from external equipment; the plugin owns the data-analytic root-cause layer
> (`wafer_map_pattern_classify`, yield-diagnostic).

---

## Parallel tracks

### Analog A1–A9 (parallel to Stages 1–3)

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| A1 | Analog spec extraction | Extract per-block analog specs from the L docs. | L5 ADI spec | `spec.json` | deterministic spec extract | `analog_a1_spec_extract_check`<br>skills: `analog-spec-extract` |
| A2 | Topology selection | Choose the circuit topology per spec. | spec.json | `topology.md` | AI topology select | `analog_a2_topology_select_check`<br>skills: `analog-topology-select` |
| A3 | Netlist generation | Generate the SPICE netlist. | topology · PDK models | `<block>.sp` | xschem netlist<br>`eda_xschem_netlist` | `analog_netlist_pdk_check`<br>skills: `analog-netlist-gen` |
| A4 | Corner sweep (PVT) | PVT corner sweep + Monte-Carlo yield (`mc_yield_pct` ≥ 95% gate). | `.sp` · PDK corner libs | `corner_results.json` (executed/derived counts) | ngspice (corner + MC)<br>`eda_spice_corner` | `analog_a4_corner_sweep_check`<br>skills: `analog-sizing-loop` |
| A5 | Analog layout | Complete the analog layout. | netlist | `layout.mag` / GDS | Magic layout<br>`eda_analog_layout` | `analog_a5_layout_check`<br>skills: `analog-layout` |
| A6 | Block physical verification (per-block DRC + LVS) | Per-block DRC + LVS before merge (catches block-level errors top-level PV would mask). | block GDS · netlist | DRC clean / LVS match flags | Magic DRC + netgen LVS | `analog_a6_block_pv_check`<br>skills: `drc-fix`・`lvs-triage` |
| A7 | 🔁 Post-layout resimulation | Re-simulate with extracted parasitics; compare pre-vs-post specs (>10% degradation loops to A3). | layout parasitics · spec | `pre_vs_post.json` | Magic extraction + ngspice<br>`eda_spice_corner` | `analog_pre_vs_post_layout_check`<br>skills: `analog-extraction-resim` |
| A8 | Hardmacro generation (LEF + Liberty + GDS + Verilog) | Package the block for Stage-3 consumption (LEF should carry obstruction layers — Magic `lef write -hide` or abstract with obs — so top-level routing cannot enter the macro). | layout · characterisation | 4-file hardmacro | Magic/abstract + characterisation | `analog_hardmacro_check`<br>skills: `analog-hardmacro-gen` |
| A9 | 🔁 Co-simulation / HW verification | Mixed digital+analog simulation and hardware-in-the-loop verification. | hardmacro · digital RTL | cosim / HW measurement results | iverilog + ngspice co-sim<br>`eda_spice`・`eda_simulate` | `mixed_signal_cosim_check`・`analog_hw_spice_correlation_check`<br>skills: `mixed-signal-cosim`・`analog-hw-tuning-loop` |

### Mixed-signal M1–M4 (triggered when analog blocks exist)

Trigger timing: runs once **A8 hardmacros are complete** and **Stage 3 is near closure** (routed/GDS mergeable) — hardmacros must exist before floorplan, but M1's GDS merge waits for the digital side to finish routing. If a hardmacro slips until Stage 3 has entered Step 31, M1 waits for the final hardmacro GDS and Step 31's top-level LVS re-runs (incremental — scoped to the macro-interface change).

| # | Step | What it does | Input | Output | Tools (EDA) | Programs / Skills |
|---|---|---|---|---|---|---|
| M1 | Top-level integration (A+D GDS merge) | Merge digital + analog GDS, place macros; run top-level LVS on the merged GDS (Magic extraction + netgen, macros blackboxed). | digital GDS · hardmacro GDS | `top_merged.gds` · merge/LVS report | KLayout merge + Magic/netgen top-LVS | `mixed_signal_top_lvs_run` (producer)・`mixed_signal_merge_check` (gate)<br>skills: `analog-flow-orchestrate` |
| M2 | Power domain verification (level shifter / isolation) | Structural verification of cross-domain level-shifters / isolation, plus a cross-power-domain signal-crossing check that derives the isolation/level-shifter requirement from the power-domain definitions and audits the UPF strategy. | L21 · merged design | power_domain / level_shifter / isolation / signal-crossing reports | structural check programs | `power_domain_crossing_check`・`level_shifter_required_check`・`isolation_cell_required_check`・`power_domain_signal_crossing_check`<br>skills: `ir-drop-triage` |
| M3 | Mixed-signal verification (AMS co-sim) | AMS co-simulation + interface signal integrity. | merged design · cosim TB | cosim results · interface SI report | AMS co-sim | `mixed_signal_cosim_check`・`mixed_signal_interface_si_check`<br>skills: `mixed-signal-cosim`・`ams-sim` |
| M4 | Mixed-signal sign-off | Top-level verdict rolled up from M1–M3. | M1–M3 reports | `signoff.json` | rollup verdict | `mixed_signal_signoff_check`<br>skills: `tapeout-checklist` |

---

## Totals

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — Specification & documents | two entries (Agent · doc-gen) + architecture front-ends | D1–D5 + IC Expert Agent |
| Phase 2 — RTL → synthesis | Stage 1 · Stage 2 | 1–14 |
| Phase 3 — Physical → Tapeout | Stage 3 · Stage 4 · Stage 5 | 15–44 |
| Parallel | Analog · Mixed-signal | A1–A9 · M1–M4 |

**44 sequential steps** (Stage 1: 1–6 · Stage 2: 7–14 · Stage 3: 15–32 ·
Stage 4: 33–39 · Stage 5: 40–44), plus Phase 1 (Agent path & doc-gen path
D1–D5) and the two parallel tracks (Analog A1–A9 · Mixed-signal M1–M4).
Path-specific steps, outside the 1→44 count: 0.5ic (route selection) ·
15.5ic · 26.5ic · 37.5ic (chip/IC path only) and 37.5ip (cell/IP path
terminal). Step 0.5ic is what decides which of the two a design is on; it
runs one path or the other, never both.
Preflight: P0 (environment health check). Conditional lettered steps: FS1 (ISO-26262 FMEDA diagnostic-coverage,
safety designs only) · DT1 (transition-delay-fault ATPG, scan designs only) · DT2 (path-delay-fault at-speed
ATPG, scan designs after routing) · DT3 (small-delay-defect at-speed grade, after DT2).
Orchestrator `vibe_ic_one_shot_runner.py` runs Phase 1 → Phase 2 → Analog → Phase 3.

Out of scope (declined with reasons): designer-EXECUTED OPC/RET (mask synthesis is foundry-side — surfaced as FOUNDRY_SIDE items in Step 35 + noted at Step 40), commercial
hardware emulators (FPGA path covers the intent), MBIST/LBIST/EDT compression
(no open-source engines), BSR/BSDL, automatic clock gating (no
characterized ICG cell in sky130; manual RTL clock gating remains available —
the SDC declaration of divided/gated clocks is guarded by Step 8's
`derived_clock_sdc_required_check`), via-doubling/CAA (commercial DFM).

**E1–E3 external-lab steps (reserved numbering, outside the 44; activated on automotive/medical grade upgrades):**

| # | Step | Notes |
|---|---|---|
| E1 | PFA / EFA | FIB / SEM / EMMI failure analysis (external lab) |
| E2 | Silicon characterization | shmoo plots · voltage/frequency sweeps |
| E3 | Temperature cycling / mechanical stress | JESD22-class environmental stress (external lab) |

## Appendix: measured wall-clock reference (for intuition)

Numbers come from REAL local sky130 open-source-flow runs (the `duration_s` fields of `reports/orchestrator/*_one_shot.json`; design sizes 0.5k–21k cells) — measured, never estimated. Durations vary with design, constraints and machine; nonlinear in cell count.

| Stage | Measured range | Samples |
|---|---|---|
| Step 9 Synthesis (Yosys) | ~0.4 s – 21 s | 0.5k cells (lpc) → 20k cells (cv32e40p) |
| Steps 15–22 PnR (OpenROAD, full) | ~3 s – 31 min | 3.4k cells (subservient) → 21k cells (sha256) |
| Step 37 GDS write | ~2 – 4 s | all samples |
| Step 31 DRC (KLayout sky130 deck) | ~8 – 84 s | 0.5k → 20k cells |
| Step 31 LVS (Magic + netgen) | this batch's samples took the light/skip path, so no representative figure; with real macro compares (e.g. Caravel-class harnesses) it runs **minutes to hours**, scaling with macro count (a field run motivated the 4-hour timeout) | — |
| Steps 40–43 manufacturing (fab/sort/pkg/final test) | external, weeks-scale | no local measurement |

Licensing & IP: the whole flow relies on open-source tools only (Apache-2.0 project; commercial-tool firewall and output ownership: repo-root `README.md` §IP ownership, plus the DCO/patent pledge in `CONTRIBUTING.md`).

繁體中文版：`ALL_STEPS_v1.4.14.zh-TW.md`.
