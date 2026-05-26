# Step 33 — Tapeout Checklist

## What ran
Compared OUR `reports/audit/tapeout_checklist.json` (signoff_audit:tapeout) against
the REF `reports/final_summary.md` signoff summary, and cross-referenced the
GAP-close signoff artifacts produced in this cross-check.

## Side-by-side
| signoff item | OURS | REF |
|---|---|---|
| GDS exists | yes (spm.gds) | yes (spm.gds) |
| Netlist exists | yes (spm_pnr.v) | yes |
| Timing (STA) | yes, all corners MET (step_22) | yes, all corners MET |
| DRC | WAIVED (li-internal only, 0 met2+) — step_29 | WAIVED (same li class) |
| LVS | device-exact 3176/3176 — step_29 | device-exact 3176/3176 |
| Antenna | 0/0 (step_25, run here) | 0/0 |
| IR drop | < 0.01% Vdd (step_23, run here) | < 0.01% Vdd |
| EM | 34.5% J_max (step_24, run here) | 10.7% J_max |
| SI crosstalk | < 0.1 fF coupling (step_26) | 35 ps bound |
| Power | 1.79e-4 W (step_31) | 1.57e-4 W |
| Post-layout sim | gate sim PASS 10013 vec (step_27) | flag approximation |
| Tapeout verdict | PASS (evidence 4/4) | PASS_WITH_WAIVERS |

## Verdict: BOTH-CLEAN / PASS_WITH_WAIVERS
OUR tapeout checklist gate is PASS (all required evidence present). After this
cross-check, OURS now has the full signoff matrix (DRC/LVS/STA/antenna/IR/EM/SI/
power/post-sim) populated with real tool runs — equal to or beyond the REF's
coverage. Both carry the same documented waivers (DRC li-deck class deferred to
foundry Calibre sign-off; full-chip SPICE/SDF-timing deferred). Equivalent
tapeout readiness.
