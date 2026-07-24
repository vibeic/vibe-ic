# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 49
  - design cells (clean context, gated): 49
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 49 (100.0%)
**Program-only cells**: 37
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L7_verification_plan.txt | 23 | 23 | 0 | 23 | 0 | 0 | PASS |
| L9_constraints_floorplan.txt | 20 | 20 | 0 | 20 | 0 | 0 | PASS |
| L1_product_metadata.txt | 15 | 15 | 0 | 15 | 0 | 0 | PASS |
| L8_submodule_integration.txt | 8 | 8 | 0 | 8 | 0 | 0 | SKIP_LOW_TOKENS |
| L2_architecture.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| L4_command_protocol.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| L3_external_interface.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| L6_calibration.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| L5_register_map.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 2 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 2 | 0 |  |
| L14_PROTOCOL_VERSIONING | 0 | 0 |  |
| L15_ENCODING_TABLES | 0 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 0 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 1 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 0 | 0 |  |
| L19_CONSTRAINTS_PDK | 3 | 0 |  |
| L1_DATASHEET | 48 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 0 | 0 |  |
| L21_POWER_INTENT | 0 | 0 |  |
| L22_VERIFICATION_PLAN | 0 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 0 | 0 |  |
| L24_SIGNOFF | 3 | 0 |  |
| L25_RELIABILITY_MISSION_PROFILE | 1 | 0 |  |
| L26_MECHANICAL_TRANSDUCTION | 0 | 0 |  |
| L27_MEMORY_MODULE_SPD | 0 | 0 |  |
| L2_FRS | 20 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 0 | 0 |  |
| L5_ADI_SPEC | 0 | 0 |  |
| L6_CONTROL_LOGIC | 1 | 0 |  |
| L7_TEST_DEBUG | 6 | 0 |  |
| L8_RTL_CONSTANTS | 12 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 1 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
