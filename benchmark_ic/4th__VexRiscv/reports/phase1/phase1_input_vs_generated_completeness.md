# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 286
  - design cells (clean context, gated): 286
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 262 (91.6%)
**Program-only cells**: 255
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 24

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| README.txt | 196 | 196 | 0 | 190 | 0 | 6 | FAIL |
| doc__gcdPeripheral__README.txt | 38 | 38 | 0 | 27 | 0 | 11 | FAIL |
| doc__gcdPeripheral__src__main__c__murax__gcd_world__makefile.txt | 28 | 28 | 0 | 28 | 0 | 0 | PASS |
| doc__nativeJtag__README.txt | 25 | 25 | 0 | 21 | 0 | 4 | FAIL |
| doc__vjtag__README.txt | 17 | 17 | 0 | 14 | 0 | 3 | FAIL |
| doc__smp__smp.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 1 | 0 |  |
| L11_OTP_CONTENT | 1 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 1 | 0 |  |
| L13_LAB_CALIBRATION | 1 | 0 |  |
| L1_DATASHEET | 217 | 0 |  |
| L2_FRS | 111 | 0 |  |
| L3_CMD_PROTOCOL | 2 | 0 |  |
| L4_REGMAP | 3 | 0 |  |
| L5_ADI_SPEC | 22 | 0 |  |
| L6_CONTROL_LOGIC | 5 | 0 |  |
| L7_TEST_DEBUG | 5 | 0 |  |
| L8_RTL_CONSTANTS | 65 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 63 | 0 |  |
| (unallocated) | 0 | 0 | 24 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
