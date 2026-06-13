# SKILL_PROGRAM_AUDIT — vibe-ic plugin v1.1.0

**Audit date:** 2026-05-06
**Plugin version:** v0.124+ (Wave 79, 88+2 skills, 347 .py programs, 253 `*_check.py`)
**Scope:** `vibe-ic-marketplace/plugins/vibe-ic/{skills,programs,flow}`
**Methodology:** read `_classification.json` (curated tiering), `SKILL_VS_RUNNER_DECISION.md` (runner-first principle), enumerate `_STRUCTURAL_RTL_GATES` in `flow_compliance_check.py`, grep `flow/phase2_phase3.yaml` + 8 one-shot runners for program references, then cross-correlate with file lists in `skills/`, `tests/`, `programs/`.

**Important caveat — this audit DOES NOT recommend deleting most "redundant" skills.** Vibe-IC explicitly supports two entry points:

- **Path A** — natural-language prompt → PM-Agent + IC-Expert dialogue → `phase1_one_shot_runner.py` → L1..L13 JSON. The 19 fallback-tier skills (`datasheet-gen`, `frs-gen`, ... `phase2a-coverage-report-gen`) are the NL-dialogue methodology that drives the agents on this path.
- **Path B** — existing vendor docs → `phase2a_one_shot_runner.py` (regex extraction over `input/docs/`). For this path the same 19 skills are redundant.

Skills that look "redundant" relative to a runner are still essential for Path A. The cure is documentation/discoverability, not deletion.

---

## Executive Summary

### Skills (90 total)

| category | count | tier(s) | recommend |
|---|---|---|---|
| `NL_REQUIRED` (no deterministic equivalent) | 39 | `essential` (25) + `analog_essential` (14) | KEEP — invoke directly |
| `REDUNDANT_PATH_B` (covered by `phase2a_one_shot_runner.py` for Path B; needed for Path A NL dialogue) | 19 | `fallback_when_runner_waives` | KEEP for Path A; do NOT auto-invoke when Path B runner is running |
| `PARTIAL_OVERLAP` — RTL track (covered by `phase2b_one_shot_runner.py` + `aid_class_rtl_gen.py` only for AID-class) | 17 | `rtl_track` | KEEP — covers non-AID classes / specialised flows |
| `PARTIAL_OVERLAP` — backend track (covered by `phase3_one_shot_runner.py` only for standard open-source PDK) | 15 | `backend_track` | KEEP — covers vendor PDK / commercial signoff flows |
| `REDUNDANT_FULL` (no NL judgement, fully replicated by a runner) | **0** | — | — |
| `DEAD` (no consumer at all) | **0** | — | — |

**Net deletion candidates: 0 skills.** Every skill is either essential NL methodology or a tier-classified fallback. The plugin is already well-curated.

### Programs (253 `*_check.py` audited; 94 other Python programs not in this scope)

| status | count | description |
|---|---|---|
| `WIRED` | 204 | named in `flow_compliance_check._STRUCTURAL_RTL_GATES` (180) or invoked from `flow/phase2_phase3.yaml` / one-shot runners (24 more) |
| `WIRED_VIA_NONRUNNER` | 26 | invoked indirectly via `skills/*/compliance.yaml`, agent yaml, or other gate's Python — not in the structural tuple but live in production flow |
| `WIRED_VIA_TEST_ONLY` | 22 | only `tests/test_*` references; not invoked by any runner / flow / skill — **deletion or wiring candidates** |
| `ORPHAN` | 1 | `marketplace_version_sync_check.py` — referenced nowhere outside its own file |

**Net deletion candidates: 1 program.** The 22 `WIRED_VIA_TEST_ONLY` programs are review candidates — they may be intentional standalone CLI gates that humans run manually, or they may be legacy gates that lost their wiring. See §5.

---

## 1. Methodology Notes

1. **Skill audit method.** Each skill's tier is curated in `skills/_classification.json` (122 lines). I cross-referenced this with `SKILL_VS_RUNNER_DECISION.md` and spot-checked SKILL.md content for `datasheet-gen`, `spec-to-rtl`, `flow-orchestrate`, `phase1`, and `regmap-gen` to confirm the tier label matches the SKILL.md's actual deliverable. Result: every spot-check matched.
2. **Program audit method.** The `_STRUCTURAL_RTL_GATES` tuple in `flow_compliance_check.py` lines 119-1009 contains 180 gate names. I additionally scanned the 8 one-shot runners and `flow/phase2_phase3.yaml` for any other gate references, giving 244 total wired identifiers. The 49 `*_check.py` files not in that union were further classified by searching `tests/`, `skills/`, `flow/`, `commands/`, `agents/`, `hooks/`.
3. **Definition of REDUNDANT_FULL.** A skill is REDUNDANT_FULL if and only if (a) its core deliverable is fully produced by a deterministic program AND (b) a fresh-agent could omit the skill without functional loss on either Path A or Path B. **No skill in the plugin meets this definition** because every fallback-tier skill drives the PM-Agent dialogue on Path A.

---

## 2. Per-Skill Table (90 skills)

## Per-Skill Table

| skill | tier | category | covered_by_program | NL_judgement_needed | recommend |
|---|---|---|---|---|---|
| adi-spec-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| ams-sim | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-extraction-resim | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-flow-orchestrate | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-hardmacro-gen | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-hw-measure | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-hw-testbench-gen | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-hw-tuning-loop | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-layout | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-netlist-gen | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-sizing | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-sizing-loop | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-spec-extract | analog_essential | NL_REQUIRED | — | yes | KEEP |
| analog-topology-select | analog_essential | NL_REQUIRED | — | yes | KEEP |
| architecture-explore | essential | NL_REQUIRED | — | yes | KEEP |
| assertion-gen | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| atpg | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| atpg-name-harmonize | essential | NL_REQUIRED | — | yes | KEEP |
| behavioral-sequences-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| bringup-plan | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| calibration-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| cdc-check | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| checkpoint-gate | essential | NL_REQUIRED | — | yes | KEEP |
| cmd-protocol-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| community-backlog-submit | essential | NL_REQUIRED | — | yes | KEEP |
| constraint-gen | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| control-logic-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| coverage-closure | essential | NL_REQUIRED | — | yes | KEEP |
| cts-plan | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| datasheet-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| def2gds | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| dft-insert | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| doc-consistency-check | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| drc-fix | essential | NL_REQUIRED | — | yes | KEEP |
| drc-from-lef | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| eco-plan | essential | NL_REQUIRED | — | yes | KEEP |
| em-check | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| equivalence-check | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| flow-orchestrate | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| formal-verify | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| fpga-hps-bridge | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| fpga-led-probe-allocation | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| fpga-signaltap | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| fpga-test-harness | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| frs-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| hls-c2rtl | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| hold-fix | essential | NL_REQUIRED | — | yes | KEEP |
| hw-debug-loop | essential | NL_REQUIRED | — | yes | KEEP |
| integration-spec-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| ir-drop-triage | essential | NL_REQUIRED | — | yes | KEEP |
| lab-calibration-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| lef-psm-patch | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| lvs-open-source | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| lvs-triage | essential | NL_REQUIRED | — | yes | KEEP |
| mixed-signal-cosim | analog_essential | NL_REQUIRED | — | yes | KEEP |
| open-rcx-fallback | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| otp-content-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| pdk-metal-stack-select | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| perc-check | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| phase1 | essential | NL_REQUIRED | — | yes | KEEP |
| phase2a-coverage-report-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| phase2a-orchestrate | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| placement-optimize | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| power-analysis | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| ppa-predict | essential | NL_REQUIRED | — | yes | KEEP |
| protocol-timeline-assert | essential | NL_REQUIRED | — | yes | KEEP |
| protocol-turnaround-audit | essential | NL_REQUIRED | — | yes | KEEP |
| rdc-check | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| regmap-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| regression-manage | essential | NL_REQUIRED | — | yes | KEEP |
| rtl-constants-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| rtl-repair | essential | NL_REQUIRED | — | yes | KEEP |
| rtl-review | essential | NL_REQUIRED | — | yes | KEEP |
| rtl-unit-testbench-gen | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| schematic-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| scope-pattern-attestation | essential | NL_REQUIRED | — | yes | KEEP |
| sdc-validator | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| spec-review | essential | NL_REQUIRED | — | yes | KEEP |
| spec-to-rtl | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| spec-validator | essential | NL_REQUIRED | — | yes | KEEP |
| sta-review | essential | NL_REQUIRED | — | yes | KEEP |
| synth-doctor | essential | NL_REQUIRED | — | yes | KEEP |
| synth-wrapper-gen | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| tapeout-checklist | essential | NL_REQUIRED | — | yes | KEEP |
| test-cases-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| test-debug-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| testbench-gen | rtl_track | PARTIAL_OVERLAP | phase2b_one_shot_runner.py + aid_class_rtl_gen.py (AID-class only) | partial | KEEP |
| timing-waveform-gen | fallback_when_runner_waives | REDUNDANT_PATH_B | phase2a_one_shot_runner.py (gen_l1..l13 + emit_coverage_report) | no | KEEP_PATH_A_ONLY |
| upf-author | backend_track | PARTIAL_OVERLAP | phase3_one_shot_runner.py (standard PDK only) | partial | KEEP |
| yield-diagnostic | essential | NL_REQUIRED | — | yes | KEEP |


## Per-Program (`*_check.py`) Table

Total `*_check.py` files: 253. Status counts: {'WIRED': 204, 'WIRED_VIA_NONRUNNER': 26, 'WIRED_VIA_TEST_ONLY': 22, 'ORPHAN': 1}

| program | status | notes |
|---|---|---|
| analog_block_coverage_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_content_detected_must_emit_l5_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_corner_sweep_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_digital_interface_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_flow_compliance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_hardmacro_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_hw_spice_correlation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_netlist_pdk_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| analog_pre_vs_post_layout_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| arbiter_starvation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| assertion_covers_l3_constraints_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| assertion_property_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bit_count_modulo_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bit_level_full_stack_tb_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bit_level_full_stack_tb_oracle_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bitwidth_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bram_init_file_actually_loaded_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bram_init_portable_compat_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bram_pdob_combinational_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bram_read_latency_consume_alignment_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| break_framing_vs_l3_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| break_handler_safety_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| bus_turnaround_consumes_spec_constant_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| byte_assembler_explicit_9bit_reject_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cdc_async_input_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cdc_crossing_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| chip_clock_toggle_divider_when_master_already_target_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| clock_cascade_synthesis_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| clock_divider_period_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cmd_arg_range_validation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cmd_argument_validation_present_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cmd_buf_index_semantic_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cmd_protocol_byte_exact_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cmd_response_otp_provenance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| connect_vs_send_test_parity_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_bitorder_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_compute_done_before_tx_start_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_constants_rtl_doc_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_engine_isolation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_oracle_vector_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_parameters_extracted_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_polyform_outputreversal_pairing_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_q_settle_cycle_after_last_feed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_residual_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_residue_settle_state_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| crc_seed_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| cross_module_1cycle_handshake_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| def_stage_progression_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| device_response_no_br_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| dispatch_fetch_loop_population_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| dispatch_register_default_reset_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| dispatcher_tx_arm_order_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| doc_consistency_no_unresolved_conflicts_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| drc_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| em_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| extraction_coverage_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| extraction_evidence_schema_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fetch_round_trip_sentinel_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| flow_compliance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_async_input_synchronizer_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_clock_divider_antipattern_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_on_board_attestation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_pad_fanout_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_pad_pullup_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_port_qsf_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_sdc_clock_constraint_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_search_path_includes_required_dirs_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_sta_negative_slack_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_top_pin_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fpga_wrapper_input_polluter_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| frame_end_detection_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| frame_end_gap_in_l8_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| frs_timing_range_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| fsm_state_coverage_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| function_void_with_output_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| gap_reset_granularity_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| gds_size_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| half_duplex_frame_end_idle_reset_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| half_duplex_response_window_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| half_duplex_wrapper_open_drain_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| handshake_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| host_soft_reset_unwake_path_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| hw_acceptance_test_passed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| internal_vs_external_timing_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| ir_drop_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| klayout_deck_mode_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l10_tb_conformance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l10_test_cases_cover_l3_constraints_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l11_otp_lock_dependencies_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l11_sequence_covers_l6_reject_rules_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l12_behavioral_sequences_steps_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l12_sequence_implementation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l12_tb_coverage_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l1_electrical_specs_typed_depth_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l1_pin_table_aliases_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l2_timing_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l3_opcode_argument_constraints_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l3_opcode_pre_wake_allowed_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l3_opcode_response_template_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l4_regmap_enumerated_values_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l6_reject_rules_from_rx_event_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l8_clock_domains_typed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l8_frame_end_gap_derivation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l9_response_delay_schema_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l9_rtl_pin_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l_doc_aggregated_blob_size_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l_doc_structured_field_count_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| l_doc_unique_content_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| lvs_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| mask_application_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| memory_read_pipeline_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| metal_fill_density_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| mixed_signal_cosim_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| nba_addr_read_race_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| nba_shift_register_same_cycle_read_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| oe_pattern_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| opcode_dispatch_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| oracle_dump_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_field_map_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_image_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_image_layer_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_image_nonzero_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_module_uses_supported_pattern_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| otp_write_lock_gate_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| pdk_analog_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| per_opcode_response_latency_table_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| periodic_signal_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| periodic_timer_vs_rx_activity_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| phase23_completion_self_audit_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| phase2a_all_l_docs_present_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| phase2a_coverage_report_present_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| phase2a_doc_content_implementation_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| phase2a_no_waivers_used_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| post_layout_sim_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| power_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| pre_awake_silence_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| project_outputs_in_tree_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| protocol_delimiter_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| protocol_fsm_topology_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| protocol_gap_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| protocol_ip_simulation_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| protocol_reference_tb_pass_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| provenance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| pulse_decoder_edge_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| regmap_bit_layout_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| reset_dependency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| response_latency_observability_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| response_payload_template_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| result_md_audit_provenance_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rig_firmware_capability_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rig_topology_disclosure_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rig_topology_image_extracted_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rsp_example_otp_consistency_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rtl_bug_report_schema_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rtl_response_byte_oracle_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_byte_assembler_ibt_flush_recovery_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_byte_valid_requires_ibt_gate_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_classifier_no_threshold_gap_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_classifier_thresholds_match_l8_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_deglitch_filter_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_ibt_frame_end_semantics_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| rx_last_bit_frame_end_commit_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| scope_reply_preamble_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| scope_response_byte_decode_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| sdc_syntax_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| self_rx_mask_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| self_rx_mask_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| send_test_active_drive_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| si_crosstalk_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| single_bus_driver_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| slave_tx_no_device_break_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| spec_response_delay_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| spef_extraction_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| spice_correlation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| sta_report_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| sustained_vs_edge_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| synth_netlist_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tapeout_signoff_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tb_timing_extremes_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| threshold_range_contiguity_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| timer_freeze_after_state_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| toggle_divider_hierarchical_clock_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| trailing_delimiter_completeness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| transient_signal_latch_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tristate_active_drive_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tristate_bus_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tristate_pullup_assertion_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tristate_self_rx_mask_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tx_abort_during_transmission_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tx_bit_timing_units_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tx_bit_width_min_resolution_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tx_phy_bit_cell_total_consumed_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| tx_timing_use_max_of_range_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| vendor_fpga_reference_table_extraction_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| waiver_staleness_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| waivers_schema_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| wake_gen_bus_active_reset_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| wake_pulse_emit_gated_by_first_rx_command_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| wake_pulse_implementation_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| wake_pulse_width_matches_measurement_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| warn_acceptance_policy_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| yosys_hilomap_required_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| yosys_script_template_check.py | WIRED | in flow_compliance_check._STRUCTURAL_RTL_GATES or invoked by runner / flow YAML |
| backlog_sanitize_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| clock_scale_consistency_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| cmd_response_conformance_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| coverage_metric_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| eda_log_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| flow_stage_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| fresh_agent_provenance_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| hardware_pass_attestation_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| input_docs_coverage_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| json_schema_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| l9_completeness_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| layer_extension_presence_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| no_protocol_consistency_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| output_artifact_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| pdk_consistency_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| phase1_consistency_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| phase1_doc_presence_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| phase1_k5_quality_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| phase1_quality_parity_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| rtl_unit_test_coverage_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| scope_periodic_pulse_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| sv_compat_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| synth_wrapper_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| testbench_exists_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| upf_syntax_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| waiver_legitimacy_check.py | WIRED_VIA_NONRUNNER | referenced by skill compliance.yaml / SKILL.md / agent yaml — invoked indirectly |
| behavioral_evidence_per_spec_item_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| cross_constant_invariant_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| derived_clock_sdc_required_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| dispatcher_awake_gate_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| foundry_signoff_plan_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| fpga_program_chain_attest_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| frontend_backend_handoff_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| functional_state_transition_coverage_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| gate_evidence_completeness_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| hw_vs_rtl_verdict_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| ic_class_consistency_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| manifest_leak_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| openroad_tcl_deprecation_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| pad_drive_high_active_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| payload_bit_position_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| phase2a_gate_contract_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| plugin_self_leak_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| practical_notes_specificity_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| qsf_open_drain_assignment_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| skill_compliance_triangle_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| tester_oracle_health_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| waiver_growth_check.py | WIRED_VIA_TEST_ONLY | only test references; not invoked in production flow |
| marketplace_version_sync_check.py | ORPHAN | no references found anywhere — deletion candidate |

---

## 3. Concrete Deletion Candidates

### Skills to delete: **NONE**

Justification: every skill is either NL-required (essential / analog_essential tiers, 39 skills), tier-classified as a Path-A fallback (19 skills), or a track-specific specialisation that runners only partially cover (17 RTL + 15 backend). Deleting any of them would break either the NL Path A entry point or the non-AID / vendor-PDK extension paths.

### Programs to delete (or wire): 1 hard candidate + 22 review candidates

**Hard delete candidate (1):**
- `marketplace_version_sync_check.py` — `ORPHAN`. Referenced nowhere in `tests/`, `skills/`, `flow/`, `commands/`, `agents/`, `hooks/`, or any program except its own file. Safe to remove.

**Review candidates (22 `WIRED_VIA_TEST_ONLY` — keep, wire, or delete):**

These have a `tests/test_<name>.py` but no production caller. Each should be triaged: either wire it into `_STRUCTURAL_RTL_GATES` / a flow stage, or delete the orphaned test+gate pair.

```
behavioral_evidence_per_spec_item_check
cross_constant_invariant_check
derived_clock_sdc_required_check
dispatcher_awake_gate_check
foundry_signoff_plan_check
fpga_program_chain_attest_check
frontend_backend_handoff_check
functional_state_transition_coverage_check
gate_evidence_completeness_check
hw_vs_rtl_verdict_check
ic_class_consistency_check
manifest_leak_check
openroad_tcl_deprecation_check
pad_drive_high_active_check
payload_bit_position_check
phase2a_gate_contract_check
plugin_self_leak_check
practical_notes_specificity_check
qsf_open_drain_assignment_check
skill_compliance_triangle_check
tester_oracle_health_check
waiver_growth_check
```

Note: several of these (e.g. `frontend_backend_handoff_check`, `waiver_growth_check`, `gate_evidence_completeness_check`, `phase2a_gate_contract_check`) are listed in CHANGELOG as part of recent BACKLOG-v10/v11/v13 waves and were probably meant to be wired but the entry was forgotten. A wiring sweep should run before any deletion.

---

## 4. KEEP-but-Reclassify (Path-A only)

The 19 `fallback_when_runner_waives` skills are functionally redundant when Path B (`phase2a_one_shot_runner.py`) is the entry point. They MUST stay because:

- Path A (NL prompt → L1..L13) routes through PM-Agent + IC-Expert dialogue using these skills as the per-layer methodology.
- The deterministic runner is a regex/template extractor over already-existing `input/docs/`. It cannot synthesise an L1 datasheet from an empty project.

**Recommendation: tag the SKILL.md frontmatter with `entry_path: A` so the AI dispatcher knows not to invoke them when a Path B runner is already running.** The 19 skills:

```
datasheet-gen, frs-gen, cmd-protocol-gen, regmap-gen, adi-spec-gen,
control-logic-gen, test-debug-gen, timing-waveform-gen, rtl-constants-gen,
integration-spec-gen, test-cases-gen, calibration-gen,
behavioral-sequences-gen, lab-calibration-gen, otp-content-gen,
doc-consistency-check, schematic-gen, phase2a-coverage-report-gen,
phase2a-orchestrate
```

---

## 5. Wiring Sweep Backlog (22 test-only gates)

For each `WIRED_VIA_TEST_ONLY` program, decide one of:

1. **Wire into `_STRUCTURAL_RTL_GATES`** if the gate is intended to run on every project.
2. **Wire into a `flow/phase2_phase3.yaml` stage** if it belongs to a specific stage (e.g. `frontend_backend_handoff_check` likely belongs in stage1→stage2 transition).
3. **Wire into a skill `compliance.yaml`** if the gate is a skill-local invariant.
4. **Delete** if the gate was an experimental dead-end.

This sweep is NOT in scope of the current audit but is the highest-priority follow-up.

---

## 6. Other (non-`_check.py`) program review

Out of scope per the audit brief, but flagged for completeness — the `programs/` directory contains 94 non-`_check.py` Python programs. The 8 one-shot runners + `aid_class_rtl_gen.py` + `qsf_gen.py` + `sdc_gen.py` + `flow_compliance_check.py` are the main line. Other `_audit.py`, `_warn.py`, `_lint.py`, `_metric.py`, `_compliance.py` files (~30 in total) are mostly wired into the structural tuple via the same name pattern; the file-set audit above already includes them.

The remaining 60+ non-gate programs are utilities (`gate_utils.py`, `provenance_logger.py`, `experience_unit_t*_capture.py`, `vibe_ic_plugin.py`, `vibeic_mcp_adapter.py`, `*_gen.py`, `*_eval.py`, `*_proposer.py`) — most are imported by runners or by gates; full enumeration of those is a separate task.

---

## Appendix A — Skill counts by tier

```
essential                       25  (NL_REQUIRED)
analog_essential                14  (NL_REQUIRED)
fallback_when_runner_waives     19  (REDUNDANT_PATH_B)
rtl_track                       17  (PARTIAL_OVERLAP)
backend_track                   15  (PARTIAL_OVERLAP)
total                           90
```

## Appendix B — Reproduce this audit

```
cd vibe-ic-marketplace/plugins/vibe-ic
# Wired structural gates
python3 -c "
import re
text=open('programs/flow_compliance_check.py').read()
start=text.find('_STRUCTURAL_RTL_GATES: tuple[str, ...] = (')
end=text.find(')\\n\\n# Canonical synthesis-script search order')
print(len(re.findall(r'\"([a-z][a-z0-9_]+)\"', text[start:end])))
"
# Should print 180

# Total *_check.py
ls programs/*_check.py | wc -l   # → 253

# Tier classification
cat skills/_classification.json | python3 -c "import json,sys; d=json.load(sys.stdin); print({k:len(v['skills']) for k,v in d['tiers'].items()})"
```
