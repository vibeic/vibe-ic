# Step 18 — Design-for-ECO: spare-cell pool (coverage + preservation)

**What ran (real tools, `iic-eda`):** OURS PnR was re-run with the phase3 Design-for-ECO insertion (`--spare-density 0.02`): a DISTRIBUTED, tied-off pool of spare std cells inserted as PHYSICAL, `dont_touch`-protected instances AFTER detailed placement and BEFORE CTS; CTS / hold-fix / route / metal-fill then completed WITH the spares present. The two plugin checkers (`spare_cell_coverage_check.py`, `spare_cell_preservation_check.py`) were run on the final netlist + DEF + GDS. REF (`4th_benchmark/sha256_v2_e2e`) was searched for any spare pool.

| Metric | OURS (Design-for-ECO) | REF (secworks run) |
|---|---|---|
| Spare std cells inserted | **203** (inv 51 / nand2 41 / nor2 31 / mux2 30 / aoi 20 / oai 10 / dff 20) | **0** |
| Spare density (count / placed-cell est.) | **0.020022** (target 0.02) | 0 |
| Distribution | **203 distinct grid positions** (spread on a √N grid across the core) — distribution_ok | n/a |
| Tie-off | all tied off (`tied_off=true`) — tie_off_ok | n/a |
| Protection | every spare `set_dont_touch` in-tool + `+ FIXED` in DEF (recognized keep marker) | none |
| Coverage verdict | **PASS** (`reports/spare_cell_coverage.json`) | — |
| Preservation: inserted / survived / removed | **203 / 203 / 0** | n/a |
| `all_keep_attr_intact` | **true** (`keep_check_applied=true`, FIXED markers found) | n/a |
| Preservation verdict | **PASS** (`reports/spare_preservation.json`) | — |
| `dont_touch` count in REF layout/netlist | — | **0 spares / 0 dont_touch** (verified absent) |

**Verdict: BETTER-THAN-REF.** OURS carries a complete, verified metal-only-ECO budget — 203 distributed, tied-off, `dont_touch`/FIXED spare std cells at density 0.0200, **coverage PASS** and **preservation intact (removed:0, all_keep_attr_intact:true)**. The spares SURVIVED every downstream optimization pass (CTS / repair_timing / detailed_placement re-legalize / global+detailed route / metal fill) — proven by name-survival in the final `sha256_pnr.v` + `sha256.def` + `filled.def` + magic GDS, with the FIXED placement-status marker intact. The REF sha256 run has **no spare pool and no `dont_touch`** (a metal-only ECO would require a base-layer respin), so OURS is strictly better on Design-for-ECO readiness.

**Sign-off STILL HOLDS with the spares present (re-verified, not assumed):**
- **Routing:** detailed route converged to **0 violations** with the 203 spares in the DB (`openroad_spare.log`, DRT-0199 = 0).
- **9-corner STA @25.9 ns:** every corner setup ≥ 0 AND hold ≥ 0 — worst setup **+4.836 ns** (SS_cold_n40C_1v60), worst hold **+0.280 ns** (FF_n40C_1v95). Values are bit-identical to the pre-spare baseline → the tied-off FIXED spares are timing-neutral (they drive no signal path). (`sta_9corner_spare.log`.)
- **DRC:** klayout `sky130A.lydrc` full deck on the regenerated **25.97 MB** magic GDS (non-vacuous — 237,778 raw polygons read) = **0 violations** (`sha256_signoff_drc_spare.lyrdb`).
- **Metal fill:** 74,737 filler cells placed AFTER the spares, with all 203 spares preserved (`filler_placement` is ECO-aware — FIXED spares are obstacles, never overlapped/stripped).

**Caveat (honest):** sha256 is a core-only digital block (no pad ring in this sky130 PnR flow), so reserved ECO *I/O pads* are N/A — the metal-only-ECO budget is carried entirely by the 203 FIXED/`dont_touch` std-cell spares. No SPEF was produced (RCX-0134 in this OpenROAD build, same as the signed-off baseline), so STA uses the placement-RC `estimate_parasitics` fallback — identical method to the verified baseline, so the comparison is apples-to-apples.

**Evidence:** `phase3/stage3/pnr/spare_cells.json`, `reports/spare_cell_coverage.json` (PASS), `reports/spare_preservation.json` (removed:0, all_keep_attr_intact:true), `phase3/stage3/pnr/{sha256.def,sha256_pnr.v,filled.def}` (203 `+ FIXED` spares), `phase3/stage4/gds/sha256_magic.gds` (25.97 MB), `phase3/stage3/pnr/{openroad_spare.log,sta_9corner_spare.log,sha256_signoff_drc_spare.lyrdb}`; REF `4th_benchmark/sha256_v2_e2e` (no spare files, no `spare`/`dont_touch` token in any DEF/netlist).
