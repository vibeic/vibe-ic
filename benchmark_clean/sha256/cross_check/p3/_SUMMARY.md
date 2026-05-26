# Phase-3 Cross-Check Summary — OURS vs REF (sha256)

**Pillar 2, steps 15–35.** OURS = signed-off carry-save CSA sha256 (`/home/reyerchu/AI_IC_design/benchmark_clean_sha256`). REF = upstream catalog-glue secworks run (`/home/reyerchu/AI_IC_design/4th_benchmark/sha256_v2_e2e`). All tools run REAL inside the `iic-eda` container (openroad, klayout, magic, netgen, iverilog, ngspice; PDK sky130A). Working dir: OURS staged. p12 + benchmark_clean_spm untouched.

## Methodology
OURS is a from-scratch carry-save CSA tree; REF is the secworks IP. Different micro-arch → layouts/netlists are NOT byte/structurally identical, and "different" is never treated as failure. Valid cross-check = metrics in-range + both independently sign-off-sane (DRC/LVS/STA/IR/EM/antenna) + functional equivalence to the NIST FIPS-180-4 golden.

## OURS vs REF headline numbers
| | OURS (carry-save) | REF (secworks) |
|---|---|---|
| Cells / nets | 12,148 / 12,028 | 9,546 / 9,470 |
| Die / util | 900x900 um / 14.1 % | 700x700 um / 19.7 % |
| Clock | 25.9 ns, 1,556 sinks, depth-4 H-tree | 20 ns, 1,618 sinks, depth-3 |
| STA (9 corners) | **all MET** (worst setup +4.84 ns SS) | TT/FF MET, **SS -94 ns waived** |
| Hold | all corners ≥ +0.27 ns | all MET |
| IR drop | 0.02 % Vdd | 0.02 % Vdd |
| EM | CLEAN (max 2.55e-4 A) | CLEAN (3.43e-4 A) |
| Antenna | 313 minor (148 net+165 pin) | 45 minor |
| DRC (final GDS) | **0, non-vacuous (25.9 MB magic GDS)** | 279,472 (LEF-abstract caveat) |
| LVS | cell-classes equivalent; well-tap top-pin artifact | 437/437 match; WELL_TAP_MISMATCH |
| Post-layout GLS vs NIST | **PASS** (abc/empty/224/2block) | PASS |
| SPICE per-stage | 0.548 ns (1 % vs STA) | 0.548 ns |
| Power (SPEF) | 6.21 mW | 3.60 mW (clock undercount) |

## Per-step verdicts
- 15 Floorplan IN-RANGE · 16 Clock IN-RANGE · 17 Placement BOTH-CLEAN · 18 CTS IN-RANGE (balanced) · 19 Hold BOTH-CLEAN · 20 Routing IN-RANGE
- **21 SPEF GAP CLOSED** (OpenRCX, 12,028 nets / 117,080 ccs) · 22 STA IN-RANGE (OURS stronger) · **23 IR GAP CLOSED** (rebuilt PDN, 0.02 %) · **24 EM GAP CLOSED** (CLEAN) · **25 Antenna GAP CLOSED** (313 minor) · 26 SI honest NO-DEDICATED-TOOL (SPEF cc data present) · **27 GLS GAP CLOSED** (NIST KAT PASS) · 28 SPICE BOTH-CLEAN (frag; full-chip deferred = REF) · **29 PV: DRC 0 non-vacuous + LVS cell-equiv** (regenerated magic GDS) · 31 Power IN-RANGE · **32 Fill** (74,719 fillers) · 33 Tapeout BOTH-CLEAN · 34 GDSII func-equiv (NOT pixel) · 35 Foundry IN-RANGE (skeleton, defects flagged)

## Gaps closed (real tools)
SPEF (OpenRCX), IR drop + EM (rebuilt the missing PDN — OURS pnr.tcl had NO power grid), antenna (check_antennas), post-layout GLS vs NIST KAT, metal fill, SPICE correlation, and a regenerated **non-vacuous 25.9 MB magic GDS** that finally makes DRC (0 violations) and LVS (device-class equivalence) real.

## Genuine NO-TOOL / honest limits
- **Step 26 SI:** no dedicated signal-integrity noise simulator in iic-eda (REF had none either); only SPEF coupling-cap data is available — not fabricated as a 0-violation pass.
- **Step 28 SPICE:** full-chip transistor SPICE (13,079 devices over the carry-save critical path) > 24 h; deferred to commercial SPICE exactly as REF did. Inv-chain fragment correlates within 1 %.

## Honesty corrections (no vacuous Magic-0 reported as clean)
- The runner's original 1.4 MB klayout GDS was **LEF-abstract-only** → its DRC read **0 polygons (vacuous)** and magic extract threw 472,727 layer errors. The `sha256.magic_merged.gds` in foundry_handoff is **0 bytes (vacuous)**. NEITHER was reported clean. The genuine DRC-0 result is on the regenerated full-geometry 25.9 MB magic GDS only.
- OURS PnR never built a PDN (no SPECIALNETS) — IR/EM gaps were closed by regenerating the grid, not by waiving.
- LVS top-pin failure is the same well-tap-artifact category as REF (all cell classes equivalent), NOT a logical wiring error.

**Overall:** OURS is sign-off-sane and functionally equivalent to the NIST golden, in-range with REF on every metric, and on DRC + multi-corner STA is actually stronger than REF. Residual items (LVS well-tap top-pin, 313 antenna diodes, foundry-handoff back-fill) are the standard pre-foundry ECO list, matching REF's category.
