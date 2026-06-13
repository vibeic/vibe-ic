# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 56
  - design cells (clean context, gated): 56
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 54 (96.4%)
**Program-only cells**: 53
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 2

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Cisco_SGMII_Specification.txt | 53 | 53 | 0 | 53 | 0 | 0 | PASS |
| __chip_root_phase3__stage4__foundry_handoff__README.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| __chip_root___rglob_readme_fallback_v1_6_343__.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 7 | 0 |  |
| L11_OTP_CONTENT | 6 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 15 | 0 |  |
| L13_LAB_CALIBRATION | 9 | 0 |  |
| L14_PROTOCOL_VERSIONING | 15 | 0 |  |
| L15_ENCODING_TABLES | 18 | 0 |  |
| L16_COMPLIANCE_PROPERTIES | 14 | 0 |  |
| L17_CHANNEL_SIGNAL_CATALOG | 19 | 0 |  |
| L18_INTERCONNECT_TOPOLOGY | 13 | 0 |  |
| L19_CONSTRAINTS_PDK | 9 | 0 |  |
| L1_DATASHEET | 49 | 0 |  |
| L20_DFT_SCAN_TOPOLOGY | 8 | 0 |  |
| L21_POWER_INTENT | 10 | 0 |  |
| L22_VERIFICATION_PLAN | 8 | 0 |  |
| L23_SECURITY_REQUIREMENTS | 9 | 0 |  |
| L2_FRS | 45 | 0 |  |
| L3_CMD_PROTOCOL | 19 | 0 |  |
| L4_REGMAP | 11 | 0 |  |
| L5_ADI_SPEC | 6 | 0 |  |
| L6_CONTROL_LOGIC | 19 | 0 |  |
| L7_TEST_DEBUG | 11 | 0 |  |
| L8_RTL_CONSTANTS | 19 | 0 |  |
| L8_TIMING_WAVEFORM | 13 | 0 |  |
| L9_INTEGRATION_SPEC | 16 | 0 |  |
| (unallocated) | 0 | 0 | 2 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
