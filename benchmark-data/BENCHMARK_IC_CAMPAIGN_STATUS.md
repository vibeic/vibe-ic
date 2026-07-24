# Benchmark IC campaign — open-PDK IC×PDK matrix status

_Last updated: 2026-07-24 (2 of 12 cells converged), plugin v1.5.66. Unit = one (IC × PDK) cell — the
same IC on a different PDK is a distinct result. Status is independently
re-derived from raw run artifacts (GDS, DRC/LVS/STA reports), never from a
run's own RESULT.md/AGENT_REPORT.md alone. This tracks the OPEN-PDK matrix
(sky130A / GF180MCU / IHP-SG13G2 / NanGate45); the separate commercial-PDK
sign-off track for spm/subservient/sha256/u_hawaii_adc is reported elsewhere
and is not part of this table._

| IC × PDK | Status | Residual |
|---|---|---|
| spm × IHP-SG13G2 | **PASS_WITH_WAIVERS** | None (foundry/board-stage waivers only) — see `ic/spm/ihp-sg13g2/RESULT.md` |
| spm × sky130A | **PASS_WITH_WAIVERS** | None — see `ic/spm/sky130A_20260724/RESULT.md` |
| spm × GF180MCU | FAIL | A metal-fill/density DRC gap was found and fixed (v1.5.66, `8ee4e441`): 0 sign-off DRC violations, LVS/STA unaffected. A separate, pre-existing residual remains — IR-Drop (Step 24) and EM check (Step 25) reports are missing for this cell. A fresh full re-verification on v1.5.66 is in progress. |
| sha256 × sky130A | FAIL | Post-route STA sign-off setup gap at the slow corner only (Step 23) — re-confirmed on a fresh v1.5.65 run |
| caravel_user_project × sky130A | FAIL | A PnR repair-escalation fix (v1.5.64) was found to regress this cell and was reverted (v1.5.65). LVS is now clean again, but a fresh v1.5.65 re-run shows the underlying STA DRV count is currently WORSE than the original baseline (376–423 real violations vs. 4 originally) — root cause not yet found; this cell needs dedicated re-convergence work, not a quick fix. |
| edge_llm_accel × NanGate45 | FAIL | Re-run in progress on v1.5.65 (long-running: >8h at last check, actively progressing, not stalled) |
| edge_llm_matmul_accel × NanGate45 | FAIL | Fresh v1.5.65 run confirms multiple residuals spanning P0, synthesis handoff, DFT ATPG, CTS, sign-off STA, physical verification, and tapeout checklist — far from convergence |
| ibex × sky130A | FAIL | Fresh v1.5.65 run: DFT ATPG (DT1), physical verification (Step 31), and tapeout-checklist residuals (Steps 36/38). Phase 1 SKIPPED for this run (reused-IP design — chip_top authoring needs the AI-in-the-loop path, not a bare deterministic runner) |
| opentitan_aes × sky130A | FAIL | Re-run in progress on v1.5.65 (long-running: >5h at last check, actively progressing, not stalled) |
| subservient × sky130A | FAIL | Re-run in progress on v1.5.65 |
| subservient × GF180MCU | FAIL | Fresh v1.5.65 run: DFT ATPG (DT1), physical verification (Step 31), and tapeout-checklist residuals (Steps 36/38) |
| u_hawaii_adc × sky130A | FAIL | Analog per-block physical verification (Step A6, DRC+LVS before merge) — required outputs not yet produced; real layout still pending |

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
report; it was caught on re-verification and reverted, not shipped — see the
caravel_user_project row above for its honest current state after that
revert).
