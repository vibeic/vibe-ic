# Benchmark IC campaign — open-PDK IC×PDK matrix status

_Last updated: 2026-08-02 (4 of 12 cells converged), plugin v1.9.56. Unit = one (IC × PDK) cell — the
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
| spm × GF180MCU | **PASS_WITH_WAIVERS** | None — see `ic/spm/gf180mcuD_20260724/RESULT.md`. Metal-fill density DRC (v1.5.66) + SS slow-corner setup (v1.5.59) both closed; GDS present, 763/763 DRC rule categories clean, LVS match, STA MET (+1.73/+0.57 ns). |
| sha256 × sky130A | FAIL | Post-route STA sign-off setup gap at the slow corner only (Step 23) — re-confirmed on a fresh v1.5.65 run |
| caravel_user_project × sky130A | **PASS_WITH_WAIVERS** | None. Closed on plugin v1.9.43 (run r15): `PASS=35 FAIL=0 MISSING=0` WAIVED-DEFERRED=3 SKIPPED=21 VACUOUS-PASS=4, `Overall: PASS_WITH_WAIVERS (strict=True)`. Streamed GDS 92,753,582 B (`sha256:205025c34762dcb12088c6044b3595816c87af9d8ad53fa5025aede04393b144`, recorded in `v1.9.43_sky130A/phase3/stage4/gds/GDS_MANIFEST.txt`; the geometry itself is not retained, per PUBLISHING.md). The Step-23 max_slew residual described in the 2026-07-24 row below was real at that time and is closed here — see `ic/caravel_user_project/v1.9.43_sky130A/RESULT.md`. |
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
