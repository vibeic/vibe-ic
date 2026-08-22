### pass-1 buckets (image lane = pinned image + PYTEST_DISABLE_PLUGIN_AUTOLOAD=1; host lane = this host + -p no:pytest_ethereum)
### PASS 1 IS ONE OBSERVATION PER LANE, taken while both lanes ran CONCURRENTLY.
### It is SUPERSEDED by TRIAGE57.md, which states a red RATIO per lane from
### interleaved repeats. Two IDs moved bucket under that treatment.
### files with a junit:  image 32/32   host 32/32
  BOTH             91
  IMAGE-ONLY       1

## IMAGE-ONLY  (1)
   red         pass        programs/tests/test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound

## BOTH  (91)
   red         red         programs/tests/test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
   red         red         programs/tests/test_extraction_input_blocked_verdict.py::test_complete_generic_tech_still_passes_end_to_end
   red         red         programs/tests/test_extraction_input_blocked_verdict.py::test_complete_tech_passes_with_real_tech_lef_layer_crosscheck
   red         red         programs/tests/test_extraction_input_blocked_verdict.py::test_complete_tech_with_matching_design_still_passes
   red         red         programs/tests/test_extraction_input_blocked_verdict.py::test_unreadable_tech_does_not_block
   red         red         programs/tests/test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
   red         red         programs/tests/test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
   red         red         programs/tests/test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
   red         red         programs/tests/test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w
   red         red         programs/tests/test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
   red         red         programs/tests/test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
   red         red         programs/tests/test_issue306_register_paydown.py::test_306_shipped_tree_is_green_against_its_register
   red         red         programs/tests/test_issue490_drc_report_check_argv.py::test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks
   red         red         programs/tests/test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
   red         red         programs/tests/test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
   red         red         programs/tests/test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_other_self_aware_shipped_gate_also_reaches_the_tier
   red         red         programs/tests/test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing
   red         red         programs/tests/test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
   red         red         programs/tests/test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
   red         red         programs/tests/test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
   red         red         programs/tests/test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition
   red         red         programs/tests/test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
   red         red         programs/tests/test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans
   red         red         programs/tests/test_matrix_63x8_coverage.py::test_the_grid_size_is_computed_from_the_live_flow_yaml
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_absent_from_audit_is_surfaced_not_swallowed
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_accessors_track_a_removed_field
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_blocks_on_presence_is_not_the_same_set_as_non_empty
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[1]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[2]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[3]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[4]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[5]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[6]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[7]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[8]
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_every_coordinate_appears_exactly_once
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_gate_presence_matches_the_yaml
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_gate_programs_non_empty_exactly_where_the_gate_names_one
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_ledger_is_the_live_cross_product
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_ledger_tracks_a_mutated_flow
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_required_outputs_non_empty_exactly_where_declared
   red         red         programs/tests/test_matrix_63x8_ledger.py::test_total_steps_field_is_not_the_step_count
   red         red         programs/tests/test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned
   red         red         programs/tests/test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_cell_states_partition_all_steps
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_manifest_covers_exactly_the_flow_steps
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
   red         red         programs/tests/test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
   red         red         programs/tests/test_matrix_d4_criteria_match.py::test_d4_selfcheck_every_cell_has_exactly_one_disposition
   red         red         programs/tests/test_matrix_d5_deps_correct.py::test_d5_covers_every_cell_exactly_once
   red         red         programs/tests/test_matrix_d5_deps_correct.py::test_d5_state_census_is_exhaustive
   red         red         programs/tests/test_matrix_d6_skip_discipline.py::test_d6_skip_discipline[step1.6x]
   red         red         programs/tests/test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
   red         red         programs/tests/test_matrix_d7_outputs_list_complete.py::test_every_cell_lands_in_exactly_one_state
   red         red         programs/tests/test_matrix_d8_missing_caught.py::test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one
   red         red         programs/tests/test_matrix_d8_missing_caught.py::test_d8_a_present_but_wrong_declared_output_is_measured_not_assumed
   red         red         programs/tests/test_matrix_d8_missing_caught.py::test_d8_downgrade_is_reachable_through_each_steps_own_real_gate
   red         red         programs/tests/test_matrix_d8_missing_caught.py::test_d8_only_one_declared_output_present_is_still_missing[step1.6x]
   red         red         programs/tests/test_matrix_d8_missing_caught.py::test_the_pin_is_the_MEASURED_population_not_a_SUPERSET_of_it
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step1.6x]
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_the_coverage_is_complete_and_the_count_is_stated
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_the_flow_declares_no_step_the_ledger_never_measured
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_the_grid_gate_names_the_cell_that_moved
   red         red         programs/tests/test_matrix_mutation_ledger.py::test_the_ledger_grid_matches_what_was_measured
   red         red         programs/tests/test_medlow_synth_dft_backlog.py::test_step11_declaration_is_satisfiable_by_a_successful_run
   red         red         programs/tests/test_organic900_901_ratchet_and_json_vacuity.py::test_a_shrink_is_still_allowed
   red         red         programs/tests/test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
   red         red         programs/tests/test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
   red         red         programs/tests/test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
   red         red         programs/tests/test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
   red         red         programs/tests/test_step_metrics_coverage.py::test_declared_coverage_matches_the_tree
   red         red         programs/tests/test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
   red         red         programs/tests/test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
   red         red         programs/tests/test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_is_deferred_not_counted_without_coverage
   red         red         programs/tests/test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition
   red         red         programs/tests/test_v0_2_97_issue477_lvs_incomplete.py::test_clean_complete_lvs_still_passes
   red         red         programs/tests/test_v0_2_97_issue477_lvs_incomplete.py::test_real_mismatch_still_fails_as_conclusive
   red         red         programs/tests/test_v0_2_97_issue477_lvs_incomplete.py::test_small_ext2spice_error_count_is_warning_not_fail
   red         red         programs/tests/test_v0_2_97_issue477_lvs_incomplete.py::test_truncated_verdict_less_report_is_incomplete_fail
   red         red         programs/tests/test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete
   red         red         programs/tests/test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_truncated_still_incomplete
   red         red         programs/tests/test_v0_3_5_issue502_503_cascade_attribution.py::test_ordering_ancestry_is_two_orders_of_magnitude_wider
   red         red         programs/tests/test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passed_the_empty_predicate_lists
   red         red         programs/tests/test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passes_the_same_empty_corpus_silently
   red         red         programs/tests/test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_was_silent_on_the_advisory_slot

