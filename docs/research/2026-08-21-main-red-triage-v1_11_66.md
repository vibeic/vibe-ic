# main's red IDs re-measured against a00f53f20 (v1.11.66)
# input set: the 97 carried forward PLUS every id in the four landing-runtime
#             guard files (none was in the inherited 92) = 419 ids / 38 files
# v1.11.64 (the opened deadline) and v1.11.66 (the crosslayer win) ARE in this tree.
# The deadline acts on carried HYGIENE findings, not on these pytest node ids:
#   measured separately -> 6 FAIL + 1 blocking empty-corpus NOT_CHECKED.
#
# measured: 419/419   (image 38/38 files, host 38/38)

## VERDICT: 3 ID(s) red in ONE LANE ONLY — named below. THIS IS A CHANGE
## from the all-zero verdict and is the most important line in this table.

   GREEN-BOTH       369
   BOTH             24
   IMAGE-ONLY       3
   FLAKY-KNOWN      1
   HOME-ARTEFACT-SUSPECT 22

## RE-READ AGAINST THE v1.11.57 POWER/NETLIST FIX (2)
## (message matches power|netlist|pre/post-PnR|clock tree|mW|CTS|liberty)
   [BOTH] test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
        AssertionError: step 19 (CTS (Clock Tree Synthesis)): 1 declared output(s) cite a run root NO corpus can supply, so the corpus-abs
   [BOTH] test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
        AssertionError: step 20 (#x1F501 Post-CTS hold fixing): 1 declared output(s) cite a run root NO corpus can supply, so the corpus-a

================================================================================================

## IMAGE-ONLY  (3)   [image | host]

  red    pass   test_pad_and_seal_ring_on_the_chip_path.py::test_a_declared_required_ring_that_could_not_be_built_earns_no_marker
  red    pass   test_pad_and_seal_ring_on_the_chip_path.py::test_a_project_that_answered_nothing_is_unchanged
  red    pass   test_pad_and_seal_ring_on_the_chip_path.py::test_answering_the_die_area_does_not_make_the_seal_section_look_started

## FLAKY-KNOWN  (1)   [image | host]

  skipped red    test_v1_4_21_dft_atpg_liberty_resolver.py::test_sky130_fault_cut_produces_real_scan_pairs

## HOME-ARTEFACT-SUSPECT  (22)   [image | host]

  red    red    test_landing_merge_verdict.py::test_a_host_without_merge_tree_names_the_version_found_and_needed
  red    red    test_landing_merge_verdict.py::test_end_to_end_a_green_test_cannot_move_b1_to_another_commit
  red    red    test_landing_merge_verdict.py::test_end_to_end_a_known_good_branch_is_allowed
  red    red    test_landing_merge_verdict.py::test_end_to_end_an_innocuous_diff_that_leaves_a_test_red_is_refused
  red    red    test_landing_merge_verdict.py::test_end_to_end_b2_corpus_mutation_is_post_attested_and_norecord
  red    red    test_landing_merge_verdict.py::test_end_to_end_candidate_cannot_prewrite_base_wave_artifacts
  red    red    test_landing_merge_verdict.py::test_end_to_end_candidate_wave_precedes_parallel_isolated_base_wave
  red    red    test_landing_merge_verdict.py::test_end_to_end_index_flags_cannot_hide_changed_b1_bytes
  red    red    test_landing_merge_verdict.py::test_end_to_end_mutable_base_cache_is_disabled_and_remeasured
  red    red    test_landing_merge_verdict.py::test_end_to_end_post_bootstrap_equal_corpus_uses_ordinary_delta
  red    red    test_landing_merge_verdict.py::test_end_to_end_relinked_parent_selection_is_norecord
  red    red    test_landing_merge_verdict.py::test_end_to_end_replace_refs_cannot_redefine_the_verified_tree
  red    red    test_landing_merge_verdict.py::test_end_to_end_the_fallback_allows_a_known_good_branch
  red    red    test_landing_merge_verdict.py::test_end_to_end_the_fallback_still_refuses_an_innocuous_diff_that_leaves_a_test_red
  red    red    test_landing_merge_verdict.py::test_end_to_end_trusted_verifier_supplies_the_one_bootstrap_evidence
  red    red    test_landing_merge_verdict.py::test_end_to_end_what_is_gated_is_the_squash_and_not_the_branch
  red    red    test_landing_merge_verdict.py::test_interruption_kills_a_term_ignoring_parallel_arm_and_removes_worktrees
  red    red    test_landing_merge_verdict.py::test_pid_only_term_kills_a_term_ignoring_b2_and_removes_worktrees
  red    red    test_landing_merge_verdict.py::test_reassert_refuses_a_record_that_was_not_a_pass
  red    red    test_landing_merge_verdict.py::test_reassert_refuses_when_the_base_moved
  red    red    test_landing_merge_verdict.py::test_the_forced_fallback_is_the_only_thing_the_env_var_can_do
  red    red    test_landing_merge_verdict.py::test_the_tier_the_script_picks_matches_this_hosts_real_capability

## GREEN-BOTH  (369)   [image | host]

  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_bound_on_a_continuation_line_still_belongs_to_its_command
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_bound_quoted_in_a_docstring_is_not_a_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_bound_that_arrives_as_a_parameter_default_is_resolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_chain_of_wrappers_resolves_to_a_fixed_point
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_checkout_with_no_harness_source_refuses_the_outer_ones
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_constant_assigned_inside_a_function_is_not_resolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_default_forwarded_into_an_UNRESOLVABLE_callee_is_advisory
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_doubles_parameter_default_that_reaches_no_launcher_is_still_safe
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_driver_command_in_dead_control_flow_is_not_a_lane[false && ]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_driver_command_in_dead_control_flow_is_not_a_lane[if false; then ]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_lane_cannot_be_redefined_before_its_reviewed_call[run_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_lane_cannot_be_redefined_before_its_reviewed_call[run_repo_tools_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_lane_cannot_be_redefined_before_its_reviewed_call[run_unselectable_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_marked_item_is_judged_against_its_own_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_marker_below_the_harness_bound_tightens_the_ceiling
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_marker_cannot_raise_the_ceiling_past_the_driver_stall_window
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_marker_on_a_fixture_does_not_raise_the_callers_item_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_marker_on_a_helper_does_not_raise_the_callers_item_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_module_constant_bound_is_resolved_to_its_value
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_module_level_pytestmark_bounds_every_call_in_the_file
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_never_called_nested_function_cannot_own_the_lane[function never_called {]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_never_called_nested_function_cannot_own_the_lane[never_called() {]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_parameter_default_the_body_rebinds_is_not_resolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_parameter_with_no_default_stays_unresolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_post_lane_success_exit_cannot_launder_a_red_lane
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_pytestmark_list_is_read_and_the_smallest_timeout_wins
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_recorded_advisory_that_stopped_existing_is_deleted
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_same_file_wrapper_that_names_its_timeout_is_resolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_same_file_wrapper_that_splats_kwargs_is_resolved
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_shell_comment_cannot_supply_the_aggregate_subject_command
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_test_doubles_signature_is_not_a_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_top_level_early_exit_cannot_skip_every_lane
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_a_zero_marker_is_no_item_bound_not_a_bound_of_zero
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_alias_forms_cannot_hide_a_direct_pytest_lane[env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /usr/bin/python3 -m pytest -q]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_alias_forms_cannot_hide_a_direct_pytest_lane[run_it=(python3 -m pytest); "${run_it[@]}"]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_alias_forms_cannot_hide_a_direct_pytest_lane[run_pytest_alias() { python3 -m pytest -q; }; run_pytest_alias]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_empty_tree_discloses_that_it_examined_nothing
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_exact_lane_call_cannot_be_made_dead[run_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_exact_lane_call_cannot_be_made_dead[run_repo_tools_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_exact_lane_call_cannot_be_made_dead[run_unselectable_pytest]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_exception_constructor_records_a_bound_it_does_not_impose
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_explicit_tests_root_replaces_the_set_and_does_not_add_to_it
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_extra_direct_pytest_lane_cannot_bypass_semantic_supervision
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_injected_offender_SPELLED_AS_A_PARAMETER_also_fails
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_injected_offender_makes_the_shipped_program_fail
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_unconditional_early_return_before_the_lane_is_refused
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_unmarked_test_beside_a_marked_one_keeps_the_harness_ceiling
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_unreadable_stall_window_refuses_rather_than_passes
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_unresolvable_callee_is_advisory_not_a_finding
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_an_unused_well_shaped_driver_helper_is_not_execution
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_both_pytest_trees_are_scanned
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_each_root_prints_its_own_file_count
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_echoed_driver_words_and_comment_only_contract_are_not_execution
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_half_migrated_semantic_lane_is_a_failure
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_installing_the_plugin_is_not_a_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_no_workflow_is_rc_2_and_says_it_is_not_a_pass
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_removing_every_semantic_lane_is_not_legacy_success
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_semantic_driver_must_disable_output_and_total_ceiling
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_semantic_landing_harness_has_no_elapsed_ceiling
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_shell_comment_stripping_preserves_quoted_hashes
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_advisory_population_is_printed_with_its_denominator
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_advisory_residual_does_not_grow_unreviewed
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_binding_bound_is_the_minimum_not_the_first
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[_docker_exec('c', ['x'], timeout=900)\n-container invocation]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[from subprocess import run\nrun(['x'], timeout=900)\n-subprocess launcher (imported by name)]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[import subprocess as sp\nsp.check_output(['x'], timeout=900)\n-subprocess launcher]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[import subprocess\nsubprocess.run(['x'], timeout=900)\n-subprocess launcher]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[p = None\np.communicate(timeout=900)\n-blocking child-process method]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_blocking_surface_is_flagged[p = None\np.wait(timeout=900)\n-blocking child-process method]
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_ceiling_is_a_fraction_of_the_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_ceiling_itself_is_allowed_and_one_second_over_is_not
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_gate_is_declared_in_the_hygiene_set
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_gate_reaches_the_merge_gate_through_the_same_script
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_innermost_binding_of_the_name_wins
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_json_record_carries_what_the_text_says
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_landing_script_alone_is_enough_to_resolve_the_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_marked_population_is_printed_with_its_value
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_pass_sentence_does_not_outrun_what_was_checked
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_resolver_stops_at_its_own_checkout_root
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_shipped_tree_is_clean
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_shipped_tree_resolves_to_the_checkout_this_file_is_in
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_shipped_workflows_declare_more_than_one_bound
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_space_form_of_the_flag_is_read
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_two_spellings_of_one_bound_produce_the_same_verdict
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_the_two_trees_use_different_globs_for_a_measured_reason
  pass   pass   test_ci_harness_timeout_ceiling_check.py::test_this_files_own_bounds_are_inside_the_ceiling
  pass   pass   test_extraction_input_blocked_verdict.py::test_complete_generic_tech_still_passes_end_to_end
  pass   pass   test_extraction_input_blocked_verdict.py::test_complete_tech_passes_with_real_tech_lef_layer_crosscheck
  pass   pass   test_extraction_input_blocked_verdict.py::test_complete_tech_with_matching_design_still_passes
  pass   pass   test_extraction_input_blocked_verdict.py::test_unreadable_tech_does_not_block
  pass   pass   test_issue1082_open_w_category_closed.py::test_no_declared_report_is_written_through_open_w
  pass   pass   test_issue1082_open_w_category_closed.py::test_no_new_offender_and_the_ratchet_holds
  pass   pass   test_issue1470_atomic_declared_report.py::test_the_gate_is_green_and_the_ratchet_holds
  pass   pass   test_issue712_prose_polarity.py::test_the_gate_is_GREEN_on_the_tree_that_ships
  pass   pass   test_landing_merge_verdict.py::test_a_base_arm_asked_for_files_that_produced_no_report_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_base_arm_that_did_not_finish_is_refused_not_passed
  pass   pass   test_landing_merge_verdict.py::test_a_base_per_file_norecord_is_named_and_refused
  pass   pass   test_landing_merge_verdict.py::test_a_base_test_arm_that_moved_to_another_commit_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_base_test_arm_that_wrote_the_tree_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_caller_supplying_no_base_selection_is_told_the_check_did_not_fire
  pass   pass   test_landing_merge_verdict.py::test_a_caller_that_never_says_what_arm_a_was_asked_for_is_disclosed
  pass   pass   test_landing_merge_verdict.py::test_a_candidate_per_file_norecord_is_named_from_structured_junit
  pass   pass   test_landing_merge_verdict.py::test_a_candidate_test_arm_that_moved_to_another_commit_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_candidate_test_arm_that_wrote_the_tree_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_candidate_that_ran_no_tests_is_not_a_pass
  pass   pass   test_landing_merge_verdict.py::test_a_complete_base_arm_is_not_flagged_as_partial
  pass   pass   test_landing_merge_verdict.py::test_a_complete_non_target_gate_record_can_join_the_composite
  pass   pass   test_landing_merge_verdict.py::test_a_failing_gate_that_stops_being_asked_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_gate_failing_on_the_base_too_is_not_this_branchs
  pass   pass   test_landing_merge_verdict.py::test_a_gate_this_branch_reddens_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_known_good_pr_shape_is_allowed
  pass   pass   test_landing_merge_verdict.py::test_a_missing_receipt_quotes_the_arms_own_refusal_not_only_the_symptom
  pass   pass   test_landing_merge_verdict.py::test_a_missing_tree_is_not_a_pass
  pass   pass   test_landing_merge_verdict.py::test_a_new_failure_this_branch_owns_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_non_target_gate_abnormal_exit_refuses_even_with_a_fake_terminal
  pass   pass   test_landing_merge_verdict.py::test_a_partial_base_arm_cannot_clear_a_silenced_failure
  pass   pass   test_landing_merge_verdict.py::test_a_partial_non_target_gate_log_is_not_a_composite_pass
  pass   pass   test_landing_merge_verdict.py::test_a_passing_test_weakened_to_skip_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_per_file_norecord_is_not_excused_by_the_same_gate_label_on_the_base
  pass   pass   test_landing_merge_verdict.py::test_a_pre_existing_red_base_still_allows_the_landing
  pass   pass   test_landing_merge_verdict.py::test_a_range_scoped_gate_cannot_be_waived_by_a_vacuous_base_failure
  pass   pass   test_landing_merge_verdict.py::test_a_rebase_conflict_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_selected_file_that_produced_no_test_case_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_selection_failure_is_not_the_test_tier
  pass   pass   test_landing_merge_verdict.py::test_a_silenced_failure_is_refused_and_is_never_an_improvement
  pass   pass   test_landing_merge_verdict.py::test_a_stamp_naming_another_commit_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_test_file_the_pr_adds_is_not_read_as_a_partial_base_arm
  pass   pass   test_landing_merge_verdict.py::test_a_test_that_stopped_existing_is_absent_not_missing
  pass   pass   test_landing_merge_verdict.py::test_a_test_the_branch_brings_is_split_out_from_one_it_broke
  pass   pass   test_landing_merge_verdict.py::test_a_test_tier_failure_with_all_green_machine_record_is_refused
  pass   pass   test_landing_merge_verdict.py::test_a_truncated_candidate_run_is_refused_not_passed
  pass   pass   test_landing_merge_verdict.py::test_aggregate_only_attestations_are_sufficient_on_both_arms
  pass   pass   test_landing_merge_verdict.py::test_an_empty_base_does_not_report_everything_as_merely_brought
  pass   pass   test_landing_merge_verdict.py::test_an_empty_base_report_makes_every_candidate_failure_new
  pass   pass   test_landing_merge_verdict.py::test_an_uninspectable_base_test_worktree_is_unmeasurable
  pass   pass   test_landing_merge_verdict.py::test_an_uninspectable_candidate_test_worktree_is_unmeasurable
  pass   pass   test_landing_merge_verdict.py::test_an_unmeasurable_refusal_still_names_the_reason_it_already_found
  pass   pass   test_landing_merge_verdict.py::test_an_unrecognised_tier_refuses_rather_than_inheriting_the_strong_silence
  pass   pass   test_landing_merge_verdict.py::test_any_non_test_gate_failure_is_refused_when_there_is_no_base_to_compare
  pass   pass   test_landing_merge_verdict.py::test_base_aggregate_norecord_is_an_absolute_refusal
  pass   pass   test_landing_merge_verdict.py::test_candidate_aggregate_norecord_is_an_absolute_refusal
  pass   pass   test_landing_merge_verdict.py::test_cli_discloses_that_the_branch_edits_its_own_gate
  pass   pass   test_landing_merge_verdict.py::test_cli_refuses_missing_or_tampered_protected_source_receipt
  pass   pass   test_landing_merge_verdict.py::test_cli_returns_one_on_a_new_failure
  pass   pass   test_landing_merge_verdict.py::test_cli_returns_two_when_the_candidate_report_is_absent
  pass   pass   test_landing_merge_verdict.py::test_cli_returns_zero_and_names_the_verified_commit
  pass   pass   test_landing_merge_verdict.py::test_end_to_end_a_conflicting_branch_is_refused_before_any_suite_runs
  pass   pass   test_landing_merge_verdict.py::test_end_to_end_the_caller_checkout_is_never_touched
  pass   pass   test_landing_merge_verdict.py::test_end_to_end_the_fallback_still_refuses_a_conflicting_branch
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[errored-failed-preexisting]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[failed-failed-preexisting]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[failed-passed-fixed]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[failed-skipped-silenced]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[failed-xfailed-silenced]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[passed-failed-new_failures]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[passed-skipped-weakened]
  pass   pass   test_landing_merge_verdict.py::test_every_row_of_the_table[skipped-errored-new_failures]
  pass   pass   test_landing_merge_verdict.py::test_fixing_a_pre_existing_failure_is_reported_and_never_required
  pass   pass   test_landing_merge_verdict.py::test_junit_outcomes_are_read_including_xfail
  pass   pass   test_landing_merge_verdict.py::test_land_gates_that_did_not_report_are_not_a_pass
  pass   pass   test_landing_merge_verdict.py::test_neither_arm_can_read_the_others_scratch_file
  pass   pass   test_landing_merge_verdict.py::test_no_overlapping_test_id_is_disclosed_as_a_degradation
  pass   pass   test_landing_merge_verdict.py::test_per_file_base_diagnostics_cannot_fill_aggregate_coverage
  pass   pass   test_landing_merge_verdict.py::test_per_file_diagnostics_cannot_fill_an_incomplete_aggregate
  pass   pass   test_landing_merge_verdict.py::test_reading_one_arms_exit_code_cannot_byte_compile_the_shared_runtime
  pass   pass   test_landing_merge_verdict.py::test_repairing_a_gate_the_base_was_failing_is_reported
  pass   pass   test_landing_merge_verdict.py::test_report_lines_are_never_read_as_gates
  pass   pass   test_landing_merge_verdict.py::test_splitting_the_count_moves_no_verdict
  pass   pass   test_landing_merge_verdict.py::test_subject_process_attributes_cannot_turn_a_failure_green
  pass   pass   test_landing_merge_verdict.py::test_subject_testcase_cannot_spoof_a_parent_process_suite
  pass   pass   test_landing_merge_verdict.py::test_the_base_gate_cache_is_disabled_at_the_adversarial_boundary
  pass   pass   test_landing_merge_verdict.py::test_the_candidate_arm_runs_without_a_maxfail_bound
  pass   pass   test_landing_merge_verdict.py::test_the_cli_record_marks_the_strong_tier_as_not_degraded
  pass   pass   test_landing_merge_verdict.py::test_the_cli_record_tells_the_two_tiers_apart_machine_readably
  pass   pass   test_landing_merge_verdict.py::test_the_cli_refuses_an_unrecognised_tier_as_unmeasurable
  pass   pass   test_landing_merge_verdict.py::test_the_critical_path_does_not_run_targeted_tests_inside_a2_again
  pass   pass   test_landing_merge_verdict.py::test_the_fallback_still_refuses_a_new_failure_this_branch_owns
  pass   pass   test_landing_merge_verdict.py::test_the_fallback_still_refuses_when_the_replay_itself_conflicted
  pass   pass   test_landing_merge_verdict.py::test_the_fallback_tier_discloses_the_cross_check_it_did_not_perform
  pass   pass   test_landing_merge_verdict.py::test_the_file_attribute_is_preferred_when_present
  pass   pass   test_landing_merge_verdict.py::test_the_forge_cross_check_is_dropped_when_the_forge_merged_another_base
  pass   pass   test_landing_merge_verdict.py::test_the_forge_disagreeing_with_the_local_merge_is_refused
  pass   pass   test_landing_merge_verdict.py::test_the_gate_tier_is_compared_against_the_base_not_asserted
  pass   pass   test_landing_merge_verdict.py::test_the_judge_is_not_supplied_by_the_subject
  pass   pass   test_landing_merge_verdict.py::test_the_junit_hook_in_the_landing_script_changes_no_verdict
  pass   pass   test_landing_merge_verdict.py::test_the_per_file_question_is_only_asked_of_a_report_that_claims_it
  pass   pass   test_landing_merge_verdict.py::test_the_replay_disagreeing_with_the_merge_is_refused
  pass   pass   test_landing_merge_verdict.py::test_the_shell_script_defers_the_decision_to_the_program
  pass   pass   test_landing_merge_verdict.py::test_the_split_is_machine_readable_not_only_prose
  pass   pass   test_landing_merge_verdict.py::test_the_strong_tier_records_that_the_cross_check_was_performed
  pass   pass   test_landing_merge_verdict.py::test_the_test_file_is_recovered_without_the_xunit1_file_attribute
  pass   pass   test_landing_merge_verdict.py::test_the_test_tier_failing_is_not_by_itself_a_refusal
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over0-True]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over1-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over2-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over3-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over4-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over5-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over6-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over7-False]
  pass   pass   test_landing_merge_verdict.py::test_the_tier_reports_what_it_checked_and_never_changes_the_answer[over8-False]
  pass   pass   test_landing_merge_verdict.py::test_the_verify_script_hands_the_verdict_arm_as_own_selection
  pass   pass   test_landing_merge_verdict.py::test_the_version_deferral_still_refuses_a_backwards_version
  pass   pass   test_landing_merge_verdict.py::test_the_worst_outcome_wins_for_a_duplicated_id
  pass   pass   test_landing_merge_verdict.py::test_there_is_no_input_that_makes_the_verdict_more_permissive_than_green
  pass   pass   test_landing_merge_verdict.py::test_verifying_a_tree_that_is_not_the_merge_tree_is_refused
  pass   pass   test_matrix_63x8_census_freshness.py::test_the_census_block_is_fresh
  pass   pass   test_matrix_63x8_census_freshness.py::test_the_published_total_equals_the_live_census
  pass   pass   test_matrix_63x8_coverage.py::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved
  pass   pass   test_matrix_63x8_coverage.py::test_live_collection_relays_finite_semantic_progress_past_old_bound
  pass   pass   test_matrix_63x8_coverage.py::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress
  pass   pass   test_matrix_63x8_coverage.py::test_the_enforcement_census_is_reported_for_humans
  pass   pass   test_matrix_63x8_coverage.py::test_the_grid_size_is_computed_from_the_live_flow_yaml
  pass   pass   test_matrix_63x8_ledger.py::test_absent_from_audit_is_surfaced_not_swallowed
  pass   pass   test_matrix_63x8_ledger.py::test_accessors_track_a_removed_field
  pass   pass   test_matrix_63x8_ledger.py::test_blocks_on_presence_is_not_the_same_set_as_non_empty
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[1]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[2]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[3]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[4]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[5]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[6]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[7]
  pass   pass   test_matrix_63x8_ledger.py::test_cells_for_returns_one_row_per_step[8]
  pass   pass   test_matrix_63x8_ledger.py::test_every_coordinate_appears_exactly_once
  pass   pass   test_matrix_63x8_ledger.py::test_gate_presence_matches_the_yaml
  pass   pass   test_matrix_63x8_ledger.py::test_gate_programs_non_empty_exactly_where_the_gate_names_one
  pass   pass   test_matrix_63x8_ledger.py::test_ledger_is_the_live_cross_product
  pass   pass   test_matrix_63x8_ledger.py::test_ledger_tracks_a_mutated_flow
  pass   pass   test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
  pass   pass   test_matrix_63x8_ledger.py::test_required_outputs_non_empty_exactly_where_declared
  pass   pass   test_matrix_63x8_ledger.py::test_total_steps_field_is_not_the_step_count
  pass   pass   test_matrix_d1_wiring.py::test_probe_declared_programs_array_orphans_are_pinned
  pass   pass   test_matrix_d2_falsifiable.py::test_d2_gate_has_a_reachable_fail[step1.6x]
  pass   pass   test_matrix_d3_outputs_produced.py::test_d3_cell_states_partition_all_steps
  pass   pass   test_matrix_d3_outputs_produced.py::test_d3_manifest_covers_exactly_the_flow_steps
  pass   pass   test_matrix_d4_criteria_match.py::test_d4_selfcheck_every_cell_has_exactly_one_disposition
  pass   pass   test_matrix_d5_deps_correct.py::test_d5_covers_every_cell_exactly_once
  pass   pass   test_matrix_d5_deps_correct.py::test_d5_state_census_is_exhaustive
  pass   pass   test_matrix_d6_skip_discipline.py::test_d6_skip_discipline[step1.6x]
  pass   pass   test_matrix_d7_outputs_list_complete.py::test_d7_required_outputs_list_is_complete[step31]
  pass   pass   test_matrix_d7_outputs_list_complete.py::test_every_cell_lands_in_exactly_one_state
  pass   pass   test_matrix_d8_missing_caught.py::test_a_readable_artefact_that_is_wrong_is_not_worth_the_same_as_a_right_one
  pass   pass   test_matrix_d8_missing_caught.py::test_d8_a_present_but_wrong_declared_output_is_measured_not_assumed
  pass   pass   test_matrix_d8_missing_caught.py::test_d8_downgrade_is_reachable_through_each_steps_own_real_gate
  pass   pass   test_matrix_d8_missing_caught.py::test_d8_only_one_declared_output_present_is_still_missing[step1.6x]
  pass   pass   test_matrix_d8_missing_caught.py::test_the_pin_is_the_MEASURED_population_not_a_SUPERSET_of_it
  pass   pass   test_matrix_mutation_ledger.py::test_the_flow_declares_no_step_the_ledger_never_measured
  pass   pass   test_matrix_mutation_ledger.py::test_the_grid_gate_names_the_cell_that_moved
  pass   pass   test_matrix_mutation_ledger.py::test_the_ledger_grid_matches_what_was_measured
  pass   pass   test_medlow_synth_dft_backlog.py::test_step11_declaration_is_satisfiable_by_a_successful_run
  pass   pass   test_program_inventory_no_drift.py::test_check_mode_exits_zero_on_the_committed_tree
  pass   pass   test_program_inventory_no_drift.py::test_clean_tree_reports_no_failure
  pass   pass   test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
  pass   pass   test_program_inventory_no_drift.py::test_stated_counts_in_the_documents_match_the_tree
  pass   pass   test_pytest_per_file_junit.py::test_a_caller_that_declared_a_rootdir_keeps_it
  pass   pass   test_pytest_per_file_junit.py::test_a_file_that_collects_nothing_is_still_named_missing
  pass   pass   test_pytest_per_file_junit.py::test_a_green_session_read_in_another_frame_is_not_refused
  pass   pass   test_pytest_per_file_junit.py::test_a_maxfail_prefix_is_named_and_still_refused
  pass   pass   test_pytest_per_file_junit.py::test_a_missing_report_is_no_record
  pass   pass   test_pytest_per_file_junit.py::test_a_nested_drivers_complaint_is_not_this_sessions_reason
  pass   pass   test_pytest_per_file_junit.py::test_a_probe_that_made_no_complaint_yields_no_protocol_reason
  pass   pass   test_pytest_per_file_junit.py::test_a_real_stall_is_not_reclassified_as_a_truncation
  pass   pass   test_pytest_per_file_junit.py::test_a_red_test_is_a_red_run_not_a_missing_record
  pass   pass   test_pytest_per_file_junit.py::test_a_session_level_red_is_not_erased_by_green_testcase_xml
  pass   pass   test_pytest_per_file_junit.py::test_a_stall_the_supervisor_actually_saw_is_still_called_a_stall
  pass   pass   test_pytest_per_file_junit.py::test_a_stream_that_appears_after_the_first_scan_is_still_admitted
  pass   pass   test_pytest_per_file_junit.py::test_a_subject_that_prints_the_stall_marker_is_not_called_a_stall
  pass   pass   test_pytest_per_file_junit.py::test_a_zero_collecting_file_is_not_reclassified_as_a_truncation
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_canary_preserves_cross_file_process_semantics
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_loss_confines_norecord_to_the_hanging_file
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_norecord_fallback_ignores_legacy_failure_threshold
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_norecord_is_named_and_returns_unknown
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_norecord_runs_diagnostic_fallback_and_stays_unknown
  pass   pass   test_pytest_per_file_junit.py::test_aggregate_refuses_a_selected_file_that_collected_no_tests
  pass   pass   test_pytest_per_file_junit.py::test_an_empty_selection_is_refused_and_never_a_pass
  pass   pass   test_pytest_per_file_junit.py::test_an_unknown_session_shape_is_never_called_a_truncation
  pass   pass   test_pytest_per_file_junit.py::test_both_landing_arms_run_through_this_driver
  pass   pass   test_pytest_per_file_junit.py::test_chatty_import_output_is_diagnostic_not_pytest_progress
  pass   pass   test_pytest_per_file_junit.py::test_cleanup_latches_first_signal_until_final_zero
  pass   pass   test_pytest_per_file_junit.py::test_cleanup_retains_subreaper_until_sigkill_pending_identity_is_zero
  pass   pass   test_pytest_per_file_junit.py::test_collect_import_activity_without_semantic_transition_is_norecord[import time\ndeadline=time.monotonic()+3\nwhile time.monotonic() < deadline: pass\ndef test_never(): assert True\n-None]
  pass   pass   test_pytest_per_file_junit.py::test_collect_import_activity_without_semantic_transition_is_norecord[import time\ndeadline=time.monotonic()+3\nwhile time.monotonic() < deadline:\n    print('COLLECT_CHATTER', flush=True)\n    time.sleep(.02)\ndef test_never(): assert True\n-COLLECT_CHATTER]
  pass   pass   test_pytest_per_file_junit.py::test_collect_only_has_its_own_complete_terminal_protocol
  pass   pass   test_pytest_per_file_junit.py::test_collect_only_terminal_must_preserve_declared_count[terminal0]
  pass   pass   test_pytest_per_file_junit.py::test_collect_only_terminal_must_preserve_declared_count[terminal1]
  pass   pass   test_pytest_per_file_junit.py::test_complete_aggregate_check_does_not_launch_per_file_sessions
  pass   pass   test_pytest_per_file_junit.py::test_corrupt_progress_growth_never_renews_the_lease
  pass   pass   test_pytest_per_file_junit.py::test_cpu_activity_without_pytest_progress_is_still_a_stall
  pass   pass   test_pytest_per_file_junit.py::test_driver_signal_cleanup_reaps_the_active_detached_descendant
  pass   pass   test_pytest_per_file_junit.py::test_duplicate_key_or_nonfinite_progress_json_is_malformed
  pass   pass   test_pytest_per_file_junit.py::test_duplicate_selected_file_is_refused_before_pytest_runs
  pass   pass   test_pytest_per_file_junit.py::test_every_unreadable_report_is_no_record_not_an_empty_one[-an empty file is not a partial answer]
  pass   pass   test_pytest_per_file_junit.py::test_every_unreadable_report_is_no_record_not_an_empty_one[<?xml version='1.0'?><testsuites name='pytest tests' />-a well-formed report with no testsuite in it]
  pass   pass   test_pytest_per_file_junit.py::test_every_unreadable_report_is_no_record_not_an_empty_one[<testsuites-a half-written XML left by a killed process]
  pass   pass   test_pytest_per_file_junit.py::test_files_not_launched_are_named_rather_than_looking_clean
  pass   pass   test_pytest_per_file_junit.py::test_finite_domain_checkpoints_keep_one_long_test_item_alive
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_outer_progress_is_exact_selection_order_only
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_outer_progress_missing_or_failed_relay_is_norecord
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_outer_progress_refuses_changed_item_denominator_or_ordinal
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_outer_progress_refuses_wrong_matrix_denominator
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_outer_progress_relays_only_exact_parent_matrix_domains
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_relay_reads_the_object_production_actually_hands_it
  pass   pass   test_pytest_per_file_junit.py::test_hermetic_relay_stays_silent_until_every_worker_agrees
  pass   pass   test_pytest_per_file_junit.py::test_invalid_domain_progress_freezes_the_semantic_score[bad0]
  pass   pass   test_pytest_per_file_junit.py::test_invalid_domain_progress_freezes_the_semantic_score[bad1]
  pass   pass   test_pytest_per_file_junit.py::test_invalid_domain_progress_freezes_the_semantic_score[bad2]
  pass   pass   test_pytest_per_file_junit.py::test_maxfail_prefix_is_norecord_not_a_complete_failure_set
  pass   pass   test_pytest_per_file_junit.py::test_missing_or_ambiguous_required_runtime_identity_never_renews
  pass   pass   test_pytest_per_file_junit.py::test_missing_progress_sidecar_is_fail_closed
  pass   pass   test_pytest_per_file_junit.py::test_natural_exit_reaps_dead_adopted_zombie_without_norecord
  pass   pass   test_pytest_per_file_junit.py::test_natural_exit_with_live_descendant_is_norecord_after_cleanup
  pass   pass   test_pytest_per_file_junit.py::test_nested_validated_progress_is_relayed_to_the_outer_session
  pass   pass   test_pytest_per_file_junit.py::test_one_session_loses_the_whole_record_and_per_file_does_not
  pass   pass   test_pytest_per_file_junit.py::test_partial_progress_line_waits_but_is_never_progress
  pass   pass   test_pytest_per_file_junit.py::test_process_verdict_key_is_stable_and_carries_exact_rc
  pass   pass   test_pytest_per_file_junit.py::test_progress_stall_catches_a_hang_pytest_timeout_cannot_see
  pass   pass   test_pytest_per_file_junit.py::test_progress_stall_cleans_a_descendant_that_escaped_the_process_group
  pass   pass   test_pytest_per_file_junit.py::test_progressing_collection_may_outlive_many_stall_windows
  pass   pass   test_pytest_per_file_junit.py::test_protocol_refusal_is_not_mislabeled_as_a_stall
  pass   pass   test_pytest_per_file_junit.py::test_pytest_deselection_is_a_complete_selected_subset
  pass   pass   test_pytest_per_file_junit.py::test_required_runtime_identity_is_bound_to_session_start
  pass   pass   test_pytest_per_file_junit.py::test_rescue_parallelism_has_cpu_memory_pid_and_absolute_hard_caps
  pass   pass   test_pytest_per_file_junit.py::test_short_natural_collect_relays_its_terminal_protocol
  pass   pass   test_pytest_per_file_junit.py::test_signal_during_parallel_fallback_reaps_detached_descendant
  pass   pass   test_pytest_per_file_junit.py::test_silent_pytest_boundaries_keep_a_long_session_alive
  pass   pass   test_pytest_per_file_junit.py::test_stratified_probe_preserves_late_and_early_green_files[eight-local-hangs-first]
  pass   pass   test_pytest_per_file_junit.py::test_stratified_probe_preserves_late_and_early_green_files[two-green-files-first]
  pass   pass   test_pytest_per_file_junit.py::test_systemic_import_hang_recovery_is_bounded_parallel_not_serial
  pass   pass   test_pytest_per_file_junit.py::test_term_during_cleanup_cancels_before_fallback_and_leaves_zero
  pass   pass   test_pytest_per_file_junit.py::test_the_bound_is_read_from_this_drivers_own_argv
  pass   pass   test_pytest_per_file_junit.py::test_the_file_with_no_record_is_named
  pass   pass   test_pytest_per_file_junit.py::test_the_landing_harness_argv_shape_is_the_one_this_file_pins
  pass   pass   test_pytest_per_file_junit.py::test_the_landing_harness_declares_semantic_progress_not_elapsed_time
  pass   pass   test_pytest_per_file_junit.py::test_the_merge_omits_files_that_have_no_record
  pass   pass   test_pytest_per_file_junit.py::test_the_merged_report_is_xunit1_and_carries_the_file_attribute
  pass   pass   test_pytest_per_file_junit.py::test_the_sink_reader_refuses_a_complete_join
  pass   pass   test_pytest_per_file_junit.py::test_the_stall_verdict_is_a_required_argument
  pass   pass   test_pytest_per_file_junit.py::test_this_files_final_test_safety_bound_is_inside_the_ceiling
  pass   pass   test_pytest_per_file_junit.py::test_unproved_final_descendant_census_is_norecord
  pass   pass   test_pytest_per_file_junit.py::test_zero_record_probe_still_attempts_the_one_unprobed_green_file
  pass   pass   test_pytest_per_file_junit.py::test_zero_selection_collect_requires_its_distinct_terminal
  pass   pass   test_step_metrics_coverage.py::test_declared_coverage_matches_the_tree
  pass   pass   test_trusted_pytest_entry.py::test_an_empty_segment_in_the_lane_is_refused
  pass   skipped test_trusted_pytest_entry.py::test_an_unset_lane_leaves_the_pinned_image_path_unchanged
  pass   pass   test_trusted_pytest_entry.py::test_every_named_directory_answers_in_the_order_it_was_named
  pass   skipped test_trusted_pytest_entry.py::test_isolated_entry_ignores_subject_pytest_and_progress_plugin
  pass   pass   test_trusted_pytest_entry.py::test_nonisolated_entry_refuses_before_subject_collection
  skipped pass   test_trusted_pytest_entry.py::test_pinned_hermetic_image_ignores_subject_module_shadows
  pass   pass   test_trusted_pytest_entry.py::test_the_entry_reports_the_runtime_it_was_given_and_never_completes_it
  pass   pass   test_trusted_pytest_entry.py::test_the_identity_record_still_shows_which_lane_answered
  pass   pass   test_trusted_pytest_entry.py::test_the_lane_cannot_be_the_subject_checkout
  pass   pass   test_trusted_pytest_entry.py::test_the_lane_is_inserted_at_the_front_not_appended
  pass   pass   test_trusted_pytest_entry.py::test_the_lane_must_be_absolute_and_must_exist
  pass   pass   test_trusted_pytest_entry.py::test_the_lane_refuses_without_the_autoload_pin
  pass   pass   test_trusted_pytest_entry.py::test_the_named_lane_records_where_the_same_entry_refused
  pass   pass   test_trusted_pytest_entry.py::test_without_the_lane_a_siteless_isolated_entry_refuses
  pass   pass   test_v0_2_77_lvs_reachable.py::test_lvs_fails_on_real_mismatch
  pass   pass   test_v0_2_77_lvs_reachable.py::test_lvs_runs_and_passes_on_match
  pass   pass   test_v0_2_97_issue477_lvs_incomplete.py::test_clean_complete_lvs_still_passes
  pass   pass   test_v0_2_97_issue477_lvs_incomplete.py::test_real_mismatch_still_fails_as_conclusive
  pass   pass   test_v0_2_97_issue477_lvs_incomplete.py::test_small_ext2spice_error_count_is_warning_not_fail
  pass   pass   test_v0_2_97_issue477_lvs_incomplete.py::test_truncated_verdict_less_report_is_incomplete_fail
  pass   pass   test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_pin_fail_is_conclusive_mismatch_not_incomplete
  pass   pass   test_v0_3_24_issue524_lvs_pin_matching_verdict.py::test_runner_truncated_still_incomplete
  pass   pass   test_v0_3_5_issue502_503_cascade_attribution.py::test_ordering_ancestry_is_two_orders_of_magnitude_wider
  pass   pass   test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passed_the_empty_predicate_lists
  pass   pass   test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_passes_the_same_empty_corpus_silently
  pass   pass   test_w4_absent_condition_is_not_a_pass.py::test_negative_control_origin_main_was_silent_on_the_advisory_slot

## BOTH  (24)   [image | host]

  red    red    test_digital_hardmacro_gen.py::test_a_pinless_abstract_is_never_staged
  red    red    test_flow_compliance_check_gate.py::test_a_real_verdict_is_not_mistaken_for_a_crash
  red    red    test_flow_manifest_declaration_parity.py::test_every_declared_path_has_a_manifest_entry
  red    red    test_flow_manifest_declaration_parity.py::test_the_population_is_the_whole_flow_and_is_not_empty
  red    red    test_issue306_register_paydown.py::test_306_shipped_tree_is_green_against_its_register
  red    red    test_issue490_drc_report_check_argv.py::test_the_docstring_does_not_claim_an_enforcement_tier_it_lacks
  red    red    test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_GUARD_the_shipped_step_is_not_vacuous_when_its_sim_actually_ran
  red    red    test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_other_self_aware_shipped_gate_also_reaches_the_tier
  red    red    test_issue901_structured_vacuity_reaches_the_step_verdict.py::test_the_shipped_step_names_the_one_clause_that_examined_nothing
  red    red    test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition
  red    red    test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
  red    red    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
  red    red    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
  red    red    *PWR* test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
  red    red    *PWR* test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
  red    red    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
  red    red    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
  red    red    test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step0.5ic]
  red    red    test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step1.6x]
  red    red    test_matrix_mutation_ledger.py::test_the_coverage_is_complete_and_the_count_is_stated
  red    red    test_organic900_901_ratchet_and_json_vacuity.py::test_a_shrink_is_still_allowed
  red    red    test_pytest_per_file_junit.py::test_nested_collect_progress_is_relayed_to_the_outer_session
  red    red    test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_is_deferred_not_counted_without_coverage
  red    red    test_v0_2_96_issue460_coverage_bridge.py::test_e2e_oracle_pass_lifts_step4_out_of_skipped_condition
