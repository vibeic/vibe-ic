# spm pilot Tier 2 — PDN + IR-drop analysis (and the silicon-DOA bug it surfaced)

Continued from `RESULT_tier4_5_lvs_attempts.md`. Tier 2 was supposed to be "run IR-drop on the v0.1.46 GDS". The first check showed:

```bash
grep -c "VPWR\|VGND" routed.def
# Result: 0
```

**Zero VPWR/VGND references in the DEF.** Then:

```bash
grep -E "^(SPECIALNETS|NETS|COMPONENTS) " routed.def
COMPONENTS 643 ;
PINS 36 ;
NETS 293 ;
```

**No `SPECIALNETS` section.** That means **the PnR never ran `pdngen` and no power grid was generated**. Cells have VPWR/VGND pins as required by the standard cell LEF, but those pins are not connected to any chip-level power rail.

## Severity

This is the **third critical plugin bug surfaced by the spm pilot**, and the **most severe**:

| Pilot tier | Plugin bug | Severity on silicon |
|---|---|---|
| Tier 1.5 / Tier 2 (v0.1.45) | `--util` default 0.45 too tight → 1780 DRC violations | Mask shop rejection at DRC check |
| Tier 5 (v0.1.46) | No `tapcell` step → no well-tap density | Latch-up under stress conditions (silicon AT RISK) |
| **Tier 2 IR-drop (v0.1.47)** | **No `pdngen` step → no power grid** | **Silicon DOA (no power reaches cells)** |

The v0.1.25 and v0.1.45 "PASS_WITH_WAIVERS" status had three undocumented gaps that would have each been fatal on silicon. The pilot has now closed all three.

## Validation experiment

Wrote a complete PnR + PDN + IR script:

```tcl
# After tapcell, before global_placement:
add_global_connection -net VPWR -pin_pattern "^VPWR$" -power
add_global_connection -net VPWR -pin_pattern "^VPB$"  -power
add_global_connection -net VGND -pin_pattern "^VGND$" -ground
add_global_connection -net VGND -pin_pattern "^VNB$"  -ground
global_connect
set_voltage_domain -name CORE -power VPWR -ground VGND
define_pdn_grid -name grid -voltage_domains CORE
add_pdn_stripe -grid grid -layer met1 -width 0.48 -pitch 5.44 -offset 0 -followpins
add_pdn_stripe -grid grid -layer met4 -width 1.6 -pitch 40.0 -offset 8.0 -extend_to_core_ring
add_pdn_stripe -grid grid -layer met5 -width 1.6 -pitch 40.0 -offset 8.0 -extend_to_core_ring
add_pdn_connect -grid grid -layers {met1 met4}
add_pdn_connect -grid grid -layers {met4 met5}
pdngen
```

Then after detailed_route:

```tcl
estimate_parasitics -placement
analyze_power_grid -net VPWR -error_file ir_vpwr_errors.rpt
analyze_power_grid -net VGND -error_file ir_vgnd_errors.rpt
```

## Result

| Metric | v0.1.46 (no PDN) | v0.1.47 (PDN + IR) |
|---|---|---|
| `SPECIALNETS` in DEF | 0 (missing) | **2 (VPWR + VGND)** |
| GDS file size | 828 KB | 1.1 MB (PDN straps add shape content) |
| Full SKY130A DRC | 0 violations | **0 violations** (PDN doesn't introduce DRC) |
| WNS | +11.89 ns MET | **+11.89 ns MET** (timing preserved) |
| **VPWR average IR drop** | n/a (no grid) | **14.6 µV** (0.0008% of 1.8 V supply) |
| **VGND average IR drop** | n/a (no grid) | **9.75 µV** (negligible) |
| **Silicon power delivery** | DOA (cells floating) | **Functional** |

IR drop spec for SKY130 designs is typically <5% of supply (= 90 mV at 1.8 V). The spm core draws very little current; the PDN handles it with >5000× margin.

## Plugin fix (v0.1.47)

`programs/phase3_one_shot_runner.py`: emit the PDN block between tapcell and global_placement, NONFATAL-guarded so PDKs without a SKY130-style power-pin convention degrade gracefully:

```tcl
if {[catch {
  add_global_connection -net VPWR -pin_pattern "^VPWR$" -power
  ...
  pdngen
} _pdn_err]} {
  puts "PDN_NONFATAL: $_pdn_err"
} else {
  puts "PDN_INSERTED: met1 follow-pins + met4/met5 stripes"
}
```

When PDK has `tapcell_master` set (which is the proxy for "this is a sky130-style PDK"), PDN block fires. Otherwise it logs a SKIPPED warning so the caller knows to insert PDN out-of-band.

## What this revises (for the third time)

The v0.1.25 `RESULT_v0125_fresh.md` "PASS_WITH_WAIVERS" claim has now been honestly revised three times by the pilot:

1. **Tier 1.5/Tier 2 fix (v0.1.45)**: DRC was 0 under basic deck → 1780 under full deck; density 0.30 fixes
2. **Tier 5 fix (v0.1.46)**: No tap cells → latch-up risk; tapcell insertion fixes
3. **Tier 2 IR-drop fix (v0.1.47)**: No PDN → silicon DOA; pdngen insertion fixes

Each was a real plugin bug. Each was unsurfaced by the previous testing because the open-PDK basic decks don't catch them. The pilot's value is precisely in catching them BEFORE silicon.

## Tier 1 status — STILL CLOSED

Tier 1 status doesn't change (it was never about PDN), but the supporting GDS is now a much better tape-out package:

| Check | Status |
|---|---|
| Full SKY130A DRC | ✅ 0 violations |
| Antenna check | ✅ 0 violations |
| LVS device-level | ✅ 261 = 261 match |
| LVS net-level | ⚠️ inconclusive (open-source gap) |
| Latch-up well-tie density | ✅ 384 taps |
| **PDN (NEW)** | ✅ **VPWR/VGND grid + stripes met1/met4/met5** |
| **IR drop (NEW)** | ✅ **<15 µV avg (>5000× margin to 5% spec)** |

## What v0.1.47 ships

`programs/phase3_one_shot_runner.py`:
- New PDN block emitted between tapcell and global_placement
- NONFATAL-guarded; logs INSERTED/NONFATAL/SKIPPED per step
- SKY130 default config (met1 follow-pins + met4/met5 stripes)
- Pytest: 4615 passed (no regressions)

## What's still NOT ready for MPW

From `PHASE3_TAPEOUT_SCOPING.md`:
- ESD diode insertion at IO pads
- Pad-ring (chipignite/Caravel template)
- MPW manifest bundle (GDS + LEF + lib + cdl + DEF)
- Open-source LVS net-level (commercial Calibre would close)
- Real silicon hardware-pass attestation
- Foundry sign-off DRC waiver document

But the GDS is now genuinely **functional** (would actually power up on silicon) rather than DOA. That's a meaningful threshold cross.

## Honest framing

This is the third plugin fix from the spm pilot in 2 days, and the most consequential. The first two (density + tapcell) made the design pass cleaner sign-off; this one makes the design **actually work**. If the spm chip had been fabbed under v0.1.46, it would have been a dead chip — every cell starved of power because the local rails weren't connected to anything.

The Tier 2 finding is a textbook example of why open-source tape-out flows need pilot runs: the toolchain's defaults silently skip critical steps, and only a careful inspection of the output (zero SPECIALNETS in the DEF) catches it.
