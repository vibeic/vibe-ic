# Design-for-ECO (deterministic core half) — implementation report

Scope: PROACTIVE Design-for-ECO in the vibe-ic plugin deterministic
half. Chip-AGNOSTIC, minimal, honest, with tests. Existing behaviour +
honesty gates preserved.

## What was added

### flow/phase1_phase2_phase3.yaml
- New PROPER INTEGER **Step 18 "Spare-cell + ECO-prep insertion
  (Design-for-ECO)"** in stage3, between Placement (17) and CTS.
- Per the coordinator correction, every numeric step id >= 18 was
  renumbered **+1** (old 18 CTS -> 19, ... old 40 -> 41). Alpha ids
  (D1, P0, A1-A9, M1-M4) unchanged. `total_steps` 40 -> 41.
- All internal "Step NN" references + cascade comments updated to the
  new numbering (GDS "only if Step 30 PV", M1 note PV->30, foundry note
  tapeout->34, header track 1..41, stage4/5 comments, final_gate footer).
- Step 18 outputs `phase3/stage3/pnr/spare_cells.json` +
  `reports/spare_cell_coverage.json`; gate runs `spare_cell_coverage_check`
  (readiness) + `spare_cell_preservation_check` (survival).
- **Step 33 Metal Fill** annotated ECO-aware: ECO-swappable fillers,
  must not overlap/remove dont_touch spares; re-runs
  `spare_cell_preservation_check` post-fill.
- YAML validated; ids 1..41 contiguous, no dups, no dangling blocks_on.

### programs/phase3_one_shot_runner.py
- New `--spare-density` arg (default 0.02 = 2%; clamped to [0, 0.2];
  0 disables). Pure helpers: `_compute_spare_density`,
  `_spare_count_from_density`, `_spare_type_distribution` (inverter/
  nand2/nor2/mux2/aoi/oai/dff mix, largest-remainder so types sum to
  count), `_spare_grid_positions` (sqrt(N) distributed grid),
  `_discover_spare_cells_from_liberty`, `_build_spare_cells_plan`,
  `_count_placed_cells_from_netlist`, `_build_spare_protection_tcl`.
- Spares inserted as PHYSICAL instances in PnR TCL AFTER detailed
  placement, BEFORE CTS. Emits spare_cells.json {count, density, types,
  tied_off:true, instances:[{name,type,cell,llx,lly,keep}], spare_pads,
  protection{}} + coverage JSON {target/actual density, distribution_ok,
  tie_off_ok, verdict}. Reserves spare IO pads when a pad ring is found.

### Protection from each optimization pass
- **Logical synth (abc/opt_clean/post-DFT resynth):** spares are
  inserted as PHYSICAL post-place instances AFTER abc — logical opt
  literally cannot reach them. Documented Yosys allowlist constant:
  spares tagged `(* keep *)` / `setattr -set keep 1`; opt_clean /
  `clean -purge` skip keep-marked objects by construction.
- **OpenROAD remove_buffers / repair_design / repair_timing / opt /
  detailed-placement legalization:** each spare emits
  `set_dont_touch <name>` (wrapped in catch -> NONFATAL). A re-legalizing
  detailed_placement after insertion honours dont_touch.
- **Metal fill (Step 33):** declared ECO-aware (swappable fillers, no
  overlap/removal of dont_touch spares); preservation re-checked post-fill.

### programs/spare_cell_coverage_check.py (NEW)
Readiness gate. PASS iff actual_density >= target (default 0.02, gate
floor is authoritative — a plan's self-target can't relax it), spares
distributed (distinct grid positions >= 50% of count and > 1), all tied
off, count > 0. Emits JSON verdict.

### programs/spare_cell_preservation_check.py (NEW)
THE key concern. Compares insertion-time spare set vs FINAL
netlist/DEF/GDS: FAIL if any spare/pad name absent (removed/optimized
away) or, when artefacts carry keep markers, lost its keep/dont_touch/
FIXED tag. GDS-only sets require survival only (no keep concept). Emits
`reports/spare_preservation.json` {inserted, survived, removed[],
untagged[], all_keep_attr_intact, verdict}.

### programs/tests/test_spare_cell_design_for_eco.py (NEW)
24 docker-free tests: density compute+clamp; count/type-dist/grid;
plan shape; netlist cell count; coverage PASS + FAIL (clustered /
untied / below-density) incl CLI; preservation PASS (stable+tagged) +
FAIL (missing spare / lost keep attr) + GDS-only survival + 3 CLI cases.

## Results
- `ast.parse` passes on all 4 .py files; YAML `yaml.safe_load` valid.
- `python3 -m pytest programs/tests/ -q`:
  - Baseline: 1334 passed, 4 skipped, 1 xfailed, 4 xpassed, 0 failed.
  - After: **1358 passed** (+24 new), 4 skipped, 1 xfailed, 4 xpassed,
    **0 failed**. No new failures, no regressions.
- Sibling agent (dfe-skills) owns the same +1 renumber in
  benchmark_verify_report.py STEP_METHOD + the new "18" key.

Files (absolute):
- /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
- /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/phase3_one_shot_runner.py
- /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/spare_cell_coverage_check.py
- /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/spare_cell_preservation_check.py
- /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_spare_cell_design_for_eco.py
