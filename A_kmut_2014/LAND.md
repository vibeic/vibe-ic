# Issue #2014 — `programs/tests/test_matrix_mutation_ledger.py`

Branch: `fix/2014-matrix-mutation-ledger` (local only — no push, no PR, no landing).
Base: `9dff42ceb` (`git clone github.com/vibeic/vibe-ic` main into `~/_kmut`, fresh).

Every number below was measured inside the pinned image
`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff`,
with `VIBE_IC_BENCHMARK_DATA` bound to a clone of `vibeic/benchmark-data` @ `98e83a61`
(`git pull` first) and `VIBEIC_NDA_TOKENS` from `~/.config/vibeic/commercial_pdk.json`.

## Counts

| arm | result |
|---|---|
| base `9dff42ceb`, image + corpus | **11 failed, 115 passed** |
| base `9dff42ceb`, image, **no** corpus pointer | 8 failed, 116 passed, 2 skipped |
| this branch, image + corpus | **126 passed, 0 failed** |

**The brief says 25 cases; the tree carries 11.** The other 14 are the measuring
harness, not the tree, and they are named rather than waved away: LOCK 2 mirrors the
plugin with `cp -al`, so a scratch root on a DIFFERENT mount than the checkout makes
every `FLOW_YAML`/`PLUGIN_TREE` replay die with
`cp: cannot create hard link ...: Invalid cross-device link`. Measured here: the same
clean `9dff42ceb` reports **25 failed** with `TMPDIR` on a second bind mount and
**11 failed** with `TMPDIR` on the same mount as the repo (and outside any git work
tree, which `scratch_root_guard` requires). Nothing in the repository changed between
those two runs. If the `ee29a2ad` sweep ran with a cross-device scratch, 14 of the 25
it attributed to this file were its own.

## The five defects, and what was done at the source

No test was weakened, skipped, xfailed or re-tiered; no baseline was rewritten; no
matrix cell was moved between tiers by hand. Every `applies_to` / `reddened` /
`witness` change below rests on a replay that was RUN, and the replay output is quoted
in the entry's own `note`.

**1. The grid pin was 12 cells stale — `LEDGER_AS_MEASURED (68,8,489) -> (68,8,501)`.**
Reddened `test_the_ledger_grid_matches_what_was_measured`,
`test_the_grid_gate_names_the_cell_that_moved`,
`test_the_coverage_is_complete_and_the_count_is_stated`,
`test_0_5ic_d3_live_replay_closes_the_exact_coverage_delta`. All twelve GAINED
enforcement, so the pin moves UP: eleven d3 cells (15,16,17,18,19,20,21,23,29,34,38)
left `NOT_MEASURED` because the corpus has published run trees again since `bcf2f94`,
which is exactly the self-invalidation the 2026-08-22 and 2026-08-31 notes predicted in
writing; DT2/d6 left `WAIVED` because dimension 6 withdrew its last waiver on
2026-08-31. Each of the twelve is struck by name in `LEDGER_CELLS_NOT_ENFORCED` with
its cause, and `544 - 43 = 501` is asserted, not asserted-about.

**2. DT2/d6 was ENFORCED with no mutation at all** —
`test_every_enforced_cell_carries_a_named_mutation[stepDT2]`. Closed by MEASUREMENT:
`--replay D6-UNCONDITIONAL-OPTIONAL --step DT2` -> **REDDENED (24.1s)**. The 2026-08-06
sweep could not have reddened it — an `xfail(strict=True)` cell reports xfail whatever
the mutation does — so withdrawing the waiver is what made the cell measurable for the
first time. `applies_to` +DT2, `reddened` 66 -> 67, `stayed_green` () .

**3. Three entries claimed an edit site on step 35 that #1980 removed** —
`test_lock1_every_recorded_edit_site_still_exists` and
`test_reverse_case_reordering_the_flow_does_not_trip_the_gate`. `867f807a7` (#1980)
deleted step 35's `advisory_program_exit_zero`/`dfm_screen_check` clause and re-declared
the producer under `program_outputs`, leaving `all_of: [files_exist: [...]]`. So
`gate_programs_rename`, `gate_append_cli_flag` and `gate_advisory_only` have nothing to
edit there and the recorded reds are no longer REPRODUCIBLE. Step 35 is withdrawn from
`D1-BLIND-GATE-PROGRAMS` (65 -> 64) and `D4-CLI-CONTRACT` (50 -> 49), each with the
cause named. **No cell lost coverage**: 35/d4 is carried by `D4-UNGATED-DELIVERABLE`,
and 35/d1 was RE-MEASURED — `--replay D1-UNREACHABLE-CLAUSE --step 35` -> **REDDENED
(11.4s)**, because the "second reachable channel" that entry recorded as its reason for
step 35 staying green is the very clause #1980 deleted. `D1-UNREACHABLE-CLAUSE` 30 -> 31.

**4. `D6-ADVISORY-ONLY-GATE` reddened 0 of its 59 recorded steps** —
`test_lock2_the_mutation_really_reddens_its_witness[D6-ADVISORY-ONLY-GATE]` and
`test_the_replay_actually_ran_and_is_not_starved`. This is the finding worth reading
twice. The edit re-declared the step's first BLOCKING gate command in the advisory slot,
on the reading that an advisory clause always passes. #1980 ended that reading:
`_evaluate_gate` now honours an advisory REFUSAL as blocking unless the gate is
two-source advisory. The FULL recorded sweep was replayed to check —
`--replay D6-ADVISORY-ONLY-GATE`, all 59 pairs, 0 unmeasurable — and **0 of 59
reddened**, every one reporting `passed=False` with
`advisory gate refusal: <cmd> [rc=1, verdict=FAIL]`. The mutant gate was refusing, not
switched off, so it was never the L1b shape: the dimension's only L1b lever was dead and
LOCK 2 was the thing that noticed.
The EDIT was rewritten, not the count: `_k_gate_advisory_only` now DELETES the blocking
clauses and keeps the step's own declared advisory ones — two-source advisory by
construction, so the gate passes on an empty project with nothing left to enforce, which
is what L1b asks about, and it is the realistic shape (a maintainer deleting the blocking
half of a gate). Re-swept one replay per step over the 20 steps that declare an advisory
clause: **7 REDDENED** (6, 9, A9, 21, 29, 31, 33), 13 held green because their advisory
clauses are themselves NOT-YET-CLEAN ratchets that refuse on nothing, 2 have no edit site
(DT2, 35). `applies_to` 59 -> 7, `reddened` 59 -> 7, all 13 greens recorded. Census
coverage is UNCHANGED — every d6 cell is still carried by `D6-UNCONDITIONAL-OPTIONAL`
(67) and P0 by `D6-UMBRELLA-ALWAYS-SKIPS`; what shrank is how many cells have a SECOND,
L1b-charging lever, and that number is now measured instead of asserted.

**5. Two d7 entries witnessed an already-red cell** —
`test_lock2_...[D7-GATE-PROBES-A-GHOST]` and `[D7-UNDECLARED-KEY]`, both reporting
"NOT ONE of them proved anything". Their witness was step 21, and 21/d7 is RED at
baseline with the corpus bound. Witnesses moved to cells that are green and were
REPLAYED: `D7-GATE-PROBES-A-GHOST` 21 -> **12** (REDDENED, 86.1s),
`D7-UNDECLARED-KEY` 21 -> **22** (REDDENED, 86.2s). The red is RECORDED, not routed
around: D1/21/34 stay in `applies_to` and are named in `baseline_red`, so their redness
leaves `attributable` and `test_lock3_...` enforces that a witness may not be one of them.

## What this lane did NOT fix, and who owns it

* **21/d7 is a real, unfixed finding in the FLOW YAML.** `pytest
  programs/tests/test_matrix_d7_outputs_list_complete.py` with the corpus bound reports
  `4 failed, 98 passed, 4 xfailed` — cells D1, 21, 34 and the module's own write-record
  population guard — identically on `9dff42ceb` and on this branch. 21/d7 says
  `[W2:produced_consumed_undeclared] 'phase3/stage3/pnr/openroad.log' (written by
  run-record:openroad; read by gate:step21)`: no step's `required_outputs` declares that
  artefact. The repair is one line of `flow/phase1_phase2_phase3.yaml`, a SHARED file and
  another lane's batch, so it was not touched here. All three cells are GREEN with no
  corpus pointer, so this is the published write ledger surfacing a gap, not a regression.
* **The grid pin is environment-dependent, and that is a defect in another file.**
  `test_matrix_d3_outputs_produced.unanswerable_citations` documents itself as deciding
  "without opening a file, which is what makes the answer identical on a host that has a
  corpus and on one that does not". It is not: measured here, the same eleven d3 cells
  are ENFORCED with the pointer bound and NOT_MEASURED without it (via
  `recorded_unpublished_output`). So `LEDGER_AS_MEASURED` can only be right in one
  environment. It is pinned to the CORPUS-PRESENT one, because that is the environment
  the landing harness creates: `tools/ci/hermetic_candidate_runner.py` mounts the corpus
  at `/corpus` and exports `VIBE_IC_BENCHMARK_DATA=/corpus` unconditionally. With no
  pointer this file reports 8 failed (the grid pin at 490, DT2, LOCK 1, and
  D6-ADVISORY-ONLY-GATE), which is a statement about that helper and not about this
  ledger. Fixing it belongs to the d3 lane.

## Landing-time step this lane may not take

Both files are PROTECTED paths, so `tools/ci/test_phase_b_activated_parity.py::
test_the_live_tree_moves_no_protected_path_the_base_did_not_authorise` refuses this tree
— the ONE test that is red on this branch and green on the base across the whole
`pytest tools/` run (85 failed/39 errors on base vs 61 failed/30 errors here; the base
arm's extra reds are its own detached shared clone, and the diff was taken by test ID,
not by count). The refusal prints its own remedy:

```
python3 tools/ci/protected_landing_manifest_author.py --commit <base> \
  --transition-id <new-id> --current-id routed-cell-identity-v2-next \
  --next-id <new-id>-next \
  --next-file vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py=vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py \
  --next-file vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py=vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py \
  --out tools/ci/protected_landing_transition.json
```

`tools/ci/protected_landing_transition.json` is ONE file shared by every lane touching a
protected path, so a lane-authored manifest collides with every other lane's. It is left
to whoever assembles the batch, and this brief authorises no landing anyway.

## Files touched

* `vibe-ic-marketplace/plugins/vibe-ic/programs/matrix_mutation_ledger.py` — the module
  this test file exists to gate, and the only place its evidence can be repaired.
* `vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_matrix_mutation_ledger.py` —
  the batch file: the `489 -> 501` pin in
  `test_0_5ic_d3_live_replay_closes_the_exact_coverage_delta`.
* `A_kmut_2014/LAND.md` — this note.

No other lane's file was edited. The flow yaml, the eight dimension modules, the waiver
registry and `tools/ci/protected_landing_transition.json` are all UNCHANGED.
