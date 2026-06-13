# Step 8 — SDC validation (OUR vs REF)

## What we ran
- Plugin `sdc_syntax_check.py OUR_project --json -`
- Plugin `sdc_validator_check.py OUR_project --l8 L8_TIMING_WAVEFORM.json --json -`

## OUR result
- **sdc_syntax_check: PASS** (`passed: true`, exit 0):
  - `CLOCK_PERIOD_OK  Clock period 10.0ns (100.0 MHz)`
  - `TIMING_FOUND  Found 2 timing constraint(s): ['set_input_delay','set_output_delay']`
  - summary: files_checked 1, valid_files 1, **errors 0**, clocks_found 1.
- **sdc_validator_check: PASS** — `[PASS] sdc_validator_check: 1 SDC file(s) OK`, exit 0.

## REF result
- REF `reports/phase2/sdc_check.json`: `passed: true` overall, but contains **1 ERROR**:
  `NO_TIMING_CONSTRAINT` on `phase2/stage1/fpga/chip_top.sdc` (a chip_top SDC with no
  timing constraints). REF summary: files_checked 5, valid_files 4, **errors 1**.

## Verdict: MATCH / OURS-CLEANER
Both validate. OUR single sign-off SDC passes with **0 errors**; REF's multi-file set
passes overall but carries 1 NO_TIMING_CONSTRAINT error on a chip_top SDC. OUR SDC
validation is strictly cleaner. MATCH (both pass), OURS cleaner.
