# Vibe-IC — ALL Steps: Phase → Stage → Step (v2.2.0)

Every flow step, organized as **Phase → Stage → Step**, with one continuous
main-track number **1 → 41** (starting at Stage 1, Spec-to-RTL). Phase 1's
doc-generation steps are lettered **D1–D5** (pre-flow, not in the 1→41 count).
Two parallel tracks — **Analog A1–A9** and **Mixed-signal M1–M4** — run alongside.

**Phase → Stage map**

- **Phase 1** — Spec & Documents: two input paths (**Agent path** · **doc-gen path D1–D5**)
- **Phase 2** — RTL → Synthesis: Stage 1 (RTL+Verify) · Stage 2 (Synthesis+DFT)
- **Phase 3** — Physical → Tapeout: Stage 3 (Physical+Sign-off) · Stage 4 (Output+Tapeout) · Stage 5 (Manufacturing & Test)
- **Parallel** — Analog A1–A9 · Mixed-signal M1–M4

---

## Phase 1 — Spec & Documents

Two input paths; both yield the same L-series design documents that feed Phase 2:

- `phase1/input_prompt/` — free text / natural language → the **Agent path**
- `phase1/input_doc/` — existing docs / structured YAML → the **doc-gen path** (D1–D5)

### Agent path (when the input is free text)

| Agent | What it does |
|---|---|
| **PM Agent** | Faces the user: turns natural-language requirements into design facts, asks one plain-language question per gap, confirms, hands off. |
| **IC Expert Agent** | Behind the PM Agent: reviews every layer with silicon expertise, fills sensible defaults, cross-checks layer consistency. Never faces the user. |

Flow: user free text → PM Agent → IC Expert Agent → finalized L-docs.

### doc-gen path D1–D5 (when the input is existing documents)

| # | Step | What it does | Tool / How |
|---|---|---|---|
| D1 | Ingest & text extraction | Collect the prompt or vendor docs into `input_doc/` and extract plain text. | `phase1_doc_one_shot_runner` |
| D2 | Generate L1–L13 core design-layer docs | Deterministically extract the core design layers (datasheet, spec, regmap, …). | deterministic extractors |
| D3 | Generate L14–L23 docs | Add the protocol / timing / skeleton overlay layers. | overlay extractors |
| D4 | Protocol-class synthesis dispatch | Detect which protocol class (81 classes) the IC belongs to and synthesize its protocol facts. | `is_<proto>` + `<proto>_synth` |
| D5 | Coverage / parity report | Verify the input documents' content fully landed in the L-docs. | `phase1` parity report |

---

## Phase 2 — RTL → Synthesis

### Stage 1 — RTL Generation & Verification

| # | Step | What it does | Tool / How |
|---|---|---|---|
| 1 | Spec-to-RTL | Author synthesizable RTL from the L-docs. | `spec-to-rtl` skill |
| 2 | 🔁 Lint | Static-check RTL style and common bugs; auto-fix what can be fixed. | `eda_lint` + `rtl_hygiene_lint` |
| 3 | 🔁 CDC / RDC check | Verify clock-domain and reset-domain crossings are safe. | `cdc-check` + `rdc-check` |
| 4 | 🔁 Simulation | Generate testbenches, run functional simulation, measure coverage. | `testbench-gen` + `eda_simulate` |
| 5 | 🔁 Formal verification | Prove key properties (assertions) always hold. | `formal-verify` + `assertion-gen` |
| 6 | FPGA early prototype | Put the design on an FPGA early to verify real behaviour. | `eda_fpga_compile` / `eda_fpga_program` → `.sof` |

### Stage 2 — Synthesis & DFT

| # | Step | What it does | Tool / How |
|---|---|---|---|
| 7 | Constraint setup | Write timing constraints (SDC) and the PVT corner matrix. | `constraint-gen` → `*.sdc` |
| 8 | 🔁 SDC validation | Validate the constraints themselves for correctness and completeness. | SDC lint + `sdc_validator_check` |
| 9 | Synthesis | Map the RTL to a standard-cell gate netlist. | `eda_synth` + `synth-doctor` |
| 10 | 🔁 Pre-layout STA | Multi-corner static timing analysis before layout. | `eda_sta` (SS/TT/FF) |
| 11 | DFT insertion | Insert scan chains and test logic; generate test patterns (ATPG). | `dft-insert` + `atpg` + `eda_dft` |
| 12 | Post-DFT optimization | Re-optimize timing and area after DFT insertion. | resynth / buffering |
| 13 | 🔁 Equivalence check | Formally prove the gate netlist is functionally equal to the RTL. | `equivalence-check` + Yosys `equiv` |

---

## Phase 3 — Physical Design → Tapeout

### Stage 3 — Physical Design & Sign-off

| # | Step | What it does | Tool / How |
|---|---|---|---|
| 14 | 🔁 pre-PnR Yosys gate | Confirm the synth script and netlist meet PnR requirements before layout. | `yosys_script_template_check` + `yosys_hilomap_required_check` |
| 15 | Floorplan + PDN | Plan the chip floorplan and power-delivery network. | `eda_pnr` (init) |
| 16 | Clock planning | Plan the clock-tree distribution strategy. | `cts-plan` skill |
| 17 | Placement | Place the standard cells (global + detailed). | `eda_pnr` |
| 18 | Spare-cell + ECO-prep insertion | Pre-place spare cells and ECO reserves so later bug fixes need only metal-layer changes. | `eda_pnr` + spare-cell checks |
| 19 | CTS (Clock Tree Synthesis) | Build the clock tree and balance skew. | `eda_pnr enable_cts=true` |
| 20 | 🔁 Post-CTS hold fixing | Fix the hold violations the clock tree introduces. | `hold-fix` (`repair_timing -hold`) |
| 21 | Routing | Route all signal nets (global + detailed). | `eda_pnr enable_detailed_route=true` |
| 22 | Parasitic extraction | Extract post-route parasitic RC (SPEF). | OpenRCX `extract_parasitics` |
| 23 | 🔁 Post-route STA | Sign-off timing analysis with real parasitics. | `eda_sta` (MMMC) |
| 24 | 🔁 IR drop | Verify power-grid voltage drop stays within limits. | OpenROAD PSM `analyze_power_grid` |
| 25 | 🔁 EM check | Check current density to ensure metal-line lifetime. | PSM `-enable_em` |
| 26 | 🔁 Antenna check | Detect and repair process antenna violations. | OpenROAD `check_antennas` + `repair_antennas` |
| 27 | 🔁 Signal integrity | Analyse crosstalk / noise impact on signals. | SPEF coupling-cap screen |
| 28 | Post-layout gate-level sim | Gate-level simulation with SDF delays to confirm post-layout function. | `eda_simulate` |
| 29 | Post-layout SPICE verification | Transistor-level simulation of critical paths and analog blocks. | `ams-sim` + `eda_spice` |
| 30 | 🔁 Physical verification | DRC / LVS / ERC physical-rule sign-off. | KLayout DRC + LVS + Magic ERC |
| 31 | 🔁 ECO | Engineering-change repair loop when sign-off finds problems. | `eco-plan` |

### Stage 4 — Output & Tapeout

| # | Step | What it does | Tool / How |
|---|---|---|---|
| 32 | Power analysis | Analyse full-chip power (pre/post-layout). | `power-analysis` |
| 33 | Metal fill | Insert metal fill to meet density rules. | OpenROAD `filler_placement` |
| 34 | Tapeout checklist | Walk the final sign-off checklist item by item. | `tapeout-checklist` + `signoff_audit` |
| 35 | GDSII output | Produce the GDSII data delivered to the foundry. | `eda_gds` + `def2gds` |
| 36 | Foundry handoff | Assemble the complete foundry delivery package. | `tapeout-checklist` + handoff checks |
| 37 | FPGA final sign-off | Final FPGA recompile and on-board test. | recompile + on-board test |

### Stage 5 — Manufacturing & Test (post-fab; fires only when silicon is received)

| # | Step | What it does | Tool / How |
|---|---|---|---|
| 38 | Fabrication | Foundry mask-set and wafer manufacturing (external). | `manufacturing_fab_intake_check` |
| 39 | Wafer sort / probe test | Probe-test wafers and pick good dies. | `wafer_sort_yield_check` |
| 40 | Packaging | Assembly (wirebond / FC-CSP / WLCSP). | `packaging_intake_check` |
| 41 | Final test | Post-package final test (functional + parametric + burn-in). | `final_test_attestation_check` |

---

## Parallel tracks

### Analog A1–A9 (runs alongside Stages 1–3)

| # | Step | What it does | Tool / How |
|---|---|---|---|
| A1 | Analog spec extraction | Extract each analog block's spec from the L-docs. | `analog-spec-extract` → `spec.json` |
| A2 | Analog topology selection | Choose a circuit topology per the spec. | `analog-topology-select` |
| A3 | Analog netlist generation | Generate the SPICE netlist. | `eda_xschem_netlist` → `<block>.sp` |
| A4 | Analog corner sweep | Sweep PVT corners to confirm spec at every corner. | `eda_spice_corner` |
| A5 | Analog layout | Complete the analog layout. | `eda_analog_layout` |
| A6 | Analog physical verification | Per-block DRC + LVS before merge. | `analog_a6_block_pv_check` |
| A7 | 🔁 Post-layout resimulation | Re-simulate with extracted parasitics; compare pre vs post. | `analog-extraction-resim` |
| A8 | Hardmacro generation | Package as LEF + Liberty + GDS + Verilog and feed Stage 3. | `analog-hardmacro-gen` |
| A9 | 🔁 Co-simulation / HW verification | Mixed analog+digital simulation and hardware-in-the-loop. | `mixed-signal-cosim` + `eda_spice` |

### Mixed-signal M1–M4 (fires when analog blocks are present)

| # | Step | What it does | Tool / How |
|---|---|---|---|
| M1 | Mixed-signal top-level integration | Merge analog + digital GDS and place macros. | `mixed_signal_merge_check` |
| M2 | Mixed-signal power domain verification | Check level-shifters / isolation across power domains. | power-domain checks |
| M3 | Mixed-signal verification | AMS co-simulation and interface signal integrity. | `mixed_signal_cosim_check` |
| M4 | Mixed-signal sign-off | Top-level physical verification and final verdict. | `mixed_signal_signoff_check` |

---

## Totals

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — Spec & Documents | two input paths (Agent · doc-gen) | D1–D5 + PM Agent · IC Expert Agent |
| Phase 2 — RTL → Synthesis | Stage 1 · Stage 2 | 1–13 |
| Phase 3 — Physical → Tapeout | Stage 3 · Stage 4 · Stage 5 | 14–41 |
| Parallel | Analog · Mixed-signal | A1–A9 · M1–M4 |

**41 sequential steps** (Stage 1: 1–6 · Stage 2: 7–13 · Stage 3: 14–31 ·
Stage 4: 32–37 · Stage 5: 38–41), plus Phase 1 (Agent path and doc-gen path D1–D5)
and the two parallel tracks (Analog A1–A9 · Mixed-signal M1–M4). Pre-flight: P0
(environment health check). Orchestrator `vibe_ic_one_shot_runner.py` runs
Phase 1 → Phase 2 → Analog → Phase 3.

繁中版：`ALL_STEPS_v2.2.0.zh-TW.md`.
