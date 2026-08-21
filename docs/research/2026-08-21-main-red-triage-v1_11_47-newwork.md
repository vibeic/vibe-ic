# PHASE B @ v1.11.47 — the 62 test files batch 2 CHANGED or ADDED, whole file, both lanes
# image: 56 files with junit, 2168 cases, 12 red
# host : 56 files with junit, 2168 cases, 11 red
# 6 more were DELETED by 752a8baa, reported ABSENT_ON_THIS_TREE, never counted green.

  BOTH 9 | IMAGE-ONLY 3 | HOST-ONLY 2

## GENUINELY NEW RED, not in the old 92 (5)
   [HOST-ONLY ] test_matrix_63x8_coverage.py::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress
   [IMAGE-ONLY] test_pad_and_seal_ring_on_the_chip_path.py::test_a_declared_required_ring_that_could_not_be_built_earns_no_marker
   [IMAGE-ONLY] test_pad_and_seal_ring_on_the_chip_path.py::test_a_project_that_answered_nothing_is_unchanged
   [IMAGE-ONLY] test_pad_and_seal_ring_on_the_chip_path.py::test_answering_the_die_area_does_not_make_the_seal_section_look_started
   [HOST-ONLY ] test_v1_4_21_dft_atpg_liberty_resolver.py::test_sky130_fault_cut_produces_real_scan_pairs

## already in the old 92 (9) — not new
    test_matrix_63x8_coverage.py::test_every_na_cell_asserts_a_live_precondition
    test_matrix_63x8_coverage.py::test_no_cell_is_counted_enforced_while_its_predicate_is_red
    test_matrix_63x8_ledger.py::test_output_entries_classify_into_the_four_kinds
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step15]
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step17]
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step19]
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step20]
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step30]
    test_matrix_d3_outputs_produced.py::test_d3_required_outputs_are_produced[step32]
