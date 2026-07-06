# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 2
  - design cells (clean context, gated): 2
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 2 (100.0%)
**Program-only cells**: 0
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| prompt.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 0 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L14_PROTOCOL_VERSIONING | 0 | 0 |  |
| L15_ENCODING_TABLES | 0 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 0 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 0 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 0 | 0 |  |
| L19_CONSTRAINTS_PDK | 0 | 0 |  |
| L1_DATASHEET | 2 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 0 | 0 |  |
| L21_POWER_INTENT | 0 | 0 |  |
| L22_VERIFICATION_PLAN | 0 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 0 | 0 |  |
| L2_FRS | 0 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 0 | 0 |  |
| L5_ADI_SPEC | 0 | 0 |  |
| L6_CONTROL_LOGIC | 0 | 0 |  |
| L7_TEST_DEBUG | 0 | 0 |  |
| L8_RTL_CONSTANTS | 0 | 0 |  |
| L8_TIMING_WAVEFORM | 0 | 0 |  |
| L9_INTEGRATION_SPEC | 0 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
