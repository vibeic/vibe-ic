# For jmain-green (192.168.1.105) — YOUR 38 non-matrix IDs, four-way bucket

subject: origin/main 867de4289 (v1.11.18), clean clone, nothing applied.
lanes  : IMAGE = pinned ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2...d01ff,
         `--skip` first, PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 (this is the CI truth)
         HOST  = 8hd-3, python3.10/pytest 9.1.1, autoload ON, -p no:pytest_ethereum
         (the same shape your own list was measured in)
method : every ID run SERIALLY, one pytest session per file, NO xdist;
         then re-measured INTERLEAVED (image then host, back to back) so both
         lanes meet the same contention. Ratios are red/observations per lane.

## VERDICT: IMAGE-ONLY = 0 and HOST-ONLY = 0.
## Your 38 are GENUINELY RED ABOUT MAIN — not artefacts of your host.
## 37 are red in BOTH lanes on every observation; the 1 FLAKY below is named
## with ratios. Nothing here can be closed by blaming the developer host.

   BOTH          37
   FLAKY         1

====================================================================================================

## FLAKY  (1)   [image red/obs | host red/obs]

  4/13      13/13     test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
            AssertionError: assert 'NO `PIN` block' in 'magic exited -11 and wrote no LEF; last output: LEF read, Line 26 [...]

## BOTH  (37)   [image red/obs | host red/obs]

  5/5       5/5       test_extraction_input_blocked_verdict.py::test_complete_generic_tech_still_passes_end_to_end
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_extraction_input_blocked_verdict.py::test_complete_tech_passes_with_real_tech_lef_layer_crosscheck
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_extraction_input_blocked_verdict.py::test_complete_tech_with_matching_design_still_passes
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_extraction_input_blocked_verdict.py::test_unreadable_tech_does_not_block
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
            AssertionError: _pytest_verdict_helper/shallow: the finding itself is missing from the evidence snippet: [...]
  5/5       5/5       test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
            AssertionError: flow yaml and the dimension-3 evidence manifest have drifted apart: 2 declared path(s) have NO [...]
  5/5       5/5       test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
            AssertionError: 162 declared paths vs 160 manifest entries (measured 134 == 134 on 3d13e2c59) — the two sides no [...]
  5/5       5/5       test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w
            AssertionError: a declared report destination is opened with `open(dest, "w")` — use `_atomic_artefact.writing()`, [...]
  5/5       5/5       test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
            AssertionError: assert 1 == 0 + where 1 = <function main at [...]
  5/5       5/5       test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
            AssertionError: assert 1 == 0 + where 1 = <function main at [...]
  5/5       5/5       test_issue306_register_paydown.py::test_306_shipped_tree_is_green_against_its_register
            AssertionError: === flow gate enforcement audit === gate clauses in flow def : 180 gates in flow definition : 171 [...]
  5/5       5/5       test_issue490_drc_report_check_argv.py::test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks
            AssertionError: === flow gate enforcement audit === gate clauses in flow def : 180 gates in flow definition : 171 [...]
  5/5       5/5       test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
            AssertionError: prose extractors that write a declared value: polarity-blind 216 (baseline 213); 10 exempted as [...]
  5/5       5/5       test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
            AssertionError: the shipped simulation step was labelled 'every executed sub-gate was vacuously satisfied' over a [...]
  5/5       5/5       test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_other_self_aware_shipped_gate_also_reaches_the_tier
            AssertionError: the tier was granted without stating the count it was granted on; an uncounted grant is the [...]
  5/5       5/5       test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing
            AssertionError: the one clause that examined nothing was dropped for failing to be unanimous — one silent pass [...]
  5/5       5/5       test_medlow_synth_dft_backlog.py::test_step11_declaration_is_satisfiable_by_a_successful_run
            assert 5 == 6
  5/5       5/5       test_organic900_901_ratchet_and_json_vacuity.py::test_a_shrink_is_still_allowed
            AssertionError: assert 1 == 0 + where 1 = _run_audit(<module 'fgea' from '/home/reyerchu/_ptmo_priv/main92/vibe- [...]
  5/5       5/5       test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
            AssertionError: `gen_program_inventory.py --check` exited 1 FAIL: 18 stated-count problem(s) - README.md: claim [...]
  5/5       5/5       test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
            AssertionError: assert ['README.md: ...Y.json.', ...] == [] Left contains 18 more items, first extra item: [...]
  5/5       5/5       test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
            AssertionError: declared not-a-count sentence is gone: 'and all 56 EDA/device tools' assert False + where False = [...]
  5/5       5/5       test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
            AssertionError: stated count drift: README.md: claim site for programs_top_level has VANISHED — no match for [...]
  5/5       5/5       test_step_metrics_coverage.py::test_declared_coverage_matches_the_tree
            assert 68 == 62 + where 62 = sm.GATE_CARRYING_STEPS
  5/5       5/5       test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
            AssertionError: assert 'real compare ran' in 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction [...]
  5/5       5/5       test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_is_deferred_not_counted_without_coverage
            AssertionError: ○ [VACUOUS-PASS ] Step 4: #x1F501 Simulation (testbench-based + L10/L12 coverage + Verilator [...]
  5/5       5/5       test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition
            AssertionError: an oracle PASS with no coverage measurement must be a disclosed deferral: ○ [VACUOUS-PASS ] Step [...]
  5/5       5/5       test_v0_2_97_issue477_lvs_incomplete.py::test_clean_complete_lvs_still_passes
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_v0_2_97_issue477_lvs_incomplete.py::test_real_mismatch_still_fails_as_conclusive
            AssertionError: assert 'LVS_EXTRACTI...LEGAL_OVERLAP' == 'LVS_MISMATCH' - LVS_MISMATCH + LVS_EXTRACTION_ILLEGAL_OVERLAP
  5/5       5/5       test_v0_2_97_issue477_lvs_incomplete.py::test_small_ext2spice_error_count_is_warning_not_fail
            AssertionError: ('FAIL', 'LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT: an extraction RAN for this [...]
  5/5       5/5       test_v0_2_97_issue477_lvs_incomplete.py::test_truncated_verdict_less_report_is_incomplete_fail
            AssertionError: assert 'LVS_EXTRACTI...LEGAL_OVERLAP' == 'LVS_NO_TERMINAL_VERDICT' - LVS_NO_TERMINAL_VERDICT + [...]
  5/5       5/5       test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete
            AssertionError: {'finding': 'LVS_EXTRACTION_ILLEGAL_OVERLAP', 'illegal_overlap_gate_rc': 1, 'lvs_verdict': [...]
  5/5       5/5       test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_truncated_still_incomplete
            AssertionError: assert 'LVS_EXTRACTI...LEGAL_OVERLAP' == 'LVS_NO_TERMINAL_VERDICT' - LVS_NO_TERMINAL_VERDICT + [...]
  5/5       5/5       test_v0_3_5_issue502_503_cascade_attribution.py::test_ordering_ancestry_is_two_orders_of_magnitude_wider
            AssertionError: 1448 assert 1448 == 1311
  5/5       5/5       test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passed_the_empty_predicate_lists
            AssertionError: control no longer discriminates on files_exist: [] assert (False, ['fil... predicate.']) == (True, [...]
  5/5       5/5       test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passes_the_same_empty_corpus_silently
            AssertionError: the defect this file pins is that origin/main returned a BARE True with no record; it returned [...]
  5/5       5/5       test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_was_silent_on_the_advisory_slot
            AssertionError: control no longer discriminates on the advisory slot assert (False is True)

====================================================================================================

# WHAT THIS MEANS FOR YOUR 38 — three things that remove work

## 1. Nothing on your list is a host phantom. Spend on all 38.

IMAGE-ONLY = 0 and HOST-ONLY = 0. Also: your list came from an `-n 10` xdist run
and the brief flagged that two IDs looked like a mutate-vs-read race. **Every one
of your 38 was re-run SERIALLY, no xdist, in both lanes, and all 38 reproduce.**
The harness-artefact bucket is empty by measurement, not by assumption.

## 2. `test_a_pinless_abstract_is_never_staged` — do NOT read your host's red as a defect

    HOST : `which magic` -> command not found
           'magic did not complete: watchdog reported launch_error after 0s'   13/13 RED
    IMAGE: /foss/tools/bin/magic 8.3.681 is present
           'magic exited -11 and wrote no LEF; last output:
            LEF read, Line 26 (Error): No layer defined for RECT.'              4/13 RED

Your host does not have `magic`. `launch_error after 0s` is the watchdog saying
"I could not look" — it is NOT "the abstract was staged". In the CI lane the tool
RUNS and SEGFAULTS intermittently on a LEF whose `RECT` names a layer the
techfile does not define. **So it is a tool crash, not the staging logic, and in
CI it PASSES 9 times in 13.** I characterised it but did not determine whether
the malformed techfile comes from the fixture or from the generator under test —
that part is open.

## 3. The atomic-write ratchet is NOT fixed by `origin/land/ppa-tf` — do not wait for it

Three of your 38 are the ratchet on `atomic_artifact_write_check.py`:
`test_issue1082_open_w_category_closed` x2 and `test_issue1470_atomic_declared_report` x1.

    main   867de4289 : 6 programs / 12 sites
    ppa-tf bb90724dc : 6 programs / 12 sites
    ONLY on ppa-tf: none      ONLY on main: none

Byte-identical on both heads. The 12 sites:

    area_total_vs_budget_check.py:393              .write_text(...)
    closed_loop_edge_check.py:346                  .write_text(...)
    crosslayer_rewrite_equivalence.py:679/701/720/729/751/755
    crosslayer_rewrite_equivalence_check.py:196/229
    declared_clock_period.py:392                   .write_text(...)
    die_density_fill_gen.py:579                    .write_bytes(...)

All twelve are mechanical and map one-for-one onto `_atomic_artefact.write_text` /
`.write_bytes`, which is the remedy the gate itself prints. `crosslayer_*` did not
exist at v1.11.5, so most of this breach arrived with the last 35 commits.

`test_no_declared_report_is_written_through_open_w` fails on exactly ONE of the
twelve — `die_density_fill_gen.py:579`, which promotes a filled layout with
`dest.write_bytes(filled.read_bytes())`, a non-atomic copy of a declared output.
That single site is a one-line fix; the other two IDs need all twelve.

## Other clusters inside your 38, by failure signature

     7  EXTRACTION_FEEDBACK_ABSENT — LVS aborts before netgen; an extraction RAN
        but nothing landed under phase3/stage3/extracted
     3  test_issue901_* structured-vacuity tier — a tier granted without stating
        the count it was granted on
     2  flow-gate enforcement audit — 180 clauses / 171 gates / 19 ENFORCED /
        152 AUDIT_ONLY / 40 declared / 131 UNDECLARED
     2  LVS verdict token changed: 'LVS_EXTRACTI...LEGAL_OVERLAP' vs 'LVS_NO_TERMI...'
     2  flow_manifest_declaration_parity — 162 declared paths vs 160 manifest
        entries; the 2 gaps are step 37.5ic's BRIEF_*.html / SIGNOFF_*.html.
        NOTE: 867de4289 IS the 37.5ic activation commit, so this is its own residue.
     4  test_program_inventory_no_drift — the committed inventory vs the tree
     1  prose polarity: polarity-blind 216 against a baseline of 213

## Provenance

Full report + per-ID tables are on branch `ptmo/main-92-red-triage` (head
8a4906e03) under `docs/research/2026-08-21-main-92-*`. Raw junit and every
runner are on 8hd-3 at /home/reyerchu/_ptmo_priv/out92/.

NOT IN YOUR 38, but the biggest single result of the night and it explains the
OTHER 54: commit 7fcbc7397 added flow step `1.6x` (68 -> 69 steps) and
regenerated NONE of the 63x8 pins. 35 of the 92 are that one commit.
