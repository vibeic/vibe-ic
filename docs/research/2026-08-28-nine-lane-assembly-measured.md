### the nine-lane assembly, measured against live main

> **SUPERSEDED — kept as a RECORD, not as a current statement (added at landing,
> 2026-08-28).** This was measured against `ae5cc4dbfc` (v1.11.96) and its
> verdict, "BOTH does not reach 0", was true of that tree. Main has since reached
> **v1.12.23** and `BOTH` is **0**, with the last seven rows moved to a
> `NOT_MEASURED` bucket that did not exist when this was written. Read the
> numbers below as what was true at the sha they name — which is exactly the
> discipline this document itself argues for.
>
> It is landed unchanged otherwise, because it is the only surviving record of a
> measurement that cost nine lanes a night, and because its own finding — that
> 44 of the published 57 had gone green or skip with NO LANE INVOLVED, so the
> table's ratios had decayed — is the thing that made the rest of the day
> possible.

MEASURED AT: main `ae5cc4dbfc3f408512270555d7a32b5e3ead18f9` (v1.11.96) vs assembly
`9bd3edf2e4f0cdce9e9e5ebd78e02278ad57f40d`, tree `ad9c067c465af784c3856931bd859b06d87d270a`.
Both trees are independent full clones of `origin`, never worktrees. Same env on both
(`PYTHONDONTWRITEBYTECODE=1`, `TMPDIR=/var/tmp/asm0828`, `VIBEIC_TRUSTED_PYTEST_SITE=auto`,
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`), same invocation (`python3 -I
programs/trusted_pytest_entry.py`), run ALTERNATING main-then-assembly per module so both
saw the same machine minute by minute. Set differences are Python sets, never `comm`.

### VERDICT: BOTH does not reach 0, and the published table's premise has decayed

  CLEARED            5
  STILL_RED          8
  NEW_RED            1
  GREEN_ON_BOTH     37
  SKIPPED_ON_BOTH    6      <- a skip is NOT a pass; reported separately, never as green
  NOT_MEASURED       0
  TOTAL             57

**Only 13 of the published 57 are still red on main today.** The ratios in
`2026-08-21-main-92-red-triage-ratios.md` were taken against `867de4289` (v1.11.18); main
has since reached v1.11.96. 44 of the 57 went green (37) or skip (6) with no lane
involved — 8 of them already recorded as CLEARED by `jlvs/lvs-family-remeasured`, the
rest measured here. Of the 13 genuinely still red, the nine lanes clear 5 and leave 8.

### NEW_RED — the only category that stops a landing

Within the 57 (1):

    test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]

Across all 75 modules measured A/B (2):

    test_matrix_63x8_census_freshness.py::test_the_generator_cli_can_go_red_and_green
    test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]

In the `tools/` tree, which `testpaths` does not collect (3):

    tools/ci/test_gate_fixtures_discriminate.py::test_fixture_pair_discriminates[every_program_is_reachable]
    tools/ci/test_phase_b_activated_parity.py::test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture
    tools/ci/test_phase_b_activated_parity.py::test_the_move_is_exactly_the_paths_the_two_states_disagree_on

**Three of the five are one lane, `fix/whole-population-reachability`, and each is caught
by a DIFFERENT gate the repo already runs.** Its gate itself is sound — `rc=0` over 1298
programs with a real denominator, against main's `rc=2` (argparse rejects `--root`) — but
the flow change around it is incomplete three ways:

  1. the gate is wired `python3 "$RUNTIME_ROOT/.../program_reachability_check.py"`, and
     `gate_mutation_fixtures._resolve_argv` substitutes only `$ROOT`, `$PLUGIN`, `$PG`,
     `$PJSON`. Both fixture arms die on a literal `$RUNTIME_ROOT` path, so the gate's
     can-pass AND can-fail directions are unproven. Suite-wide: `$RUNTIME_ROOT` appears in
     0 gate lines on main and 1 on the assembly. `unresolved_shell()` already names this
     class of defect; nothing consults it before invoking.
  2. its new advisory clause moves four ANCHORED figures in `matrix_63x8/flowref.py` by
     exactly +1 (`gate_clauses_advisory_program_exit_zero` 74->75, `gate_clauses_total`
     252->253, `gate_program_tokens_distinct` 210->211, `gate_commands_total` 219->220).
     No lane touched `flowref.py`.
  3. `reports/phase3/perc_sweep.json` becomes a load-bearing gate-designated output
     (written by `perc_corpus_sweep`, read by `gate:step31`) that step 31's
     `required_outputs` never declares. NOTE the obvious fix is NOT safe: the sweep emits
     that report only when it finds a routed DEF, which is why the lane guarded its own
     clause with `condition_files_exist`. Declaring it required would redden every run
     over an empty corpus. This is a design question for the author.

DROP-THE-LANE CONTROL, both directions. An 8-lane assembly without it, matching main on
all three controls (84 advisory clauses, 0 `$RUNTIME_ROOT`, 72 fixtures): findings 2 and 3
go GREEN and finding 1's id does not exist (74 deselected, exactly as on main). The two
`test_phase_b_activated_parity` ids stay RED — which is the disconfirming half, and it
held: those two are STRUCTURAL, not that lane's doing. The assembly edits 2 of the 47
paths in `protected_landing_transition.json` (`tools/ci/repo_hygiene_gates.sh`, by three
lanes; `tools/gatekeeper-land.sh`, by one), so the live tuple matches neither recorded
state of `batch96-landing-v1-11-96`. ANY branch touching a protected path trips these
until the transition is re-prepared at landing. The manifest was NOT re-recorded here:
doing so is rewriting what the check checks.

### STILL_RED (8 of the 57) — byte-identical failures on both trees

    test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
    test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
    test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
    test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
    test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
    test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
    test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
    test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans

Read, not inferred from matching counts: `test_issue712_prose_polarity` reports
`polarity-blind 214 (baseline 213)` on BOTH trees, so the assembly's new programs added no
offender. `test_matrix_63x8_coverage` fails the same 4 ids on both, with no 2-in/2-out
swap — the node-id sets are equal, which a red COUNT alone would not have shown.

### CLEARED — 5 of the 57, 13 across all 75 modules

    test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
    test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
    test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
    test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
    test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds

The further 8 outside the 57: `test_empty_record_cannot_erase`,
`test_hardmacro_magic_is_looked_for_where_it_runs`, `test_issue1241_vendored_attribution_wired`,
`test_issue193_custom_pdk_primary_selection_ngspice`, `test_pdk_yosys_flatten_for_quartus`,
`test_three_orphan_checkers_have_a_machine_runner`, `test_v1_3_47_stall_watchdog`,
`test_v1_4_66_issue171_step4_professional_tb_supersede`.

### FLAKY — measured 5x each, alternating; NOT called cleared

    test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged                          5/5 green both trees
    test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound 5/5 green both trees

20 runs, all green. The table recorded the first as 13/13 RED on host. A known flake coming
up green is the observation to trust least, so both stay in the FLAKY bucket rather than
moving to CLEARED on a colour.

### one lane contributed nothing, and that is the measurement

`fix/manifest-required-metrics-inconclusive` merges to a BYTE-IDENTICAL tree — the tree sha
before and after its merge commit is `0d7007776c500387725a3de98a71361d3b2d3279` both times.
Eight of its nine files already match main exactly; main's `mcp-eda/src/index.js` is a
strict superset of the lane's (both imports present, `writeManifest` byte-identical, the
broken `/wns\s+([\d.-]+)/` already gone, plus a `clockConstrained` guard the lane lacks).
It landed on main at `ea51511ef`. Its 764 stated insertions are already spent.

### conflicts

THREE, of which two were resolved on strict-superset evidence and one is handed back.

`test_v1_4_66_issue171_step4_professional_tb_supersede.py` — took OURS
(`lane-code-reds-0827`). AST-compared with docstrings stripped: both sides carry the
identical 21 top-level statements, and exactly one function differs by exactly one added
assertion (`assert not any("required_outputs missing" in str(x) for x in res.reasons)`).
The slice-extraction side's unique content is comment and docstring prose only. Ours is a
strict superset in enforcement. MEASURED: the module is CLEARED on the assembly.

`test_routed_def_corpus_dispatch.py` — took THEIRS for a comment-only hunk: the lane's own
measured retraction of a sentence ("it is not red on `81cd5321b`") that its §10 shows to be
wrong about the outcome. The AST is otherwise identical across that hunk. **The load-bearing
part of this file was NOT in the conflict markers**: the lane's base predates the `#1770`
repair and still asserts `exempt_until == "2099-01-01"` with
`not_checked_unexempted == []`. The 3-way merge correctly kept main's post-repair form
(`exempt_until is None`, `exempt_reason is None`, `exemption_expired is False`,
`not_checked_unexempted == [_EMPTY_LABEL]`). Taking `--theirs` for the file would have
silently re-dated an exemption to 2099 and pulled the row out of the unexempted list. This
was verified by reading the merged bytes, not assumed from the absence of markers.

`test_issue901_structured_vacuity_reaches_the_step_verdict.py` — **HANDED BACK. Neither side
is a superset.** Both lanes repair the same premise-death (v1.11.92 `e314f1923d` split
`coverage_actual.json` into a functional verdict and a measurement):

  lane-code-reds-0827      writes ONE `_measurement` blob to BOTH coverage paths.
  slice-extraction         writes the functional verdict to `coverage_actual.json`, and to
                           `coverage_verilator.json` a measurement carrying `tool` and a
                           `coverage_dat` backlink, plus the `coverage.dat` file itself.

`coverage_verilator.json` under slice-extraction IS a superset of the other; `coverage_actual.json`
is not — the payloads are different in kind. MEASURED both arms on the two affected modules:
armA (slice, shipped) 21 passed / 10 passed; armB (lane-code-reds) 21 passed / 10 passed.
The choice changes NOTHING that any test in either module observes. The distinguishing
artefact is the `coverage_dat` backlink that
`verilator_coverage_measure.artefact_looks_tool_generated` resolves, and no test here
exercises it — which is exactly why the measurement cannot decide this. The assembly ships
armA; swapping is a one-file change with no measured consequence.

### what was regenerated, and what deliberately was not

REGENERATED — `PROGRAM_INVENTORY.json` plus the six stated counts in the two bound READMEs.
The nine lanes add 3 `.py` files under the programs tree (two from
`fix/whole-population-reachability`, one from `lane/gate-corrupted-checkout`) and none
regenerated the inventory, so five ids in `test_program_inventory_no_drift.py` were RED on
the assembly and GREEN on main. This is `programs/gen_program_inventory.py`, the declared
single source of truth, and its diff is two counts and their sorted-path sha256 — no
offender list, no exemption, nothing suppressed. MEASURED the identical staleness on an
8-lane assembly without the reachability lane, so the cause is file addition by any lane.
Module after: 23 passed, was 5 failed / 18 passed.

NOT REGENERATED, on purpose:
  * `gen_matrix_63x8_census.py --fix-figures`, which `test_the_generator_cli_can_go_red_and_green`
    names as its own repair. Writing a baseline on a hygiene gate is refused here even when
    the gate asks, and the figures moved because ONE lane's clause moved them — the author
    should move them, so the change is attributable.
  * `tools/ci/protected_landing_transition.json`. Re-recording it would make the parity
    check pass by rewriting what it checks.

Nothing was weakened anywhere: no assertion touched, no case deleted, no `skipif` added, no
tolerance widened, no exemption added or re-dated. The `1260 top level` figure adjacent to
one edited README line was LEFT ALONE — it is stale on main too, this gate does not bind
it, and moving a figure no failure named would be an unmeasured edit riding along with a
measured one.

### assembly arithmetic

37 files, +3580/-141 before the two regeneration commits. Deletions are far under the ~270
the nine branches sum to, so no branch was reverted by being merged backwards. Three lanes
had an older merge-base and were replayed onto main by a REAL 3-way merge against their own
base (a synthetic squash commit parented at the merge-base), never by applying a
main-to-branch diff, which for `fix/manifest-required-metrics-inconclusive` alone would have
deleted 11007 lines.

Verified beyond the absence of conflict markers:
  * `repo_hygiene_gates.sh` 106 -> 108 `run` invocations, ALL LABELS UNIQUE, no gate wired
    twice. The two new ones are `every program is reachable` and `no pattern-based process
    kill`, both on the blocking `run` wrapper (`_dispatch 0 0`).
  * zero autouse fixtures patching the same attribute — the named hazard from the earlier
    bad assembly — because the changed files declare none.
  * zero duplicate top-level definitions in any changed `.py` (the merged-twice tell).
  * every changed `.json` parses with unique keys; the flow yaml parses, 68 steps, no
    duplicate step id.
  * enforcement declarations read through the repo's own `declared_intent`
    (DECL_WINDOW_BYTES=4000) and A/B'd against main: ONE ADDED (`sweep_reach_check.py`,
    undeclared -> advisory), NONE LOST, and no file carries a second declaration.

### the two new gates, both directions

  every program is reachable --strict   assembly rc=0, 1298 programs scanned
                                        (advisory_or_dispatched 210, blocking 93,
                                        code_only 804, shell_or_doc 191)
                                        main     rc=2 — argparse rejects `--root`
  no pattern-based process kill         assembly rc=0, 1335 python files examined
                                        main     rc=0, states NO denominator

Neither PASS is a green over an empty scan. The reachability gate's mutation pair does NOT
discriminate, for the `$RUNTIME_ROOT` reason above — its can-fail direction is unproven.

### the IMAGE lane, run at the same two shas — and one row the table gets wrong

The tally above is the HOST lane. The published table is a FOUR-way document and
`jlvs/lvs-family-remeasured` set its rule explicitly: a row leaves BOTH only when it has
been re-measured green in BOTH lanes at a named later sha. So the host lane alone cannot
move a row, and CLEARED above is a host-lane statement until the image agrees.

Pinned digest `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff`, present on this host.
Invoked with the four flags that make the lane runnable (`--group-add` for the socket gid,
the host docker CLI bound in, `-v /tmp:/tmp`, and `--skip` FIRST or the entrypoint parses
the command as its own options and runs nothing at rc=1). Eleven modules, both trees,
alternating. Verdicts are read from junit xml, never from an exit code after a pipe.

**AGREES WITH THE HOST, id for id:**

    STILL_RED, both lanes   test_issue712_prose_polarity::test_the_gate_is_GREEN_on_the_tree_that_ships
                            test_issue1082_open_w_category_closed::test_no_new_offender_and_the_ratchet_holds
                            test_issue1470_atomic_declared_report::test_the_gate_is_green_and_the_ratchet_holds
    CLEARED, both lanes     test_flow_manifest_declaration_parity::test_every_declared_path_has_a_manifest_entry
                            test_flow_manifest_declaration_parity::test_the_population_is_the_whole_flow_and_is_not_empty
                            test_issue901...::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
                            test_matrix_63x8_ledger::test_output_entries_classify_into_the_four_kinds
    NEW_RED, both lanes     test_matrix_d7_outputs_list_complete::test_d7_required_outputs_list_is_complete[step31]
                            test_matrix_63x8_census_freshness::test_the_generator_cli_can_go_red_and_green
    STILL_RED, both lanes   test_matrix_63x8_census_freshness::test_the_census_block_is_fresh
                            test_matrix_63x8_census_freshness::test_the_published_total_equals_the_live_census

**The NEW_RED reproduces in the image.** It is a genuine BOTH red the assembly introduces,
not a host artefact — which is the severity that matters, and it is confirmed in both lanes.

`test_program_inventory_no_drift` is 23/23 green on BOTH trees in the image, so the
regeneration recorded above holds there too.

### IMAGE-ONLY IS NOT 0 AT v1.11.96, AND THE TABLE SAYS IT IS

    test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing

On main `ae5cc4dbf`: RED in the image, GREEN on the host. The table's own header asserts
"IMAGE-ONLY = 0 and HOST-ONLY = 0, so main is genuinely red here", and lists this id as
BOTH 5/5 5/5. At v1.11.96 that is no longer true of this row: the two lanes disagree.

It does NOT block the assembly — the id is GREEN on the assembly in BOTH lanes, so whatever
the divergence is, the assembly closes it. It is recorded because the table's environment
claim is load-bearing for how every other row is read, and it has decayed the same way the
ratios did. Anyone re-deriving the BOTH bucket at a current sha should expect the
IMAGE-ONLY and HOST-ONLY buckets to be non-empty and should not default them to 0.

### one module is NOT_MEASURED in the image lane, and the cause was my own probe

    test_flow_compliance_check_gate.py   (5 ids, both trees)

The first image run mounted the clone `:ro`, and all five ids failed with
`OSError: [Errno 30] Read-only file system` writing `programs/_pytest_*_helper.py`. Those
tests legitimately write helper programs into the programs tree; the host lane permits it
and the mount did not. **That is a fact about the probe, not about either tree**, so the run
is void as a measurement in BOTH arms and the ids are NOT_MEASURED in the image lane rather
than red — and `test_a_real_verdict_is_not_mistaken_for_a_crash`, CLEARED on the host, is
NOT claimed as cleared in BOTH until a writable run says so. Re-measured on throwaway
writable COPIES under /tmp, never on the real clones, so nothing in the container could
prune a clone's `.git`.

**RE-MEASURED, and it agrees with the host id for id.** Writable copies, same digest, same
flags: main `1 failed, 35 passed` with the single red
`test_a_real_verdict_is_not_mistaken_for_a_crash`; assembly `36 passed`, no reds. So that
id IS cleared in BOTH lanes and CLEARED stands at 5 -- the apparent five-red image result
was the mount and nothing else. Recorded in full because a probe that manufactures reds is
the failure this document exists to refuse: the :ro run and the writable run differ by four
ids in each arm, and only one of the two runs is a measurement.

### the image lane, complete: 10 of 11 modules agree with the host id for id

Eleven modules, both trees, in the pinned digest, alternating; the one module the `:ro`
mount voided re-measured writable and folded in. Comparing RED SETS by node id, never
counts:

    AGREE     test_flow_compliance_check_gate.py          (writable re-measure)
    AGREE     test_flow_manifest_declaration_parity.py
    AGREE     test_issue1082_open_w_category_closed.py
    AGREE     test_issue1470_atomic_declared_report.py
    AGREE     test_issue712_prose_polarity.py
    DISAGREE  test_issue901_structured_vacuity_reaches_the_step_verdict.py   <- the IMAGE-ONLY row
    AGREE     test_matrix_63x8_census_freshness.py
    AGREE     test_matrix_63x8_coverage.py
    AGREE     test_matrix_63x8_ledger.py
    AGREE     test_matrix_d7_outputs_list_complete.py
    AGREE     test_program_inventory_no_drift.py

The one disagreement is the row recorded above: on main, `test_the_shipped_step_names_the_
one_clause_that_examined_nothing` is RED in the image and GREEN on the host. Every other id
in every other module lands the same way in both lanes.

`test_matrix_63x8_coverage` deserves a note because its two arms reported the SAME wall
time to two decimals (701.44 s), which is the shape of a duplicated result. It is not one:
the two logs differ by md5, the junit `time` attributes differ in the millisecond
(701.415 / 701.416) and the files are eleven minutes apart. The duration is dominated by a
fixed internal bound, not by the tree. Both arms carry the same 4 reds, matching the host.

### WHAT THIS MEANS FOR THE FOUR-WAY TABLE

Every verdict below is now measured in BOTH lanes at named shas:

  CLEARED, both lanes (5)      test_flow_compliance_check_gate::test_a_real_verdict_is_not_mistaken_for_a_crash
                               test_flow_manifest_declaration_parity::test_every_declared_path_has_a_manifest_entry
                               test_flow_manifest_declaration_parity::test_the_population_is_the_whole_flow_and_is_not_empty
                               test_issue901...::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
                               test_matrix_63x8_ledger::test_output_entries_classify_into_the_four_kinds

  STILL_RED, both lanes (8)    as listed above; the 63x8 coverage and census rows carry
                               byte-identical red sets in both lanes on both trees.

  NEW_RED, both lanes (2 of the 3 real ones, measured here)
                               test_matrix_d7_outputs_list_complete::test_d7_required_outputs_list_is_complete[step31]
                               test_matrix_63x8_census_freshness::test_the_generator_cli_can_go_red_and_green

The third real NEW_RED and the two structural ids live in `tools/`, which the plugin's
`testpaths` does not collect, so the module sweep above did not reach them. They were run
SEPARATELY in the same image, on writable copies, rather than left NOT_MEASURED -- a
default this document refuses:

    test_phase_b_activated_parity.py                main  7 cases, NO reds
                                                    asm   7 cases, reds = test_the_live_tree_is_
                                                          exactly_one_recorded_state_and_never_a_
                                                          mixture, test_the_move_is_exactly_the_
                                                          paths_the_two_states_disagree_on
    test_gate_fixtures_discriminate.py
      -k every_program_is_reachable                 main  0 cases collected (74 deselected -- the
                                                          id does not exist on main)
                                                    asm   1 case, RED

Both match the host exactly. **So all five NEW_RED are confirmed in BOTH lanes, and the
image lane carries no NOT_MEASURED.**

So the five CLEARED are cleared under the table's own BOTH rule and may be moved to its
CLEARED block with `9bd3edf2e` as the named sha. The eight STILL_RED stay. BOTH does not
reach 0.

### CORRECTION FROM THE OWNER, 2026-08-28 — the two-arm differential is withdrawn as a method

Owner instruction received after the measurement above was taken: **stop the two-arm
differential.** Do not run a base arm, do not alternate candidate against pristine main,
do not take a set difference by node id. Measure the tree you built, once, and report its
red set as what it is. Judge the work by (a) the ids in your own slice being green now and
red before your change, and (b) a falsification — revert the fix and the check must still
refuse. Both are self-contained and need no base arm. For any red you did not set out to
fix, report it by node id and say you did not attribute it.

The reason, recorded so it is not re-derived: the differential costs about as much as the
fix and had failed repeatedly the same night in ways that were CONFIDENTLY wrong rather
than obviously wrong — arms on two hosts returning 2 new / 89 cleared where 82 were one
family that is red where docker is unreachable and green where it is not, i.e. the
environment reported as the diff; and a "fast" probe inventing a new red by comparing a
harness red set against a standalone probe.

**This report was produced under the OLD method and everything above is a two-arm result.**
It is left standing as the record of what was run, not re-issued as if it had been taken
the new way. What follows is the same tree stated the new way.

**THE INSTRUCTION IS NOT HYPOTHETICAL FOR THIS REPORT.** The `:ro` mount recorded above
manufactured five reds in `test_flow_compliance_check_gate` that were `OSError: Read-only
file system` and not verdicts, in BOTH arms, and on the strength of that void run a CLEARED
id was briefly downgraded before a writable re-measure recovered it. That is the same
failure the owner names: the environment reporting as the result. A single-arm measurement
plus a falsification would not have produced it, because there would have been no
cross-arm delta to believe.

### THE STATE OF THIS TREE, MEASURED ONCE

Assembly `da5ac11bf`, code sha `9bd3edf2e` (every commit since is this document).
75 modules run whole, JUnit XML, host lane:

    modules 75      cases 1873      RED 13

**MY SLICE — the one fix I authored.** The nine lanes add 3 `.py` files under the programs
tree and none regenerated the inventory, so I ran `programs/gen_program_inventory.py` and
corrected the six stated counts in the two bound READMEs.

    ids in my slice still red:  0     (test_program_inventory_no_drift.py: 23 passed)

**FALSIFICATION, both directions, one tree, no base arm.** Same clone, same host, same
invocation; the only variable is my own change:

    tree as it ships          rc=0   23 passed
    my fix reverted in place  rc=1   5 failed
                                     test_a_source_mismatch_is_not_checked_rather_than_a_drift_verdict
                                     test_check_mode_exits_zero_on_the_committed_tree
                                     test_clean_tree_reports_no_failure
                                     test_committed_inventory_matches_the_tree
                                     test_stated_counts_in_the_documents_match_the_tree

The revert was `git checkout def0963c8 -- <the three files>` and was restored immediately;
the working tree is clean at both ends. The check still refuses when the fix is absent, so
the fix is doing the work and not merely coinciding with green.

### RED ON THIS TREE, NOT ATTRIBUTED (13)

Red on the tree I built. **I am not claiming whether main carries them.** No base arm was
run for these and none should be:

    test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
    test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
    test_issue693_signoff_integrity_wiring.py::test_the_shipped_baseline_matches_the_shipped_source
    test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
    test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
    test_matrix_63x8_census_freshness.py::test_the_generator_cli_can_go_red_and_green
    test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
    test_matrix_63x8_coverage.py::test_a_not_measured_cell_is_never_counted_as_enforced
    test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
    test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
    test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans
    test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
    test_matrix_d7_outputs_list_complete.py::test_the_dropped_edge_RETURNS_when_the_step_stops_supplying_the_flag

Plus, in `tools/` (which `testpaths` does not collect, run separately):

    tools/ci/test_gate_fixtures_discriminate.py::test_fixture_pair_discriminates[every_program_is_reachable]
    tools/ci/test_phase_b_activated_parity.py::test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture
    tools/ci/test_phase_b_activated_parity.py::test_the_move_is_exactly_the_paths_the_two_states_disagree_on

Three of these carry a DIAGNOSIS that stands on its own and needed no base arm, because it
was read out of the code rather than out of a diff: the gate `fix/whole-population-
reachability` adds is wired with `$RUNTIME_ROOT`, which `gate_mutation_fixtures` does not
substitute; its new advisory clause moves four anchored `flowref.py` figures by +1; and it
makes `reports/phase3/perc_sweep.json` load-bearing without declaring it in step 31. Those
are findings about the code, and they are why that lane should go back to its author —
independent of what main does.

### CORRECTION 2 — converge, do not measure. Two causes fixed and landed; the rest handed back.

Owner instruction: stop measuring, fix the named tests, land as you go. No full suite runs,
no base arm, no set differences. For each id: run that one test, read the failure, fix the
cause, run it again, break the thing it guards, commit and push. Anything not mine gets one
line and no investigation. Acknowledged, and this section is the result.

**FIXED AND LANDED (2 causes, both proved in both directions on one tree):**

  1. `test_matrix_63x8_census_freshness::test_the_generator_cli_can_go_red_and_green`
     Four anchored `flowref.py` figures each stale by +1 against the tree.
     fixed rc=0 1 passed / `gate_clauses_total` set to 999 -> rc=1 naming the drift /
     restored rc=0. Four numbers changed, nothing relaxed.

  2. `tools/ci/test_gate_fixtures_discriminate::test_fixture_pair_discriminates[every_program_is_reachable]`
     `_resolve_argv` did not substitute `$RUNTIME_ROOT`, so BOTH fixture arms died on a
     literal path and neither direction of that gate was ever proved. Taught the engine the
     name, in the same category as `$PG` (the runtime's code, never the subject).
     fixed rc=0 / can_fail arm made to ship the can_pass tree -> rc=1 "CAN-FAIL fixture was
     ACCEPTED (rc 0)" / restored rc=0. Shared code, so the covering module ran whole:
     75 passed, up from 74 passing plus one pair that could not be driven at all.

**HANDED BACK — `test_matrix_d7_outputs_list_complete[step31]`.** Not mechanical, and the
flow's own doctrine says why. `matrix_d7_artifact_graph` states the exemption: *a path is
conditional only when EVERY clause of that step designating it is an
`optional_program_exit_zero` carrying a non-empty `condition_files_exist`*, and
*`required_outputs` has no conditional form -- it is ALL-of-N and unconditional*. The lane
put `condition_files_exist` on the CONSUMER (`sweep_reach_check`) but left the PRODUCER
(`perc_corpus_sweep ... --report reports/phase3/perc_sweep.json`) an
`advisory_program_exit_zero`, i.e. unconditional, so W1 fires. The two available repairs
are both DESIGN decisions the lane's author owns, not edits an assembler should make:

  (a) make the producing clause `optional_program_exit_zero` with a non-empty
      `condition_files_exist`. W1 then exempts the path -- but read what that does to the
      force level, because it is not a weakening and it is not cosmetic. The flow's own
      definitions: `advisory_program_exit_zero` "runs, reports, does NOT block";
      `optional_program_exit_zero` is "blocking **only when** every path in
      `condition_files_exist` is present". So (a) PROMOTES an advisory clause to a
      conditionally BLOCKING one. That is a strengthening, and it is precisely the change
      this repo has a named acceptance standard for -- `flow-change-acceptance` requires an
      explicit BLOCKING-vs-ADVISORY declaration and a PROVE-BY-RUN that a gate declared
      blocking actually stops the flow, plus a bidirectional negative control. None of that
      belongs in an assembly commit, and an assembler slipping a new blocking clause into
      the flow while merging nine lanes is how a gate arrives that nobody accepted.
  (b) declare the path in step 31's `required_outputs`. REFUSED here: the list is ALL-of-N
      and unconditional, and the sweep emits that report only when it finds a routed DEF,
      so this would redden every run over an empty corpus -- a pass-shaped edit that breaks
      real runs.

**NOT MINE — one line each, not investigated:**

    tools/ci/test_phase_b_activated_parity::test_the_live_tree_is_exactly_one_recorded_state_and_never_a_mixture
    tools/ci/test_phase_b_activated_parity::test_the_move_is_exactly_the_paths_the_two_states_disagree_on
        red because the assembly edits 2 of the 47 protected paths; the transition manifest
        is re-prepared at landing by the owner, not by me.

    test_issue1082_open_w_category_closed::test_no_new_offender_and_the_ratchet_holds
    test_issue1470_atomic_declared_report::test_the_gate_is_green_and_the_ratchet_holds
    test_issue693_signoff_integrity_wiring::test_the_shipped_baseline_matches_the_shipped_source
    test_issue712_prose_polarity::test_the_gate_is_GREEN_on_the_tree_that_ships
    test_matrix_63x8_census_freshness::test_the_census_block_is_fresh
    test_matrix_63x8_census_freshness::test_the_published_total_equals_the_live_census
    test_matrix_63x8_coverage::test_a_not_measured_cell_is_never_counted_as_enforced
    test_matrix_63x8_coverage::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
    test_matrix_63x8_coverage::test_no_cell_is_counted_enforced_while_its_predicate_is_red
    test_matrix_63x8_coverage::test_the_enforcement_census_is_reported_for_humans
    test_matrix_d7_outputs_list_complete::test_the_dropped_edge_RETURNS_when_the_step_stops_supplying_the_flag
        red on this tree. Not attributed, not investigated, not a blocker I am claiming.

**SHARED-CODE CHECK for fix 1.** `flowref.py` is read by several matrix modules, so its
covering module was run whole after the change: `test_matrix_63x8_census_freshness`
**2 failed, 4 passed** (306 s), down from 3 reds. The fixed id
`test_the_generator_cli_can_go_red_and_green` is green; the two that remain --
`test_the_census_block_is_fresh` and `test_the_published_total_equals_the_live_census` --
were red before the change and are NOT mine: both assert over a nested outcome run and
fail on a red OUTSIDE the cell join, namely
`test_matrix_d7_outputs_list_complete::test_the_dropped_edge_RETURNS_when_the_step_stops_supplying_the_flag`.
Downstream of another red, one line, not investigated.

### SLICE CLOSED

Two causes fixed, each proved in both directions on one tree and landed as its own push.
One handed back with the flow's own doctrine quoted. Everything else on this tree named by
node id and left alone. No base arm was run for any of it.
