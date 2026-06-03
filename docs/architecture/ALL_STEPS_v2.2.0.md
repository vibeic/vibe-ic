# Vibe-IC — ALL Steps, by Stage, in Order (v2.2.0)

One ordered list of every flow step, grouped by stage, with a single continuous
number **1 → 33 starting at Stage 1 (Spec-to-RTL)**. Phase 1 doc-generation is the
lettered pre-flow (**D1–D5**, not in the 1→33 count). Two parallel tracks — Analog
(A1–A9) and Mixed-signal (M1–M4) — follow the main flow. Source of truth = the
runners; finer code-level markers are auto-generated in `FLOW_STEPS_GENERATED.md`.

Stage map: **D** Spec/Docs (Phase 1) · **1** RTL+Verify · **2** Synthesis+DFT ·
**3** Physical+Sign-off · **4** Output+Tapeout.

---

## Phase 1 (pre-flow) — Spec & Documents · D1–D5 (not in the 1→33 count)

| # | Step | Tool / How |
|---|---|---|
| D1 | Ingest & text extraction (prompt or vendor docs → `input_doc/`) | `phase1_doc_one_shot_runner` |
| D2 | Generate L1–L13 core design-layer docs | deterministic extractors |
| D3 | Generate L14–L23 protocol / timing / skeleton docs | overlay extractors |
| D4 | Protocol-class synthesis dispatch (81 classes) | `is_<proto>` + `<proto>_synth` |
| D5 | Coverage / parity report | `phase1` parity report |

## Stage 1 — RTL Generation & Verification

| # | Step | Tool / How |
|---|---|---|
| 1 | Spec-to-RTL (author RTL from L-docs) | `spec-to-rtl` skill |
| 2 | Lint | `eda_lint` + hygiene gates |
| 3 | CDC / RDC check | `cdc-check` |
| 4 | Simulation | `testbench-gen` + `eda_simulate` |
| 5 | Formal verification | `formal-verify` + `assertion-gen` |
| 6 | FPGA early prototype | `eda_fpga_compile` / `eda_fpga_program` → `.sof` |

## Stage 2 — Synthesis & DFT

| # | Step | Tool / How |
|---|---|---|
| 7 | Constraint setup | `constraint-gen` → `*.sdc` |
| 8 | SDC validation | SDC lint |
| 9 | Synthesis (Yosys) | `eda_synth` + `synth-doctor` |
| 10 | Pre-layout STA | `eda_sta_mcorner` (SS/TT/FF) |
| 11 | DFT insertion (scan + ATPG) | `dft-insert` + `atpg` + `eda_dft` |
| 12 | Post-DFT optimization | resynth / buffering |
| 13 | Equivalence check (LEC) | `equivalence-check` + Yosys `equiv` |

## Stage 3 — Physical Design & Sign-off

| # | Step | Tool / How |
|---|---|---|
| 14 | Floorplan + PDN | `eda_pnr` (init) |
| 15 | Clock planning | `clock-planning` skill |
| 16 | Placement (global + detailed) | `eda_pnr` |
| 17 | CTS | `eda_pnr enable_cts=true` |
| 18 | Post-CTS hold fixing | `repair_timing -hold` |
| 19 | Routing (global + detailed) | `eda_pnr enable_detailed_route=true` |
| 20 | Parasitic extraction → SPEF | OpenRCX `extract_parasitics` |
| 21 | Post-route STA (MMMC) | `eda_sta_mcorner` |
| 22 | IR drop | OpenROAD PSM `analyze_power_grid` |
| 23 | EM check | PSM `-enable_em` |
| 24 | Antenna check | OpenROAD `check_antennas` |
| 25 | Signal integrity (crosstalk) | SPEF coupling-cap screen |
| 26 | Post-layout gate-level sim (+SDF) | `eda_simulate` |
| 27 | Physical verification (DRC / LVS / ERC + PERC-equivalent) | KLayout DRC + LVS sign-off chain + Magic ERC + `perc_equivalent` |
| 28 | ECO repair loop | `eco-plan` |

## Stage 4 — Output & Tapeout

| # | Step | Tool / How |
|---|---|---|
| 29 | Power analysis | pre + post layout |
| 30 | Metal fill (density fill) | OpenROAD `filler_placement` |
| 31 | Tapeout checklist | `tapeout-checklist` + `signoff_audit` |
| 32 | GDSII output | `eda_gds` + `def2gds` |
| 33 | FPGA final sign-off | recompile + on-board test + attestation |

---

## Parallel track — Analog A1–A9 (`analog_one_shot_runner.py`, runs alongside Stages 1–3)

| # | Step | Tool / How |
|---|---|---|
| A1 | spec_extract | → `A1_spec.json` |
| A2 | topology_select | `analog-topology-select` → `A2_topology.json` |
| A3 | netlist_gen | → `<block>.sp` |
| A4 | corner_sweep | `ams-sim` → `A4_corners.json` |
| A5 | layout (Magic) | → `A5_layout.json` |
| A6 | per-block physical verification (DRC + LVS) | `analog_a6_block_pv_check` |
| A7 | post-layout resim | → `A7_postsim.json` |
| A8 | hardmacro_gen | → `{.lef,.lib,.gds,.v}` (feeds Stage 3) |
| A9 | hw_verify (HIL) / co-sim | → `A9_hw_verify.json` |

## Parallel track — Mixed-signal M1–M4 (`mixed-signal-cosim` skill, no dedicated runner)

| # | Step | Tool / How |
|---|---|---|
| M1 | top merge | `mixed_signal_m1_top_merge_check.py` |
| M2 | co-sim setup | `mixed-signal-cosim` skill |
| M3 | co-sim run | `mixed-signal-cosim` skill |
| M4 | integration verify | `mixed-signal-cosim` skill |

---

## Totals

**33 sequential steps** — Stage 1: 1–6 · Stage 2: 7–13 · Stage 3: 14–28 · Stage 4: 29–33 —
preceded by the lettered **Phase 1 pre-flow (D1–D5)**, plus **9 Analog (A1–A9)** and
**4 Mixed-signal (M1–M4)** parallel steps.

Pre-flight: P0 (`mcp_server_health_check`, `eda_doctor`). Orchestrator
`vibe_ic_one_shot_runner.py` runs Phase 1 → Phase 2 → Analog → Phase 3.

> Detail beyond this summary: the runner's live code-level markers in
> `FLOW_STEPS_GENERATED.md`; the LVS sign-off chain + PERC-equivalent coverage in
> `PERC_SIGNOFF_MEMO.md`. 繁中版見 `ALL_STEPS_v2.2.0.zh-TW.md`.
