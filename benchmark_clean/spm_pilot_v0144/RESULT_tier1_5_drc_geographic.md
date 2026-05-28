# spm pilot Tier 1.5 — DRC violation geographic distribution

Continued from `RESULT_tier1_drc.md`. The 1780 SKY130A DRC violations are **NOT uniformly distributed** — they cluster in two distinct zones, which makes the fix much more tractable than "everything is broken".

## Spatial heatmap (8×8 grid over the chip die)

Die size: **200 × 200 µm** (from DEF DIEAREA). Each grid cell ≈ 22 × 17 µm.

```
X →   col0  col1  col2  col3  col4  col5  col6  col7
row7   .     .     .     .     .    17    56   105
row6   .     .     .     .     .    58   116   210    ← upper-right
row5   .     .     .     .     .   155   204    87       dense logic area
row4   .     .     .     .     .    57   121   103
row3   .     .     .     .     .    47   124   114
row2   .     .     .     .     .     .     .     .
row1   .     .     .     .     .     .     .     .
row0  196    .     .     .     .     .     .     .    ← bottom-left
                                                         empty/routing zone
```

Roughly 1574 violations (89%) cluster in the upper-right; 196 (11%) in a single bottom-left cell; the entire left-center half of the chip is **DRC clean**.

## What's in each zone

### Upper-right (x ∈ [120, 180] µm, y ∈ [25, 130] µm) — 233 std cells, ~1574 violations

Cell breakdown (top 8):
- 31 × `sky130_fd_sc_hd__a21oi_1`
- 27 × `sky130_fd_sc_hd__nand3_1`
- 26 × `sky130_fd_sc_hd__nand2_1`
- 26 × `sky130_fd_sc_hd__dfxtp_1`
- 17 × `sky130_fd_sc_hd__a21o_1`
- 14 × `sky130_fd_sc_hd__nor3_1`
- 14 × `sky130_fd_sc_hd__o21a_1`
- 12 × `sky130_fd_sc_hd__clkinv_1`

**Verdict**: cell library is `sky130_fd_sc_hd` (the correct high-density variant); 233 cells in an ~60 × 105 µm area = ~37 cells/(100 µm²) density. That's congestion — the PnR packed all the logic into this corner. Re-PnR with utilization < 50% should distribute cells more evenly and clear most li.3 (min spacing) violations.

### Bottom-left (x ∈ [0, 22] µm, y ∈ [0, 17] µm) — **0 std cells**, 196 violations

A 22 × 17 µm region with no standard cells but 196 li-rule violations. The violations must come from:
- Power-strap routing (li used for local power grid)
- Pin/port shapes at the die boundary
- IO pin escape routing

**Verdict**: needs PnR script audit — likely the bottom-left corner is where the power grid (or one IO ring) enters, and the li shapes there are too close. A focused inspection of one violation in this zone would confirm.

## What this means for the next chunk

The original Tier 1 framing ("1780 violations, need re-PnR") was right but vague. With the geographic clustering:

1. **Upper-right cluster** = congestion problem. **Fix: re-PnR with lower `place_density`** (e.g. 0.5 instead of default 0.7), bigger die, or better partitioning. Estimated: 1 OpenROAD run, ~10-30 min, should drop count by ≥80%.

2. **Bottom-left cluster** = power-strap / IO escape DRC. **Fix: audit `pdngen` settings** (PDN config) to widen li spacing or move power-strap routing off li layer to met1+. Estimated: small TCL change, re-PnR, re-DRC.

3. **Left-center half** = already clean. Nothing to do.

So the actual ~~1780 violations~~ → ~~~1574 congestion + 196 PDN~~ → likely **2 root causes**, each with a known fix.

## What v0.1.44.2 delivers

This is a **diagnostic finding**, not a code fix. The plugin doesn't ship anything new under this writeup. The value:

- Tier 1 finding was honest but vague; Tier 1.5 makes it actionable
- A future PnR re-run can be measured against this baseline (1780 → ?)
- The split between place-congestion and PDN-routing root causes is the kind of finding that goes into `agents/sta-review/SKILL.md` or `agents/drc-fix/SKILL.md` once verified

## Methodology note

Heatmap generation: parse `drc_full.lyrdb` `<item>` blocks, extract edge-pair coordinate midpoints, bin into 8×8 grid over [min_x, max_x] × [min_y, max_y]. Reproducible from `drc_full.lyrdb` (excluded from git per `benchmark_clean/.gitignore` but reproducible with the same `klayout -b -r sky130A.lydrc` command in the iic-eda container).

Flat-vs-hierarchical DRC sanity check: both modes report identical 1780, confirming violations are top-level (routing), not inside reused cells.

## Honest gaps

- The upper-right 233 cells are placed somewhat structurally (presumably during the PnR step); haven't confirmed whether this is `chip_top` logic or a specific submodule.
- The bottom-left 196 violations might be EDGE-OF-DIE artifacts that some foundry rule decks allow as waivable; haven't checked the deck's waiver rules.
- Antenna / latch-up still pending (Magic tech file misload).

## Next chunk recommendation

The single highest-leverage move: **re-PnR with reduced `place_density`** and re-DRC. If 1780 drops by ≥80%, that confirms upper-right was just congestion. If it stays high, the deck or library has an issue we missed. 1-day chunk.
