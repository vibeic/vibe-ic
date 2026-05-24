# Programs audit — vibe-ic v1.3.0 plugin
Auto-generated audit of every `.py` file under `vibe-ic-marketplace/plugins/vibe-ic/programs/` (370 files).
Methodology:
- Read each program's docstring and import block.
- Built reference index by grepping every program name across the entire plugin tree (1,381 source files: .py, .yaml, .md, .json, .sh) plus the burn driver at `mcp-eda-server/src/devices/fpga/terasic-de10lite/driver.py`.
- Treated `programs/INDEX.md`, `CHANGELOG.md`, `README.md`, `MIGRATION_LOG.md` as auto-generated catalog / changelog NOT production wiring.
- Computed transitive wiring: program is `TRANSITIVELY_WIRED` if any caller chain reaches a `WIRED_PRIMARY` program.

## Status definitions
| Status | Definition |
|---|---|
| `WIRED_PRIMARY:struct_gate` | name is in `flow_compliance_check.py::_STRUCTURAL_RTL_GATES` |
| `WIRED_PRIMARY:runner_or_yaml` | invoked by `flow/phase2_phase3.yaml`, a `*_one_shot_runner.py`, `aid_class_rtl_gen.py`, or the burn driver |
| `WIRED_BY_SKILL` | invoked by a skill SKILL.md / agent yaml |
| `TRANSITIVELY_WIRED` | helper imported by another program that is itself `WIRED_PRIMARY` |
| `WIRED_TEST_ONLY` | only referenced by `tests/`; production chain does not call it |
| `STANDALONE_TOOL_OR_DOC` | has `__main__` and is mentioned in markdown docs but no invoker — deliberate manual CLI |
| `HELPER_BUT_DEAD_CHAIN` | imported by another program, but the calling program is itself unwired (dead cluster) |
| `ORPHAN` | no references anywhere |

## Executive summary
Total programs audited: **370**

### Status counts
- `HELPER_BUT_DEAD_CHAIN` — 32
- `ORPHAN` — 1
- `STANDALONE_TOOL_OR_DOC` — 20
- `TRANSITIVELY_WIRED` — 17
- `WIRED_BY_SKILL` — 12
- `WIRED_PRIMARY:runner_or_yaml` — 62
- `WIRED_PRIMARY:struct_gate` — 180
- `WIRED_TEST_ONLY` — 46

### Recommendation counts
- **KEEP** — 291
- **REVIEW** — 33
- **WIRE_IN** — 46

## Per-program audit table
| # | Program | Status | Refs | Recommendation | Notes |
|---|---|---|---|---|---|
| 1 | `_facts_yaml` | TRANSITIVELY_WIRED | prog=4 test=1 | KEEP | shared helper transitively reached from a wired program; *_facts_yaml.py — shared YAML reader for `facts.yaml` (v0.119.70 / Wave 42).* |
| 2 | `_phase1_sentinel` | HELPER_BUT_DEAD_CHAIN | prog=2 test=2 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *Shared no-protocol sentinel detection for Phase-1 gates.* |
| 3 | `acceptance_gate_cli` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *acceptance_gate_cli.py — CLI surface acceptance gate.* |
| 4 | `acceptance_gate_full` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *acceptance_gate_full.py — full end-to-end MARKETPLACE LIFECYCLE acceptance gate.* |
| 5 | `acceptance_gate_registry` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *acceptance_gate_registry.py — registry round-trip acceptance gate.* |
| 6 | `aid_class_qsf_gen` | TRANSITIVELY_WIRED | prog=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *Backwards-compat shim — to be removed in v0.130.* |
| 7 | `aid_class_rtl_gen` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=2 prog=1 test=2 doc=4 | KEEP | invoked by runner / flow YAML / burn driver; *aid_class_rtl_gen — Vibe-IC plugin Phase 2b RTL generator for EXAMPLE_PROTOCOL-class half-duplex protocol.* |
| 8 | `aid_class_sdc_gen` | TRANSITIVELY_WIRED | prog=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *Backwards-compat shim — to be removed in v0.130.* |
| 9 | `analog_block_coverage_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_block_coverage_check.py — deterministic gate for analog block design coverage* |
| 10 | `analog_content_detected_must_emit_l5_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_content_detected_must_emit_l5_check.py — Wave 47 / v0.120.1* |
| 11 | `analog_corner_sweep_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_corner_sweep_check.py — deterministic gate for PVT corner coverage* |
| 12 | `analog_digital_interface_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_digital_interface_check.py — deterministic gate for digital-analog interface validation* |
| 13 | `analog_flow_compliance_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_flow_compliance_check.py — analog track compliance gate (A1-A8)* |
| 14 | `analog_hardmacro_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_hardmacro_check.py — deterministic gate for analog hardmacro deliverables* |
| 15 | `analog_hw_spice_correlation_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_hw_spice_correlation_check.py — deterministic gate for HW-vs-SPICE correlation* |
| 16 | `analog_netlist_pdk_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_netlist_pdk_check.py — deterministic gate for SPICE netlist PDK compliance* |
| 17 | `analog_one_shot_runner` | WIRED_BY_SKILL | skill=3 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *analog_one_shot_runner.py — A1..A8 analog flow (parallel to Phase 2 digital).* |
| 18 | `analog_pre_vs_post_layout_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *analog_pre_vs_post_layout_check.py — deterministic gate for pre/post-layout comparison* |
| 19 | `arbiter_starvation_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *arbiter_starvation_check.py — BACKLOG-v11 P0.6.* |
| 20 | `assertion_covers_l3_constraints_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *assertion_covers_l3_constraints_check.py — Wave 39 / D3* |
| 21 | `assertion_property_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *assertion_property_check.py — Deterministic compliance check for assertion-gen.* |
| 22 | `atpg` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=5 prog=1 doc=10 | KEEP | invoked by runner / flow YAML / burn driver; *atpg.py — Phase 3 backend step (replaces skill atpg).* |
| 23 | `auto_diagnostic_led_synth` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *auto_diagnostic_led_synth.py — v0.114 (BACKLOG-v6 D1).* |
| 24 | `backlog_sanitize_check` | WIRED_BY_SKILL | skill=1 test=1 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *backlog_sanitize_check.py — Organic Plugin gate: verify that a community* |
| 25 | `behavioral_evidence_per_spec_item_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *behavioral_evidence_per_spec_item_check.py — v0.100 J1* |
| 26 | `billing_log` | HELPER_BUT_DEAD_CHAIN | prog=2 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *billing_log.py — v1.0 P. Per-call billing rail.* |
| 27 | `binary_doc_low_extraction_warn` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *binary_doc_low_extraction_warn.py — gate (LL-36).* |
| 28 | `bist_window_calculator` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *bist_window_calculator.py — Size BIST response-capture windows for worst-case.* |
| 29 | `bit_count_modulo_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bit_count_modulo_check.py — M3: Verify that serial RX bit assemblers* |
| 30 | `bit_level_full_stack_tb_check` | WIRED_PRIMARY:runner_or_yaml | primary=2 prog=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *bit_level_full_stack_tb_check.py — v0.52 plugin gate* |
| 31 | `bit_level_full_stack_tb_oracle_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bit_level_full_stack_tb_oracle_check.py — v0.119.44 (Wave 12) plugin gate.* |
| 32 | `bitwidth_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bitwidth_consistency_check.py — flag Verilog bit-selects that exceed the* |
| 33 | `bram_init_file_actually_loaded_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bram_init_file_actually_loaded_check.py — Wave 16 CRITICAL gate.* |
| 34 | `bram_init_portable_compat_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bram_init_portable_compat_check.py — BACKLOG-v11 P1.2.* |
| 35 | `bram_pdob_combinational_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bram_pdob_combinational_check.py — BACKLOG-v11 P1.3 (WARNING-class).* |
| 36 | `bram_read_latency_consume_alignment_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bram_read_latency_consume_alignment_check.py — Wave 26 (v0.119.58) gate.* |
| 37 | `break_framing_vs_l3_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *break_framing_vs_l3_check.py — Verify RX command parser uses break-to-break* |
| 38 | `break_handler_safety_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *break_handler_safety_check.py — Verify that FSM break/reset handlers do NOT* |
| 39 | `bringup_plan_gen` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *bringup_plan_gen.py — emit bring-up plan from L13_LAB_CALIBRATION.* |
| 40 | `bus_turnaround_consumes_spec_constant_check` | WIRED_PRIMARY:struct_gate | primary=1 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *bus_turnaround_consumes_spec_constant_check.py — R1 deterministic gate* |
| 41 | `byte_assembler_explicit_9bit_reject_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *byte_assembler_explicit_9bit_reject_check.py — Wave 37 (v0.119.69).* |
| 42 | `cdc_async_input_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *cdc_async_input_check.py — deterministic compliance check derived from EXAMPLE_CHIP v040 debug.* |
| 43 | `cdc_crossing_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=4 | KEEP | invoked by runner / flow YAML / burn driver; *cdc_crossing_check.py -- Deterministic CDC report checker.* |
| 44 | `chip_clock_toggle_divider_when_master_already_target_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *chip_clock_toggle_divider_when_master_already_target_check.py — gate* |
| 45 | `class_convergence_eval` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *class_convergence_eval.py — v0.79 (B2) cross-IC pattern convergence.* |
| 46 | `clock_cascade_synthesis_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *clock_cascade_synthesis_check.py — refuse a top-level RTL that ties* |
| 47 | `clock_divider_period_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *clock_divider_period_check.py — BACKLOG-v11 P0.2.* |
| 48 | `clock_scale_consistency_check` | TRANSITIVELY_WIRED | skill=3 prog=1 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *clock_scale_consistency_check.py — Catch un-rescaled threshold values.* |
| 49 | `cmd_arg_range_validation_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *cmd_arg_range_validation_check.py — M4: Verify that command argument fields* |
| 50 | `cmd_argument_validation_present_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *cmd_argument_validation_present_check.py — every opcode in* |
| 51 | `cmd_buf_index_semantic_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *cmd_buf_index_semantic_consistency_check.py — Wave 37 (v0.119.69).* |
| 52 | `cmd_protocol_byte_exact_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *cmd_protocol_byte_exact_check.py — gate that catches L3_CMD_PROTOCOL.json* |
| 53 | `cmd_protocol_crc_verify` | TRANSITIVELY_WIRED | prog=1 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *cmd_protocol_crc_verify.py — Derive + verify CRC params from xlsx golden vectors.* |
| 54 | `cmd_response_conformance_check` | TRANSITIVELY_WIRED | skill=3 prog=2 test=3 doc=6 | KEEP | shared helper transitively reached from a wired program; *cmd_response_conformance_check.py — v0.50 plugin gate* |
| 55 | `cmd_response_otp_provenance_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *cmd_response_otp_provenance_check.py — for opcodes whose response* |
| 56 | `connect_vs_send_test_parity_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *connect_vs_send_test_parity_check.py — Wave 27 (v0.119.59) gate.* |
| 57 | `constants_validation` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *constants_validation.py — Deterministic compliance check for rtl-constants-gen.* |
| 58 | `corner_coverage_audit` | WIRED_BY_SKILL | skill=1 test=2 doc=3 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *corner_coverage_audit.py — Audit PVT corner coverage in IC design flows.* |
| 59 | `coverage_closure` | STANDALONE_TOOL_OR_DOC | doc=2 | KEEP | standalone CLI / generator referenced in skill docs; *coverage_closure.py — read coverage report; identify gaps.* |
| 60 | `coverage_metric_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *coverage_metric_check.py -- Deterministic coverage report metric checker.* |
| 61 | `crc_bitorder_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=2 doc=4 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_bitorder_check.py — Detect CRC bit-ordering mismatches in TX data loading.* |
| 62 | `crc_completeness_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_completeness_check.py — deterministic compliance check derived from EXAMPLE_CHIP v040 debug.* |
| 63 | `crc_compute_done_before_tx_start_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_compute_done_before_tx_start_check.py — v0.119.44 (Wave 12) plugin gate.* |
| 64 | `crc_constants_rtl_doc_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_constants_rtl_doc_consistency_check.py — gate (LL-37) cross-checks* |
| 65 | `crc_engine_isolation_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_engine_isolation_check.py — M2: Verify that shared CRC engines have* |
| 66 | `crc_oracle_vector_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_oracle_vector_check.py — BACKLOG-v11 P0.5.* |
| 67 | `crc_parameters_extracted_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_parameters_extracted_check.py — gate (LL-34) catching extractor* |
| 68 | `crc_polyform_outputreversal_pairing_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_polyform_outputreversal_pairing_check.py — Wave 25 hardening gate.* |
| 69 | `crc_q_settle_cycle_after_last_feed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_q_settle_cycle_after_last_feed_check.py — Wave 16 silent-bug gate.* |
| 70 | `crc_residual_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_residual_check.py — deterministic compliance check derived from* |
| 71 | `crc_residue_settle_state_required_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_residue_settle_state_required_check.py — Wave 26 (v0.119.58) gate.* |
| 72 | `crc_seed_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_seed_consistency_check.py — Validate that RTL CRC params match spec test vectors.* |
| 73 | `crc_validation_present` | WIRED_PRIMARY:struct_gate | primary=2 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *crc_validation_present.py — Wave 58 / BACKLOG-v12 P0.3 plugin gate.* |
| 74 | `crc_vector_gen` | STANDALONE_TOOL_OR_DOC | test=3 doc=3 | KEEP | standalone CLI / generator referenced in skill docs; *crc_vector_gen.py — General parametric CRC RTL + reference + test-vector generator.* |
| 75 | `cross_constant_invariant_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *cross_constant_invariant_check.py — Verify named timing/protocol constants* |
| 76 | `cross_module_1cycle_handshake_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *cross_module_1cycle_handshake_check.py — BACKLOG-v11 P0.3.* |
| 77 | `cts_plan` | STANDALONE_TOOL_OR_DOC | doc=2 | KEEP | standalone CLI / generator referenced in skill docs; *cts_plan.py — Phase 3 backend step (replaces skill cts-plan).* |
| 78 | `dead_timing_constant_warn` | WIRED_PRIMARY:struct_gate | primary=2 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *dead_timing_constant_warn.py — R4 cheap WARN gate* |
| 79 | `decision_log_append` | HELPER_BUT_DEAD_CHAIN | prog=2 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *decision_log_append.py — v0.79 § 3.6 Decision Trace recorder.* |
| 80 | `decision_log_extract` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *decision_log_extract.py — v0.79 § 3.6 EDA-log → decision_log.jsonl extractor.* |
| 81 | `def_stage_progression_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *def_stage_progression_check.py — Catch fabricated PnR stage DEF files.* |
| 82 | `derived_clock_sdc_required_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *derived_clock_sdc_required_check.py — Verify any register-divided clock* |
| 83 | `device_response_no_br_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *device_response_no_br_check.py — deterministic compliance check derived from* |
| 84 | `dft_insert` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *dft_insert.py — Phase 3 backend step (replaces skill dft-insert).* |
| 85 | `dispatch_fetch_loop_population_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *dispatch_fetch_loop_population_check.py — Stub multi-frame fetch loop detector.* |
| 86 | `dispatch_handler_completeness` | WIRED_PRIMARY:struct_gate | primary=2 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *dispatch_handler_completeness.py — Wave 58 / BACKLOG-v12 P0.2 plugin gate.* |
| 87 | `dispatch_register_default_reset_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *dispatch_register_default_reset_check.py — Response register reset at frame boundaries.* |
| 88 | `dispatcher_awake_gate_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *dispatcher_awake_gate_check.py — v0.114 (BACKLOG-v7 P2.2).* |
| 89 | `dispatcher_response_size_table_audit` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *dispatcher_response_size_table_audit.py — v0.114 (BACKLOG-v7 P2.1).* |
| 90 | `dispatcher_tx_arm_order_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *dispatcher_tx_arm_order_check.py — TX handshake arm-before-data race.* |
| 91 | `doc_consistency_no_unresolved_conflicts_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *doc_consistency_no_unresolved_conflicts_check.py — Wave 37 / A4* |
| 92 | `doc_extract` | TRANSITIVELY_WIRED | prog=5 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *doc_extract.py — Convert vendor docs (.doc/.docx/.pdf/.pptx/.xlsx/.txt) to* |
| 93 | `drc_fix` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *drc_fix.py — deterministic first-pass for drc-fix known patterns.* |
| 94 | `drc_rdb_summarize` | HELPER_BUT_DEAD_CHAIN | prog=1 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *drc_rdb_summarize.py — Summarize a KLayout DRC report into a structured JSON blob.* |
| 95 | `drc_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *DRC report check — wrapper for eda_report_audit --mode drc.* |
| 96 | `eco_loop_audit` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *Audit ECO (Engineering Change Order) log for completeness.* |
| 97 | `eda_log_check` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=2 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *eda_log_check.py — Deterministic EDA tool log/report checker.* |
| 98 | `eda_report_audit` | TRANSITIVELY_WIRED | prog=7 test=9 doc=2 | KEEP | shared helper transitively reached from a wired program; *eda_report_audit.py -- Multi-mode EDA report checker for backend skills.* |
| 99 | `em_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *em_check.py — Phase 3 backend step (replaces skill em-check).* |
| 100 | `em_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *EM report check — wrapper for eda_report_audit --mode em.* |
| 101 | `experience_unit_t5_capture` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *experience_unit_t5_capture.py — v0.78 § 3.4 T5 hardware-bench capture helper.* |
| 102 | `experience_unit_t6_capture` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *experience_unit_t6_capture.py — v0.78.3 § 3.4 T6 silicon-tapeout capture.* |
| 103 | `extraction_coverage_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 prog=6 test=2 doc=17 | KEEP | in _STRUCTURAL_RTL_GATES; *extraction_coverage_check.py — gate (LL-38) verifies input/docs/* |
| 104 | `extraction_coverage_denominator_audit` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *extraction_coverage_denominator_audit.py — gate (Wave 31, v0.119.63).* |
| 105 | `extraction_evidence_schema_check` | WIRED_PRIMARY:struct_gate | primary=2 prog=2 test=3 doc=11 | KEEP | in _STRUCTURAL_RTL_GATES; *extraction_evidence_schema_check.py — gate (LL-40, v0.119.39).* |
| 106 | `fault_atpg_run` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *fault_atpg_run.py — Open-source ATPG via Fault (cloudv-io/fault).* |
| 107 | `fetch_round_trip_sentinel_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fetch_round_trip_sentinel_check.py — P0.1 deterministic gate* |
| 108 | `final_report_generate` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *final_report_generate.py — v0.114 (BACKLOG-v10 P2.1).* |
| 109 | `flow_compliance_check` | WIRED_PRIMARY:runner_or_yaml | primary=3 skill=7 prog=11 test=17 doc=8 | KEEP | invoked by runner / flow YAML / burn driver; *flow_compliance_check.py — Strict 34-step Vibe-IC phase 2+3 gate.* |
| 110 | `flow_stage_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *Flow stage check — wrapper for signoff_audit --mode flow.* |
| 111 | `foundry_signoff_plan_check` | TRANSITIVELY_WIRED | prog=1 test=1 doc=1 | KEEP | shared helper transitively reached from a wired program; *foundry_signoff_plan_check.py — v0.113 (BACKLOG-v10 P1.2).* |
| 112 | `fpga_async_input_synchronizer_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_async_input_synchronizer_check.py — Verify every external input/inout* |
| 113 | `fpga_clock_divider_antipattern_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_clock_divider_antipattern_check.py — gate that catches the FPGA* |
| 114 | `fpga_on_board_attestation_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *fpga_on_board_attestation_check.py — Step 28 hardening.* |
| 115 | `fpga_pad_fanout_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_pad_fanout_check.py — Category-C structural gate that catches FPGA* |
| 116 | `fpga_pad_pullup_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_pad_pullup_consistency_check.py — cross-check L5 pad pull-up* |
| 117 | `fpga_port_qsf_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_port_qsf_consistency_check.py — LL-10.* |
| 118 | `fpga_program_chain_attest_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *fpga_program_chain_attest_check.py — Audit the FPGA compile→program→test chain.* |
| 119 | `fpga_pullup_lint` | TRANSITIVELY_WIRED | skill=1 prog=1 test=1 doc=1 | KEEP | shared helper transitively reached from a wired program; *fpga_pullup_lint.py — Flag tristate inout ports without weak pull-up assignment.* |
| 120 | `fpga_qsf_lint` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *Deterministic QSF lint: validate Quartus project files.* |
| 121 | `fpga_sdc_clock_constraint_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_sdc_clock_constraint_check.py — Wave 24 / v0.119.56.* |
| 122 | `fpga_search_path_includes_required_dirs_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_search_path_includes_required_dirs_check.py — Wave 16 silent-bug gate.* |
| 123 | `fpga_sta_negative_slack_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_sta_negative_slack_check.py — Wave 24 / v0.119.56.* |
| 124 | `fpga_test_harness_gen` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *fpga_test_harness_gen.py — emit FPGA test harness wrapper.* |
| 125 | `fpga_top_pin_completeness_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_top_pin_completeness_check.py — gate that catches an FPGA top module* |
| 126 | `fpga_verification_audit` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *fpga_verification_audit.py — v0.53 plugin gate* |
| 127 | `fpga_wrapper_input_polluter_check` | WIRED_PRIMARY:struct_gate | primary=2 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fpga_wrapper_input_polluter_check.py — flag FPGA wrappers that AND/OR* |
| 128 | `frame_end_detection_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *frame_end_detection_check.py — BACKLOG-v11 P0.4.* |
| 129 | `frame_end_gap_in_l8_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *frame_end_gap_in_l8_check.py — LL-2.* |
| 130 | `fresh_agent_provenance_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *fresh_agent_provenance_check.py — honesty check for "fresh-agent" claims.* |
| 131 | `fresh_agent_rtl_bug_density_metric` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *fresh_agent_rtl_bug_density_metric.py — BACKLOG-v11 P2.3 + v10 P2.4.* |
| 132 | `frontend_backend_handoff_check` | WIRED_BY_SKILL | skill=1 test=1 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *frontend_backend_handoff_check.py — Verify all frontend deliverables are* |
| 133 | `frs_timing_range_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *frs_timing_range_check.py — gate that catches L2 timing fields stored as* |
| 134 | `fsm_error_invariant` | WIRED_PRIMARY:struct_gate | primary=2 test=3 doc=6 | KEEP | in _STRUCTURAL_RTL_GATES; *fsm_error_invariant.py — Detect FSMs where an error signal can break upper-layer* |
| 135 | `fsm_state_coverage_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *fsm_state_coverage_check.py — v0.119.45 (Wave 13) gate.* |
| 136 | `function_void_with_output_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *function_void_with_output_check.py — Wave 29 (v0.119.61) gate.* |
| 137 | `functional_state_transition_coverage_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *functional_state_transition_coverage_check.py — Verify TBs exercise the* |
| 138 | `gap_reset_granularity_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *gap_reset_granularity_check.py — deterministic compliance check derived from* |
| 139 | `gate_evidence_completeness_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *gate_evidence_completeness_check.py — v0.100 L1* |
| 140 | `gate_utils` | TRANSITIVELY_WIRED | prog=24 test=1 doc=1 | KEEP | shared helper transitively reached from a wired program; *gate_utils.py — Shared helpers for v0.117+ structural-RTL gates.* |
| 141 | `gds_size_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *gds_size_check.py — Deterministic GDS file existence and size checker.* |
| 142 | `half_duplex_frame_end_idle_reset_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *half_duplex_frame_end_idle_reset_check.py — structural-RTL gate for* |
| 143 | `half_duplex_response_window_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *half_duplex_response_window_check.py — LL-4.* |
| 144 | `half_duplex_wrapper_open_drain_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=2 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *half_duplex_wrapper_open_drain_check.py — structural-RTL gate that* |
| 145 | `handshake_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *handshake_check.py — deterministic compliance check derived from EXAMPLE_CHIP v040 debug.* |
| 146 | `hardware_pass_attestation_check` | TRANSITIVELY_WIRED | skill=3 prog=1 test=2 doc=3 | KEEP | shared helper transitively reached from a wired program; *hardware_pass_attestation_check.py — v0.50 plugin gate (third layer)* |
| 147 | `hold_fix` | HELPER_BUT_DEAD_CHAIN | prog=1 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *hold_fix.py — deterministic first-pass for hold-fix known patterns.* |
| 148 | `host_soft_reset_unwake_path_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *host_soft_reset_unwake_path_check.py — Verify that any soft-reset / abort* |
| 149 | `hw_acceptance_test_passed_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *hw_acceptance_test_passed_check.py — final-step gate for the closed* |
| 150 | `hw_vs_rtl_verdict_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *hw_vs_rtl_verdict_check.py — Require N byte-identical FAILs before blaming hardware.* |
| 151 | `ic_class_consistency_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *ic_class_consistency_check.py — gate (Wave 42, v0.119.70 / SF6).* |
| 152 | `ic_class_profile` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=2 prog=19 test=11 doc=14 | KEEP | invoked by runner / flow YAML / burn driver; *ic_class_profile.py — IC class detection helper (Wave 36, v0.119.68).* |
| 153 | `input_docs_coverage_check` | TRANSITIVELY_WIRED | prog=1 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *input_docs_coverage_check.py — v0.50 plugin gate* |
| 154 | `integration_spec_audit` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *integration_spec_audit.py — Deterministic compliance check for integration-spec-gen.* |
| 155 | `interface_encoding_audit` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=2 doc=4 | KEEP | in _STRUCTURAL_RTL_GATES; *interface_encoding_audit.py — Detect gray-code vs binary encoding mismatches* |
| 156 | `internal_vs_external_timing_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=3 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *internal_vs_external_timing_check.py — L8 must separate host-side from DUT-side timing.* |
| 157 | `ir_drop_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *IR-drop report check — wrapper for eda_report_audit --mode ir_drop.* |
| 158 | `ir_drop_triage` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *ir_drop_triage.py — deterministic first-pass for ir-drop-triage known patterns.* |
| 159 | `json_schema_check` | WIRED_BY_SKILL | skill=3 test=2 doc=2 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *json_schema_check.py — Deterministic JSON schema key checker.* |
| 160 | `k3_class_miner` | HELPER_BUT_DEAD_CHAIN | skill=2 prog=2 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *k3_class_miner.py — v0.78.4 § 3.1 K3 class-stub miner from open-source IC repos.* |
| 161 | `k3_patch_proposer` | HELPER_BUT_DEAD_CHAIN | prog=7 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *k3_patch_proposer.py — v0.78 § 3.1 IC-Expert K3 patch proposer (MVP).* |
| 162 | `k3_view_resolve` | HELPER_BUT_DEAD_CHAIN | skill=1 prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *k3_view_resolve.py — v0.85 D6 unified K3 view across core + installed plugins.* |
| 163 | `klayout_deck_mode_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *klayout_deck_mode_check.py — BACKLOG-v10 P0.1 enforcement loop.* |
| 164 | `l10_tb_conformance_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *l10_tb_conformance_check.py — v0.53 plugin gate* |
| 165 | `l10_test_cases_cover_l3_constraints_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l10_test_cases_cover_l3_constraints_check.py — Wave 39 / D1* |
| 166 | `l11_otp_lock_dependencies_typed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l11_otp_lock_dependencies_typed_check.py — Wave 38 / B5* |
| 167 | `l11_sequence_covers_l6_reject_rules_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l11_sequence_covers_l6_reject_rules_check.py — Wave 39 / D2* |
| 168 | `l12_behavioral_sequences_steps_typed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l12_behavioral_sequences_steps_typed_check.py — Wave 38 / B6* |
| 169 | `l12_sequence_implementation_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l12_sequence_implementation_check.py — Enforce that each declared L12* |
| 170 | `l12_tb_coverage_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=10 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *l12_tb_coverage_check.py — v0.52 plugin gate* |
| 171 | `l1_electrical_specs_typed_depth_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l1_electrical_specs_typed_depth_check.py — Wave 38 / B1* |
| 172 | `l1_pin_table_aliases_typed_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l1_pin_table_aliases_typed_check.py — Wave 38 / B2* |
| 173 | `l2_timing_completeness_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l2_timing_completeness_check.py — gate (LL-32) catching frs-gen* |
| 174 | `l3_opcode_argument_constraints_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l3_opcode_argument_constraints_check.py — Wave 37 / A3* |
| 175 | `l3_opcode_pre_wake_allowed_typed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l3_opcode_pre_wake_allowed_typed_check.py — Wave 37 (v0.119.69).* |
| 176 | `l3_opcode_response_template_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l3_opcode_response_template_check.py — Wave 37 / A2* |
| 177 | `l4_regmap_enumerated_values_typed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l4_regmap_enumerated_values_typed_check.py — Wave 38 / B3* |
| 178 | `l6_reject_rules_from_rx_event_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *l6_reject_rules_from_rx_event_check.py — Wave 37 (v0.119.69).* |
| 179 | `l8_clock_domains_typed_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l8_clock_domains_typed_check.py — Wave 38 / B4* |
| 180 | `l8_frame_end_gap_derivation_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *l8_frame_end_gap_derivation_check.py — LL-3.* |
| 181 | `l9_completeness_check` | STANDALONE_TOOL_OR_DOC | test=2 doc=3 | KEEP | standalone CLI / generator referenced in skill docs; *l9_completeness_check.py — Deterministic L9 Integration Spec completeness checker.* |
| 182 | `l9_response_delay_schema_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l9_response_delay_schema_check.py — R5 L9 spec mandate* |
| 183 | `l9_rtl_pin_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l9_rtl_pin_consistency_check.py — Wave 79 cross-layer integrity gate.* |
| 184 | `l_doc_aggregated_blob_size_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l_doc_aggregated_blob_size_check.py — gate (Wave 31, v0.119.63).* |
| 185 | `l_doc_structured_field_count_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 prog=1 test=3 doc=6 | KEEP | in _STRUCTURAL_RTL_GATES; *l_doc_structured_field_count_check.py — gate (Wave 31/32, v0.119.64).* |
| 186 | `l_doc_unique_content_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *l_doc_unique_content_check.py — gate (Wave 31, v0.119.63).* |
| 187 | `layer_extension_presence_check` | HELPER_BUT_DEAD_CHAIN | skill=3 prog=1 test=2 doc=2 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *layer_extension_presence_check.py — v0.50 plugin gate* |
| 188 | `lef_psm_patch` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *lef_psm_patch.py — Phase 3 backend step (replaces skill lef-psm-patch).* |
| 189 | `lvs_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *LVS report check — wrapper for eda_report_audit --mode lvs.* |
| 190 | `lvs_triage` | WIRED_BY_SKILL | skill=1 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *lvs_triage.py — deterministic first-pass for lvs-triage known patterns.* |
| 191 | `manifest_leak_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *manifest_leak_check.py — Detect benchmark-value leaks in fact manifests.* |
| 192 | `marketplace_version_sync_check` | ORPHAN | none | REVIEW | no callers anywhere; verify if it is a manual CLI tool; *marketplace_version_sync_check.py* |
| 193 | `mask_application_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *mask_application_check.py — Verify any AND-mask rule the spec declares* |
| 194 | `mcp_execution_verify` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *mcp_execution_verify.py — Deterministic MCP tool execution verifier.* |
| 195 | `mcp_tool_registry` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *mcp_tool_registry.py — v1.0 O. mcp-eda-server hand-off for installed* |
| 196 | `example_tester_bfm_gen` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *example_tester_bfm_gen.py — LL-13 generator.* |
| 197 | `memory_gc` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *memory_gc.py — v0.55 advisory tool for Claude Code memory directories* |
| 198 | `memory_read_pipeline_check` | WIRED_PRIMARY:struct_gate | primary=3 prog=1 test=3 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *memory_read_pipeline_check.py — Registered-read memory modules must* |
| 199 | `metal_fill_density_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *Verify metal fill was inserted and density is within bounds.* |
| 200 | `mixed_signal_cosim_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *mixed_signal_cosim_check.py — deterministic gate for mixed-signal co-simulation* |
| 201 | `module_port_audit` | STANDALONE_TOOL_OR_DOC | test=2 doc=3 | KEEP | standalone CLI / generator referenced in skill docs; *module_port_audit.py — Deterministic port-name mismatch detector for multi-module* |
| 202 | `nba_addr_read_race_check` | WIRED_PRIMARY:struct_gate | primary=2 prog=2 test=3 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *nba_addr_read_race_check.py — FSM consuming addressed data without pipelining.* |
| 203 | `nba_shift_register_same_cycle_read_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *nba_shift_register_same_cycle_read_check.py — v0.119.44 (Wave 12) plugin gate.* |
| 204 | `no_protocol_consistency_check` | HELPER_BUT_DEAD_CHAIN | skill=3 prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *no_protocol_consistency_check.py — v0.56 plugin gate* |
| 205 | `oe_pattern_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *oe_pattern_check.py — Analyze output-enable (OE) patterns for tristate bus drivers.* |
| 206 | `opcode_dispatch_completeness_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *opcode_dispatch_completeness_check.py — v0.119.45 (Wave 13) gate.* |
| 207 | `open_rcx_fallback` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *open_rcx_fallback.py — Phase 3 backend step (replaces skill open-rcx-fallback).* |
| 208 | `openroad_drc_report_normalize` | HELPER_BUT_DEAD_CHAIN | prog=1 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *openroad_drc_report_normalize.py — Normalize OpenROAD detailed_route's DRC* |
| 209 | `openroad_tcl_deprecation_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *openroad_tcl_deprecation_check.py — Recursively scan a plugin tree for* |
| 210 | `oracle_dump_required_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *oracle_dump_required_check.py — Category-B workflow gate.* |
| 211 | `oracle_vector_gen` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *oracle_vector_gen.py — v0.114 (BACKLOG-v6 C1 closure).* |
| 212 | `otp_field_map_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *otp_field_map_check.py — gate that catches L11_OTP_CONTENT.json missing a* |
| 213 | `otp_image_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=2 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *otp_image_check.py — Validate an OTP/NVM .ver image against an L4 register map.* |
| 214 | `otp_image_layer_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *otp_image_layer_consistency_check.py — P1.3 deterministic gate* |
| 215 | `otp_image_nonzero_check` | WIRED_PRIMARY:struct_gate | primary=3 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *otp_image_nonzero_check.py* |
| 216 | `otp_module_uses_supported_pattern_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *otp_module_uses_supported_pattern_check.py — Wave 21 (v0.119.53).* |
| 217 | `otp_write_lock_gate_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *otp_write_lock_gate_check.py — Static heuristic audit for OTP / fuse / NVM* |
| 218 | `output_artifact_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *output_artifact_check.py — Deterministic output artifact existence checker.* |
| 219 | `packet_length_check_present` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *packet_length_check_present.py — Static audit for packet-length sanity* |
| 220 | `pad_drive_high_active_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *pad_drive_high_active_check.py — v0.114 (BACKLOG-v6 P1).* |
| 221 | `pattern_effectiveness_eval` | HELPER_BUT_DEAD_CHAIN | prog=4 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *pattern_effectiveness_eval.py — v0.78.1 § 3.7 K3 pattern effectiveness validator.* |
| 222 | `payload_bit_position_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *payload_bit_position_check.py — Cross-reference spec doc bit-layout* |
| 223 | `pdk_analog_completeness_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *pdk_analog_completeness_check.py* |
| 224 | `pdk_consistency_check` | TRANSITIVELY_WIRED | prog=1 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *pdk_consistency_check.py — Deterministic PDK-netlist consistency checker.* |
| 225 | `per_opcode_response_latency_table_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *per_opcode_response_latency_table_check.py — gate (LL-33) catching* |
| 226 | `perc_check` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *perc_check.py — Phase 3 backend step (replaces skill perc-check).* |
| 227 | `periodic_signal_required_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *periodic_signal_required_check.py — Verify that for every protocol-mandated* |
| 228 | `periodic_timer_vs_rx_activity_check` | WIRED_PRIMARY:struct_gate | primary=2 prog=1 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *periodic_timer_vs_rx_activity_check.py — Periodic TX-triggering timer* |
| 229 | `phase1_consistency_check` | HELPER_BUT_DEAD_CHAIN | skill=2 prog=2 test=4 doc=3 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *phase1_consistency_check.py — Cross-layer consistency gate (K4).* |
| 230 | `phase1_doc_presence_check` | HELPER_BUT_DEAD_CHAIN | skill=4 prog=1 test=3 doc=10 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *phase1_doc_presence_check.py — Fail if fewer than 10 Phase-1 layer docs exist.* |
| 231 | `phase1_k5_quality_check` | WIRED_BY_SKILL | skill=1 test=3 doc=4 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *phase1_k5_quality_check.py — catch the 6 K5 issues found by real Phase-2 synth.* |
| 232 | `phase1_one_shot_runner` | WIRED_BY_SKILL | skill=2 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *phase1_one_shot_runner.py — Phase 1 (Path A: prompt → L1-L13 JSON + human MD).* |
| 233 | `phase1_quality_parity_check` | WIRED_BY_SKILL | skill=6 test=2 doc=2 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *phase1_quality_parity_check.py — v0.50 gate* |
| 234 | `phase23_completion_self_audit_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *phase23_completion_self_audit_check.py — v0.109 mandatory self-audit gate.* |
| 235 | `phase23_one_shot_runner` | WIRED_PRIMARY:runner_or_yaml | primary=3 skill=2 prog=2 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *phase23_one_shot_runner.py — Phase 2 + Phase 3 chain.* |
| 236 | `phase2_one_shot_runner` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=3 | KEEP | invoked by runner / flow YAML / burn driver; *phase2_one_shot_runner.py — thin chain of Phase 2a + Phase 2b.* |
| 237 | `phase2a_all_l_docs_present_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=4 | KEEP | in _STRUCTURAL_RTL_GATES; *phase2a_all_l_docs_present_check.py — gate (Wave 23, v0.119.55).* |
| 238 | `phase2a_coverage_report_gen` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=4 test=5 doc=9 | KEEP | invoked by runner / flow YAML / burn driver; *phase2a_coverage_report_gen.py — Phase 2a extraction-coverage REPORT.* |
| 239 | `phase2a_coverage_report_present_check` | WIRED_PRIMARY:struct_gate | primary=2 prog=1 test=3 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *phase2a_coverage_report_present_check.py — gate (BACKLOG-v13 Wave 5).* |
| 240 | `phase2a_doc_content_implementation_completeness_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *phase2a_doc_content_implementation_completeness_check.py — Wave 47* |
| 241 | `phase2a_gate_contract_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *phase2a_gate_contract_check.py — Meta-checker for Phase-2a deterministic gates.* |
| 242 | `phase2a_no_waivers_used_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=7 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *phase2a_no_waivers_used_check.py — gate (Wave 23, v0.119.55).* |
| 243 | `phase2a_one_shot_runner` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=3 test=1 doc=4 | KEEP | invoked by runner / flow YAML / burn driver; *phase2a_one_shot_runner.py — chip-AGNOSTIC Phase 2a orchestrator.* |
| 244 | `phase2b_one_shot_runner` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *phase2b_one_shot_runner.py — Phase 2b main impl (L1-L13 → RTL → SOF → EXAMPLE_TESTER).* |
| 245 | `phase3_one_shot_runner` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=4 prog=11 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *phase3_one_shot_runner.py — single-call orchestrator for Phase 3 (synth → GDS).* |
| 246 | `phy_counter_audit` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *phy_counter_audit.py — Detect bus-state-sampling anti-pattern in TX PHY counters.* |
| 247 | `placement_optimize` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *placement_optimize.py — Phase 3 backend step (replaces skill placement-optimize).* |
| 248 | `plugin_crypto` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *plugin_crypto.py — v0.95 AES-256-GCM helpers for encrypted IP artifacts.* |
| 249 | `plugin_manifest` | HELPER_BUT_DEAD_CHAIN | prog=2 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *plugin_manifest.py — v0.85 D1+D2 plugin.yaml schema validator.* |
| 250 | `plugin_registry_client` | HELPER_BUT_DEAD_CHAIN | prog=3 test=9 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *plugin_registry_client.py — v0.90 HTTP client for the vibe-ic registry.* |
| 251 | `plugin_self_leak_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *plugin_self_leak_check.py — Plugin self-audit for embedded production RTL.* |
| 252 | `plugin_sign` | HELPER_BUT_DEAD_CHAIN | prog=1 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *plugin_sign.py — v0.85 D5 ed25519 detached signatures for plugin bundles.* |
| 253 | `post_layout_sim_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *Verify post-layout gate-level simulation with SDF back-annotation.* |
| 254 | `power_analysis` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *power_analysis.py — Phase 3 backend step (replaces skill power-analysis).* |
| 255 | `power_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *Power report check — wrapper for eda_report_audit --mode power.* |
| 256 | `ppa_predict` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *ppa_predict.py — deterministic first-pass for ppa-predict known patterns.* |
| 257 | `practical_notes_proposer` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *practical_notes_proposer.py — v0.78 § 3.5 PRACTICAL_NOTES draft generator.* |
| 258 | `practical_notes_specificity_check` | HELPER_BUT_DEAD_CHAIN | prog=2 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *practical_notes_specificity_check.py — meta-gate for plugin docs.* |
| 259 | `pre_awake_silence_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *pre_awake_silence_check.py — M1: Verify that any protocol with a wake/sleep* |
| 260 | `project_outputs_in_tree_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *project_outputs_in_tree_check.py* |
| 261 | `protocol_delimiter_consistency_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *protocol_delimiter_consistency_check.py — Verify the RTL FSM that validates* |
| 262 | `protocol_fsm_topology_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *protocol_fsm_topology_check.py — BACKLOG-v11 P0.1.* |
| 263 | `protocol_gap_check` | WIRED_PRIMARY:struct_gate | primary=1 test=3 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *protocol_gap_check.py — Generate inter-unit gap assertions for any serial protocol.* |
| 264 | `protocol_ip_simulation_required_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *protocol_ip_simulation_required_check.py — BACKLOG-v11 P2.1.* |
| 265 | `protocol_reference_tb_pass_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *protocol_reference_tb_pass_check.py — Wave 28/29 (v0.119.60+) gate.* |
| 266 | `provenance_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *provenance_check.py — Verify a file was produced by a logged tool run.* |
| 267 | `provenance_hash_audit` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *provenance_hash_audit.py — v0.114 (BACKLOG-v10 P2.3).* |
| 268 | `provenance_logger` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=2 test=3 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *provenance_logger.py — Wrap a tool invocation, record hashed provenance.* |
| 269 | `pulse_decoder_edge_check` | WIRED_PRIMARY:struct_gate | primary=2 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *pulse_decoder_edge_check.py — Enforce rising-edge-driven classification in* |
| 270 | `qsf_gen` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=1 prog=2 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *qsf_gen.py — auto-generate Quartus QSF (FPGA pin assignments).* |
| 271 | `qsf_open_drain_assignment_check` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *qsf_open_drain_assignment_check.py — DEPRECATED in v0.119.29.* |
| 272 | `quartus_map_audit` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=2 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *quartus_map_audit.py — Scan Quartus .map.rpt for silent-failure indicators.* |
| 273 | `reference_parity_eval` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *reference_parity_eval.py — v0.78.5 § 3.1 fidelity-to-silicon scoring.* |
| 274 | `regmap_bit_layout_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *regmap_bit_layout_check.py — gate that catches L4_REGMAP.json registers* |
| 275 | `release_audit` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *release_audit.py — v0.55 plugin invariant gate* |
| 276 | `reset_dependency_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *reset_dependency_check.py — deterministic compliance check derived from EXAMPLE_CHIP v040 debug.* |
| 277 | `response_latency_observability_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *response_latency_observability_check.py — LL-5.* |
| 278 | `response_payload_template_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *response_payload_template_check.py — M5: Verify that response payload bytes* |
| 279 | `result_md_audit_provenance_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *result_md_audit_provenance_check.py — Wave 33 (v0.119.65).* |
| 280 | `rig_firmware_capability_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rig_firmware_capability_check.py — Wave 58 / BACKLOG-v12 P0.5 plugin gate.* |
| 281 | `rig_topology_disclosure_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rig_topology_disclosure_check.py — verify hardware rig topology is declared.* |
| 282 | `rig_topology_image_extracted_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rig_topology_image_extracted_check.py — gate (LL-35).* |
| 283 | `rom_init_lint` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=2 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *rom_init_lint.py — Detect Quartus-unsafe ROM initialization patterns.* |
| 284 | `rsp_example_otp_consistency_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=3 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *rsp_example_otp_consistency_check.py — L3 response examples must match L11 OTP content.* |
| 285 | `rtl_bug_report_schema_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *rtl_bug_report_schema_check.py — v0.54 plugin gate* |
| 286 | `rtl_hygiene_lint` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=4 test=3 doc=8 | KEEP | invoked by runner / flow YAML / burn driver; *rtl_hygiene_lint.py — General-purpose RTL hygiene checker.* |
| 287 | `rtl_precheck_gate` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *rtl_precheck_gate.py — aggregate every RTL static auditor into a* |
| 288 | `rtl_response_byte_oracle_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *rtl_response_byte_oracle_check.py — P0.2 deterministic gate* |
| 289 | `rtl_unit_test_coverage_check` | TRANSITIVELY_WIRED | prog=1 test=2 doc=3 | KEEP | shared helper transitively reached from a wired program; *rtl_unit_test_coverage_check.py — v0.50.2 plugin gate* |
| 290 | `rx_byte_assembler_ibt_flush_recovery_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_byte_assembler_ibt_flush_recovery_check.py — Wave 15 silent-bug gate.* |
| 291 | `rx_byte_valid_requires_ibt_gate_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_byte_valid_requires_ibt_gate_check.py — Wave 26 (v0.119.58) gate.* |
| 292 | `rx_classifier_no_threshold_gap_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_classifier_no_threshold_gap_check.py — Wave 26 (v0.119.58) gate.* |
| 293 | `rx_classifier_thresholds_match_l8_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_classifier_thresholds_match_l8_check.py — Wave 14 (v0.119.47) gate.* |
| 294 | `rx_deglitch_filter_required_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_deglitch_filter_required_check.py — Wave 22 silent-bug gate.* |
| 295 | `rx_ibt_frame_end_semantics_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_ibt_frame_end_semantics_check.py — Wave 15 silent-bug gate.* |
| 296 | `rx_last_bit_frame_end_commit_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *rx_last_bit_frame_end_commit_check.py — Wave 29 (v0.119.61) gate.* |
| 297 | `rx_tolerance_sweep` | WIRED_TEST_ONLY | test=3 doc=3 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *rx_tolerance_sweep.py — General RX boundary-width tolerance sweep.* |
| 298 | `scope_long_decode` | WIRED_TEST_ONLY | test=1 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *scope_long_decode.py — LL-9 (debug helper, not a structural gate).* |
| 299 | `scope_periodic_pulse_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=2 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *scope_periodic_pulse_check.py — Layer-3 hardware attestation gate.* |
| 300 | `scope_reply_preamble_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *scope_reply_preamble_check.py — Wave 58 / BACKLOG-v12 P0.4 plugin gate.* |
| 301 | `scope_response_byte_decode_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *scope_response_byte_decode_check.py — P0.3 deterministic gate* |
| 302 | `scoreboard_to_csv` | HELPER_BUT_DEAD_CHAIN | prog=3 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *scoreboard_to_csv.py — v0.78.1 per-IC scoreboard extraction.* |
| 303 | `sdc_gen` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=2 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *sdc_gen.py — auto-generate Synopsys Design Constraints (SDC).* |
| 304 | `sdc_syntax_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *sdc_syntax_check.py — Deterministic compliance check for constraint-gen.* |
| 305 | `sdc_validator_check` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *sdc_validator_check.py — validate SDC against L8 timing constraints.* |
| 306 | `self_rx_mask_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *self_rx_mask_check.py — Verify any *_oe / *_drive_low output that drives a* |
| 307 | `self_rx_mask_required_check` | WIRED_PRIMARY:struct_gate | primary=2 skill=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *self_rx_mask_required_check.py — Wave 16 silent-bug gate.* |
| 308 | `send_test_active_drive_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *send_test_active_drive_check.py — Wave 27 (v0.119.59) gate.* |
| 309 | `si_crosstalk_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *Verify signal integrity / crosstalk analysis was performed.* |
| 310 | `signoff_audit` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=2 test=6 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *signoff_audit.py -- Multi-mode signoff evidence checker (LEGACY gate).* |
| 311 | `single_bus_driver_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *single_bus_driver_check.py — structural-RTL gate that catches the* |
| 312 | `skill_compliance_triangle_check` | HELPER_BUT_DEAD_CHAIN | prog=1 test=2 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *skill_compliance_triangle_check.py — v0.55 plugin invariant gate* |
| 313 | `slave_tx_no_device_break_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=2 test=2 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *slave_tx_no_device_break_check.py — Wave 25/34 silent-bug gate.* |
| 314 | `spec_response_delay_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=3 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *spec_response_delay_check.py — Response path must honour spec-declared* |
| 315 | `spef_extraction_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *Verify parasitic extraction (SPEF) was produced after routing.* |
| 316 | `spice_correlation_check` | WIRED_PRIMARY:struct_gate | primary=2 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *spice_correlation_check.py — deterministic gate for post-layout SPICE verification* |
| 317 | `sta_report_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *STA report check — wrapper for eda_report_audit --mode sta.* |
| 318 | `sta_review` | WIRED_BY_SKILL | skill=1 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *sta_review.py — deterministic first-pass for sta-review known patterns.* |
| 319 | `stage1_compliance` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *Stage 1 (RTL + Verification) interim gate.* |
| 320 | `stage2_compliance` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *Stage 2 (Synthesis + DFT) interim gate.* |
| 321 | `stage3_compliance` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *Stage 3 (Physical Design + Sign-off) interim gate.* |
| 322 | `stage4_compliance` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=1 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *Stage 4 (Output + Validation) interim gate.* |
| 323 | `sustained_vs_edge_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *sustained_vs_edge_check.py — Flag RTL using edge-detect when spec calls for sustained.* |
| 324 | `sv_compat_check` | TRANSITIVELY_WIRED | skill=1 prog=1 test=2 doc=2 | KEEP | shared helper transitively reached from a wired program; *sv_compat_check.py — Check if Verilog files require the -sv flag for Yosys synthesis.* |
| 325 | `synth_doctor` | WIRED_BY_SKILL | skill=3 doc=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *synth_doctor.py — deterministic first-pass for synth-doctor known patterns.* |
| 326 | `synth_netlist_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 skill=2 test=2 doc=3 | KEEP | invoked by runner / flow YAML / burn driver; *synth_netlist_check.py — Deterministic synthesis netlist validation checker.* |
| 327 | `synth_wrapper_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *synth_wrapper_check.py — Deterministic compliance check for synth-wrapper-gen.* |
| 328 | `synth_wrapper_gen` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *synth_wrapper_gen.py — auto-generate synthesis wrapper for inout-port designs.* |
| 329 | `tapeout_signoff_check` | WIRED_PRIMARY:runner_or_yaml | primary=2 skill=1 prog=1 test=4 doc=4 | KEEP | invoked by runner / flow YAML / burn driver; *Tapeout signoff check — wrapper for signoff_audit --mode tapeout.* |
| 330 | `tb_timing_extremes_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *tb_timing_extremes_check.py — LL-6.* |
| 331 | `testbench_exists_check` | STANDALONE_TOOL_OR_DOC | test=2 doc=2 | KEEP | standalone CLI / generator referenced in skill docs; *testbench_exists_check.py — Deterministic testbench existence and coverage checker.* |
| 332 | `testbench_gen` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *testbench_gen.py — emit unit + integration testbench from L10 test_cases.* |
| 333 | `tester_oracle_health_check` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *tester_oracle_health_check.py — Prove the tester works before iterating RTL.* |
| 334 | `tester_verdict_frame_decode` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *tester_verdict_frame_decode.py — T1 composability fix* |
| 335 | `threshold_range_contiguity_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=3 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *threshold_range_contiguity_check.py — Discrete classification ranges must be contiguous.* |
| 336 | `timer_freeze_after_state_check` | WIRED_PRIMARY:struct_gate | primary=1 skill=1 prog=2 test=3 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *timer_freeze_after_state_check.py — Static heuristic for the* |
| 337 | `toggle_divider_hierarchical_clock_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *toggle_divider_hierarchical_clock_check.py — gate (LL-31) extending* |
| 338 | `trailing_delimiter_completeness_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *trailing_delimiter_completeness_check.py — Verify each cmd packet stimulus* |
| 339 | `transient_signal_latch_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *transient_signal_latch_check.py — Flag 1-cycle pulses read by multi-cycle FSMs without latching.* |
| 340 | `tristate_active_drive_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *tristate_active_drive_check.py — P1.1 deterministic gate* |
| 341 | `tristate_bus_check` | WIRED_PRIMARY:struct_gate | primary=1 test=4 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *tristate_bus_check.py — Generate general tristate / open-drain bus assertions.* |
| 342 | `tristate_pullup_assertion_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *tristate_pullup_assertion_check.py — BACKLOG-v11 P1.1.* |
| 343 | `tristate_self_rx_mask_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *tristate_self_rx_mask_check.py — Self-RX masking audit for tristate/open-drain* |
| 344 | `trust_tier_recompute` | HELPER_BUT_DEAD_CHAIN | prog=3 test=3 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *trust_tier_recompute.py — v0.90 L. Nightly trust-tier recompute job.* |
| 345 | `tx_abort_during_transmission_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *tx_abort_during_transmission_check.py — Verify TX modules do not abort/reset* |
| 346 | `tx_bit_timing_units_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *tx_bit_timing_units_check.py — verify TX bit-cell constants in* |
| 347 | `tx_bit_width_min_resolution_check` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *tx_bit_width_min_resolution_check.py — advisory gate that flags when the* |
| 348 | `tx_phy_bit_cell_total_consumed_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *tx_phy_bit_cell_total_consumed_check.py — Wave 15 silent-bug gate* |
| 349 | `tx_timing_use_max_of_range_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=3 | KEEP | in _STRUCTURAL_RTL_GATES; *tx_timing_use_max_of_range_check.py — structural-RTL gate that catches* |
| 350 | `upf_author` | STANDALONE_TOOL_OR_DOC | doc=1 | KEEP | standalone CLI / generator referenced in skill docs; *upf_author.py — Phase 3 backend step (replaces skill upf-author).* |
| 351 | `upf_syntax_check` | WIRED_TEST_ONLY | test=2 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *upf_syntax_check.py -- Deterministic UPF file syntax checker.* |
| 352 | `vendor_fpga_reference_table_extraction_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *vendor_fpga_reference_table_extraction_check.py — gate (LL-29) that* |
| 353 | `verilator_coverage_measure` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *verilator_coverage_measure.py — v0.53 plugin gate* |
| 354 | `vibe_ic_one_shot_runner` | WIRED_BY_SKILL | skill=1 | KEEP | invoked by skill SKILL.md (skill-driven invocation); *vibe_ic_one_shot_runner.py — full Vibe-IC flow orchestrator.* |
| 355 | `vibe_ic_plugin` | HELPER_BUT_DEAD_CHAIN | prog=7 test=20 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *vibe_ic_plugin.py — v0.85 D3 plugin CLI (local-only, no remote registry).* |
| 356 | `vibeic_mcp_adapter` | WIRED_TEST_ONLY | test=2 doc=1 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *vibeic_mcp_adapter.py — v0.98 X: out-of-repo bridge for mcp-eda-server.* |
| 357 | `vibeic_registry_server` | HELPER_BUT_DEAD_CHAIN | prog=2 test=10 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *vibeic_registry_server.py — v0.90 reference server (deployable to vibeic.ai).* |
| 358 | `waiver_growth_check` | HELPER_BUT_DEAD_CHAIN | prog=1 test=1 doc=1 | REVIEW | helper for a chain whose entry point is itself unwired (V078 proposer / marketplace registry CLI); *waiver_growth_check.py — v0.112 release-gate (BACKLOG-v10 P0 follow-up).* |
| 359 | `waiver_legitimacy_check` | WIRED_TEST_ONLY | test=1 doc=2 | WIRE_IN | tests exist but production chain does not invoke; consider adding to _STRUCTURAL_RTL_GATES or skill SKILL.md; *waiver_legitimacy_check.py — v0.116 (BACKLOG-v11 candidate).* |
| 360 | `waiver_staleness_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *waiver_staleness_check.py — BACKLOG-v10 P1.3.* |
| 361 | `waivers_schema_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=2 test=3 doc=2 | KEEP | invoked by runner / flow YAML / burn driver; *waivers_schema_check.py — Validate <project>/waivers.json for the 33-step flow.* |
| 362 | `wake_gen_bus_active_reset_check` | WIRED_PRIMARY:struct_gate | primary=1 prog=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *wake_gen_bus_active_reset_check.py — Wave 15 silent-bug gate.* |
| 363 | `wake_gen_silence_gate` | WIRED_PRIMARY:struct_gate | primary=1 test=2 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *wake_gen_silence_gate.py — Wave 58 / BACKLOG-v12 P0.1 plugin gate.* |
| 364 | `wake_pulse_emit_gated_by_first_rx_command_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *wake_pulse_emit_gated_by_first_rx_command_check.py — Wave 18 gate.* |
| 365 | `wake_pulse_implementation_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=1 | KEEP | in _STRUCTURAL_RTL_GATES; *wake_pulse_implementation_check.py — LL-11 / Wake-pulse value gate.* |
| 366 | `wake_pulse_width_matches_measurement_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *wake_pulse_width_matches_measurement_check.py — Wave 18 silent-bug gate.* |
| 367 | `warn_acceptance_policy_check` | WIRED_PRIMARY:struct_gate | primary=1 test=1 doc=2 | KEEP | in _STRUCTURAL_RTL_GATES; *warn_acceptance_policy_check.py — O3: Enforce that every WARN finding from* |
| 368 | `xlsx_extract` | TRANSITIVELY_WIRED | prog=1 test=2 doc=3 | KEEP | shared helper transitively reached from a wired program; *xlsx_extract.py — Extract tables from .xlsx spec documents into JSON.* |
| 369 | `yosys_hilomap_required_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 prog=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *yosys_hilomap_required_check.py — Assert a Yosys .ys script's commands occur* |
| 370 | `yosys_script_template_check` | WIRED_PRIMARY:runner_or_yaml | primary=1 test=2 doc=1 | KEEP | invoked by runner / flow YAML / burn driver; *yosys_script_template_check.py — Audit a Yosys .ys script for the three* |

## DELETE list
Programs that the audit found UNREFERENCED. None of the 370 programs is provably safe to delete without further review — the only true ORPHAN (`marketplace_version_sync_check.py`) is a STANDALONE CLI tool intended for manual invocation. So this list is empty.

## WIRE_IN list — production tests exist but no production chain invokes
These have `tests/test_<name>.py` plus a working `__main__`, but `flow_compliance_check::_STRUCTURAL_RTL_GATES` does not include them and no runner / flow YAML calls them. They are good candidates to either add to `_STRUCTURAL_RTL_GATES`, wire into the appropriate phase YAML step, or attach to a skill SKILL.md `## Programs called by this skill` section.

| Program | Likely target | One-line purpose |
|---|---|---|
| `acceptance_gate_cli` | _STRUCTURAL_RTL_GATES | acceptance_gate_cli.py — CLI surface acceptance gate. |
| `acceptance_gate_full` | _STRUCTURAL_RTL_GATES | acceptance_gate_full.py — full end-to-end MARKETPLACE LIFECYCLE acceptance gate. |
| `acceptance_gate_registry` | _STRUCTURAL_RTL_GATES | acceptance_gate_registry.py — registry round-trip acceptance gate. |
| `auto_diagnostic_led_synth` | _STRUCTURAL_RTL_GATES | auto_diagnostic_led_synth.py — v0.114 (BACKLOG-v6 D1). |
| `behavioral_evidence_per_spec_item_check` | _STRUCTURAL_RTL_GATES | behavioral_evidence_per_spec_item_check.py — v0.100 J1 |
| `bist_window_calculator` | _STRUCTURAL_RTL_GATES | bist_window_calculator.py — Size BIST response-capture windows for worst-case. |
| `constants_validation` | _STRUCTURAL_RTL_GATES | constants_validation.py — Deterministic compliance check for rtl-constants-gen. |
| `coverage_metric_check` | _STRUCTURAL_RTL_GATES | coverage_metric_check.py -- Deterministic coverage report metric checker. |
| `cross_constant_invariant_check` | _STRUCTURAL_RTL_GATES | cross_constant_invariant_check.py — Verify named timing/protocol constants |
| `decision_log_extract` | _STRUCTURAL_RTL_GATES | decision_log_extract.py — v0.79 § 3.6 EDA-log → decision_log.jsonl extractor. |
| `derived_clock_sdc_required_check` | _STRUCTURAL_RTL_GATES | derived_clock_sdc_required_check.py — Verify any register-divided clock |
| `dispatcher_awake_gate_check` | _STRUCTURAL_RTL_GATES | dispatcher_awake_gate_check.py — v0.114 (BACKLOG-v7 P2.2). |
| `dispatcher_response_size_table_audit` | _STRUCTURAL_RTL_GATES | dispatcher_response_size_table_audit.py — v0.114 (BACKLOG-v7 P2.1). |
| `em_check` | _STRUCTURAL_RTL_GATES | em_check.py — Phase 3 backend step (replaces skill em-check). |
| `final_report_generate` | _STRUCTURAL_RTL_GATES | final_report_generate.py — v0.114 (BACKLOG-v10 P2.1). |
| `flow_stage_check` | _STRUCTURAL_RTL_GATES | Flow stage check — wrapper for signoff_audit --mode flow. |
| `fpga_program_chain_attest_check` | _STRUCTURAL_RTL_GATES | fpga_program_chain_attest_check.py — Audit the FPGA compile→program→test chain. |
| `fpga_qsf_lint` | _STRUCTURAL_RTL_GATES | Deterministic QSF lint: validate Quartus project files. |
| `fresh_agent_provenance_check` | _STRUCTURAL_RTL_GATES | fresh_agent_provenance_check.py — honesty check for "fresh-agent" claims. |
| `fresh_agent_rtl_bug_density_metric` | _STRUCTURAL_RTL_GATES | fresh_agent_rtl_bug_density_metric.py — BACKLOG-v11 P2.3 + v10 P2.4. |
| `functional_state_transition_coverage_check` | _STRUCTURAL_RTL_GATES | functional_state_transition_coverage_check.py — Verify TBs exercise the |
| `gate_evidence_completeness_check` | _STRUCTURAL_RTL_GATES | gate_evidence_completeness_check.py — v0.100 L1 |
| `hw_vs_rtl_verdict_check` | _STRUCTURAL_RTL_GATES | hw_vs_rtl_verdict_check.py — Require N byte-identical FAILs before blaming hardware. |
| `ic_class_consistency_check` | _STRUCTURAL_RTL_GATES | ic_class_consistency_check.py — gate (Wave 42, v0.119.70 / SF6). |
| `integration_spec_audit` | _STRUCTURAL_RTL_GATES | integration_spec_audit.py — Deterministic compliance check for integration-spec-gen. |
| `manifest_leak_check` | _STRUCTURAL_RTL_GATES | manifest_leak_check.py — Detect benchmark-value leaks in fact manifests. |
| `mcp_execution_verify` | tests/CI only — confirm production need | mcp_execution_verify.py — Deterministic MCP tool execution verifier. |
| `memory_gc` | _STRUCTURAL_RTL_GATES | memory_gc.py — v0.55 advisory tool for Claude Code memory directories |
| `openroad_tcl_deprecation_check` | _STRUCTURAL_RTL_GATES | openroad_tcl_deprecation_check.py — Recursively scan a plugin tree for |
| `oracle_vector_gen` | _STRUCTURAL_RTL_GATES | oracle_vector_gen.py — v0.114 (BACKLOG-v6 C1 closure). |
| `output_artifact_check` | _STRUCTURAL_RTL_GATES | output_artifact_check.py — Deterministic output artifact existence checker. |
| `pad_drive_high_active_check` | _STRUCTURAL_RTL_GATES | pad_drive_high_active_check.py — v0.114 (BACKLOG-v6 P1). |
| `payload_bit_position_check` | _STRUCTURAL_RTL_GATES | payload_bit_position_check.py — Cross-reference spec doc bit-layout |
| `phase2a_gate_contract_check` | flow/phase2_phase3.yaml | phase2a_gate_contract_check.py — Meta-checker for Phase-2a deterministic gates. |
| `plugin_self_leak_check` | tools/regression CI runner | plugin_self_leak_check.py — Plugin self-audit for embedded production RTL. |
| `power_analysis` | _STRUCTURAL_RTL_GATES | power_analysis.py — Phase 3 backend step (replaces skill power-analysis). |
| `qsf_open_drain_assignment_check` | _STRUCTURAL_RTL_GATES | qsf_open_drain_assignment_check.py — DEPRECATED in v0.119.29. |
| `release_audit` | tools/regression CI runner | release_audit.py — v0.55 plugin invariant gate |
| `rx_tolerance_sweep` | _STRUCTURAL_RTL_GATES | rx_tolerance_sweep.py — General RX boundary-width tolerance sweep. |
| `scope_long_decode` | _STRUCTURAL_RTL_GATES | scope_long_decode.py — LL-9 (debug helper, not a structural gate). |
| `synth_wrapper_check` | _STRUCTURAL_RTL_GATES | synth_wrapper_check.py — Deterministic compliance check for synth-wrapper-gen. |
| `tester_oracle_health_check` | _STRUCTURAL_RTL_GATES | tester_oracle_health_check.py — Prove the tester works before iterating RTL. |
| `tester_verdict_frame_decode` | _STRUCTURAL_RTL_GATES | tester_verdict_frame_decode.py — T1 composability fix |
| `upf_syntax_check` | _STRUCTURAL_RTL_GATES | upf_syntax_check.py -- Deterministic UPF file syntax checker. |
| `vibeic_mcp_adapter` | tests/CI only — confirm production need | vibeic_mcp_adapter.py — v0.98 X: out-of-repo bridge for mcp-eda-server. |
| `waiver_legitimacy_check` | _STRUCTURAL_RTL_GATES | waiver_legitimacy_check.py — v0.116 (BACKLOG-v11 candidate). |

## REVIEW list — HELPER_BUT_DEAD_CHAIN clusters
Two clusters of mutually-imported helpers whose entry points are themselves unwired in the production chain. Decide whether to keep as a documented sub-toolchain or fold into adjacent gates.

### Cluster 1: V078 Proposer Toolchain
Documented in `programs/V078_PROPOSER_TOOLCHAIN.md`. Five proposer programs that draft K3 class-library + per-skill PRACTICAL_NOTES patches. No automated entry point in flow YAML or runners. Programs: `k3_patch_proposer`, `k3_class_miner`, `class_convergence_eval`, `pattern_effectiveness_eval`, `reference_parity_eval`, `scoreboard_to_csv`, `practical_notes_proposer`, `practical_notes_specificity_check`, `experience_unit_t5_capture`, `experience_unit_t6_capture`, `decision_log_append`, `k3_view_resolve`, `decision_log_extract` (production), `hold_fix` (test-only).

### Cluster 2: Marketplace registry / plugin-signing CLI
Programs that implement the optional plugin-marketplace registry surface. No flow / runner calls them. Programs: `vibe_ic_plugin`, `vibeic_registry_server`, `acceptance_gate_cli`, `acceptance_gate_full`, `acceptance_gate_registry`, `plugin_crypto`, `plugin_manifest`, `plugin_registry_client`, `plugin_sign`, `mcp_tool_registry`, `trust_tier_recompute`, `billing_log`, `vibeic_mcp_adapter`. They form a self-contained CLI surface, exercised only by their own tests.

### Cluster 3: Phase-1 sentinel utilities
`_phase1_sentinel`, `phase1_consistency_check`, `phase1_doc_presence_check`, `layer_extension_presence_check`, `no_protocol_consistency_check`, `phase1_quality_parity_check` — referenced by `tools/phase1_fg/` (Phase 1 fact-graph engine) but the engine itself is invoked via the `phase1` skill and `phase1_one_shot_runner.py` — so these likely ARE production-live; flagged because the wiring runs through a non-grep'd path. Recommend manual confirmation against `tools/phase1_fg/` source.

### Other dead-chain helpers
- `eda_log_check`, `openroad_drc_report_normalize`, `drc_rdb_summarize`, `openroad_tcl_deprecation_check` — the OpenROAD log-normalisation chain is unwired in flow YAML; appears to be standalone tooling for manual log triage.
- `skill_compliance_triangle_check`, `phase2a_gate_contract_check` — meta-gates (verify other gates), only test-referenced.
- `waiver_growth_check`, `waiver_legitimacy_check` — only invoked by tests; should be wired into `_STRUCTURAL_RTL_GATES`.

## MERGE list — duplicate / templated programs

### Round 4 backend wrappers (10 files, all 39-line identical templates)
Each one is a `[SKIP] <name>: deterministic first-pass — invoke …` placeholder. They serve as namespace shims for the migrated Phase-3 backend skills. They could be replaced with a single `phase3_backend_step.py <skill_name>` driver:
- `cts_plan.py`, `dft_insert.py`, `em_check.py`, `lef_psm_patch.py`, `open_rcx_fallback.py`, `perc_check.py`, `placement_optimize.py`, `power_analysis.py`, `upf_author.py`, `atpg.py`

### First-pass triage shims (7 files, 36-line identical templates)
Each one writes a `PASS_DEFERRED_TO_AI` summary JSON. Could be folded into a single `first_pass_triage.py <skill_name>` driver:
- `drc_fix.py`, `hold_fix.py`, `ir_drop_triage.py`, `lvs_triage.py`, `ppa_predict.py`, `sta_review.py`, `synth_doctor.py`

### l_doc_* + l3_opcode_* + l8/l11 typed-depth gates
Wave-38 / Wave-39 introduced 7 `l_doc_<aspect>_check.py` and 6 `l<n>_<thing>_typed_check.py` programs that share the same scaffolding (load L*.json, walk schema, emit JSON report). Each is a distinct gate, but their schema-walking helper logic should be lifted into `_l_doc_schema_utils.py` (today only `gate_utils.py` exists for half-duplex/wake gates).
