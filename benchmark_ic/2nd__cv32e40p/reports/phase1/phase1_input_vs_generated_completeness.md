# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 347
  - design cells (clean context, gated): 347
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 319 (91.9%)
**Program-only cells**: 306
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 28

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| source__control_status_registers.txt | 136 | 136 | 0 | 134 | 0 | 2 | FAIL |
| source__verification.txt | 65 | 65 | 0 | 60 | 0 | 5 | FAIL |
| source__intro.txt | 47 | 47 | 0 | 44 | 0 | 3 | FAIL |
| source__instruction_set_extensions.txt | 36 | 36 | 0 | 25 | 0 | 11 | FAIL |
| source__perf_counters.txt | 31 | 31 | 0 | 31 | 0 | 0 | PASS |
| source__integration.txt | 29 | 29 | 0 | 29 | 0 | 0 | PASS |
| source__debug.txt | 28 | 28 | 0 | 28 | 0 | 0 | PASS |
| source__exceptions_interrupts.txt | 28 | 28 | 0 | 28 | 0 | 0 | PASS |
| source__glossary.txt | 26 | 26 | 0 | 26 | 0 | 0 | PASS |
| source__pipeline.txt | 26 | 26 | 0 | 25 | 0 | 1 | FAIL |
| source__core_versions.txt | 25 | 25 | 0 | 25 | 0 | 0 | PASS |
| source__fpu.txt | 24 | 24 | 0 | 24 | 0 | 0 | PASS |
| source__load_store_unit.txt | 22 | 22 | 0 | 22 | 0 | 0 | PASS |
| images__blockdiagram.txt | 16 | 16 | 0 | 16 | 0 | 0 | PASS |
| README.txt | 15 | 15 | 0 | 15 | 0 | 0 | PASS |
| images__CV32E40P_Block_Diagram.txt | 15 | 15 | 0 | 15 | 0 | 0 | PASS |
| source__corev_hw_loop.txt | 15 | 15 | 0 | 14 | 0 | 1 | FAIL |
| source__instruction_fetch.txt | 13 | 13 | 0 | 13 | 0 | 0 | PASS |
| Makefile.txt | 12 | 12 | 0 | 7 | 0 | 5 | FAIL |
| images__obi_data_multiple_outstanding.txt | 12 | 12 | 0 | 12 | 0 | 0 | PASS |
| source__sleep.txt | 12 | 12 | 0 | 12 | 0 | 0 | PASS |
| source__register_file.txt | 10 | 10 | 0 | 10 | 0 | 0 | PASS |
| images__obi_data_back_to_back.txt | 8 | 8 | 0 | 8 | 0 | 0 | SKIP_LOW_TOKENS |
| source__index.txt | 8 | 8 | 0 | 8 | 0 | 0 | SKIP_LOW_TOKENS |
| source__preface.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| images__debug_halted.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| images__debug_running.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| images__obi_instruction_basic.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| images__obi_data_basic.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| images__obi_data_slow_response.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| images__wfi.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| images__load_event.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| images__obi_instruction_multiple_outstanding.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| requirements.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 2 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L1_DATASHEET | 244 | 0 |  |
| L2_FRS | 69 | 0 |  |
| L3_CMD_PROTOCOL | 2 | 0 |  |
| L4_REGMAP | 80 | 0 |  |
| L5_ADI_SPEC | 16 | 0 |  |
| L6_CONTROL_LOGIC | 4 | 0 |  |
| L7_TEST_DEBUG | 1 | 0 |  |
| L8_RTL_CONSTANTS | 26 | 0 |  |
| L8_TIMING_WAVEFORM | 1 | 0 |  |
| L9_INTEGRATION_SPEC | 19 | 0 |  |
| (unallocated) | 0 | 0 | 28 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
