# LAND — vibe-ic#2013: two D2 cells ENFORCED-CONTRADICTED (step 23, obstruction gates)

Lane: kd2 · host 8HD-6 · clone `~/_kd2` (fresh, `github.com/vibeic/vibe-ic` main @ `8f3755d9f`, v1.15.55)
Branch: `next/kd2` (ONE local branch; NOT pushed, no PR, no landing — per brief)
Image: `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…` (tag 0.3.6, id b8b65ea3af6e) via `tools/ci/run_suite_in_eda_image.sh`

## 1. What the two assertion messages said (measured, host AND pinned image, byte-identical)

```
test_d2_gate_has_a_reachable_fail[step23]
  step 23: 1 clause(s) in UNREDDENED now reach a real FAIL — the gap closed, so the entry is a
  lie and must be deleted: 'drv_promotion_corroboration_check . --json reports/phase3/sta/drv_prom'
  -> FAIL (fixture EMPTY) :: === DRV promotion corroboration === verdict: FAIL a repaired route was
  PROMOTED as the sign-off route but no sign-off re…

test_d2_the_two_obstruction_gates_redden_and_only_on_content
  step 15: on a tree with nothing to read 'macro_obs_load_parity_check . --json …' answered PASS,
  not VACUOUS_PASS. If it is FAIL the fixture is measuring nothing the bare tree does not; if it is
  PASS the gate now certifies a run it could not read :: INCOMPLETE: macro_obs_load_parity_check …
  — reason_class=EXECUTION_ERROR; [CANNOT DETERMINE] macro_obs_load_parity: no LEF under .. …
```

The issue text guessed the mechanism ("step 23's gate has no reachable fail"); the assertion says
the opposite — a registered gap started reddening, on the wrong arm. Diagnosis was taken from the
assertions, not the issue.

## 2. Root causes — two separate landings, neither of them the D2 file

### 2a. Step 23 — red since v1.14.76 (`5ef6b79e3`, 2026-09-01)
That commit rewired the step-23 DRV clause as `optional_program_exit_zero` with
`condition_files_exist` naming the promotion marker `routed_base_prerepair.def` (both pnr dirs)
and the non-promotion record. The D2 harness materialises every unmatched condition pattern
(`_materialise_conditions`: a ZERO-BYTE `.def`, `{}` for `.json`), so on EMPTY the gate now sees a
promotion marker and no sign-off report and refuses on its "uncorroborated promotion" arm. The
UNREDDENED excuse ("PASS: needs an STA report claiming a DRV promotion that a second source does
not corroborate") became stale and anti-rot assertion (4) fired. The gate itself is correct: an
uncorroborated promotion IS its documented failure mode. What was stale is the register, and the
arm that reddened is not the arm the register named.

### 2b. Steps 15 / 21 — red since v1.15.6 (`bf6292fa3`, #1978, 2026-09-01)
#1978 made `flow_compliance_check._check_program_exit_zero` classify every rc=2 by a typed
`reason_class`: read from the `--json` report the clause names, else inferred from the message,
else **fail-closed to `EXECUTION_ERROR`**, and only a skip-eligible class keeps `VACUOUS_PASS`;
everything else is rewritten `INCOMPLETE: <cmd> — reason_class=…` with `passed=True`.
Neither obstruction gate published a class (the no-LEF / no-DEF branches wrote no JSON at all),
so every refusal graded "the gate blew up". Two consequences:

* the D2 harness's `_classify` had no branch for the `INCOMPLETE:` rewrite and read
  `passed=True` as **PASS** — "the gate now certifies a run it could not read", verbatim;
* on a REAL published run (`~/_kicspm_accept2`, spm, no macro integrated) step 21 read
  `INCOMPLETE: the gate reports its input was applicable and was NOT examined:
  macro_obs_geometry_intersect_check …` with ledger `rc=2 INCOMPLETE reason_class=EXECUTION_ERROR`.
  That is a live flow defect, not only a harness one.

## 3. The fix — at the gate/predicate, no re-tiering, no census edits by hand

### Gates (source)
* `programs/macro_obs_geometry_intersect_check.py`
  * `_MACRO_DECLARATION_SITES = ("input/pdk_local", "phase3/analog/hardmacro")` — the flow's OWN
    definition of "this design integrates a macro" (step 15's `ip_integration_check`
    `condition_files_exist`, whose W4 text states the doctrine). Pinned to the yaml by a test.
  * `_typed_refusal(json_out, check, reason_class, reason, rep)` — every rc=2 branch now writes
    the JSON the clause names with `verdict = _flow_reason_taxonomy.record_verdict(cls)`
    (SKIP/BLOCKED/INCOMPLETE — no new vocabulary), `reason_class`, `reason`, and the audit's own
    counts when the refusal came after one. Every `[CANNOT DETERMINE]` stderr line is unchanged.
  * classes: no routed DEF → BLOCKED_BY_UPSTREAM; no macro LEF → DESIGN_DECLARED_NA if no
    declaration site exists, else BLOCKED_BY_UPSTREAM; no master declares OBS → DESIGN_DECLARED_NA;
    OBS masters but none placed → DESIGN_DECLARED_NA; unresolved masters after comparison →
    BLOCKED_BY_UPSTREAM; contradictory OBS evidence → EXECUTION_ERROR; truncated read →
    BLOCKED_BY_UPSTREAM.
* `programs/macro_obs_load_parity_check.py` — same helper; no LEF → DESIGN_DECLARED_NA /
  BLOCKED_BY_UPSTREAM by declaration site; no OBS declared → DESIGN_DECLARED_NA; zero layers
  declared (836f57214's refusal) → ZERO_DENOMINATOR.
* `programs/drv_promotion_corroboration_check.py` — the "never ran" VACUOUS_PASS record now carries
  `reason_class: BLOCKED_BY_UPSTREAM` (was inferred EXECUTION_ERROR). Tier unchanged (INCOMPLETE
  family both before and after); the word is now true.

### Harness (predicate)
* `test_matrix_d2_falsifiable.py`
  * new tier `INCOMPLETE_TIER = "DISCLOSED_INCOMPLETE"`; `_classify` grades the consumer's
    `INCOMPLETE:` rewrite (via the consumer's own `_INCOMPLETE_STDOUT_TOKEN`) as that tier,
    never PASS. Not in `DEMONSTRATIONS`.
  * step 23: fixture `DRV_PROMOTION_CONTRADICTED` (marker + repair log claiming 1 + sign-off
    report showing 3 → FAIL on the CONTRADICTION arm the register named); assigned in
    `CLAUSE_FIXTURE`; the UNREDDENED entry deleted with its history; new control
    `test_d2_the_promotion_corroboration_clause_reddens_and_only_on_content` (4 arms:
    contradicted FAIL / agreeing PASS / marker-alone FAIL uncorroborated / bare tree
    INCOMPLETE+BLOCKED_BY_UPSTREAM).
  * obstruction control: EMPTY arm now pins tier AND `reason_class` per gate
    (15 → VACUOUS/DESIGN_DECLARED_NA, 21 → INCOMPLETE_TIER/BLOCKED_BY_UPSTREAM), plus two new
    arms per gate: subject present with no OBS → VACUOUS/DESIGN_DECLARED_NA; macro declared at
    the flow's site with no abstract → INCOMPLETE_TIER/BLOCKED_BY_UPSTREAM. Both negative
    controls (corrected trees → PASS) unchanged.
  * classifier self-check extended; fixture docstrings carry RE-MEASURED blocks (pinned records
    kept verbatim, new measurement added).
* `test_macro_obs_gates_are_wired.py` — 5 tests: declaration-site pin to the yaml; typed refusals
  through real subprocesses for both gates (NA / blocked / no-OBS / zero-denominator).
* `test_issue220_drv_promotion_disclosure_reaches_the_gate.py` — 1 test: never-ran is typed.

Nothing was waived, no cell re-tiered, no census figure hand-edited, no gate weakened: the count
of clauses driven to a content-earned FAIL went UP by one (step 23's DRV clause).

## 4. Evidence

### 4a. Acceptance — the test file fully green in the pinned image, clean clone
`run_suite_in_eda_image.sh … -- test_matrix_d2_falsifiable.py test_macro_obs_gates_are_wired.py
test_issue220_…py` → **111 passed, 2 xfailed** (the 2 xfails are the pre-existing strict waivers
for steps 1/12/35, unchanged). Host: D2 file alone → 86 passed, 2 xfailed.

### 4b. Red-without proof (two-tree)
`git worktree add … 8f3755d9f` (pristine main) + ONLY the three test files copied in:
**8 failed, 103 passed, 2 xfailed** — the 8 are exactly the new/changed assertions
(obstruction control, promotion control, 5 wiring tests, issue220 typed test). Every new
assertion fails against main's gates and passes against the fixed ones.

### 4c. Real run (`~/_kicspm_accept2`, `flow_compliance_check --read-only --phase 3`)
```
BASE   GATE_RAN macro_obs_geometry_intersect_check  rc=2  INCOMPLETE   reason_class=EXECUTION_ERROR
       step 21: INCOMPLETE: the gate reports its input was applicable and was NOT examined: …
FIXED  GATE_RAN macro_obs_geometry_intersect_check  rc=2  VACUOUS_PASS reason_class=DESIGN_DECLARED_NA
       step 21: PARTIALLY-VACUOUS (1 of 5 gate clause(s) examined nothing): …
```
Summary line identical otherwise (PASS=0 FAIL=2 MISSING=17 … INCOMPLETE=9 in both); step 21 stays
MISSING on unrelated audit-created evidence. The fix moves exactly the line it targets.

### 4d. Neighbouring suites (host, 33 files, 589 tests): 5 failed, 577 passed, 7 skipped —
ALL FIVE fail identically on pristine main (measured on the base worktree, same ids):
`test_ppa_runner_extraction_ledger::test_no_new_ppa_logic…`, `test_routed_def_corpus_dispatch` ×2
(corpus-bound), `test_signoff_required_outputs_completeness::test_the_matrix_does_not_hold_the_step31_json_entry`,
`test_step23_drv_promotion_absent…::test_a_declared_unmet_clause_leaves_the_signoff_step_and_its_successor_passing`
(expects the pre-#1978 PARTIALLY-VACUOUS for an unconditionally wired never-ran gate; #1978 makes
it INCOMPLETE; my BLOCKED typing does not change that tier). Not touched here — out of scope and
pre-existing.

### 4e. Guards
`source_chip_agnostic_check.py .` → PASS (1677 files). `PROGRAM_INVENTORY.json` carries no entry
for the three programs (0 mentions) — nothing to re-record.

### 4f. A self-inflicted NORECORD, recorded so nobody chases it
The first `--fix` run went NORECORD ("test_matrix_d6_skip_discipline.py exited rc=1 but every raw
test report is non-red"): I had written this LAND.md into the clone while the nested validation was
running, and `suite_write_guard` flagged the appeared file. Not a matrix defect. Re-run with the tree
untouched; see §5 for the result.

## 5. Census — `tools/gen_flow_matrix_census.py --fix` (tree untouched during the run)

`--fix` rewrote the 7 drifted anchors (182→183 blocking clauses etc.; main was already stale —
the anchors disagreed with the tree on the pristine clone, see baseline below) in
`flow_matrix/README.md`, `flow_matrix/flowref.py`, `test_matrix_d2_falsifiable.py`, then
regenerated the README census block. Both derived files are in this branch.

```
BASE  (pristine 8f3755d9f)  612 cells: 531 ENFORCED, 2 ENFORCED-CONTRADICTED, 7 WAIVED, 19 NA, 26 NOT_MEASURED, 25 ENFORCED-SKIPPED, 2 WAIVED-SKIPPED
                             dim 2 row: … CONTRADICTED 1   dim 8 row: … CONTRADICTED 1
THIS  (next/kd2)            612 cells: 532 ENFORCED, 1 ENFORCED-CONTRADICTED, 7 WAIVED, 19 NA, 26 NOT_MEASURED, 25 ENFORCED-SKIPPED, 2 WAIVED-SKIPPED
                             dim 2 row: … CONTRADICTED 0   dim 8 row: … CONTRADICTED 1
```

**Dimension 2 reads 0 ENFORCED-CONTRADICTED** — both cells this issue names are ENFORCED. The
remaining 1 is a DIMENSION-8 cell that was already contradicted on the pristine clone (the
`test_d8_any_of_entry_both_directions[step5-*]` / `test_d8_downgrade…` family, fixture leaks on
step 5's formal any_of entry) — not a D2 cell, not this issue, not touched here. Headline moves
2 → 1 because this branch cures exactly the one that was mine to cure.

**The generator's verdict is still NORECORD**, on both the pristine clone and this branch, for
reds OUTSIDE the matrix cell join that no regeneration can cure and that are not this issue:

```
test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned
  (4 newly orphaned `programs:` entries: 20/hold_area_budget_check, 31/lvs_triage_classify,
   31/perc_corpus_sweep, 31/pnr_via_stack_completeness_check)
test_matrix_d5_deps_correct.py::test_d5_cells_with_no_derived_dependency_are_named_not_silent
test_matrix_d5_deps_correct.py::test_d5_derived_dependency_denominator_is_disclosed
  (derived-dependency floor 23, live 22)
test_matrix_d8_missing_caught.py::test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one
test_matrix_d8_missing_caught.py::test_d8_any_of_entry_both_directions[step5-anyof0|anyof1]
test_matrix_d8_missing_caught.py::test_d8_downgrade_is_reachable_through_each_steps_own_real_gate
test_matrix_d8_missing_caught.py::test_d8_gate_written_json_output_is_reprobed_after_the_gate
  (mixed_signal_merge_check rc=2 untyped → INCOMPLETE → MISSING; fails standalone on the
   pristine worktree twice — a #1978 casualty of a gate this branch does not touch, and it was
   not in the baseline --check's list only because that nested session happened not to record
   it; measured red on base regardless)
```
All 8 were measured red on the pristine clone (7 in the baseline `--check`, the 8th standalone
on the base worktree). The baseline `--check` on pristine main: rc=2, 7 stale anchors, block
stale, NORECORD on the same foreign reds. This branch: anchors fresh (`[PASS] 63x8 derived
figures fresh: 57 anchored figure(s)`), block regenerated, NORECORD on the same foreign reds.
"0 ENFORCED-CONTRADICTED on --check" therefore cannot be reached honestly by ANY change scoped to
this issue: the D8 cell and the eight foreign reds each need their own owner. The census is what
the tree says, and the block published here says so.

## 6. Not done, and why
* No push, no PR, no version bump, no landing (brief). Branch `next/kd2` in `~/_kd2` on 8HD-6.
* The 5 pre-existing neighbouring reds (§4d) and the 8 foreign matrix reds (§5) are left as
  measured. Each is named with its assertion so the next lane can take it without re-deriving.
* `test_step23_drv_promotion_absent…::test_a_declared_unmet_clause…` expects the pre-#1978
  PARTIALLY-VACUOUS tier for an unconditionally wired, never-ran DRV gate; #1978 makes that
  INCOMPLETE (BLOCKED with this branch — the class is now true, the tier is the taxonomy's).
  Re-deciding that test's expectation belongs to whoever owns #1978's step-level semantics.

## 7. Files in the branch
```
programs/macro_obs_geometry_intersect_check.py        typed refusals, declaration sites, _typed_refusal
programs/macro_obs_load_parity_check.py               typed refusals
programs/drv_promotion_corroboration_check.py         never-ran record typed BLOCKED_BY_UPSTREAM
programs/tests/test_matrix_d2_falsifiable.py          INCOMPLETE_TIER, DRV fixture+control, typed obstruction control, anchor 183
programs/tests/test_macro_obs_gates_are_wired.py      +5 tests (yaml pin, typed refusals)
programs/tests/test_issue220_drv_promotion_disclosure_reaches_the_gate.py  +1 test
programs/tests/flow_matrix/README.md                  regenerated block + anchor   (derived)
programs/tests/flow_matrix/flowref.py                 anchors                      (derived)
A_kd2_2013/LAND.md                                    this note
```
