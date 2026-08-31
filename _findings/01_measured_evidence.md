# i1962 — measurement evidence captured on this host

Container: `vibeic-eda` (ghcr.io/vibeic/vibeic-eda, ngspice-47). All decks run
through `bash -lc` (the login profile exports SPICE_USERINIT_DIR, without which
Verilog-A/OSDI model types are never registered and every device fails to bind).

## 1. Two-point square-law reproduces the issue's published constants EXACTLY

IHP sg13g2 LV, `.lib .../cornerMOSlv.lib mos_tt`, explicit-metres geometry
(`w=10u l=1u`, NO `.option scale`), Vds=1.2, T=27C:

    MEAS n1= 0.00041508    (Vgs=0.7)
    MEAS n2= 0.000803438   (Vgs=0.9)
    MEAS p1= 4.97223E-05   (|Vgs|=0.7)
    MEAS p2= 0.000118256   (|Vgs|=0.9)

    fit: m = (sqrt(I2)-sqrt(I1))/(Vg2-Vg1);  Vth = Vg1 - sqrt(I1)/m;  k' = 2m^2/(W/L)
    -> LV k'n = 317.7 uA/V^2,  LV k'p = 73.1 uA/V^2

Issue #1962 body states "LV k'n=317.7u, k'p=73.1u". Bit-for-bit agreement, so the
extraction math in this program is the same math the hand run used.

## 2. GEOMETRY-UNIT idiom is per-device and NOT optional (measured)

IHP `sg13_lv_nmos` declares METRIC subckt defaults. Same bias, two idioms:

    .option scale=1u + `w=10 l=1`  ->  Id = -4.2981 A     (nonsense)
    explicit metres `w=10u l=1u`   ->  Id = 265.318 uA    (correct)

sky130's own `all.spice:2` sets `.option scale=1.0u`, so on sky130 the bare-micron
idiom is the correct one and explicit metres puts W/L outside every model bin
("could not find a valid modelname"). => the deck emitter must key on the
family's OWN declared convention (`DeckContext.device_geometry_units`), exactly as
`analog_real_corner_sweep._emit_metric_geometry` already does.

## 3. TWO-LENGTH / TWO-AREA differential beats the single-device hand deck

Single-device (the hand deck's method) carries the resistor's END/CONTACT
resistance and the capacitor's PERIMETER fringe into the "sheet"/"area" number.
Measured, w=0.5 l=20|40 (res) and 10x10|20x20 um (cap):

| PDK    | device                | single-shot | differential | PDK's own stated value |
|--------|-----------------------|-------------|--------------|------------------------|
| ihp    | rppd                  | 260.4 ohm/sq| **260.00**   | 260 ohm/sq             |
| ihp    | cap_cmim              | 1.516 fF/um2| **1.500**    | 1.5 fF/um2             |
| sky130 | res_high_po_0p35      | 397.3 ohm/sq| **386.8** (+603 ohm end) | -           |
| sky130 | cap_mim_m3_1          | 2.066 fF/um2| **2.000** (+0.164 fF/um perim) | 2.0 fF/um2 |

The differential recovers each PDK's OWN nominal constant on two independent
PDKs, and it additionally yields `r_end_ohm` / `cap_perim_ff_per_um`, which a
short resistor or a small MiM is dominated by. Adopted.

## 4. Device binding must go through the ONE existing binder

`analog_a3_netlist_emit.resolve_role_models()` is already the flow's role->device
binder (deck-context election -> curated registry `device_map` -> `device_models`
heuristic) and is what A3 puts in the netlist. Measuring k' on a device the flow
does not instantiate would be a misattribution, so the characterizer reuses it.
`resolve_pdk_context()` wraps it but resolves the PDK from the PROJECT's L19 doc;
a PDK-shaped caller has no project, and passing a dummy path made an
`ihp-sg13g2` request silently resolve to **sky130's lib and sky130 devices**.
=> the characterizer must pass its own `analog_pdk_availability.resolve_pdk()`
result in.

## 5. gf180 cannot be characterized today, and that is a PRE-EXISTING defect

`_KNOWN_FAMILIES["gf180"]` names `design.ngspice` + sections ss/tt/ff and keeps
the sky130 device NAMES (documented historical behaviour in
analog_pdk_deck_context). Measured: `design.ngspice` declares no `.lib` section
at all (it only sets global `.param`s such as `fnoicor`), and the sections
actually live in `sm141064.ngspice` as typical/ss/ff/fs/sf. Loading the section
lib alone aborts with `Undefined parameter [fnoicor]`.
=> out of scope for #1962. The characterizer reports gf180 as an HONEST GAP with
the simulator's own diagnostic, and never fabricates a number for it.

## 6. THE BIAS GRID WAS THE REAL DEFECT IN THE HAND METHOD (measured)

The evidence decks bias the gate at numbers typed for the process they were
typed on. Generalized as fractions of the supply (0.50 / 0.625 / 0.75 of Vdd),
that grid lands the LOW point at or below threshold on a high-threshold device.
Measured on sky130A's p-role at Vdd=1.8:

    |Vgs| = 0.90 -> Id =  0.168 uA      (essentially subthreshold)
    |Vgs| = 1.35 -> Id = 41.5   uA
    two-point fit -> k'p = 35.9 uA/V^2, and the interior point sits 89.6% away

A k' extracted there is an artefact of where the grid fell, not a process
constant. Fix: TWO PASSES — pass 1's only product is a preliminary threshold;
pass 2 re-biases at fractions of the gate swing that REMAINS above it
(0.25 / 0.375 / 0.50 of Vdd - Vth), capped at 0.95 of the rail. Measured, same
device, same lib:

    k'p 35.9 -> 59.7 uA/V^2      residual 89.6% -> 4.7%
    k'n 190.2 -> 210.4 uA/V^2    residual  3.1% -> 2.3%

The interior point is spent on the residual and never on the fit, so the record
publishes how well the square law describes each device instead of implying it.

## 7. THE PROCESS CORNERS COME OUT MONOTONIC (sky130A, measured)

|        | k'n (uA/V^2) | k'p | Vth_n | Vth_p |
|--------|--------------|-----|-------|-------|
| ss     | 197.2 | 51.1 | 0.5579 | 0.9974 |
| tt     | 210.4 | 59.7 | 0.5368 | 0.9780 |
| ff     | 223.3 | 67.6 | 0.5157 | 0.9569 |

slow < typ < fast on both transconductance parameters and the reverse on both
thresholds — which is what a process corner IS, and is therefore assertable as
an invariant rather than as a literal. sky130A's R and C come out corner-
INVARIANT because that PDK's ss/tt/ff sections vary only the MOS models; that
is the PDK's own statement and is recorded rather than smoothed over.

## 8. A SECOND DEFECT, FOUND BY RUNNING IT (family-name resolution)

`resolve_pdk_context` reports `family` from the LIB PARSE, which drops
punctuation. The parsed name matched no registry entry, so the declared supply
could not be read and the whole run refused NO_SUPPLY on a family whose supply
the registry states plainly. Fixed by resolving the registry entry through the
one shared matcher over three candidates — the binder's family, THE SELECTOR
THE CALLER ASKED FOR, and the parsed family — with a test that pins the middle
rung specifically.

## 9. THE MOST DANGEROUS DEFECT, FOUND BY READING THE OUTPUT (not by a gate)

`analog_pdk_deck_context.known_family_context` keeps an authored fast-path table
keyed on two open-PDK selectors. A selector that is not a KEY of that table —
including the registry's own full family names — falls back to the first entry
while still reporting the name that was ASKED FOR. Its own docstring says so:

    "An UNKNOWN selector falls back to sky130's template while `family` records
     the name that was ASKED FOR, so the context claims to describe a PDK whose
     devices and model lib it does not carry ... a LATENT trap for the next
     consumer that reads ctx.device_map / ctx.model_lib at face value"

This program was that next consumer. MEASURED, before the guard was added — a
`--pdk gf180mcuD` run published, into pdk_registry.json, under gf180mcuD's name:

    sections  [["/foss/pdks/sky130A/libs.tech/ngspice/sky130.lib.spice","tt"]]
    params    k_prime_n_ua_per_v2 177.4  k_prime_p_ua_per_v2 58.1
              vth_n_extracted_v 0.495    vth_p_extracted_v 0.956
    status    MEASURED

Every one of those is another process's constant. The MOS decks ran happily
because the fallback supplies BOTH the lib and the device names, so they agree
with each other; only the passive roles failed loudly ("unknown subckt:
res_generic_po"), and only because gf180's passive names are not sky130's.

FIX: `context_describes_target()` — STRUCTURAL, trusting no name. Every
`(lib, section)` the decks would load must live under the `pdk_root` the
resolver matched for the selector, or be one of the libs it resolved.
Anything else -> `CONTEXT_IS_NOT_THIS_PDK`, rc 2, nothing measured, nothing
published. Two tests pin it (including the `/x/zeta2` vs `/x/zeta` prefix
case), plus a third asserting the invariant on the SHIPPED registry data so a
foreign-lib record could not sit there even if the guard were removed.

gf180mcuD therefore ships NO measured record on this branch, and that is the
honest answer: its known-family table names `design.ngspice` + sections
ss/tt/ff, and neither exists (see finding 5). Fixing that table is a separate
change to shared deck-emission behaviour and is out of scope for #1962.
