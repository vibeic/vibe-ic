# Step 17 — Placement (density + legality)

## What ran
OpenROAD `check_placement -verbose` + `report_design_area` on OUR and REF
`routed.def` in the iic-eda container; placement target density and
utilization from the PnR `openroad.log`.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| check_placement | clean (no overlap / off-site / region errors) | clean |
| Design area | 2029 µm² | 2883 µm² |
| Placed utilization | 7.49% (GPL) / 7% (report) | 10.50% (GPL) / 10% (report) |
| Placement target density | 0.4500 | 0.4500 |
| Final placement area (GPL) | 2143.39 | 3004.39 |

## Verdict: BOTH-CLEAN / IN-RANGE
`check_placement` reports zero violations on both — both placements are legal
(no overlaps, all cells on-site, inside core). Same target density (0.45).
OUR design area is ~70% of REF (2029 vs 2883 µm²) and utilization 7.5% vs 10.5%,
consistent with the leaner carry-save netlist (249 vs 302 cells). Legality MATCH;
density IN-RANGE.
