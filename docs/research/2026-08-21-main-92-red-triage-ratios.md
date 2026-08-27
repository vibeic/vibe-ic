### the 57 non-1.6x IDs — red ratio per lane, pass 1 + interleaved repeats

### VERDICT: IMAGE-ONLY = 0 and HOST-ONLY = 0, so **main is genuinely red here — these are NOT environment artefacts of one lane**. Of these 57 IDs, 55 reproduce in BOTH the pinned CI image and on this host, on every observation taken; the only exceptions are the 2 named FLAKY below, whose red ratios are stated. Nothing on this list can be closed by blaming the developer host. **These ratios were taken against `867de4289` (v1.11.18) and are historical; a row leaves the BOTH bucket only when it has been RE-MEASURED green in both lanes at a named later sha, and moves to CLEARED below rather than disappearing.**

### bucket needs BOTH lanes to have >=1 observation; NOT_MEASURED is never a default
  BOTH          34
  CLEARED       21
  FLAKY         2

bucket        image    host     id
FLAKY         4/13     13/13    test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
FLAKY         1/10     0/10     test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound
BOTH          5/5      5/5      test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
BOTH          5/5      5/5      test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
BOTH          5/5      5/5      test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
BOTH          5/5      5/5      test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w
BOTH          5/5      5/5      test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
BOTH          5/5      5/5      test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
BOTH          5/5      5/5      test_issue306_register_paydown.py::test_306_shipped_tree_is_green_against_its_register
BOTH          5/5      5/5      test_issue490_drc_report_check_argv.py::test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks
BOTH          5/5      5/5      test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
BOTH          2/2      2/2      test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
BOTH          2/2      2/2      test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
BOTH          2/2      2/2      test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
BOTH          2/2      2/2      test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition
BOTH          2/2      2/2      test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
BOTH          2/2      2/2      test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans
BOTH          5/5      5/5      test_matrix_63x8_ledger.py::test_absent_from_audit_is_surfaced_not_swallowed
BOTH          5/5      5/5      test_matrix_63x8_ledger.py::test_accessors_track_a_removed_field
BOTH          5/5      5/5      test_matrix_63x8_ledger.py::test_every_coordinate_appears_exactly_once
BOTH          5/5      5/5      test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
BOTH          5/5      5/5      test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
BOTH          5/5      5/5      test_medlow_synth_dft_backlog.py::test_step11_declaration_is_satisfiable_by_a_successful_run
BOTH          5/5      5/5      test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
BOTH          5/5      5/5      test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
BOTH          5/5      5/5      test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
BOTH          5/5      5/5      test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
BOTH          5/5      5/5      test_step_metrics_coverage.py::test_declared_coverage_matches_the_tree
BOTH          5/5      5/5      test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_is_deferred_not_counted_without_coverage
BOTH          5/5      5/5      test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition
BOTH          5/5      5/5      test_v0_3_5_issue502_503_cascade_attribution.py::test_ordering_ancestry_is_two_orders_of_magnitude_wider

### CLEARED — re-measured GREEN in both lanes at a named later sha

Not a re-bucketing of the old observation: a new measurement, stated with the sha it
was taken at. The original ratio is kept in the row so the history is not erased.

The `now` ratios are the pooled observations of TWO independent sessions on two
different fleet hosts, each with its own fresh `--no-local` clone, its own control
clone and its own constructed violations: 2+2 image runs and 3+3 host runs, whole
modules, no `-k` selection, `VIBEIC_CORPUS_ROOT` unset. Neither pass reused an
artefact of the other and both reached the same verdict.

cleared_at   was(image/host)  now(image/host)  id
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_clean_complete_lvs_still_passes
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_real_mismatch_still_fails_as_conclusive
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_small_ext2spice_error_count_is_warning_not_fail
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_2_97_issue477_lvs_incomplete.py::test_truncated_verdict_less_report_is_incomplete_fail
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete
ae5cc4dbf    5/5 5/5 RED     0/4 0/6 GREEN  test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_truncated_still_incomplete
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_generic_tech_still_passes_end_to_end
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_tech_passes_with_real_tech_lef_layer_crosscheck
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_complete_tech_with_matching_design_still_passes
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_extraction_input_blocked_verdict.py::test_unreadable_tech_does_not_block
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_other_self_aware_shipped_gate_also_reaches_the_tier
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_organic900_901_ratchet_and_json_vacuity.py::test_a_shrink_is_still_allowed
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passed_the_empty_predicate_lists
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passes_the_same_empty_corpus_silently
628ca251f    5/5 5/5 RED     0/2 0/2 GREEN  test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_was_silent_on_the_advisory_slot
5d1b82988    5/5 5/5 RED     0/1 0/1 GREEN  test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
5d1b82988    5/5 5/5 RED     0/1 0/1 GREEN  test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]

All eight are one cause and one fix. The three modules' shared `_fake_docker` stub
modelled a Magic `ext2spice` that wrote the extracted netlist but never wrote
`FEEDBACK_OUT` — an extraction whose error channel was never dumped, which real Magic
always dumps (0 bytes when `feedback count` is 0). `step_lvs`'s pre-netgen gate
`magic_illegal_overlap_check` refused it, correctly, as `EXTRACTION_FEEDBACK_ABSENT`:
an absent file is not a measured zero. Every one of the eight died at that abort
before netgen was ever reached. `d3dce649b` (v1.11.43) repaired the stub in all three
modules; no assertion was weakened, no case deleted, no skipif added, no tolerance
widened. Both directions are shown in
`docs/research/2026-08-27-lvs-family-remeasured-at-v1-11-96.md`: removing that same
`FEEDBACK_OUT` write again at `ae5cc4dbf` sends the two `test_v0_2_77` IDs straight
back to RED with the same finding, and leaves the module's three non-extraction tests
green.

The independent second pass is in
`docs/research/2026-08-28-lvs-family-independent-reverification.md`, and it closes
the two holes a single-direction proof leaves. Its CONTROL run at the ratios
table's own subject `867de4289` fails exactly these eight IDs and no others, in
BOTH lanes — so the harness demonstrably can produce this red, and the original
`5/5 5/5` was a true measurement of its own subject. Its constructed violation V1
(remove the `FEEDBACK_OUT` write at head, all three modules) also fails exactly
these eight in BOTH lanes; its constructed violation V2 feeds the gate a feedback
dump that IS written and carries two real `Illegal overlap` records while netgen
reports `Circuits match uniquely`, and `step_lvs` still returns FAIL /
`LVS_EXTRACTION_ILLEGAL_OVERLAP` in both lanes. The gate therefore refuses an
unmeasured channel AND a dirty one, and is not a check that refuses everything.

ADJACENT, NOW MOVED — the four `test_extraction_input_blocked_verdict.py` IDs carry
the same `FEEDBACK_OUT` stub repair from the same commit. They were measured green at
`ae5cc4dbf` and left in BOTH because they were another slice's to move; that slice has
now moved them, on its own measurement at `628ca251f`, together with seven more. See
the section below.


### the extraction / structured-vacuity / w4 slice — 11 IDs, cleared at `628ca251f`

```
subject   628ca251f  (v1.12.8)   TREE_SHA 7a7f8cb0ca9667aded2669c78ba4e00a5c28f9d1
control   867de4289  (v1.11.18)  — the sha this table's own ratios were taken at
host      8HD-9 (192.168.1.105)
image     ghcr.io/vibeic/vibeic-eda:latest  (entrypoint bypassed)
env       PYTHONDONTWRITEBYTECODE=1 · TMPDIR outside the account home ·
          VIBEIC_TRUSTED_PYTEST_SITE=auto · PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 ·
          VIBEIC_CORPUS_ROOT unset · one `python3 -m pytest` per lane, serial, no xdist
```

Whole modules, never a `-k` selection. At `628ca251f`: **119 passed, 2 skipped** on every
run — host 2/2, image 2/2. (The same four modules at `88809e6bf` also gave 119 passed /
2 skipped, host 3/3 and image 2/2.) The two skips are
`test_extraction_input_blocked_verdict.py` lines 1143 and 1162, both gated on real PDK
technology files, and neither is one of these eleven. All 11 named IDs collect and PASS
explicitly — 11 collected, 0 skipped — so the green is not a collection hole.

**The control.** At `867de4289`, the same command in the same two lanes fails
**11 of 120**, and the failing set is these eleven exactly — not a superset, not a
subset — in BOTH lanes (`host 11 failed, 107 passed, 2 skipped`; image identical). The
harness demonstrably still produces this red, and the original `BOTH 5/5 5/5` was a true
measurement of its own subject.

**Three causes, not eleven.**

1. *The four extraction IDs* — the shared `_fake_docker` stub modelled a Magic
   `ext2spice` that wrote the netlist but never wrote `FEEDBACK_OUT`. Repaired by
   `d3dce649b` (v1.11.43); same cause and same commit as the eight LVS IDs above.
2. *The three w4 negative controls* — the control asserted that the reference evaluator
   still exhibits the bug, but aimed at `origin/main`, a MOVING ref. It died the moment
   the fix landed there, reporting "the control no longer discriminates". `d3dce649b`
   pinned `_BASE_REV = "397b3f25f"`. A control must be built from a state that stays
   legitimately vulnerable, and only an immutable revision is that.
3. *`test_a_shrink_is_still_allowed`* — the ratchet FAILED when it tightened. Paying a
   debt cost a red board, and the remedy the audit named was `--write-baseline`, the one
   write that would also record that run's NEW findings as accepted debt. A shrink is now
   reported as a TIGHTENING. (The three `issue901` IDs move with the tier work in the
   same span.)

No assertion was weakened, no case deleted, no `skipif` added, no tolerance widened, and
no baseline written: every repair is in a test fixture, in a pinned revision, or in the
direction of refusing more.

**Constructed violations — each family put back to red at head.**

| # | violation at `628ca251f` | effect |
|---|---|---|
| V1 | remove the `FEEDBACK_OUT` write from the stub | the 4 extraction IDs FAIL, `EXTRACTION_FEEDBACK_ABSENT` |
| V2 | point `_BASE_REV` back at `origin/main` | the 3 w4 controls FAIL, "control no longer discriminates" |
| V3 | make the write path refuse any change, not only growth | the shrink ID FAILS: "refusing to GROW ... (116 -> 115)" |
| V4 | silence BOTH partial-vacuity producers | 2 of the 3 issue901 IDs FAIL |
| V5 | withhold the unanimous `VACUOUS_PASS` tier grant | the 3rd issue901 ID FAILS, "consumed as PARTIALLY-VACUOUS" |

Two of these took a second attempt, and the reason is worth recording. The
partial-vacuity disclosure has **two independent producers** — the tier's own
`else` branch and the structured channel below it, printing the same sentence from the
same numerator and denominator by design. Silencing either one alone leaves every test
GREEN, which reads exactly like "this guard cannot detect the defect". Only V4, which
silences both, is a falsification. The same trap caught the shrink ID: `_run_audit`
passes `--write-baseline`, so a mutation on the read/compare path never executes, and
`_json_report_signals_vacuous` is documented as NOT WIRED INTO THE STEP TIER. A mutation
that lands in a dead arm is indistinguishable from a guard that does not work.
