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
| ~~spm × IHP-SG13G2~~ | **RETIRED 2026-08-09 — NOT A CELL** (row kept as history; was: PASS_WITH_WAIVERS) | `spm` declares sky130A primary + gf180mcuD secondary and the run's own L19 says `pdk_target: sky130` — see `ic/CELL_MATRIX.md`. Evidence moved to `ic/spm/retired/v1.5.58_ihp-sg13g2/` (`RETIRED.md` there); **do not cite it as a result**. |
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
| ~~u_hawaii_adc × sky130A~~ | **RETIRED 2026-08-09 — NOT A CELL** (row kept as history; was: FAIL) | `u_hawaii_adc` declares **ihp-sg13g2** (L19 `pdk_target: sg13g2`; L1 "Target PDK **IHP SG13G2**"); `sky130` appears 0 times in its input docs — see `ic/CELL_MATRIX.md`. Evidence moved to `ic/u_hawaii_adc/retired/v1.9.86_sky130A/` (`RETIRED.md` there); **do not cite it as a result**. The declared cell `u_hawaii_adc × ihp-sg13g2` is unpublished. |

> **The denominator in this file's header is not derived.** It says "12 cells";
> `ic/CELL_MATRIX.md` (2026-08-09) derives **11** cells from the designs' own
> `L19`/`L1` declarations, and two rows in the table above are among the
> combinations it lists as **not cells at all**. Those two rows are struck
> through and kept — the header line is left at its 2026-08-02 wording because
> re-stamping a historical count against a matrix it was not derived from is the
> fabrication `CELL_MATRIX.md` exists to prevent. **Take the cell population
> from `ic/CELL_MATRIX.md`, not from this table.**

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
