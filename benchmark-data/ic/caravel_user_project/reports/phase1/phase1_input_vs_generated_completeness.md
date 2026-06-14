# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 32
  - design cells (clean context, gated): 32
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 31 (96.9%)
**Program-only cells**: 16
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 1

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L9_constraints_floorplan.txt | 16 | 16 | 0 | 16 | 0 | 0 | PASS |
| L1_product_metadata.txt | 8 | 8 | 0 | 8 | 0 | 0 | SKIP_LOW_TOKENS |
| L3_external_interface.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| L7_verification_plan.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| L8_submodule_integration.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| L5_register_map.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| L2_architecture.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| L4_command_protocol.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| L6_calibration.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 0 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L14_PROTOCOL_VERSIONING | 0 | 0 |  |
| L15_ENCODING_TABLES | 0 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 0 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 0 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 0 | 0 |  |
| L19_CONSTRAINTS_PDK | 3 | 0 |  |
| L1_DATASHEET | 30 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 0 | 0 |  |
| L21_POWER_INTENT | 0 | 0 |  |
| L22_VERIFICATION_PLAN | 0 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 0 | 0 |  |
| L2_FRS | 24 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 0 | 0 |  |
| L5_ADI_SPEC | 0 | 0 |  |
| L6_CONTROL_LOGIC | 0 | 0 |  |
| L7_TEST_DEBUG | 1 | 0 |  |
| L8_RTL_CONSTANTS | 4 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 5 | 0 |  |
| (unallocated) | 0 | 0 | 1 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
