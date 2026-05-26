# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 77
  - design cells (clean context, gated): 77
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 74 (96.1%)
**Program-only cells**: 74
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 3

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| README.txt | 55 | 55 | 0 | 53 | 0 | 2 | FAIL |
| overview.txt | 47 | 47 | 0 | 46 | 0 | 1 | FAIL |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 3 | 0 |  |
| L11_OTP_CONTENT | 3 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 3 | 0 |  |
| L13_LAB_CALIBRATION | 3 | 0 |  |
| L1_DATASHEET | 71 | 0 |  |
| L2_FRS | 22 | 0 |  |
| L3_CMD_PROTOCOL | 5 | 0 |  |
| L4_REGMAP | 3 | 0 |  |
| L5_ADI_SPEC | 4 | 0 |  |
| L6_CONTROL_LOGIC | 4 | 0 |  |
| L7_TEST_DEBUG | 6 | 0 |  |
| L8_RTL_CONSTANTS | 5 | 0 |  |
| L8_TIMING_WAVEFORM | 3 | 0 |  |
| L9_INTEGRATION_SPEC | 28 | 0 |  |
| (unallocated) | 0 | 0 | 3 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
