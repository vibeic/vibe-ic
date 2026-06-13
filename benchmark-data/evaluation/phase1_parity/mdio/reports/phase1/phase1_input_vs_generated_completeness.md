# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 50
  - design cells (clean context, gated): 50
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 50 (100.0%)
**Program-only cells**: 50
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| IEEE_802.3_MDIO_Clause22_45.txt | 50 | 50 | 0 | 50 | 0 | 0 | PASS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 11 | 0 |  |
| L11_OTP_CONTENT | 12 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 35 | 0 |  |
| L13_LAB_CALIBRATION | 17 | 0 |  |
| L14_PROTOCOL_VERSIONING | 21 | 0 |  |
| L15_ENCODING_TABLES | 30 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 23 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 24 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 24 | 0 |  |
| L19_CONSTRAINTS_PDK | 16 | 0 |  |
| L1_DATASHEET | 49 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 17 | 0 |  |
| L21_POWER_INTENT | 10 | 0 |  |
| L22_VERIFICATION_PLAN | 9 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 11 | 0 |  |
| L2_FRS | 45 | 0 |  |
| L3_CMD_PROTOCOL | 34 | 0 |  |
| L4_REGMAP | 24 | 0 |  |
| L5_ADI_SPEC | 9 | 0 |  |
| L6_CONTROL_LOGIC | 32 | 0 |  |
| L7_TEST_DEBUG | 20 | 0 |  |
| L8_RTL_CONSTANTS | 28 | 0 |  |
| L8_TIMING_WAVEFORM | 35 | 0 |  |
| L9_INTEGRATION_SPEC | 30 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
