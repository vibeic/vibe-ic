# Step 15 — Floorplan / PDN

## What ran
Read OUR vs REF `floorplan.def` / `routed.def` DIEAREA; OpenROAD IFP log core
area + effective utilization; PDN strap layers from DEF TRACKS/SPECIALNETS.

## Metrics side-by-side
| metric | OURS | REF |
|---|---|---|
| Die area | (0 0)-(200000 200000) = 200x200 µm | identical 200x200 µm |
| Core area | 28,624.954 µm² | 28,624.954 µm² (identical) |
| Effective utilization (floorplan) | 0.066 (6.6%) | 0.092 (9.2%) |
| PDN strap layers | met4 (W 0.3) + met5 (W 1.6) tracks present | met4/met5 + met1 followpin |
| Pins | 36 | 36 |

## Verdict: MATCH / IN-RANGE
Identical die + core area + pin count (same fixed floorplan template). OUR
utilization is lower (6.6% vs 9.2%) because the carry-save spm has fewer cells.
PDN uses the same met4/met5 stripe stack on both. The REF persists a full
met1-followpin + met4/met5 PDN into `routed_pdn.def`; OURS keeps the PDN only
in the OpenROAD session (routed.def has 0 SPECIALNETS) — for IR/EM analysis the
PDN was regenerated via pdngen (see step_23 / step_24). Floorplan geometry MATCH;
utilization IN-RANGE (smaller is expected for the leaner micro-arch).
