# Phase 1 (doc-extraction) — input → generated_docs cell completeness

**Verdict**: FAIL
**Raw cell matches across non-reference docs**: 316
  - design cells (clean context, gated): 316
  - garble / PDF-DOC binary artefact cells (reported, NOT gated): 0
**Captured (program + AI)**: 219 (69.3%)
**Program-only cells**: 203
**AI-only cells (extraction_strategy = ai_deep_review_patch)**: 0
**Missing everywhere**: 97

## Per-document cell counts

| Document | raw_total | design | garble | program_captured | ai_captured | missing | verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| doc__03_reference__verification_stages.txt | 87 | 87 | 0 | 33 | 0 | 54 | FAIL |
| doc__03_reference__cs_registers.txt | 75 | 75 | 0 | 70 | 0 | 5 | FAIL |
| doc__03_reference__coverage_plan.txt | 65 | 65 | 0 | 65 | 0 | 0 | PASS |
| doc__03_reference__performance_counters.txt | 44 | 44 | 0 | 17 | 0 | 27 | FAIL |
| doc__03_reference__verification.txt | 29 | 29 | 0 | 28 | 0 | 1 | FAIL |
| doc__02_user__integration.txt | 23 | 23 | 0 | 20 | 0 | 3 | FAIL |
| README.txt | 17 | 17 | 0 | 17 | 0 | 0 | PASS |
| doc__03_reference__instruction_decode_execute.txt | 17 | 17 | 0 | 17 | 0 | 0 | PASS |
| doc__03_reference__exception_interrupts.txt | 14 | 14 | 0 | 12 | 0 | 2 | FAIL |
| doc__03_reference__cosim.txt | 12 | 12 | 0 | 10 | 0 | 2 | FAIL |
| doc__03_reference__icache.txt | 11 | 11 | 0 | 11 | 0 | 0 | PASS |
| doc__03_reference__tracer.txt | 10 | 10 | 0 | 7 | 0 | 3 | FAIL |
| doc__03_reference__pipeline_details.txt | 9 | 9 | 0 | 9 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__01_overview__compliance.txt | 7 | 7 | 0 | 7 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__02_user__configuration.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__history.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__instruction_fetch.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__load_store_unit.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__pmp.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__testplan.txt | 6 | 6 | 0 | 6 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__02_user__examples.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__02_user__system_requirements.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__register_file.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__security.txt | 5 | 5 | 0 | 5 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__01_overview__verification_overview.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__debug.txt | 4 | 4 | 0 | 4 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__01_overview__index.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__01_overview__targets.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__rvfi.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__index.txt | 2 | 2 | 0 | 2 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__01_overview__licensing.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__02_user__getting_started.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__04_developer__index.txt | 1 | 1 | 0 | 1 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__02_user__index.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__03_reference__index.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |
| doc__04_developer__concierge.txt | 0 | 0 | 0 | 0 | 0 | 0 | SKIP_LOW_TOKENS |

## Per-Layer cell counts

| Layer | caught_cells | ai_patched_cells | missing_cells |
| --- | ---: | ---: | ---: |
| L10_TEST_CASES | 2 | 0 |  |
| L11_OTP_CONTENT | 0 | 0 |  |
| L12_BEHAVIORAL_SEQUENCES | 0 | 0 |  |
| L13_LAB_CALIBRATION | 0 | 0 |  |
| L1_DATASHEET | 171 | 0 |  |
| L2_FRS | 83 | 0 |  |
| L3_CMD_PROTOCOL | 1 | 0 |  |
| L4_REGMAP | 56 | 0 |  |
| L5_ADI_SPEC | 17 | 0 |  |
| L6_CONTROL_LOGIC | 11 | 0 |  |
| L7_TEST_DEBUG | 3 | 0 |  |
| L8_RTL_CONSTANTS | 18 | 0 |  |
| L8_TIMING_WAVEFORM | 5 | 0 |  |
| L9_INTEGRATION_SPEC | 34 | 0 |  |
| (unallocated) | 0 | 0 | 97 |

Cell = chip-AGNOSTIC vendor token harvested from input docs (numeric+unit, hex const, register / pin / opcode identifier, section ref, etc.). `program_captured` = caught by deterministic phase1 programs. `ai_captured` = caught only inside an AI-patched sub-tree (`extraction_strategy: ai_deep_review_patch`) added by the `phase1-completeness-deep-review` skill. `missing` = present in input doc but in no L*.json.
