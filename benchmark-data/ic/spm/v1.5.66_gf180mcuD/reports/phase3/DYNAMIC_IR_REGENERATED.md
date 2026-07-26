# Dynamic (transient) IR — REGENERATED against THIS folder's routed DEF

Companion to `EM_IR_REGENERATED.md`, which closed the STATIC half of review
finding F7 for this cell and explicitly said *"This is a STATIC analysis. No
vectored / dynamic IR is claimed."* This closes the dynamic half.

Regenerated on **2026-07-26**. It is NOT the original campaign output and must
not be conflated with it. The campaign's own `dynamic_ir_transient.tcl` is left
untouched.

## What was here before, and why it was not wrong

The shipped `dynamic_ir.json` carried

```
"status": "ERROR_NO_PSM_IR",
"dynamic_ir_report_emitted": false,
"reason": "PSM produced no 'Worst dynamic IR drop' line ..."
```

with a `log_tail` ending in

```
[ERROR PSM-0079] Cannot determine the supply voltage for VDD.
PSM_TRANSIENT_NONFATAL VDD: PSM-0079
```

That was an honest record of a real failed run on this cell — not a stale copy
from another cell, and not a fabricated number. Its `log_tail` reads
`/home/reyerchu/campaign_v1566/spm/converge_1.5.66_gf180mcuD/phase3/stage3/pnr/filled.def`
and reports `2007 components / 8412 component-terminals / 2 special nets, 2140
connections / 367 nets, 1118 connections`, which is this folder's own layout.
It was simply an ERROR standing where a measurement belongs, and the mechanism
to obtain the measurement has since landed.

## Root cause, reproduced here as a NEGATIVE CONTROL

Same root cause as the static half (vibe-ic#362): the gf180 standard-cell
liberty declares an `operating_conditions(...)` block but names no
`default_operating_conditions`, so PSM cannot resolve the supply and aborts.

`dynamic_ir_NEGATIVE_CONTROL.tcl` is the campaign's script shape — no
`set_operating_conditions` — run against THIS folder's DEF.
`dynamic_ir_NEGATIVE_CONTROL.log` ends:

```
=== DYN_IR PSM VDD transient period=10.0ns ===
[INFO PSM-0040] All shapes on net VDD are connected.
[ERROR PSM-0079] Cannot determine the supply voltage for VDD.
PSM_TRANSIENT_NONFATAL VDD: PSM-0079
```

So the published failure reproduces exactly, on the DEF this folder ships. The
one line that changes the outcome is `set_operating_conditions
gf180mcu_fd_sc_mcu7t5v0__tt_025C_5v00` (`dynamic_ir_regenerated.tcl` line 5),
which the emitter now writes automatically.

## What it is evidence ABOUT

```
phase3/stage3/pnr/routed.def
sha256 4369ed411ba634855c06ff8610b9930f703cfbb79d946558c57af29dc7683dc1
UNITS DISTANCE MICRONS 2000 ;   DIEAREA ( 0 0 ) ( 474000 474000 ) ;  -> 237.0 x 237.0 um
```

The campaign's transient ran on `filled.def`; that file is not in this
deliverable, so this regeneration uses `routed.def`, which is. The substitution
is checkable rather than asserted — OpenROAD's DEF banner is identical on both:

| | campaign `filled.def` (from the old `log_tail`) | this run, `routed.def` |
|---|---|---|
| pins | 36 | 36 |
| components / terminals | 2007 / 8412 | 2007 / 8412 |
| special nets / connections | 2 / 2140 | 2 / 2140 |
| nets / connections | 367 / 1118 | 367 / 1118 |

Metal fill sits on a dummy datatype excluded from extraction, so it adds no
electrical node to the power grid; the two DEFs present PSM the same grid.

## Result

`dynamic_ir_regenerated.log`, verbatim:

```
########## Dynamic (transient) IR report ##########
Net                    : VDD
Corner                 : default
Supply voltage         : 5.00e+00 V
Timestep               : 1.00e-10 s
Steps                  : 100
Capacitance model      : quasi-static (no on-die cap supplied)
Worst static IR drop   : 7.15e-03 V
Worst dynamic IR drop  : 1.43e-02 V
Dynamic/static ratio   : 2.00
Current model          : vectorless (simultaneous worst case)
Worst droop time       : 5.00e-09 s (step 50)
###################################################
```

Worst dynamic droop **14.3 mV = 0.286 % of a 5.00 V supply**, against the
plugin's 15 % dynamic budget (750 mV) -> **PASS**. Supply read by the tool from
the liberty's own operating condition, not asserted by this document.

`dynamic_ir.json` was assembled by the shipped emitter's own parsers and
`build_result`, from this log — no number in it is hand-entered.

## Numbers that differ from the static set, and why

This run reports `Worst static IR drop 7.15e-03 V`, while `ir_drop.json` in
this folder carries `worst_ir_uv 6370.0` (6.37 mV) from the static
regeneration. They are not the same analysis: the transient script does
`read_sdc` and the static one does not, so the two solve different power
estimates (`Total power` 8.34e-03 W here vs 7.56e-03 W there). Both are in the
folder; neither is retro-fitted to the other. `dynamic_ir.json` keeps the
Step-24 static (6.37 mV) as `static_ir_mv` — the emitter prefers the external
static number — and records this run's own as `static_from_transient_mv`.

## Stack

* container **ghcr.io/vibeic/vibeic-eda:0.2.30**, PDK **gf180mcuD**,
  OpenROAD **26Q3-155-g1bade74e72** — the same OpenROAD build the static set
  and the campaign's own reports print.
* Ran in a sandbox (`/home/reyerchu/_f7dynir`) holding a byte-identical copy of
  the DEF above. `dynamic_ir_regenerated.tcl`, `dynamic_ir_NEGATIVE_CONTROL.tcl`
  and both logs ship VERBATIM and therefore carry that sandbox path. They are
  the scripts and logs that actually ran; rewriting the paths would make them a
  description of the run rather than the run itself.

## Stated limits

* **Vectorless**, not vectored. The current model is PSM's simultaneous
  worst-case per-clock triangular source, not a SAIF/VCD activity trace. A
  vectored DVD number would be lower and is not claimed.
* **Quasi-static capacitance** — no on-die decap was supplied, which is why the
  solver's own dynamic/static ratio is 2.00. This is the BASE transient tier.
* No package / board L*di/dt term. PSM printed no `Package L*di/dt droop` line
  and none is recorded (the emitter writes that key only when the tool prints
  it).
* Supply model is PSM's default single-bump pattern (`PSM-0073`) on a padless
  core — a CONSERVATIVE upper bound, as for the static set.
