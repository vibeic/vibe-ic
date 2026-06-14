# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 328
  - design cells (clean context, gated): 328
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 288 (87.8%)
**Program-only cells**: 288
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 40

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| aes_registers.txt | 151 | 151 | 0 | 150 | 0 | 1 | FAIL |
| aes_checklist.txt | 108 | 108 | 0 | 81 | 0 | 27 | FAIL |
| aes_programmers_guide.txt | 77 | 77 | 0 | 66 | 0 | 11 | FAIL |
| aes_theory_of_operation.txt | 47 | 47 | 0 | 46 | 0 | 1 | FAIL |
| aes_interfaces.txt | 37 | 37 | 0 | 37 | 0 | 0 | PASS |
| aes_README.txt | 20 | 20 | 0 | 20 | 0 | 0 | PASS |
| aes_block_diagram.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| aes_block_diagram_cipher_core_masked.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| ghash_masked_block_diagram.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| ghash_masked_algorithm.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 0 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L14_PROTOCOL_VERSIONING | 1 | 0 |  |
| L15_ENCODING_TABLES | 1 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 28 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 1 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 0 | 0 |  |
| L19_CONSTRAINTS_PDK | 1 | 0 |  |
| L1_DATASHEET | 241 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 2 | 0 |  |
| L21_POWER_INTENT | 1 | 0 |  |
| L22_VERIFICATION_PLAN | 1 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 2 | 0 |  |
| L2_FRS | 192 | 0 |  |
| L3_CMD_PROTOCOL | 1 | 0 |  |
| L4_REGMAP | 0 | 0 |  |
| L5_ADI_SPEC | 2 | 0 |  |
| L6_CONTROL_LOGIC | 4 | 0 |  |
| L7_TEST_DEBUG | 7 | 0 |  |
| L8_RTL_CONSTANTS | 2 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 13 | 0 |  |
| (unallocated) | 0 | 0 | 40 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
