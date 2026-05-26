# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 120
  - design cells (clean context, gated): 120
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 120 (100.0%)
**Program-only cells**: 120
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| README.txt | 94 | 94 | 0 | 94 | 0 | 0 | PASS |
| picosoc_README.txt | 28 | 28 | 0 | 28 | 0 | 0 | PASS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 1 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 1 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L1_DATASHEET | 112 | 0 |  |
| L2_FRS | 57 | 0 |  |
| L3_CMD_PROTOCOL | 3 | 0 |  |
| L4_REGMAP | 2 | 0 |  |
| L5_ADI_SPEC | 36 | 0 |  |
| L6_CONTROL_LOGIC | 2 | 0 |  |
| L7_TEST_DEBUG | 2 | 0 |  |
| L8_RTL_CONSTANTS | 56 | 0 |  |
| L8_TIMING_WAVEFORM | 2 | 0 |  |
| L9_INTEGRATION_SPEC | 73 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
