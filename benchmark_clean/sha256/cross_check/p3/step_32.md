# Step 31 — Power (report_power, SPEF-annotated)

**What ran (real tool):** OpenSTA `report_power` on OURS `routed.def` with the freshly-extracted SPEF annotated (Step 21), TT corner. Compared to REF `report_power` and OURS pre-SPEF power.rpt.

| Group | OURS (SPEF-annotated) | OURS (pre-SPEF) | REF |
|---|---|---|---|
| Sequential | 2.664e-03 W (42.9 %) | 2.80e-03 W (84.5 %) | 3.52e-03 W (98.0 %) |
| Combinational | 2.256e-04 W (3.6 %) | 5.12e-04 W (15.5 %) | 7.32e-05 W (2.0 %) |
| Clock | 3.320e-03 W (53.5 %) | 0 (not annotated) | 0 |
| **Total** | **6.21e-03 W** | 3.31e-03 W | 3.60e-03 W |
| Internal / Switching / Leakage | 78.5 / 21.5 / 0.0 % | 89.6 / 10.4 / 0.0 % | 98.7 / 1.3 / 0.0 % |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK.** OURS SPEF-annotated total power is 6.21 mW. Once the SPEF is annotated, OURS correctly attributes 53.5 % of power to the **clock network** (3.32 mW) — the carry-save design has a 1,556-sink clock tree at 25.9 ns, and SPEF gives the clock-net RC its real switching cost. REF reported 3.60 mW but with clock power = 0 (its power.rpt was not SPEF-annotated on the clock, so it under-counts clock tree power — a REF-side measurement limitation, not lower real power). OURS's higher total reflects more cells + honest clock-tree accounting; leakage is ~31 nW in both, negligible. Same tool (OpenSTA report_power), same TT corner.

**Evidence:** `phase3/stage3/extracted/power_spef.rpt`, `phase3/stage3/extracted/xc_signoff.log`; REF `reports/phase3/power.rpt`.
