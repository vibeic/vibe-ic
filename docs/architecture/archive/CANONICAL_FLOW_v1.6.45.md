# Vibe-IC Canonical Flow — Phases / Stages / Steps with I/O + Folder Structure

**Plugin version**: v1.6.45
**Generated**: 2026-05-09 (regenerate when the YAML changes)
**Source of truth**: `vibe-ic-marketplace/plugins/vibe-ic/flow/phase2_phase3.yaml` + `programs/_path_layout.py`
**Compliance enforcer**: `programs/flow_compliance_check.py` (parses the YAML and emits PASS / FAIL / WAIVED per step)

> Any agent claiming "Phase 2+3 complete" MUST first run `flow_compliance_check.py --strict` and report `Overall: PASS` or `PASS_WITH_WAIVERS`. See CLAUDE.md §11 for the SOLE ACCEPTANCE CRITERION.

---

## 1. Two-entry-point overview

```
Path A:  Prompt / Dialogue ──► Phase 1 (phase1 skill, fact-graph engine)
                               ├─ phase2a/generated_docs/L*.json   → Phase 2b machine input
                               └─ human_docs/L*.md                  → human review

Path B:  Existing Design Docs ──► Phase 2a (17 skills, vendor PDF/DOCX → L*.json)
                                  ├─ phase2a/extracted_docs/        verbatim source extracts
                                  └─ phase2a/generated_docs/L*.json → Phase 2b machine input

Phase 2b (22 skills): L1-L13 → RTL → lint → sim → formal → FPGA SOF + on-board test
Analog (A1-A9, parallel): per-block sizing → layout → hardmacro (LEF+LIB+GDS+V) → cosim
Mixed-signal (M1-M4): A+D top-level merge → power-domain check → AMS co-sim → final PV
Phase 3 (23 skills): synth → 3-corner STA → DFT → PnR → DRC/LVS → tapeout → manufacturing
```

The canonical flow is **40 main-track steps + 9 analog (A1-A9) + 4 mixed-signal (M1-M4) + 1 P0 pre-flight = 54 entities**.

---

## 2. Top-level project folder layout

Every project root MUST follow this layout. The `top_level_layout_check` gate enforces the whitelist; only the 6 canonical directories and 3 metadata files may exist at the top.

```
<project>/
├── input/                     raw vendor docs, OTP, PDK
│
├── phase2a/                   docs → L1-L13 JSON (17 skills)
│   ├── extracted_docs/        verbatim extracts (Path B)
│   ├── generated_docs/        L1.json … L13.json (Path A or B output)
│   ├── extraction_patterns.json
│   ├── extraction_patterns.auto.json
│   ├── completeness_check_config.json
│   └── ai_deep_review_patches.json
│
├── phase2b/                   L1-L13 → RTL → SOF (22 skills)
│   ├── stage1/                Steps 1-6: RTL + verification
│   │   ├── rtl/                       Step 1 output  (.sv / .v)
│   │   ├── rtl.pre_gen_backup/        snapshot before regen
│   │   ├── sim/                       Step 4 output
│   │   ├── sim_full_stack/            Step 5 bit-level full-stack TB
│   │   ├── formal/                    Step 5 SBY decks + proof traces
│   │   ├── tb/                        testbench library
│   │   └── fpga/                      Step 6 early prototype + Step 36 final
│   │       └── final/                 Step 36 final SOF + on_board_pass.json
│   └── stage2/                Steps 7-13: synth + DFT
│       ├── constraints/               Step 7  SDC + PVT matrix
│       ├── synth/                     Step 9 / 12 / 14 netlists
│       └── dft/                       Step 11 scan + ATPG
│
├── analog/                    A1-A9 (parallel with phase2b)
│   ├── <block>/                       per-block sizing / layout / corners
│   │   ├── spec.json                  A1
│   │   ├── topology.md                A2
│   │   ├── *.sp                       A3
│   │   ├── corner_results.json        A4
│   │   ├── layout.mag                 A5
│   │   ├── pre_vs_post.json           A7
│   │   ├── drc_clean.flag             A6
│   │   └── lvs_match.flag             A6
│   └── hardmacro/<block>/             A8 outputs
│       ├── *.lef                      Abstract LEF for PnR
│       ├── *.lib                      Liberty for STA
│       ├── *.gds                      Geometry for merge
│       └── *.v                        Black-box behavioural model
│
├── phase3/                    Steps 14-36 (PD → tapeout sign-off)
│   ├── stage3/                Steps 14-30: physical design
│   │   ├── pnr/                       Steps 15-20, 32 (def files)
│   │   ├── cts/                       Steps 16, 18
│   │   ├── extracted/                 Step 21 (SPEF)
│   │   ├── eco/                       Step 30
│   │   ├── spice/                     Step 28 (post-layout SPICE)
│   │   ├── sta/                       Steps 10, 22 (pre + post route)
│   │   └── sim_postlayout/            Step 27 (post-layout gate-level)
│   ├── mixed_signal/          M1-M4
│   │   └── cosim/                     M3 AMS co-sim outputs
│   └── stage4/                Steps 31-36: sign-off + handoff
│       ├── gds/                       Step 34 final GDS
│       └── foundry_handoff/           Step 35 (mask spec, WAT, scribe, corner kit)
│
├── manufacturing/             Steps 37-40 (off-tree foundry handover)
│
├── reports/                   human-readable summaries + per-phase artefacts
│   ├── final_summary.md               (root) doctrine rule #3 — chip-AGNOSTIC
│   ├── chip_specific_summary.md       (root) doctrine rule #3 — chip-specific
│   ├── phase2a/                       Step 1 extraction-coverage + completeness
│   ├── phase2b/                       Steps 2-13 lint / cdc / sim / fpga / dft
│   ├── phase3/                        Steps 22-29 STA / IR / EM / DRC / LVS …
│   ├── analog/                        A4-A9 + M1-M4 reports
│   ├── audit/                         flow_compliance.json, tapeout_checklist.json
│   └── orchestrator/                  one_shot runners' JSON + logs
│
├── waivers.json               machine-readable per-step deferrals
├── provenance.jsonl           append-only audit trail
└── rig_topology.json          hardware lab wiring snapshot (for FPGA + scope)
```

**Rules:**
1. Programs MUST resolve paths via `programs/_path_layout.py` (`rtl_dir`, `report_path`, …) — never hardcode strings.
2. `reports/` is partitioned into 6 phase-aligned subfolders (`reports/{phase2a,phase2b,phase3,analog,audit,orchestrator}/`). The only two files allowed at `reports/` root are `final_summary.md` and `chip_specific_summary.md` (`reports_subfolder_taxonomy_check` gate).
3. Top-level whitelist: `input/`, `phase2a/`, `phase2b/`, `phase3/`, `analog/`, `reports/` + `provenance.jsonl`, `rig_topology.json`, `waivers.json` (`top_level_layout_check` gate).

---

## 3. `reports/` filename → subfolder auto-routing

`programs/_path_layout.py::report_path(project, filename)` routes any flat report name into its phase-aligned subfolder. Highlights:

| Filename pattern                         | Routed to                |
|------------------------------------------|--------------------------|
| `extraction_coverage_report.{md,json}`   | `reports/phase2a/`       |
| `synth_netlist.json`, `sdc_check.json`   | `reports/phase2b/`       |
| `rtl_bugs.json`, `md905_test.json`       | `reports/phase2b/`       |
| `cdc/`, `coverage/`, `dft/`, `fpga/`, `gates/`, `lint/`, `plugin_quality/` | `reports/phase2b/<sub>/` |
| `antenna.{rpt,json}`, `drc_signoff.{rpt,json}`, `em.{rpt,json}`, `ir_drop.{rpt,json}`, `lvs.{rpt,json}`, `power.{rpt,json}`, `si_crosstalk.{rpt,json}`, `spice_correlation.json` | `reports/phase3/` |
| `pnr/`, `sta/` subdirs                   | `reports/phase3/<sub>/`  |
| `mixed_signal/` subdir                   | `reports/analog/<sub>/`  |
| `flow_compliance.json`, `phase23_completion_audit.json`, `tapeout_checklist.json`, `FINAL_REPORT.md`, `signoff/`, `hardware/` | `reports/audit/` |
| `phase{2a,2b,3,23}_one_shot.json`, `vibe_ic_one_shot.json` | `reports/orchestrator/` |
| Unknown filenames                         | `reports/audit/` (fallback) — surfaces in `reports_subfolder_taxonomy_check` |

---

## 4. Stage summary

| Stage              | Owner       | Steps                  | Brief                                                           |
|--------------------|-------------|------------------------|-----------------------------------------------------------------|
| `stage1`           | Phase 2b    | 1-6                    | RTL gen → lint → CDC/RDC → sim → formal → FPGA early prototype |
| `stage2`           | Phase 2b    | 7-13                   | SDC → SDC validation → synth → STA → DFT → post-DFT → LEC      |
| `stage_analog`     | Analog      | A1-A9                  | Spec → topology → netlist → corners → layout → DRC/LVS → resim → hardmacro → cosim |
| `stage3`           | Phase 3     | 14-30                  | pre-PnR Yosys → floorplan → place/route → STA → IR/EM/antenna/SI → post-layout sim/SPICE → DRC/LVS/ERC → ECO |
| `stage_mixed_signal` | Mixed-sig | M1-M4                  | Top GDS merge → power-domain/level-shifter → AMS cosim → top-level PV |
| `stage4`           | Phase 3     | 31-36                  | Power → fill → tapeout-checklist → GDS → foundry handoff → FPGA final |
| `stage5_manufacturing` | Foundry | 37-40                  | Fab → wafer sort → packaging → final ATE                       |
| `stage_p0`         | Plugin CI   | P0                     | 77 chip-AGNOSTIC structural-RTL pre-flight gates               |

🔁 indicates a closed-loop step (FAIL falls back to an earlier step rather than aborting the run).

---

## 5. Per-step input/output reference

> "Inputs" below = upstream step outputs + spec layers a step is required to read.
> "Required outputs" come straight from the YAML's `required_outputs:` array; closed-loop trigger comes from `closed_loop:`.

### stage1 — RTL Generation + Verification

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| 1 | Spec-to-RTL |  | `phase2b/stage1/rtl/*.sv`, `reports/phase2a/extraction_coverage_report.md`, +1 more |
| 2 | Lint (RTL + Quartus-unsafe + RTL-bug claim schema) | 🔁 | `reports/phase2b/lint/rtl_hygiene.json`, `reports/phase2b/lint/rom_init_lint.json` |
| 3 | CDC / RDC check | 🔁 | `reports/phase2b/cdc/crossing.json`, `reports/phase2b/cdc/async_input.json`, +1 more |
| 4 | Simulation (testbench + L10/L12 coverage + Verilator coverage) | 🔁 | `phase2b/stage1/sim/*.log`, `phase2b/stage1/sim/results.xml`, +1 more |
| 5 | Formal verification (assertions proved + bit-level full-stack TB) | 🔁 | `phase2b/stage1/formal/*.sby`, `phase2b/stage1/formal/results.json`, +1 more |
| 6 | FPGA early prototype + verification report audit |  | `phase2b/stage1/fpga/output_files/*.sof`, `phase2b/stage1/fpga/output_files/*.map.rpt`, +1 more |

### stage2 — Synthesis + DFT

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| 7  | Constraint setup (SDC + PVT matrix) |  | `phase2b/stage2/constraints/*.sdc`, `phase2b/stage2/constraints/pvt_matrix.json` |
| 8  | SDC validation | 🔁 | `reports/phase2b/sdc_check.json` |
| 9  | Synthesis (Yosys → mapped netlist) |  | `phase2b/stage2/synth/netlist.v`, `phase2b/stage2/synth/area.rpt` |
| 10 | Pre-layout STA (multi-corner) | 🔁 | `phase3/stage3/sta/pre_pnr_timing.rpt`, `reports/phase3/sta/pre_pnr_summary.json` |
| 11 | DFT insertion (scan chain + ATPG) |  | `phase2b/stage2/dft/scan_netlist.v`, `phase2b/stage2/dft/atpg_coverage.rpt`, +1 more |
| 12 | Post-DFT optimization (resynth / buffering) |  | `phase2b/stage2/synth/post_dft_netlist.v` |
| 13 | Equivalence check (RTL ≡ post-DFT netlist) | 🔁 | `reports/lec.rpt`, `reports/lec.json` |

### stage_analog — Analog Pipeline (parallel with phase2b)

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| A1 | Analog Spec Extraction |  | `analog/*/spec.json` |
| A2 | Analog Topology Selection |  | `analog/*/topology.md` |
| A3 | Analog Netlist Generation |  | `analog/*/*.sp` |
| A4 | Analog Corner Sweep (PVT) |  | `analog/*/corner_results.json` |
| A5 | Analog Layout |  | `analog/*/layout.mag` |
| A6 | Analog Physical Verification (per-block DRC + LVS before merge) |  | `analog/*/drc_clean.flag`, `analog/*/lvs_match.flag` |
| A7 | Post-Layout Resimulation | 🔁 | `analog/*/pre_vs_post.json` |
| A8 | Hardmacro Generation (LEF + Liberty + GDS + Verilog) |  | `analog/hardmacro/*/*.lef`, `analog/hardmacro/*/*.lib`, +2 more |
| A9 | Co-Simulation / HW Verification | 🔁 | `phase3/mixed_signal/cosim/*_cosim_results.json` |

### stage3 — Physical Design + Sign-off

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| 14 | pre-PnR Yosys gate (synth script template + hilomap-ordering audit) | 🔁 | `phase2b/stage2/synth/netlist.v` |
| 15 | Floorplan + PDN |  | `phase3/stage3/pnr/floorplan.def`, `phase3/stage3/pnr/pdn.tcl` |
| 16 | Clock planning |  | `phase3/stage3/cts/clock_plan.json` |
| 17 | Placement (global + detailed) |  | `phase3/stage3/pnr/placed.def` |
| 18 | CTS (Clock Tree Synthesis) |  | `phase3/stage3/pnr/post_cts.def`, `phase3/stage3/cts/clock_tree.rpt` |
| 19 | Post-CTS hold fixing | 🔁 | `phase3/stage3/pnr/post_hold.def` |
| 20 | Routing (global + detailed) |  | `phase3/stage3/pnr/routed.def`, `phase3/stage3/pnr/drc.rpt` |
| 21 | Parasitic Extraction (RC → SPEF) |  | `phase3/stage3/extracted/parasitic.spef` |
| 22 | Post-route STA (multi-corner multi-mode sign-off) | 🔁 | `phase3/stage3/sta/post_route_timing.rpt`, `reports/phase3/sta/post_route_summary.json` |
| 23 | IR Drop (static + dynamic) | 🔁 | `reports/phase3/ir_drop.rpt`, `reports/phase3/ir_drop.json` |
| 24 | EM check (electromigration lifetime) | 🔁 | `reports/phase3/em.rpt` |
| 25 | Antenna check (gate-oxide protection) | 🔁 | `reports/phase3/antenna.rpt` |
| 26 | Signal Integrity (Crosstalk / Noise / Glitch) | 🔁 | `reports/phase3/si_crosstalk.rpt` |
| 27 | Post-Layout Gate-Level Simulation (Post-Sim + SDF) |  | `phase3/stage3/sim_postlayout/results.log` |
| 28 | Post-Layout SPICE Verification (critical-path correlation + analog) |  | `phase3/stage3/spice/*.sp`, `phase3/stage3/spice/correlation.json` |
| 29 | Physical Verification (DRC + LVS + ERC + Density) | 🔁 | `reports/phase3/drc_signoff.rpt`, `reports/phase3/lvs.rpt`, +1 more |
| 30 | ECO (Engineering Change Order — repair loop) | 🔁 | `phase3/stage3/eco/eco_log.json` |

### stage_mixed_signal — Mixed-Signal Integration

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| M1 | Top-Level Integration (A+D GDS merge + macro placement) |  | `phase3/mixed_signal/top_merged.gds`, `reports/analog/mixed_signal/merge.json` |
| M2 | Power Domain + Level Shifter / Isolation Verification |  | `reports/analog/mixed_signal/power_domain.json`, `reports/analog/mixed_signal/level_shifter.json`, +1 more |
| M3 | Verification (AMS co-sim + RNM + interface SI) |  | `phase3/mixed_signal/cosim/mixed_signal_results.json`, `reports/analog/mixed_signal/interface_si.json` |
| M4 | Sign-Off (top-level PV + final verdict) |  | `reports/analog/mixed_signal/signoff.json` |

### stage4 — Output + Validation

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| 31 | Power analysis (pre/post-layout) |  | `reports/phase3/power.rpt`, `reports/phase3/power.json` |
| 32 | Metal Fill (density fill insertion) |  | `phase3/stage3/pnr/filled.def` |
| 33 | Tapeout checklist (final sign-off confirmation) |  | `reports/audit/tapeout_checklist.json` |
| 34 | GDSII output (only if Step 28 PV fully clean) |  | `phase3/stage4/gds/*.gds` |
| 35 | Foundry Handoff (mask spec + WAT plan + scribe + corner test kit) |  | `phase3/stage4/foundry_handoff/mask_spec.json`, `phase3/stage4/foundry_handoff/wat_plan.json`, +3 more |
| 36 | FPGA final sign-off (recompile + on-board test) |  | `phase2b/stage1/fpga/final/*.sof`, `reports/phase2b/fpga/on_board_pass.json` |

### stage5_manufacturing — Manufacturing & Test

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| 37 | Fabrication (foundry mask-set + wafer fab — external) |  | `manufacturing/mask_set_received.json`, `manufacturing/wafer_lot_received.json` |
| 38 | Wafer Sort / Probe Test (ATE + probe card) |  | `manufacturing/wafer_sort_yield.json`, `manufacturing/wafer_map.csv` |
| 39 | Packaging (assembly: wirebond / FC-CSP / WLCSP) |  | `manufacturing/packaging_log.json` |
| 40 | Final Test (ATE: functional + parametric + burn-in) |  | `manufacturing/final_test_yield.json`, `manufacturing/burn_in_results.json` |

### Pre-flight — P0

| Step | Name | 🔁 | Required outputs (head) |
|------|------|:--:|--------------------------|
| P0 | Structural-RTL pre-flight (77 chip-AGNOSTIC structural gates) |  | (gate-only — no required artefact; populates `reports/phase2b/gates/*.json` lazily) |

---

## 6. Compliance & sign-off

Run from the project root:

```bash
python3 vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py <project> --strict
```

Verdict semantics (CLAUDE.md §11):

- **`Overall: PASS`** — every canonical step executed and verified. Production tapeout-ready.
- **`Overall: PASS_WITH_WAIVERS`** — structurally complete, N steps deferred via `<project>/waivers.json`. Each waiver MUST carry `evidence`, `ticket` and `review_required: true`. **Cannot be claimed as "all canonical steps PASS"** — narrate as "executed PASS = X / (total − N), deferred = N pending foundry sign-off".
- **`Overall: FAIL`** — incomplete; continue.

Individual gate PASS (`tapeout_signoff_check 4/4`, `BACKLOG-v6 P0 9/9`, `BACKLOG-v7 P0 5/5`, …) is necessary but not sufficient — the SOLE acceptance criterion is `flow_compliance_check.py --strict` with one of the three verdicts above.

---

## 7. Regenerating this file

This file is hand-written but its core tables are derived from the canonical YAML. To refresh after a YAML edit:

```bash
cd vibe-ic-marketplace/plugins/vibe-ic
python3 - <<'EOF' > /tmp/steps_compact.md
import yaml; y = yaml.safe_load(open('flow/phase2_phase3.yaml'))
# (see this doc's git history for the full per-stage table emitter)
EOF
```

Then merge the regenerated tables into `## 5. Per-step input/output reference`. The folder layout in `## 2` stays in sync with `programs/_path_layout.py`'s docstring.

---

## 8. Out-of-date predecessors (deleted in v1.6.45 doc-cleanup)

The following older snapshots were deleted in commit `01d07478` because they referenced obsolete step counts (33/34) and pre-v1.6.0 plugin layouts:

- `docs/architecture/vibe_ic_34_steps_io_and_validation.md` (v0.119.1, kept for now — superseded by this doc)
- `docs/design/vibe_ic_steps_assessment_v1.6.15.md` (deleted)
- `docs/design/STANDARD_FLOW.md` (v1.0, kept — narrative-style overview, complementary)
- `docs/tutorials/33_step_flow_overview.md` (kept — tutorial-style introduction, references this canonical doc)

This file (`CANONICAL_FLOW_v1.6.45.md`) is the authoritative reference; the others should defer to it on conflicts.
