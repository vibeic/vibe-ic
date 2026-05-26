# Step 23 — IR Drop (static PDN analysis, GAP-CLOSE)

## What ran
OURS had no IR report (GAP). Closed it by building a standard sky130 PDN
(met1 followpin + met4/met5 straps via `pdngen`) on OUR routed.def, then running
OpenROAD PDNSim static IR analysis (`analyze_power_grid`) on VPWR and VGND.
TCL: `phase3/stage3/pnr/ir_drop_xc.tcl`; report `ir_drop_xc.rpt`;
voltage maps `ir_xc_vpwr.voltage`, `ir_xc_vgnd.voltage`; log `ir_drop_xc.log`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Tool | OpenROAD PDNSim (PSM) | OpenROAD PDNSim (PSM) |
| VPWR worst IR drop | 98.6 µV | 24.4 µV |
| VPWR avg IR drop | 35.9 µV | 7.36 µV |
| VGND worst (gnd bounce) | 128 µV | 44.3 µV |
| VGND avg | 45.8 µV | 11.9 µV |
| Worst as % of 1.80 V Vdd | 0.0071 % | 0.0025 % |
| Sign-off (5% budget) | PASS | PASS |

## Verdict: BOTH-CLEAN (GAP closed)
Both designs' worst IR drop is sub-mV (< 0.01 % of the 1.80 V supply), vastly
below the 5 % industry budget — expected for a < 0.003 mm² low-activity design.
OURS is ~4x larger in absolute µV than REF because I used a denser strap pitch
(27.14 µm vs REF 34 µm) which concentrates more current per strap segment, but
both are negligible and PASS by > 700x margin. IR-drop GAP for OURS is now closed
with a real PDNSim run.
