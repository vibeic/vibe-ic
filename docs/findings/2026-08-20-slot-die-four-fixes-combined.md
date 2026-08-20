# One die with all four fixes on — what each was worth, and what survived

Independent run on host `8HD-8`, 2026-08-20. The three fixes had each been
proven separately and never combined; this is the combined run, plus the four
arms that say which fix delivered which category.

Naming: `$PDK` is the process design kit; `the operator` is the shuttle whose
precheck container is the external authority here. No vendor, node or part
identifier appears.

## 0. Where the geometry came from

Not computed. The operator's published project template pins it, per slot:

    FP_SIZING: absolute
    DIE_AREA:  [0, 0, 1936, 2531]      # the slot
    CORE_AREA: [442, 442, 1494, 2089]  # inset 442um on all four sides

`check_size.py` in the operator's own container recomputes the same
`1936.0 x 2531.0` from its own three constants and compares with `!=` on floats
to the micron. Template HEAD `0de7e394337a1f7f5303ac7a3681bf2481b58176`.

## 1. The four arms — same base project, same flags but one

All four are full `phase3_one_shot_runner` runs on the same design, same PDK,
same container. Counts are per-category item counts from the flow's own sign-off
deck, parsed out of `reports/phase3/drc_signoff.rpt`.

| rule | A: fix 1 | B: + fix 2 | C: + seal ring, **no keep-out** | D: + keep-out + FEOL |
|---|---:|---:|---:|---:|
| `GR.2`  (marker-to-metal, 10um) | 0 | 0 | **17623** | **0** |
| `M2.3`  (min metal2 AREA) | 334 | 334 | 334 | 334 |
| `PP.2`  | 85 | **0** | 0 | 0 |
| `DF.13_MV` | 79 | **0** | 0 | 0 |
| `NP.2`  | 78 | **0** | 0 | 0 |
| `NW.2b_LV` | 58 | **0** | 0 | 0 |
| `NW.2a_LV` | 47 | **0** | 0 | 0 |
| `DV.5`  | 42 | **0** | 0 | 0 |
| `M3.3`  (min metal3 AREA) | 18 | 27 | 27 | 27 |
| `DF.14_MV` | 14 | **0** | 0 | 0 |
| `NW.2b_MV` | 5 | **0** | 0 | 0 |
| `ANT.16_ii_ANT.4` | 4 | **0** | 0 | 0 |
| `ANT.16_ii_ANT.3` | 3 | 3 | 3 | 3 |
| `PL.8` (poly density) | 1 | 1 | 1 | 1 † |
| `M1.4` (metal1 density) | 1 | 1 | **0** | 0 |
| **total** | **769** | **366** | **17988** | **365** |

† the flow's deck build counts only DRAWN poly2 for `PL.8`; the operator's own
container counts drawn + dummy and reports the layer at 32.294905% against a 14%
floor — see §3. The two decks are different builds of the same $PDK.

**Fix 1 (the die is a rectangle).** `ppl place_pins` places pins on the DIE
boundary and has no core-boundary mode, so `-core_area` alone cannot move them.
With the template's CORE_AREA handed over AS `-die_area`, all 41 pins land
**442.260 um** inside the slot — measured off `routed.def`, whose `DIEAREA` is
`( 884000 884000 ) ( 2988000 4178000 )` at `UNITS 2000` = exactly the template
rectangle. The seal ring then has 442 um of clear silicon to be drawn in.

**Fix 2 (spacers, not decaps).** 33,320 filler instances from 7 masters, all of
the spacer family, zero decaps. It clears eight categories outright — the six
well/implant ones plus `DF.13_MV` and one antenna rule — 769 -> 366. Two
disagreements with the prior separate measurement, recorded because they are
disagreements and not confirmations: `DF.14_MV` went **14 -> 0** here (it had
been reported as unaffected, 9 -> 9), and `M3.3` went **18 -> 27**, so the
spacer pass is not free.

**Fix 3 (the keep-out) — arm C is the whole argument.** Arm C and arm D differ
by ONE config field. Arm C: `"keepout": []`. Arm D: one entry,
`{layer: [167,5], space_um: 10.0}` — the marker layer and the clearance the
$PDK's own deck states for it (`guard_ring.rb:66`,
`metal.separation(guard_ring_mk, 10.um)`). Everything else is bit-identical,
including all five per-layer densities. The difference is **17623 `GR.2`**, and
NO other rule moves. The engine reports what it excluded: 1 marker polygon,
318878.48 um^2 of keep-out.

## 2. The seal ring: the generator, and the PDK that ships it broken

`die_finishing_gen` calls the PDK's own `sealring.py`. In the EDA image's copy
of $PDK the script is present and the PCell library it imports is **not**: it
prints `Error: Couldn't load the seal ring library.`, calls `sys.exit()` with no
argument — so it **exits 0** — and writes nothing. Trusting the exit status
would have recorded a ring that does not exist. The program diffs the layouts
instead and reported `state: FAIL`, correctly.

Staging a copy of $PDK that DOES ship `pymacros/sealring_cells` makes the same
script produce the ring. Sealed die, measured: top cell single, dbu 0.001,
bbox exactly `(0,0)-(1936,2531)`, `guard_ring_mk` 1 polygon, `Via5` and
`MetalTop` both empty — which is five of the operator's six ladder checks, and
the sixth is the size it just became.

**The trap the brief names is real and I hit it in the first run.** Left to
itself the generator takes the routed DEF's own `DIEAREA` — which after fix 1 is
the CORE rectangle — and sealed `1052 x 1647`, reporting PASS. `--slot-rect`
exists so the finished die is declared, not inferred.

## 3. The operator's own verdict

Density, from the container's own log, before and after the FEOL half:

| layer | floor | before | after |
|---|---:|---:|---:|
| COMP + dummy (`DCF.1b`) | 25% | 3.383586% | **29.128910%** |
| Poly2 + dummy (`PL.8`)  | 14% | 0.130530% | **32.294905%** |
| Metal1 (`M1.4`) | 30% | 44.070249% | 44.070249% |
| Metal2 (`M2.4`) | 30% | 44.608640% | 44.608640% |
| Metal3 (`M3.4`) | 30% | 44.682958% | 44.682958% |
| Metal4 (`M4.4`) | 30% | 45.008999% | 45.008999% |
| Metal5 (`M5.4`) | 30% | 45.236905% | 45.236905% |
| MetalTop (`MT.3`) | 30% | 45.236905% | 45.236905% |
| | | `FAILURE (2 violation(s))` | `SUCCESS (0 violation(s))` |

The metal columns are bit-identical, which is the control that says the FEOL
pass touched only FEOL. The metal engine reaches 44-45% where the $PDK's own
metal lattice cannot: its metal5 dummy line space is 2um against 1.2um below, so
that lattice's ceiling is 4/(4.0^2-0.5^2) = 25.4%, under the 30% floor at any
utilisation. The FEOL floors are the mirror image — the flow's engine derives
its config from the tech LEF's ROUTING layers and has no configuration for
active or poly, and the $PDK ships generators for exactly those. So step 34 now
uses both: our engine for metal, the $PDK's own scripts for active and poly.
Adding the FEOL pass changed the DRC count by **zero** (361 -> 361).

## 4. What survived, and why it is not one of the four

**361 of the 365, and they are minimum-AREA, not spacing.** `M2.3` and `M3.3`
are `Minimum metal2/metal3 area : 0.1444um^2`. 310 of the 334 `M2.3` are one
shape, `0.28 x 0.38 um = 0.1064 um^2` — a lone via landing pad. Three
independent facts put them on the router and not on any of the four fixes:

1. Every one of the 361 lies INSIDE the core rectangle.
2. Not one has a single dummy-fill polygon within 0.6 um of it (measured
   per violation against layers 36/4 and 42/4).
3. `M2.3` is **334 in all four arms**, including arm A, where there is no ring
   and the fill field is a different shape entirely.

The flow already knows: `MIN_AREA_PATCH_DONE: deficient=304 patched=125
unpatchable=179`, and it names each one, e.g.
`net=_026_ layer=Metal2 area=425600 need=577600` — 0.1064 against 0.1444 um^2 in
DEF units. A patcher that reports 179 it could not fix, on a die where the deck
finds 361, is a real and separate gap.

**3 antenna items, and they are ONE net.** All three carry the same
`RATIO 902.496275072` against a limit of 400, the same `GATE_AREA 0.5235` and
`DIODES_AREA 0`; one of the three polygons is a single Metal2 wire running
`y = 1264.45 .. 1701.63` — 437 um. This is a DIFFERENT failure mode from the
one the separate measurements found: there the single antenna item WAS the seal
ring, and here the ring contributes none, because fix 1 moved every pin 442 um
away from it. What is left is a long internal route, which is what a small
design stretched across a mandated slot produces. OpenROAD's own antenna checker
called the design clean (`ANTENNA_ALREADY_CLEAN`) and inserted no diode; the
sign-off deck disagrees. Same authority mismatch, new instance.

## 5. Not run

Extraction and STA on the filled die. Metal2 now carries ~41 points of dummy
directly above and below live routing and no deck rule constrains inter-layer
coupling. LVS on the sealed+filled die was not obtained either (post-layout LEC
returned RUN_ERROR on this project, unrelated to these changes). Magic DRC
reports 1698 of the same two min-area rules and is advisory in the operator's
flow (`ERROR_ON_MAGIC_DRC: False`); it was not triaged.
