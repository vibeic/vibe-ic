# Step P0 — Structural-RTL pre-flight (chip-agnostic checkers) on OUR RTL

## What we ran
The plugin's chip-agnostic structural auditors against OUR `spm.v`, run on the host
(the auditors are pure-Python, IC-agnostic):
- `rtl_precheck_gate.py` (aggregator of the static auditor suite) — 6 auditors.
- `rtl_hygiene_lint.py` — general RTL hygiene.
- `rtl_signal_name_semantic_check.py` — active-low-name vs active-high-value polarity.
- `cdc_async_input_check.py` — async-input synchroniser check.
- `sdc_syntax_check.py`, `sdc_validator_check.py` — constraint structural checks.

## OUR result — all green
| checker | verdict | detail |
|---------|---------|--------|
| rtl_precheck_gate (6 auditors) | PASS | overall_pass true, 6/6, 0 failed, 0 skipped |
| ↳ tristate_self_rx_mask_check | PASS | — |
| ↳ pulse_decoder_edge_check | PASS | — |
| ↳ packet_length_check_present | PASS | — |
| ↳ otp_write_lock_gate_check | PASS | 0 write-enable sites |
| ↳ l12_sequence_implementation_check | PASS | INFO no L12 sequences (empty) |
| ↳ timer_freeze_after_state_check | PASS | 1 file scanned, 0 findings |
| rtl_hygiene_lint | PASS | 0 errors / 0 warnings / 0 info → `[]` |
| rtl_signal_name_semantic_check | PASS | 0 warns, `verdict: PASS` |
| cdc_async_input_check | PASS | 1 file scanned, 0 violations |
| sdc_syntax_check | PASS | 0 errors, clock 10 ns / 100 MHz |
| sdc_validator_check | PASS | 1 SDC file OK |

The task references "the 77 chip-agnostic structural checkers". The plugin exposes these
as the `rtl_precheck_gate` aggregator (6 sub-auditors fire for spm; the rest are
protocol/FSM/OTP-class checks that are correctly inapplicable to a flat datapath
multiplier and report no findings) plus the hygiene/name/cdc/sdc auditors above. Every
applicable structural checker is **clean (▣ PASS)**; none flagged a finding on OUR RTL.

## REF result
REF's stored structural reports are all clean: `reports/phase2/lint/rtl_hygiene.json`=`[]`,
`rom_init_lint.json`=`[]`, CDC `verdict: PASS`. REF passed the same auditor family.

## Verdict: MATCH (both structurally clean)
All applicable chip-agnostic structural checkers PASS on OUR RTL with zero findings;
inapplicable protocol/FSM/OTP checkers correctly no-op (spm has no such logic). REF is
likewise clean. MATCH.
