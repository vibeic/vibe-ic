# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 182
  - design cells (clean context, gated): 182
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 149 (81.9%)
**Program-only cells**: 132
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 33

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| ibex_cs_registers.txt | 75 | 75 | 0 | 75 | 0 | 0 | PASS |
| ibex_performance_counters.txt | 44 | 44 | 0 | 17 | 0 | 27 | FAIL |
| ibex_verification.txt | 29 | 29 | 0 | 28 | 0 | 1 | FAIL |
| ibex_integration.txt | 23 | 23 | 0 | 20 | 0 | 3 | FAIL |
| ibex_instruction_decode_execute.txt | 17 | 17 | 0 | 17 | 0 | 0 | PASS |
| ibex_exception_interrupts.txt | 14 | 14 | 0 | 12 | 0 | 2 | FAIL |
| ibex_pipeline_details.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_compliance.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_instruction_fetch.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_load_store_unit.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_pmp.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_register_file.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_system_requirements.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_verification_overview.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_index.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_targets.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| ibex_licensing.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 2 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L14_PROTOCOL_VERSIONING | 0 | 0 |  |
| L15_ENCODING_TABLES | 0 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 3 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 0 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 0 | 0 |  |
| L19_CONSTRAINTS_PDK | 0 | 0 |  |
| L1_DATASHEET | 99 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 1 | 0 |  |
| L21_POWER_INTENT | 0 | 0 |  |
| L22_VERIFICATION_PLAN | 0 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 0 | 0 |  |
| L2_FRS | 75 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 72 | 0 |  |
| L5_ADI_SPEC | 0 | 0 |  |
| L6_CONTROL_LOGIC | 2 | 0 |  |
| L7_TEST_DEBUG | 1 | 0 |  |
| L8_RTL_CONSTANTS | 13 | 0 |  |
| L8_TIMING_WAVEFORM | 4 | 0 |  |
| L9_INTEGRATION_SPEC | 20 | 0 |  |
| (unallocated) | 0 | 0 | 33 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
