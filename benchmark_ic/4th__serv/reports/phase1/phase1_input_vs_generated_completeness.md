# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: PASS
**Raw cell matches across non-reference docs**: 112
  - design cells (clean context, gated): 112
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 112 (100.0%)
**Program-only cells**: 107
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 3
**Missing everywhere**: 0

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| doc__servant.txt | 64 | 64 | 0 | 64 | 0 | 0 | PASS |
| README.txt | 22 | 22 | 0 | 22 | 0 | 0 | PASS |
| doc__interface.txt | 21 | 21 | 0 | 21 | 0 | 0 | PASS |
| doc__servile.txt | 17 | 17 | 0 | 14 | 3 | 0 | PASS |
| doc__modules.txt | 15 | 15 | 0 | 15 | 0 | 0 | PASS |
| doc__serving.txt | 14 | 14 | 0 | 14 | 0 | 0 | PASS |
| PROVENANCE.txt | 8 | 8 | 0 | 8 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__overview.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__index.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__subservient.txt | 3 | 3 | 0 | 3 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__reservoir.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__datasheet.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__internals.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 0 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L1_DATASHEET | 101 | 0 |  |
| L2_FRS | 80 | 0 |  |
| L3_CMD_PROTOCOL | 0 | 0 |  |
| L4_REGMAP | 0 | 0 |  |
| L5_ADI_SPEC | 17 | 0 |  |
| L6_CONTROL_LOGIC | 0 | 0 |  |
| L7_TEST_DEBUG | 1 | 0 |  |
| L8_RTL_CONSTANTS | 25 | 3 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 20 | 0 |  |
| (unallocated) | 0 | 0 | 0 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
