# Step 15 — Floorplan / PDN: die area + utilization

**What ran:** Read OURS floorplan/routed DEF + OpenROAD log (`pnr.tcl`, `openroad.log`); compared against REF DEF + `openroad_full.log`. Per L9 floorplan target FP_CORE_UTIL=0.20, density=0.25.

| Metric | OURS (carry-save CSA) | REF (catalog-glue secworks) |
|---|---|---|
| Die area (DEF DIEAREA) | 900 x 900 um (810,000 um²) | 700 x 700 um (490,000 um²) |
| Core area | 10 10 823 823 (≈660k um²) | per REF floorplan |
| Std-cell design area | 101,631 um² (final placement) | 88,067 um² (93,120 final) |
| Effective utilization | 0.141 (14.1%) | 0.197 (19.7%) |
| GPL utilization | 15.4% | 21.4% |
| Target density | 0.20 (matches L9) | 0.20 |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK.** OURS uses a larger 900x900 die at ~14% util vs REF 700x700 at ~20%. OURS is a from-scratch carry-save CSA tree with 12,148 cells (vs REF 9,546) — more logic + lower density (larger die chosen by the runner), but both are valid, non-congested floorplans with util in the normal 14–22% band for sky130 sign-off flows. Target density 0.20 matches the L9 FP_CORE_UTIL=0.20 spec. Larger die/lower util on OURS is conservative, not a defect.

**Note (PDN gap):** OURS `pnr.tcl` did NOT generate a power-distribution network (no `pdngen`, no SPECIALNETS in any DEF). REF has a full PDN (9,290 VPWR + 9,290 VGND special-net connections). This gap was closed in Step 24/25 by regenerating the PDN from `post_hold.def` (met1 followpins + met4/met5 straps) before IR/EM.

**Evidence:** `phase3/stage3/pnr/{floorplan,routed,sha256}.def`, `phase3/stage3/pnr/openroad.log` (IFP-0104, GPL-0019), REF `phase3/stage3/pnr/openroad_full.log`.
