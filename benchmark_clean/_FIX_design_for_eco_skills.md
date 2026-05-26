# FIX: Design-for-ECO SKILL + optimization-skill preservation audit + benchmark-verify gate

Owner-agent: dfe-skills (skills + benchmark_verify_report.py side of the Design-for-ECO work).
Sibling: dfe-core (owns flow yaml, phase3_one_shot_runner.py, spare_cell_*_check.py).

## What was done (chip-AGNOSTIC, honest)

### 1. New skill: `skills/design-for-eco/SKILL.md`
Methodology doc: WHY pre-place spares (metal-only ECO days+partial-mask vs base-layer
respin weeks+full-mask), WHAT to insert (inverter/nand2/nor2/dff/mux2/aoi/oai mix,
~1-5% density, mandatory tie-offs, even spatial distribution, reserved ECO pads — all
`dont_touch`/`keep`), WHERE (Step 18: after placement, before CTS), ECO-aware metal fill,
the HARD preservation rule, and the readiness acceptance criteria. Registered in
`skills/_classification.json` under the `nl_primary` tier (idempotent add).

### 2. Preservation rule added to ALL 6 optimization skills
A clearly-marked `⛔ ECO spare-cell preservation (mandatory)` block, each TAILORED:
- **synth-doctor** — no `opt_clean`/`clean -purge`/`remove_buffers`/area-recovery on keep cells.
- **rtl-repair** — dead-code elim / keep-removal must not strip spare instantiations or keep attrs.
- **hold-fix** — may realize a new buffer ON a spare site, but must NOT consume a spare buffer
  without replacing it (pool must not be depleted).
- **eco-plan** — may WIRE UP spares, but must not delete/clean remaining spares reserved for the NEXT ECO.
- **ppa-predict** — must NOT RECOMMEND deleting/recovering spares for area; report them as intentional reserve.
- **drc-fix** — density/fill fix stays ECO-aware: no deleting spares to clear spacing, no locking fill over spare tracks.
All reference `spare_cell_preservation_check.py` MUST still PASS (keep attrs intact, 0 removed) and the `design-for-eco` skill.

### 3. `programs/benchmark_verify_report.py` — sixth pillar gate
- New `_has_place_and_route()` detector: applies the gate to any digital PnR IC (DEF/GDS under
  phase3/, excluding phase3/analog/ GDS); **N/A** if the IC genuinely never reached PnR.
- Pillar 6 "Design-for-ECO readiness" reads BOTH `reports/spare_cell_coverage.json`
  (readiness → `status:PASS`) AND `reports/spare_preservation.json`
  (`all_keep_attr_intact:true` + `removed:0`). States: PASS / N/A / PENDING (missing report =
  PENDING, never silent pass) / FAIL.
- Wired into the gate set (`g_dfe`) and `overall`; rendered in the pillar table + a dedicated
  "Pillar 6" section; added to stdout summary (`design_for_eco=...`).
- Existing 5 pillars + exit-code logic intact.
- **Flow renumber applied** (per dfe-core: Design-for-ECO is integer **Step 18**, all numeric
  steps ≥18 shift +1; mfg 37-40→38-41): STEP_METHOD updated, fallback id list updated,
  "55-step"→"56-step" everywhere. STEP_METHOD now has a method entry for "18".

### 4. `skills/benchmark-verify/SKILL.md`
Documented the new Pillar 6 (spare-cell coverage + preservation), the two checkers, the
`design-for-eco` skill cross-ref, applicability/PENDING rules; updated 5→6 pillars, 55→56 steps,
procedure step 6b, and acceptance criteria.

## Verification
- `json.load` (_classification.json) + `ast.parse` (benchmark_verify_report.py): OK.
- `pytest -k "benchmark or spare or coverage"`: **94 passed, 0 failed** (note: the task-named
  `test_mcp_tool_coverage_inventory.py` does not exist in this repo; ran the keyword-filtered
  subset over programs/tests/).
- Re-ran `benchmark_verify_report.py benchmark_clean/spm`: parses + runs; Pillar 6 = **PENDING**
  (digital IC, spare reports not yet backfilled) — expected, NOT a regression.

## Honest notes / artifacts (NOT my-file regressions)
- spm OVERALL = NOT-COMPLETE: caused by dfe-core's flow renumber. spm's pre-existing
  `cross_check/step_*.md` files are still numbered under the OLD 55-step scheme, so the renamed
  Step 37 (old 36 = FPGA final) shows PENDING (off-by-one for steps ≥18). The benchmark cross_check
  data needs re-running/renaming by the benchmark-data owner; my code reads the flow yaml
  dynamically and matches step ids correctly.
- `_FIX_design_for_eco_core.md` was never present during this session; proceeded from the task
  contract + the coordinator's renumber correction, which matches the on-disk flow yaml edits.
