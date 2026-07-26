# EM / IR-drop evidence — REGENERATED against THIS folder's routed DEF (review finding F7)

The v1.5.66 campaign folder shipped no EM / IR-drop reports. This set is
**regenerated on 2026-07-26** to close that gap. It is NOT the original
campaign output and must not be conflated with it.

## What it is evidence ABOUT

The input is **this folder's own** routed DEF, not a re-run layout:

```
phase3/stage3/pnr/routed.def
sha256 4369ed411ba634855c06ff8610b9930f703cfbb79d946558c57af29dc7683dc1
UNITS DISTANCE MICRONS 2000 ;   DIEAREA ( 0 0 ) ( 474000 474000 ) ;  → 237.0 × 237.0 um
```

Anchoring matters here and is the reason an earlier submission of this same
gap (PR #363) was rejected: its `em_segments.csv` carried node coordinates
reaching **253.2 um in X and 250.9 um in Y**, ~16 um OUTSIDE this die on
both axes, so it could not have come from this DEF. Its own header anchored
its provenance to the RTL rather than to the routed DEF, which is consistent
with it having re-run the flow and analysed a floorplan that is not in this
deliverable. Reports placed in a folder are read as evidence about THAT
folder's layout; anchoring them to the RTL does not make that true.

Every EM node in this set lies inside the die: X 10.3 … 214.3 um,
Y 15.2 … 212.5 um.

The 237 um figure is not taken on this document's word — two of the
CAMPAIGN's own reports in this same folder, written by the original run and
not by this regeneration, agree with it independently:

| campaign artefact | field | value | implies |
|---|---|---|---|
| `reports/phase3/metal_density.json` | `die_area_um2` | 56 169.0 | 237.0 × 237.0 um |
| `reports/phase3/pnr/floorplan_pdn.json` | `die_area_units` | 224 676 000 000 | 474 000 × 474 000 DBU |

So the layout this folder documents is 237 um on both axes, and coordinates
beyond it did not come from this campaign at all.

This folder also already shipped the campaign's own `ir_em_spm.tcl`, which
reads `/home/reyerchu/campaign_v1566/.../spm.def` — the original run did
execute the IR/EM step; only its reports were never published, which is what
F7 recorded. That file is left untouched; this regeneration's script ships
separately as `ir_em_regenerated.tcl`.

## Stack

* plugin **v1.6.30**, container **vibeic-eda:0.2.30**, PDK **gf180mcuD**
  (named branch, resolved from the registry inside the container).
* OpenROAD **26Q3-155-g1bade74e72**.
* The regeneration ran in a sandbox (`/home/reyerchu/_repro363`) holding a
  byte-identical copy of the DEF above; `ir_em_spm.tcl` and `ir_em.log` are
  shipped VERBATIM and therefore carry that sandbox path. They are the
  script and log that actually ran — rewriting the paths would make them a
  description of the run rather than the run itself.

## Results

* `ir_drop.rpt` / `ir_drop.json` — verdict **PASS**. Worst IR **6.37 mV =
  0.127 % of VDD** against a 10 % static budget. Supply **5.00 V**, read by
  the tool from the liberty's own operating condition.
* `em.rpt` / `em.json` — **MEASURED**. 2 735 segments (Metal1 2 648,
  Metal2 26, Metal3 26, Metal4 35), max segment current **1.401 mA**.
  `em_segments.csv` carries the real per-segment data.

`PSM-0079` is no longer a blocker. `v1.6.24/25` selects the liberty's own
operating condition **by NAME** instead of parsing a voltage value out of
it, so the tool reads its own authoritative supply:

```
IR/EM: selected the liberty's own operating condition
'gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00' (it defines the block but names no
default — PSM otherwise aborts PSM-0079)
[INFO PSM-0040] All shapes on net VDD are connected.
Supply voltage : 5.00e+00 V
```

## Stated limits

* The supply model is PSM's default single-bump pattern (`PSM-0073`) on a
  padless core. That is a CONSERVATIVE upper bound: real multi-bump power
  delivery gives a lower drop. The number is not a substitute for a
  package-aware analysis.
* This is a STATIC analysis. No vectored / dynamic IR is claimed.
* EM is reported as segment current; converting it to a lifetime verdict
  needs the PDK's Jmax per layer, which this set does not assert.
