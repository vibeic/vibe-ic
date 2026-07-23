# Benchmark IC campaign — open-PDK IC×PDK matrix status

_Last updated: 2026-07-24, plugin v1.5.65. Unit = one (IC × PDK) cell — the
same IC on a different PDK is a distinct result. Status is independently
re-derived from raw run artifacts (GDS, DRC/LVS/STA reports), never from a
run's own RESULT.md/AGENT_REPORT.md alone. This tracks the OPEN-PDK matrix
(sky130A / GF180MCU / IHP-SG13G2 / NanGate45); the separate commercial-PDK
sign-off track for spm/subservient/sha256/u_hawaii_adc is reported elsewhere
and is not part of this table._

| IC × PDK | Status | Residual |
|---|---|---|
| spm × IHP-SG13G2 | **PASS_WITH_WAIVERS** | None (foundry/board-stage waivers only) — see `ic/spm/ihp-sg13g2/RESULT.md` |
| spm × sky130A | FAIL | Equivalence check (RTL vs post-DFT netlist) genuinely non-equivalent; a marginal (sub-ns) post-route STA DRV after a reroute fix |
| spm × GF180MCU | FAIL | DFT at-speed ATPG residual on this PDK's synthesis path; Tapeout-checklist DRC follow-up |
| sha256 × sky130A | FAIL | Post-route STA sign-off setup gap at the slow corner |
| caravel_user_project × sky130A | FAIL | Multiple stage1-3 residuals under active investigation (a recent PnR repair-escalation fix was found to regress this cell and has been reverted; re-converging) |
| edge_llm_accel × NanGate45 | FAIL | Re-verification in progress |
| edge_llm_matmul_accel × NanGate45 | FAIL | Multiple residuals across synthesis/PnR/sign-off; needs re-run on the latest plugin |
| ibex × sky130A | FAIL | DFT ATPG + physical-verification + tapeout-checklist residuals; needs re-run on the latest plugin (P0 gate fix already landed separately) |
| opentitan_aes × sky130A | FAIL | Post-route STA setup gap at the sign-off corner; antenna + PERC reliability sign-off pending |
| subservient × sky130A | FAIL | Needs re-run on the latest plugin (Step P0 + Step 4 fixes landed since this cell's last run) |
| subservient × GF180MCU | FAIL | Needs re-run on the latest plugin (same fixes as above) |
| u_hawaii_adc × sky130A | FAIL | Analog corner-sweep (PVT) residual |

## What "PASS" requires here

A cell counts as converged only when independently re-derived from raw
artifacts: real GDS present, 0 sign-off DRC violations (raw report), LVS
"Circuits match uniquely" (raw netgen tail), multi-corner STA MET (raw STA
report, not a gate's cached verdict), and no fabricated/waived-away residual
standing in for a real defect. See `checks-that-lie-campaign` doctrine:
a gate that measures something adjacent to the real question and reports it
as an answer is exactly the failure mode this campaign exists to eliminate —
including in its own tooling (one PnR repair-escalation fix this session
passed its own internal check but regressed the real downstream sign-off
report; it was caught on re-verification and reverted, not shipped).
