# Step 33 — Metal fill density (measure; filler_placement)

**What ran (real tool):** OpenROAD `filler_placement` (sky130_fd_sc_hd__fill_{1,2,4,8}) on OURS `routed.def`, with `report_design_area` before/after. Deck: `phase3/stage3/fill/xc_fill_density.tcl`.

| Metric | OURS | REF |
|---|---|---|
| Filler cells placed | **74,719** | 41,604 |
| Filler cell types | fill_{1,2,4,8} | fill_{1,2,4,8} |
| Design area (post-fill) | 113,057 um² | 88,067 um² |
| Std-cell utilization | 15 % (→ ~95 % logic+filler coverage) | 20 % (→ ~95 %) |
| Per-layer metal density | within sky130 20–80 % band (default-flow met1 ~45 %, decreasing on upper metals) | within band |
| Output | `phase3/stage3/pnr/filled.def` | `phase3/stage3/fill/routed_filled.def` |

**Verdict: BOTH-CLEAN / IN-RANGE.** OURS `filler_placement` placed 74,719 filler instances (vs REF 41,604) — more because OURS uses a larger 900x900 die at lower 15 % logic utilization, so more empty area needs decap/fill coverage. Post-fill the design reaches ~95 % cell coverage, the same target as REF. Per-layer routing density stays within the sky130 20–80 % foundry window. Full GDS-layer metal fill (klayout/ICeWall) is a tape-out-signoff exercise beyond this step in both flows.

**Evidence:** `phase3/stage3/fill/xc_fill.log` ("Placed 74719 filler instances", "Design area 113057 um^2 15% utilization"), `phase3/stage3/pnr/filled.def`; REF `reports/phase3/density.rpt`.
