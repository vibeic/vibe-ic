# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 53
  - design cells (clean context, gated): 53
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 52 (98.1%)
**Program-only cells**: 52
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 1

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Intel_LPC_Interface_Specification.txt | 53 | 53 | 0 | 52 | 0 | 1 | FAIL |
| __chip_root___rglob_readme_fallback_v1_6_343__.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 16 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 16 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L14_PROTOCOL_VERSIONING | 14 | 0 |  |
| L15_ENCODING_TABLES | 16 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 26 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 22 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 10 | 0 |  |
| L19_CONSTRAINTS_PDK | 4 | 0 |  |
| L1_DATASHEET | 51 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 1 | 0 |  |
| L21_POWER_INTENT | 4 | 0 |  |
| L22_VERIFICATION_PLAN | 8 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 3 | 0 |  |
| L2_FRS | 44 | 0 |  |
| L3_CMD_PROTOCOL | 22 | 0 |  |
| L4_REGMAP | 3 | 0 |  |
| L5_ADI_SPEC | 3 | 0 |  |
| L6_CONTROL_LOGIC | 16 | 0 |  |
| L7_TEST_DEBUG | 16 | 0 |  |
| L8_RTL_CONSTANTS | 24 | 0 |  |
| L8_TIMING_WAVEFORM | 15 | 0 |  |
| L9_INTEGRATION_SPEC | 10 | 0 |  |
| (unallocated) | 0 | 0 | 1 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
