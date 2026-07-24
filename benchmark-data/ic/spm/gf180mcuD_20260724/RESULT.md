# RESULT — spm × GF180MCU (Benchmark IC campaign, plugin v1.5.66, 2026-07-24)

_Run date: 2026-07-24. IC: `spm` — configurable N-bit serial-parallel integer
multiplier (N=32), PDK: GF180MCU (`gf180mcu_fd_sc_mcu7t5v0`). Plugin: v1.5.66.
Container: `vibeic-eda:0.2.28`._

## VERDICT

**PASS_WITH_WAIVERS.** Independently re-derived from raw artifacts:

- **GDS**: `spm.gds`, 1,180,456 bytes, present at
  `phase3/stage4/gds/spm.gds`.
- **Sign-off DRC** (KLayout, GF180MCU's own official sign-off deck): raw
  report — **763/763 rule categories checked, all clean** (0 violations).
  "N/N" is the same claim-strength as a commercial deck's
  "rules-checked/total"; GF180MCU's open sign-off deck has fewer total rule
  categories than a commercial foundry's proprietary NDA deck — a property of
  the PDK, not a thinner check.
- **LVS** (netgen): raw report tail — *"Final result: Circuits match
  uniquely."*
- **STA** (multi-corner, real SPEF): raw report — worst setup slack **+1.73
  ns**, worst hold slack **+0.57 ns**. Both MET.
- Confirmed via `flow_compliance_check.py --strict`: **Overall:
  PASS_WITH_WAIVERS**.

## Two chip-agnostic plugin fixes this cell's convergence proved

1. **SS slow-corner setup closure (v1.5.59)** — OpenROAD `buffer_ports`
   inserted signal DELAY macros (`dlyd_1`-class) as input buffers, adding
   ~4.9 ns/stage at the SS corner so the typ corner MET while SS VIOLATED
   (−0.56 ns). Fix: exclude the PDK's delay-macro function family
   (`*__dly*`/`*__delay*`) from the resizer/buffer pool — delay macros are
   only legitimate for deliberate hold padding, never as signal/port buffers,
   in any PDK. Chip-agnostic (keyed on the std-cell delay-macro function
   family, no PDK/SKU literal). This closed SS setup −0.56 → +1.77 ns.
2. **Density metal-fill for bridge-less open PDKs (v1.5.66)** — the flow's
   density metal-fill was gated on a `metal_fill_density` config that only a
   PDK *bridge* supplied; GF180MCU (like every open PDK) ships no bridge, so
   fill silently ran as zero-fill and Step 36 failed on 6 metal
   minimum-area/CMP-density violations. Fix: derive the fill config directly
   from PDK-declared files (streamout layermap, tech-LEF routing width +
   manufacturing grid, DRC-deck dummy datatype + spacings + density floor),
   snap fill shapes to the manufacturing grid (no OFFGRID), and place fill on
   a dummy datatype excluded from LVS extraction (no LVS regression). Also
   threaded the run's own EDA container name into the fill step so KLayout
   actually executed instead of silently skipping. Chip/PDK-agnostic; closed
   the 6 DRC violations to 0 with LVS/STA unaffected.

## Honest scope

One cell (IC × PDK) of the open-PDK matrix. This is the 3rd cell in the
matrix to reach an independently re-derived PASS (after spm × IHP-SG13G2 and
spm × sky130A). See `benchmark-data/BENCHMARK_IC_CAMPAIGN_STATUS.md` for the
full matrix. Nothing here is claimed for any cell other than `spm × GF180MCU`.
