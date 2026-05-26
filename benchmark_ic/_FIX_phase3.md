# Phase-3-backend systematic fixes — phase3_one_shot_runner.py

Date: 2026-05-26
File owned/edited (ONLY this .py): `plugins/vibe-ic/programs/phase3_one_shot_runner.py`
New tests: `plugins/vibe-ic/programs/tests/test_phase3_backend_fixes.py`

## What changed (chip-AGNOSTIC, minimal)

### Fix #1 — DRC stdcell-library classifier broadened (per-PDK table-driven)
- `_V1_6_604_STDCELL_LAYER_RULE_PREFIXES` for sky130/sky130A/sky130B now buckets
  `li.*`, `ct.*`/`licon`/`mcon`, and `m1.*`/`met1.*` as stdcell-library-internal
  (the detailed router's signal stack starts at met2; contact layer never emitted).
  gf180 kept at `li.*` only (uncharacterised contact/m1).
- Added `_V1_6_604_USER_ROUTING_RULE_PREFIXES` + `_v1_6_604_rule_is_user_routing()`
  — an explicit honesty gate that takes PRECEDENCE over the stdcell table: any
  `m2.*`/`met2.*` and above (incl. `via2+`) is ALWAYS user-routing → keeps FAIL.
- Added optional geometry-aware cross-check `_classify_geometry_inside_cells()`
  (a rule whose EVERY violation lies wholly inside a placed-cell DEF bbox is
  cell-internal). It still cannot override the met2+ honesty gate.

### Fix #2 — Vacuous-Magic detection
- `_detect_vacuous_magic(transcript, drc_count)` flags dropped geometry
  ("Unknown layer/datatype", 0 cells loaded, empty 0 0 0 0 bbox). A 0-violation
  result on dropped geometry is `vacuous=True` → callers report
  "Magic DRC inconclusive (geometry not loaded)" instead of PASS.

### Fix #3 — Magic re-stream fallback + merge-correct streamout
- (a) `step_gds` now PREFERS Magic DEF→GDS (`_magic_def_to_gds`, merges abutting
  same-layer geometry); falls back to KLayout when Magic absent or its stream is
  vacuous. Records `streamout_engine` in extras.
- (b) `step_drc`: when KLayout-deck count is >90% min-spacing/min-width edge-pairs
  (`_klayout_streamout_false_positive_dominated`), auto re-streams via Magic and
  re-runs DRC (`_magic_run_drc`), recording BOTH counts. Magic count is
  authoritative ONLY when non-vacuous (ties to Fix #2).
- (c) Surfaces OpenROAD-detailed-route DRC count vs KLayout-deck count
  (`_extract_openroad_drt_violations`, `_format_drc_engine_discrepancy`) in the
  DRC step detail/extras.

### Fix #4 — `--util` is a FRACTION (0..1)
- `_normalize_util()`: value >1 ⇒ /100 with a logged warning (percent→fraction);
  <=0 clamped to 0.05; result always clamped to (0,1]; non-numeric → 0.45 default.
  Wired into `main()` before any step.

### Fix #5 — SV synth frontend fallback + provenance
- `_decide_synth_frontend()` chooses the SV-aware path when the default
  `read_verilog -sv` failed AND (SV error signature present OR any `.sv` input).
- Fallback order: `yosys -m slang`/`read_slang` (preferred, preserves hierarchy)
  → `sv2v` pre-pass emitting Verilog-2005. Selected frontend recorded as
  `synth_frontend` in the synth StepResult extras + detail.

## Honesty-preservation notes
- Genuine met2+ user-routing violations are never auto-waived (explicit
  precedence gate; verified by tests `test_met2_is_user_routing_FAIL`,
  `test_mixed_met1_and_met2_keeps_user_routing`, `test_geometry_never_overrides_honesty_gate`).
- A vacuous Magic 0-count is never a clean pass (`vacuous=True` path; Magic re-stream
  only authoritative when geometry loaded).
- Unknown PDKs default to no-auto-waiver (conservative FAIL).
- `-DSIMULATION` define, `_v1_6_605_remap_surviving_dlatch`, and STA-0164 handling
  all verified intact and not reverted.

## Test results
- New file `test_phase3_backend_fixes.py`: 39 tests, all PASS.
- Filtered subset (`-k "phase3 or drc or util or stdcell or magic or slang or backend_fixes"`):
  45 passed, 1268 deselected.
- Full `programs/tests/` suite: 1304 passed, 4 skipped, 1 xfailed, 4 xpassed
  (xfail/xpass pre-existing, unrelated). No NEW failures.
- `ast.parse` of the edited file: OK. Runner `--help` OK.
