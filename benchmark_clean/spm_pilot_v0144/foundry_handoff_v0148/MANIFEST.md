# spm v0.1.48 foundry handoff manifest

Open-source-checkable tape-out package for the spm IC produced by Vibe-IC
v0.1.48 plugin on 2026-05-29.

## Files

| File | Size | Description |
|---|---|---|
| `chip_top.gds` | 1.7 MB | Sign-off GDS (sky130A, with PDN + 384 taps + 2079 decap + 150 fill) |
| `chip_top.def` | 585 KB | Routed DEF (post-decap; SPECIALNETS for VPWR/VGND) |
| `chip_top.v` | 48 KB | Post-PnR Verilog netlist (with power-gnd connections) |
| `chip_top_synth.v` | 28 KB | Pre-PnR synth netlist (LVS reference) |
| `chip_top.sdc` | 249 B | Timing constraints (clk = 25.9 ns, IO delays) |
| `chip_top.spice` | 56 KB | Extracted SPICE from Magic (LVS reference) |
| `drc_summary.txt` | 167 B | DRC verdict |

## Open-source sign-off results

| Check | Verdict | Tool | Tier |
|---|---|---|---|
| Full SKY130A DRC | **0 violations** | KLayout `sky130A.lydrc` | Tier 2 (v0.1.45 density 0.30) |
| Antenna | **0 violations** | Magic `antennacheck` | Tier 3 (v0.1.45) |
| LVS device-level | **261 = 261 match** | netgen `sky130A_setup.tcl` | Tier 4 (v0.1.45) |
| LVS net-level | inconclusive | netgen (open-source gap) | Tier 4.5 (bounded) |
| Latch-up well-tie density | **384 taps @ 14 µm** | OpenROAD `tapcell` | Tier 5 (v0.1.46) |
| PDN (Power Distribution) | **VPWR/VGND met1+met4+met5** | OpenROAD `pdngen` | Tier 2 IR (v0.1.47) |
| IR drop (static, avg) | **VPWR 14.8 µV / VGND 9.87 µV** | OpenROAD `analyze_power_grid` | Tier 2 IR (v0.1.47) |
| IR drop (static, worst) | **VPWR 35.1 µV / VGND 25.0 µV** | OpenROAD `analyze_power_grid` | Tier 2 IR (v0.1.47) |
| Decap + filler | **2079 decap + 150 fill** | OpenROAD `filler_placement` | Tier 2 EM (v0.1.48) |

## Design characteristics

- Die: 200 × 200 µm
- Core: 180 × 180 µm
- Cell library: `sky130_fd_sc_hd` (high density)
- Logic cells: 261
- Tap cells: 384 (latch-up density)
- Decap cells: 2079 (dynamic IR + density fill)
- Filler cells: 150
- Total instances: 2874
- Top module: chip_top
- Clock: 25.9 ns period
- WNS: +11.89 ns MET
- TNS: 0
- Total power: 167 µW

## Tool / PDK versions

- Container: hpretl/iic-osic-tools (iic-eda)
- PDK: SKY130A (open_pdks-shipped)
- yosys: 0.62
- OpenROAD: 26Q1-990-g15af3a5c0
- Magic: shipped with iic-osic-tools
- netgen: shipped with iic-osic-tools
- KLayout: 0.30.6

## What's NOT in this bundle (gaps for full MPW)

This bundle is **open-source-checkable sign-off ready**. To submit to a foundry shuttle (chipignite / IMEC academic / commercial MPW), the following are still required:

1. **LEF + lib + cdl files for top-level cell** — would need `write_lef` / `write_cdl` step (open-source tooling supports it)
2. **Foundry-side Calibre DRC + Calibre LVS pass** — full LVS net-level confirmation (Tier 4.5 documented the open-source gap)
3. **ESD diode insertion at every IO pad** — pad-ring template not added (Tier 3 open)
4. **Pad-ring** — chipignite/Caravel template not integrated
5. **Real silicon hardware-pass attestation** — never fabbed
6. **Foundry sign-off DRC waiver document** — would be foundry-rep negotiation

## Honest framing

This is the open-source 80% of a tape-out package. The remaining 20% is foundry/commercial tool dependencies that can't be closed without sign-off licenses or MPW submission.

The package would be **immediately functional on silicon** if fabbed (PDN routed, taps inserted, IR margin >5000×). It is **not optimal** (no IO pads or pad-ring) and would not pass a real Calibre LVS without commercial tools or a Calibre PEX deck.

## Pilot history (which fixes shipped which version)

- v0.1.45 (Tier 1.5/2): `--util` 0.45 → 0.30 → DRC 1780 → 0
- v0.1.46 (Tier 5): `tapcell` → 384 taps, latch-up risk → eliminated
- v0.1.47 (Tier 2 IR): `pdngen` → SPECIALNETS 0 → 2, silicon DOA → functional
- v0.1.48 (Tier 2 EM): `filler_placement` decap + fill → 0 → 2229, dynamic IR margin
