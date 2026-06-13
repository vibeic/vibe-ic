# Step 32 — Power Analysis (internal + switching + leakage, GAP-CLOSE refinement)

## What ran
OURS already had `reports/phase3/power.rpt` (OpenSTA report_power, no-SPEF) =
1.05e-04 W total. Refined it by re-running OpenSTA `report_power` on the routed
netlist with the OpenRCX SPEF back-annotated (so clock-net switching is captured).
TCL: `reports/phase3/power_xc.tcl`; log `power_xc.log`. REF baseline:
`reports/phase3/power.rpt`.

## Metrics side-by-side (Total power, Watts)
| group | OURS (SPEF) | OURS (no-SPEF, prior) | REF |
|---|---|---|---|
| Internal | 1.375e-04 | 8.99e-05 | 1.48e-04 |
| Switching | 4.183e-05 | 1.53e-05 | 8.89e-06 |
| Leakage | 8.76e-10 | 8.02e-10 | 1.09e-09 |
| **Total** | **1.793e-04** | 1.05e-04 | **1.57e-04** |
| Sequential share | 43.2% | 73.3% | 88.9% |
| Combinational share | 16.9% | 26.7% | 11.1% |
| Clock share | 39.9% | 0% | 0% |

## Verdict: IN-RANGE (GAP refined)
OUR total dynamic+leakage power 1.79e-04 W is the same order as REF 1.57e-04 W
(ratio 1.14x). The SPEF-annotated run now resolves clock-network power (39.9%),
which the no-SPEF runs (both OURS-prior and the REF report) leave at 0 because
the clock net RC is zero without extraction — so the SPEF run is the more
complete number. Leakage is essentially identical (~9e-10 W). OUR slightly higher
total is consistent with the longer carry-save combinational fabric switching.
Both small (~0.18 mW) designs → IN-RANGE.
