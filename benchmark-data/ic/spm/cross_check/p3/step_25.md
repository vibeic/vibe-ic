# Step 25 — Electromigration (EM, GAP-CLOSE)

## What ran
OpenROAD `analyze_power_grid -enable_em` on OUR routed.def with the regenerated
PDN (same as step_23). The tool DOES support EM (`-enable_em -em_outfile`).
TCL: `phase3/stage3/pnr/em_xc.tcl`; report `em_xc.rpt`; per-segment current CSVs
`em_xc_vpwr.csv` (1203 segs), `em_xc_vgnd.csv` (1238 segs); log `em_xc.log`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Tool | OpenROAD PDNSim EM | OpenROAD PDNSim EM |
| VPWR max current | 65.2 µA | 14.2 µA |
| VGND max current | 82.7 µA | 25.7 µA |
| Worst current density | 0.1723 mA/µm | 0.0535 mA/µm |
| sky130 met1 J_max guidance | 0.5 mA/µm | 0.5 mA/µm |
| Worst as % of J_max | 34.5 % | 10.7 % |
| Sign-off | PASS (> 2.9x margin) | PASS (> 9x margin) |

## Verdict: BOTH-CLEAN (GAP closed)
The EM tool IS available (OpenROAD PDNSim) — closed with a real run, not a
NO-TOOL. Both designs pass the 10-year EM lifetime check. OUR worst current
density (34.5 % of J_max) is higher than REF (10.7 %) because the denser PDN
strap pitch I used carries more current per met1 followpin segment; both remain
comfortably below the 0.5 mA/µm sky130 met1 guidance with > 2.9x margin. PASS.
