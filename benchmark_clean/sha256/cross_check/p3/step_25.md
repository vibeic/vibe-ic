# Step 25 — Electromigration (analyze_power_grid -enable_em) (GAP CLOSED)

**Gap:** Same root cause as Step 24 — no PDN existed on OURS, so EM analysis could not run. Closed by rebuilding the PDN first.

**What ran (real tool):** OpenROAD `analyze_power_grid -net VPWR/VGND -enable_em` on the PDN-rebuilt OURS design. Script: `phase3/stage3/ir_drop/xc_pdn_ir_em.tcl`.

| Metric | OURS VPWR | OURS VGND | REF VPWR | REF VGND |
|---|---|---|---|---|
| Max current | 2.55e-04 A | 2.28e-04 A | 3.43e-04 A | 2.66e-04 A |
| Avg current | 5.10e-06 A | 4.86e-06 A | 4.29e-06 A | 4.74e-06 A |
| PDN resistors analyzed | 22,961 | 23,958 | 16,230 | 15,522 |
| EM limit (Javg) | 4.0 mA/um, 10-yr lifetime | | 4.0 mA/um, 10-yr | |
| Verdict | CLEAN | CLEAN | CLEAN | CLEAN |

**Verdict: GAP CLOSED / BOTH-CLEAN / IN-RANGE.** OURS EM currents (max 2.55e-04 A on VPWR) are the same order as REF (3.43e-04 A); per-segment currents are far below the sky130 4.0 mA/um Javg / 10-year-lifetime limit. OURS has more PDN resistors (22,961 vs 16,230) because its grid covers a larger 900x900 die. No EM hotspots reported by OpenROAD.

**Evidence:** `phase3/stage3/ir_drop/pdn_ir_em.log` (EM analysis VPWR/VGND blocks); REF `reports/phase3/em.json`.
