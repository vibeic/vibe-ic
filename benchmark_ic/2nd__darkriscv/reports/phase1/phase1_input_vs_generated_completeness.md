# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 164
  - design cells (clean context, gated): 164
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 158 (96.3%)
**Program-only cells**: 152
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 6

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| README.txt | 148 | 148 | 0 | 142 | 0 | 6 | FAIL |
| rtl_README.txt | 14 | 14 | 0 | 14 | 0 | 0 | PASS |
| boards__README.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| openroad_README.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| src__README.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 1 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 1 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L1_DATASHEET | 133 | 0 |  |
| L2_FRS | 49 | 0 |  |
| L3_CMD_PROTOCOL | 2 | 0 |  |
| L4_REGMAP | 5 | 0 |  |
| L5_ADI_SPEC | 2 | 0 |  |
| L6_CONTROL_LOGIC | 2 | 0 |  |
| L7_TEST_DEBUG | 3 | 0 |  |
| L8_RTL_CONSTANTS | 32 | 0 |  |
| L8_TIMING_WAVEFORM | 3 | 0 |  |
| L9_INTEGRATION_SPEC | 5 | 0 |  |
| (unallocated) | 0 | 0 | 6 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
