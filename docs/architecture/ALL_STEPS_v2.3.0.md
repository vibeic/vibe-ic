# Vibe-IC — All Steps: Phase → Stage → Step (v2.3.0)

Every step of the full flow, organised as **Phase → Stage → Step** with a
**single continuous numbering 1 → 44** (starting from Stage 1's Spec-to-RTL).
Phase 1's document-generation steps are labelled **D1–D5** (pre-flow, not
counted in 1→44); two parallel tracks — **Analog A1–A9** and **Mixed-signal
M1–M4** — run alongside.

v2.3.0 highlights (aligned with the industry-standard flow, fixed once
before official release):

- **Step 14 moved into Stage 2**: it is the synthesis→PnR handoff QA (the
  synthesis stage's closing gate), not a physical-design step; marked
  open-source-Yosys-specific.
- **New Step 28: PERC / Reliability sign-off** — ESD pad-ring + discharge
  topology, latch-up well-tap, cross-voltage-domain protection; mirrors the
  industry's standalone Calibre-PERC sign-off deck as an enforced numbered
  step (old 28–41 renumbered to 29–42).
- **New Step 35: DFM screen** — CMP density window + redundant-via
  ratio (deterministic DEF count) + OPC/RET/SRAF/PSM as NAMED
  `FOUNDRY_SIDE` disclosure items (mask synthesis is foundry-side; at
  <=28nm they become designer-collaboration items).
- **New Step 44: Reliability qualification (HTOL)** — long-duration
  operating-life qual, distinct from Step 43's burn-in (infant-mortality
  screen).
- Every step now carries **Input / Output** columns (outputs derive from the
  flow yaml's required_outputs).

**Phase → Stage map**

- **Phase 1** — Specification & documents: two entries (**Agent path** ·
  **doc-gen path D1–D5**) + optional architecture-exploration front-ends
- **Phase 2** — RTL → synthesis: Stage 1 (RTL+verification) · Stage 2
  (constraints+synthesis+DFT+handoff gate)
- **Phase 3** — Physical → Tapeout: Stage 3 (physical+sign-off) · Stage 4
  (output+tapeout) · Stage 5 (manufacturing & test)
- **Parallel** — Analog A1–A9 · Mixed-signal M1–M4

---

## Phase 1 — Specification & documents

Two entries; both produce the same L-series design documents that feed Phase 2:

- `phase1/input_prompt/` — free text / natural language → **Agent path**
- `phase1/input_doc/` — existing documents / structured YAML → **doc-gen path** (D1–D5)

### Agent path (free-text input)

| Agent | What it does |
|---|---|
| **PM Agent** | User-facing: turns natural-language requirements into design facts, asks one plain-language question per gap, hands off once confirmed. |
| **IC Expert Agent** | Behind the PM: reviews every layer with silicon expertise, fills sensible defaults, cross-layer consistency checks. Never user-facing. |

Flow: user free text → PM Agent → IC Expert Agent → finalised L-series documents.

### doc-gen path D1–D5 (existing-document input)

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| D1 | Doc extraction → L1–L13 | Ingest prompt/docs into `input_doc/` and deterministically extract the core design layers. | user docs / prompt | `L1`–`L13` JSON |
| D2 | Core design-layer docs L1–L13 | Deterministic extraction of datasheet, FRS, register map, etc. | D1 plain text | `L1_DATASHEET` … `L13` |
| D3 | Extended docs L14–L23 | Protocol, timing, power intent (L21), skeletons. | L1–L13 | `L14`–`L23` JSON |
| D4 | Protocol-class synthesis | Detect the IC's protocol class (81 classes) and synthesise class facts. | full input text | `ic_class` + protocol facts |
| D5 | Coverage report | Verify the input documents landed completely in the L docs. | input docs + L docs | parity / coverage report |

### Architecture-exploration front-ends (optional, feed Step 1)

| Front-end | What it does | Input | Output |
|---|---|---|---|
| architecture-explore | Design-space exploration (pipeline depth / parallelism / memory vs PPA, Pareto filter). | L docs + perf targets | architecture decisions (feed Step 1) |
| hls-c2rtl | C/C++/SystemC → RTL via HLS (open-source XLS, etc.). | C/SystemC model | RTL (verified from Step 2 onward) |
| SpinalHDL/Chisel front-end | `eda_spinalhdl_gen` emits Verilog from Scala HDL. | SpinalHDL source | Verilog RTL |

---

## Phase 2 — RTL → synthesis

### Stage 1 — RTL generation & verification

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| 1 | Spec-to-RTL | Author synthesizable RTL from the L-series docs (SoC/CPU classes may take the IP-catalog reuse + glue path). | L1–L23 docs | `rtl/*.v(.sv)` · coverage report |
| 2 | 🔁 Lint (RTL hygiene) | Static RTL style/bug checks; auto-fixable issues fixed first. | RTL | lint reports (hygiene / ROM-init) |
| 3 | 🔁 CDC / RDC check | Clock-domain / reset-domain crossing safety. | RTL | CDC/RDC reports (crossing / async / reset-dep) |
| 4 | 🔁 Simulation (testbench + coverage) | Per-IC oracle testbench functional simulation (golden compares) + coverage measurement. | RTL · L10 test cases | sim logs · results.xml · coverage report |
| 5 | 🔁 Formal verification (assertions) | Prove key properties hold (`all_proved` requires the .sby + SymbiYosys evidence chain). | RTL · L3 constraints | `.sby` · formal results · full-stack TB results |
| 6 | FPGA early prototype | Pre-synthesis behavioral prototype on FPGA. | RTL · board constraints | `.sof` · map report · FPGA verification audit |

### Stage 2 — Constraints, synthesis, DFT & handoff gate

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| 7 | Constraint setup (SDC + PVT matrix) | Author timing constraints (SDC) + PVT corner matrix; power intent modelled via L21. | L8 timing · L21 · PDK liberty | `*.sdc` · `pvt_matrix.json` |
| 8 | 🔁 SDC validation | Validate constraint correctness, completeness, and exception (false_path/multicycle) justification. | SDC · L8 | SDC check report |
| 9 | Synthesis (Yosys → mapped netlist) | Synthesize RTL and technology-map (dfflibmap + abc -liberty) to the standard-cell netlist. | RTL · SDC · liberty | `synth/netlist.v` · area stats |
| 10 | 🔁 Pre-layout STA (multi-corner) | Pre-layout static timing analysis (SS/TT/FF). | netlist · SDC · liberty | pre-PnR timing report + summary |
| 11 | DFT insertion (scan chain + ATPG) | Insert scan chains + generate patterns (open-source Fault: scan + stuck-at ATPG + TAP; MBIST/LBIST/compression out of open-source scope). | netlist | scan netlist · ATPG coverage report |
| 12 | Post-DFT optimization (resynth / buffering) | Re-optimise timing/area after DFT insertion. | scan netlist | `post_dft_netlist.v` |
| 13 | 🔁 Equivalence check (RTL ≡ netlist) | Formally prove gate-level netlist ≡ RTL (LEC). | RTL · post-DFT netlist | LEC report |
| 14 | 🔁 Synthesis handoff gate (pre-PnR Yosys audit) | Synthesis→PnR handoff QA: synth script + netlist audit (**open-source-Yosys specific**; the synthesis stage's closing gate). | synth script · netlist | handoff audit reports |

---

## Phase 3 — Physical design → Tapeout

### Stage 3 — Physical design & sign-off

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| 15 | Floorplan + PDN | Chip floorplan + power delivery network; tapcell insertion (latch-up well-ties, SKY130 14 µm rule). | netlist · hardmacro LEFs (`pdk_local/` auto-included) | `floorplan.def` · PDN |
| 16 | Clock planning | Clock-tree distribution strategy. | floorplan | `clock_plan.json` |
| 17 | Placement (global + detailed) | Place standard cells. | floorplan · netlist | `placed.def` |
| 18 | Spare-cell + ECO-prep insertion | Pre-place spare cells / ECO readiness so later fixes are metal-only. | placed.def | `spare_cells.json` · coverage report |
| 19 | CTS (clock tree synthesis) | Build and balance the clock tree. | placed.def · clock plan | `post_cts.def` · clock-tree report |
| 20 | 🔁 Post-CTS hold fixing | Repair hold violations after CTS (the runner repeats hold repair post-global-route). | post_cts.def | `post_hold.def` |
| 21 | Routing (global + detailed) | Complete all signal routing. | post_hold.def | `routed.def` · router DRC report |
| 22 | Parasitic extraction (SPEF) | Extract post-route parasitics. | routed.def · tech LEF | SPEF |
| 23 | 🔁 Post-route STA (multi-corner sign-off) | Sign-off timing with real parasitics (MMMC = per-corner loop, one report per corner). | netlist · SPEF · SDC · multi-corner liberty | post-route timing report · `per_corner/` |
| 24 | 🔁 IR drop | Power-grid voltage-drop analysis, PASS/FAIL vs the 5%-of-VDD budget. | routed.def (PSM) | IR report (worst µV + budget verdict) |
| 25 | 🔁 EM check (electromigration) | Current-density / metal-lifetime screen. | routed.def (PSM -enable_em) | EM report + per-segment currents |
| 26 | 🔁 Antenna check | Detect + repair process-antenna violations. | routed.def | antenna report |
| 27 | 🔁 Signal integrity (crosstalk) | Crosstalk/noise screen (SPEF coupling-cap; advisory tier explicitly named). | SPEF | SI report (incl. >0.9 coupling watch-list) |
| 28 | 🔁 PERC / Reliability sign-off (ESD + latch-up + cross-domain) | **(new)** Enforced sign-off: ESD pad-ring + discharge topology, latch-up well-tap, cross-voltage-domain protection; device-physics sizing stays a named manual-review item. | routed.def · step-24–27 reports | `perc_equivalent.json` · PERC memo · gate verdict |
| 29 | Post-layout gate-level simulation (SDF) | Gate-level sim with SDF delays to confirm post-layout function (honest SKIP when no SDF re-sim ran). | gate netlist · SDF · TB | post-sim results |
| 30 | Post-layout SPICE verification | Transistor-level correlation for critical paths + analog blocks. | SPICE decks · SPEF | SPICE correlation report |
| 31 | 🔁 Physical verification (DRC + LVS + ERC + density) | Sign-off physical rules incl. per-layer CMP density window; LVS = Magic extraction + real netgen compare. | GDS · gate netlist · PDK decks | sign-off DRC · LVS · ERC reports |
| 32 | 🔁 ECO (repair loop) | Engineering-change repair loop when sign-off finds issues. | sign-off reports | ECO log or no-ECO flag |

### Stage 4 — Output & Tapeout

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| 33 | Power analysis (post-layout) | Full-chip power sign-off (post-layout vectorless OpenSTA report_power; optional VCD vector mode). | netlist · SDC · liberty (+ optional VCD) | power report (leakage+dynamic, analysis_mode) |
| 34 | Metal fill (density fill insertion) | Std-cell-row filler placement (white-space); per-layer metal CMP density screened by Step 31's KLayout deck. | routed.def | `filled.def` · density report |
| 35 | DFM screen (manufacturability) | **(new)** CMP density window + redundant-via ratio (single-cut fraction advisory); OPC/RET/SRAF/PSM as FOUNDRY_SIDE disclosure items (designer-collaboration at <=28nm). | routed.def · density report | `dfm_screen.json` (via stats + foundry-side list) |
| 36 | Tapeout checklist (final sign-off) | Item-by-item final confirmation (substance checks: DRC counts, evidence chains). | all sign-off reports | `tapeout_checklist.json` |
| 37 | GDSII output | Stream the foundry-deliverable GDSII (only when Step 31 PV is fully clean). | routed.def · merged GDS | sign-off `*.gds` |
| 38 | Foundry handoff (mask spec + WAT + scribe + corner vectors) | Foundry physical mask kit: mask spec + WAT plan + scribe PCM + corner ATE vectors (chip-specific; foundry-supplied fields named `PENDING_FOUNDRY_*`). | GDS · netlist stats · L10 cases | `mask_spec.json` · `wat_plan.json` · scribe · `corner_test_vectors.json` |
| 39 | FPGA final sign-off (on-board test) | Final FPGA recompile + on-board attestation with hardware evidence. | RTL · board | final `.sof` · `on_board_pass.json` |

### Stage 5 — Manufacturing & test (post-fab; triggers on silicon receipt)

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| 40 | Fabrication (foundry, external) | Foundry mask-set + wafer fab (OPC/RET are foundry-side mask synthesis). | foundry handoff kit | mask/wafer intake attestations |
| 41 | Wafer sort / probe test | Wafer probing, good-die selection; yield independently re-derived vs target. | wafer lot · probe card | `wafer_sort_yield.json` · `wafer_map.csv` |
| 42 | Packaging (assembly) | wirebond / FC-CSP / WLCSP assembly. | good dies | `packaging_log.json` |
| 43 | Final test (ATE + burn-in) | Post-package final test (functional + parametric + burn-in infant-mortality screen). | packaged units · ATE patterns | `final_test_yield.json` · `burn_in_results.json` |
| 44 | Reliability qualification (HTOL / FIT) | **(new)** Long-duration HTOL qual (device-hours / failures / FIT attestation; required for automotive/medical grades, dormant for consumer MPW). | HTOL chamber results | `htol_results.json` verdict |

> Out-of-flow lab steps (unnumbered): PFA/EFA (destructive FIB/SEM/EMMI
> failure analysis) and silicon characterization (shmoo) — data originates
> from external equipment; the plugin owns the data-analytic root-cause layer
> (`wafer_map_pattern_classify`, yield-diagnostic).

---

## Parallel tracks

### Analog A1–A9 (parallel to Stages 1–3)

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| A1 | Analog spec extraction | Extract per-block analog specs from the L docs. | L5 ADI spec | `spec.json` |
| A2 | Topology selection | Choose the circuit topology per spec. | spec.json | `topology.md` |
| A3 | Netlist generation | Generate the SPICE netlist. | topology · PDK models | `<block>.sp` |
| A4 | Corner sweep (PVT) | PVT corner sweep + Monte-Carlo yield (`mc_yield_pct` ≥ 95% gate). | `.sp` · PDK corner libs | `corner_results.json` (executed/derived counts) |
| A5 | Analog layout | Complete the analog layout. | netlist | `layout.mag` / GDS |
| A6 | Block physical verification (per-block DRC + LVS) | Per-block DRC + LVS before merge (catches block-level errors top-level PV would mask). | block GDS · netlist | DRC clean / LVS match flags |
| A7 | 🔁 Post-layout resimulation | Re-simulate with extracted parasitics; compare pre-vs-post specs (>10% degradation loops to A3). | layout parasitics · spec | `pre_vs_post.json` |
| A8 | Hardmacro generation (LEF + Liberty + GDS + Verilog) | Package the block for Stage-3 consumption. | layout · characterisation | 4-file hardmacro |
| A9 | 🔁 Co-simulation / HW verification | Mixed digital+analog simulation and hardware-in-the-loop verification. | hardmacro · digital RTL | cosim / HW measurement results |

### Mixed-signal M1–M4 (triggered when analog blocks exist)

| # | Step | What it does | Input | Output |
|---|---|---|---|---|
| M1 | Top-level integration (A+D GDS merge) | Merge digital + analog GDS, place macros; run top-level LVS on the merged GDS (Magic extraction + netgen, macros blackboxed). | digital GDS · hardmacro GDS | `top_merged.gds` · merge/LVS report |
| M2 | Power domain verification (level shifter / isolation) | Structural verification of cross-domain level-shifters / isolation (plus a DEF-level cross-domain sign-off check). | L21 · merged design | power_domain / level_shifter / isolation reports |
| M3 | Mixed-signal verification (AMS co-sim) | AMS co-simulation + interface signal integrity. | merged design · cosim TB | cosim results · interface SI report |
| M4 | Mixed-signal sign-off | Top-level verdict rolled up from M1–M3. | M1–M3 reports | `signoff.json` |

---

## Totals

| Phase | Stages | Steps |
|---|---|---|
| Phase 1 — Specification & documents | two entries (Agent · doc-gen) + architecture front-ends | D1–D5 + PM Agent · IC Expert Agent |
| Phase 2 — RTL → synthesis | Stage 1 · Stage 2 | 1–14 |
| Phase 3 — Physical → Tapeout | Stage 3 · Stage 4 · Stage 5 | 15–44 |
| Parallel | Analog · Mixed-signal | A1–A9 · M1–M4 |

**44 sequential steps** (Stage 1: 1–6 · Stage 2: 7–14 · Stage 3: 15–32 ·
Stage 4: 33–39 · Stage 5: 40–44), plus Phase 1 (Agent path & doc-gen path
D1–D5) and the two parallel tracks (Analog A1–A9 · Mixed-signal M1–M4).
Preflight: P0 (environment health check).
Orchestrator `vibe_ic_one_shot_runner.py` runs Phase 1 → Phase 2 → Analog → Phase 3.

Out of scope (declined with reasons): designer-EXECUTED OPC/RET (mask synthesis is foundry-side — surfaced as FOUNDRY_SIDE items in Step 35 + noted at Step 40), commercial
hardware emulators (FPGA path covers the intent), MBIST/LBIST/EDT compression
(no open-source engines), PFA/EFA, BSR/BSDL, automatic clock gating (no
characterized ICG cell in sky130; manual RTL clock gating remains available),
via-doubling/CAA (commercial DFM).

繁體中文版：`ALL_STEPS_v2.3.0.zh-TW.md`.
