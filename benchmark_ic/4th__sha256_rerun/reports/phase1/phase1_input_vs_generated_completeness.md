# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 83
  - design cells (clean context, gated): 83
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 83 (100.0%)
**Program-only cells**: 81
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| L5_register_map.txt | 32 | 32 | 0 | 32 | 0 | 0 | PASS |
| L4_command_protocol.txt | 27 | 27 | 0 | 27 | 0 | 0 | PASS |
| L7_verification_plan.txt | 25 | 25 | 0 | 25 | 0 | 0 | PASS |
| L8_submodule_integration.txt | 22 | 22 | 0 | 22 | 0 | 0 | PASS |
| L1_product_metadata.txt | 17 | 17 | 0 | 17 | 0 | 0 | PASS |
| L2_architecture.txt | 17 | 17 | 0 | 17 | 0 | 0 | PASS |
| L9_constraints_floorplan.txt | 16 | 16 | 0 | 16 | 0 | 0 | PASS |
| L3_external_interface.txt | 11 | 11 | 0 | 11 | 0 | 0 | PASS |
| L6_calibration.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 0 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 22 | 0 |  |
| L13_LAB_CALIBRATION | 2 | 0 |  |
| L1_DATASHEET | 82 | 0 |  |
| L2_FRS | 52 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 2 | 0 |  |
| L5_ADI_SPEC | 2 | 0 |  |
| L6_CONTROL_LOGIC | 5 | 0 |  |
| L7_TEST_DEBUG | 2 | 0 |  |
| L8_RTL_CONSTANTS | 6 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 10 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
