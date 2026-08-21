# The die's DRC, converged — and how much of it was already on `main`

_Measured 2026-08-21 on host `8HD-8`. Design: a small digital cell on `gf180mcuD`
targeting the smallest slot of an open shuttle's published project template.
"The operator" is that shuttle. No vendor, node or part identifier appears._

## 0. The premise this started from was already out of date

The task was to combine three separately-proven fixes — a seal-ring band reserved
at floorplan time, a filler master list that is spacers rather than decaps, and a
keep-out for the density fill — and produce one end-to-end DRC number.

All three were already on `main` when this began:

    729b62b29  fix(phase3): reserve the seal-ring band at floorplan time, and keep
               dummy fill off a chip edge
    69ce9260d  feat(37.5ic): fill the die to the PDK's floors, and make the release
               documents an output

`729b62b29` describes itself as "three wirings, all hanging off one gate —
`_slot_geometry(project) is not None`", and those three wirings ARE the three
fixes. So nothing was re-landed. What follows is (a) the end-to-end measurement
nobody had taken with all three in at once and a real ring on the die, and (b) the
one thing the combination measured that was still wrong.

## 1. The measurement design

Two things had to be true for the number to mean anything.

**The die has to carry a ring.** `729b62b29` states plainly that its keep-out
"moves sign-off DRC by ZERO here ... this image's PDK ships no `sealring_cells`,
so the flow's layout carries no ring to protect". That is still true of the pinned
image: `$PDK/libs.tech/klayout/tech/scripts/sealring.py` does
`from sealring_cells import gf180mcu_sealring` at line 37 and
`$PDK/libs.tech/klayout/tech/pymacros/` contains `cells`, `gf180mcu.lym`,
`README.md`, `testing` — and no `sealring_cells`. On the `ImportError` the script
prints one line and calls `sys.exit()` with no argument, so it exits **0** and
writes nothing. Every arm below therefore runs in a container built from the
pinned image with ONE read-only overlay: the PDK's own `sealring_cells/` mounted
where the PDK's own script looks for it — identical in every arm EXCEPT the two
`*_noring` controls, whose whole purpose is to be the image as it actually ships.
**This is the
root blocker for all three rows and it is in the image, not the plugin** — the
flow's own `die_finishing_gen` diagnoses it correctly (it diffs the layouts
instead of trusting `rc`) but cannot repair it.

**The fill has to run.** This die's core utilisation is 1.87%, under the 5%
sparse-die guard, so the shipped default skips filler placement outright.
`VIBEIC_SPARSE_DIE_FILL_PCT=0.5` in every arm, identically.

Everything else is the flow as shipped. No `--die-um`, no die rectangle, no slot
rectangle on the command line: the after-arms read all of it out of the operator's
own template, ingested by step 0.5ic.

    ./prep_proj.sh <arm> <plugin>       # copy the design, wipe phase3, ingest the slot
    VIBEIC_SPARSE_DIE_FILL_PCT=0.5 \
      python3 programs/phase3_one_shot_runner.py <arm> --top-name spm \
        --container <container> --allow-pdk-target-mismatch --pdk gf180mcuD

## 2. The arms

Eight full `phase3_one_shot_runner` runs on one design. Each after-arm differs from
its control by ONE thing, and each control is a single suppressed statement in an
otherwise unmodified checkout, not a different revision.

| arm | plugin | the one difference |
|---|---|---|
| `arm_base`   | `0cd4039ca` (the commit before the three fixes) | none — the flow as it was, die auto-sized |
| `arm_base2`  | `0cd4039ca` | as above, handed the slot's own size with `--die-um 1936x2531` |
| `arm_nores`  | `origin/main` + 1 statement | the floorplan reserve suppressed; die, ring and keep-out unchanged |
| `arm_noko`   | `origin/main` + 1 statement | the fill keep-out suppressed; floorplan and ring unchanged |
| `arm_noring` | `origin/main`, container WITHOUT the PDK overlay | the seal ring cannot be generated |
| `arm_head2`  | `origin/main` | — |
| `arm_mine`   | this branch | the keep-out is read from the deck instead of assumed as a band |
| `arm_mine_noring` | this branch, container WITHOUT the overlay | the paired control for `arm_noring` |

## 3. What the ring costs now: nothing

`reports/phase3/drc_signoff.rpt` is the flow's own sign-off DRC — the PDK's own
`gf180mcu.drc`, run by the flow, on the die the flow is about to ship. Counted
with one instrument (`<item><category>` out of the KLayout report database),
validated first against a report whose answer was already published.

The four rules the seal ring introduces, on the die that carries the ring:

| rule | what it is | before (published, this design + slot) | measured here |
|---|---|---:|---:|
| `GR.4` | `metal.not_outside(guard_ring_mk).width(12um)` | 794 | **0** |
| `GR.2` | `metal.separation(guard_ring_mk, 10um)` | 19 | **0** |
| `V1.2a` | min via1 spacing | 2 | **0** |
| `V3.2a` | min via3 spacing | 2 | **0** |
| | **ring-attributable** | **817** | **0** |

`GR.4` is the one worth reading twice: `not_outside` selects any polygon merely
TOUCHING the marker band and then measures that WHOLE polygon, so one 0.28 um pin
wire touching the band is reported along its entire length. 794 of the 817 were
that. They are gone because the pins are no longer in the band:

    arm_base2 (before)   DEF DIEAREA [0, 0, 1936, 2531]        min pin-to-slot-edge 0.000 um
    arm_head2 (after)    DEF DIEAREA [442, 442, 1494, 2089]    min pin-to-slot-edge 442.000 um

41 of 41 pins in both. The after-arm was given no die argument at all; it read
both rectangles out of the operator's own template.

## 4. The keep-out: what it was, what it is now, and why the difference is real

The engine has carried two keep-out forms since it got one, and its own docstring
says which is which:

    keepout_layers   "the exact form when the PDK ships a marker for the band ...
                      because it follows the ring the generator actually drew
                      instead of assuming where it went"
    keepout_edge_um  "the `fill_all.rb` form, for a PDK that ships no marker"

Only the fallback was ever populated. Nothing in the tree wrote `keepout_layers`.

The band's width is read out of the PDK's own fill scripts —
`tp.var("space_to_scribe_line", 26 / $ly.dbu)` — and it is claimed whenever the
DESIGN declares a slot. On this PDK it happens to be exactly right, and the reason
is a coincidence of three numbers that nothing enforces:

    the ring marker      sealring_cells/draw_sealring.py: GUARD_RING_MK start 0 end 16
    the deck's clearance guard_ring.rb:66  metal.separation(guard_ring_mk, 10.um)
    the fill script      fill_metal.rb:167 space_to_scribe_line = 26
                                                        16 + 10 == 26

Measured on the sealed die, from the two arms' own `cmp_fill_emit.json`:

    arm_head2  ['edge:26.0um']                        area 229580.00 um^2
    arm_mine   ['75/0:EMPTY','220/0:EMPTY','96/1:EMPTY','152/5:EMPTY',
                '122/5:EMPTY','173/5:EMPTY','167/5+10.0um']  area 318878.48 um^2
    both       measurement bbox [0, 0, 1936, 2531]

Different areas, same fillable region:

    edge band 26 um inside 1936x2531 : 1936*2531 - 1884*2479 = 229580   exact
    marker grown by 10 um            : 1956*2551 - 1884*2479 = 319320   (318878.48 measured,
                                                                         sized-region corners)

Both have the same inner boundary, 1884x2479. Inside the die they ARE the same
band; the extra 89298 um^2 lies outside the die, where there is nothing to fill.
So on this PDK the change moves no geometry — which is the point. It replaces a
coincidence with the rule, and six of the seven derived entries report `EMPTY`,
which is the self-gating a band cannot do.

The measurement bbox is deliberately unchanged by either form: the foundry's
density rule measures over the whole die, so shrinking the denominator to make the
numbers look better would be the exact dishonesty this file's docstring refuses
elsewhere. A keep-out makes the target HARDER to reach, and an unreachable target
stays visible as `reached: false`.

### What the deck actually says, read as data

`parse_metal_keepout_layers` takes every `<metal>.separation(<layer>, <D>.um)` the
deck states, looks the layer's GDS number up in the deck's OWN layer table, and
emits `[layer, datatype, D]`. Layers that are themselves routing metal are excluded
— dummy-to-circuit spacing is not a keep-out REGION, it is the per-layer
`space_to_metal` the same config already carries, and re-expressing it would
subtract every wire on the die. On this PDK's deck (8966 lines, read out of the
pinned image) that yields seven:

    167/5  +10.0 um   guard_ring_mk   the seal-ring marker, at GR.2's own distance
     75/0  + 6.0 um   fusetop         }
    220/0  + 6.0 um   polyfuse        }  the deck's six DM.8 dummy-metal
     96/1  + 6.0 um   fusewindow_d    }  clearances, which the fill engine
    152/5  + 6.0 um   pmndmy          }  had never honoured at all
    122/5  + 6.0 um   mtpmark         }
    173/5  + 6.0 um   otp_mk          }

Six of the seven are structures a digital die does not carry, so they report EMPTY
and cost nothing. Nothing in the logic is a PDK, vendor or chip literal — the
layer, the datatype and the distance are all the deck's, and the deck's own NAME
for each is disclosed in `_derivation.keepout_layer_names` so a reader can check
the derivation against the RULE rather than against a number.

### The trap, which is now the negative arm

The first version of this also derived a base-layer keep-out at 1 um, from

    #  dm_5_dm_7_l1 = metal_dummy.separation(poly2, 1.um, euclidian)

a rule this PDK ships COMMENTED OUT (its own fill script has a knob for the same
thing). That layer blankets the core, so the keep-out would have removed most of
the fillable die — silently, and in the direction that looks like caution. The
comment stripper is quote-aware, because a live rule's own output label is
`"DM#{idx}.3"` and cutting at that `#` truncates the line. Every positive test is
now paired with the same text commented out, so a parser that cannot tell a live
rule from a dead one fails the suite rather than passing it.

### One disclosed behaviour change beyond the chip die

Before, the keep-out was claimed only for a design that declares a shuttle slot,
so an IP macro got none. Now `keepout_layers` is derived for EVERY design, because
the deck's rules are about the layout, not about the submission route. On a macro
that carries none of the named structures every entry reports `EMPTY` and nothing
is kept out — identical behaviour, now DISCLOSED rather than assumed. On a macro
that DOES carry one (a fuse window, an OTP marker), dummy metal now clears it by
the distance the deck states, which it previously did not. That is a behaviour
change and it is the deck's answer, not this flow's.


## 5. The two arms that price the two mechanisms

**The keep-out is load-bearing.** `arm_noko` is `origin/main` with one statement
suppressed, so the ring is drawn and the floorplan reserve is in force and the
only difference is that the fill keeps out of nothing (`keepout [] area 0.0`).

**And the band was firing on the wrong rectangle.** `arm_noring` is `origin/main`,
unmodified, in a container built from the same image WITHOUT the `sealring_cells`
overlay — i.e. the shipped image exactly as anyone has it. The generator fails, the
flow says so correctly, and then:

    keepout  ['edge:26.0um']  area 137645.56 um^2
    bbox     [441.97, 442.0, 1494.0, 2089.0]      <- the ROUTED CORE, not the die

1052 x 1647 core = 1732644 um^2, of which 137645.56 — 7.9% — is deleted to protect
a ring that is not on the layout. `1052.03*1647 - 1000.03*1595 = 137645`, exact.

**And the honest size of that, measured.** The paired arm on this branch reports
`167/5:EMPTY` — the marker is not on the layout, so nothing is kept out — and
fills 258044 shapes against main's 257816, every layer reaching target in BOTH.
On this die the wrong-rectangle band costs 228 fill shapes and no failed target,
because a 1052x1647 core at 1.87% utilisation has enough headroom to fill
elsewhere. The case where it is NOT free is already on record in `729b62b29`
itself: an ungated 26 um band on a 240x240 um macro removes 38.6% of the die and
takes metal2 from 0.3500 (reached) to 0.3499 (not). That commit gated it on
`chip_die`; this reads the rule, which is the only form that cannot be wrong about
a rectangle it never has to guess.

**137645.56 is the figure `729b62b29`'s own commit message quotes as evidence its
keep-out works** — "The keep-out fires (declared:true, 137645.56 um^2) but this
image's PDK ships no sealring_cells, so the flow's layout carries no ring to
protect." The number is right; the reading is inverted. That is not the keep-out
firing, it is the keep-out firing on the wrong rectangle for no reason, and it is
the case a marker keep-out cannot get wrong: an absent marker is an EMPTY region.

## 6. The end-to-end number

`reports/phase3/drc_signoff.rpt`, the flow's own sign-off DRC, on the die the flow
is about to ship, with all three fixes in and a real ring on the layout:

| arm | plugin | role | `GR.2` | `GR.4` | `V1.2a` | `V3.2a` | `M2.3` | `M3.3` | `PL.8` | `M1.4` | **total** |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `arm_base` | 0cd4039ca, auto die | before all three | — | — | — | — | — | — | — | — | **no die** |
| `arm_base2` | 0cd4039ca, --die-um 1936x2531 | before all three, slot-sized | — | — | — | — | — | — | — | — | **no die** |
| `arm_nores` | main, reserve suppressed | control for the ring band | — | — | — | — | — | — | — | — | **no die** |
| `arm_noko` | main, keep-out suppressed | control for the keep-out | 16732 | 0 | 0 | 0 | 329 | 19 | 1 | 0 | **17081** |
| `arm_noring` | main, PDK without sealring_cells | control for the band-with-no-ring | 0 | 0 | 0 | 0 | 329 | 19 | 0 | 0 | **348** |
| `arm_head2` | origin/main | after | 0 | 0 | 0 | 0 | 329 | 19 | 1 | 0 | **349** |
| `arm_mine` | this branch | after + deck-derived keep-out | 0 | 0 | 0 | 0 | 329 | 19 | 1 | 0 | **349** |
| `arm_mine_noring` | this branch, no overlay | paired control for arm_noring | 0 | 0 | 0 | 0 | 329 | 19 | 0 | 0 | **348** |

## 7. What survives, and it is none of the three

The survivors are `M2.3` / `M3.3` — "Minimum metal2/metal3 area 0.1444 um^2" —
and they are the router's, not the ring's, the fill list's or the keep-out's. The
flow already knows, in its own log for this run:

    phase3/stage3/pnr/openroad.log:2051
    MIN_AREA_PATCH_DONE: deficient=390 patched=185 unpatchable=205 pin_merged_skipped=0

390 shapes below the minimum-area rule, 185 patched, 205 the patcher could not
fix. A patcher that reports 205 it could not fix, on a die where the deck finds
349, is a real and SEPARATE gap. It is named here and not touched: the only ways
to make that number fall from here are the ones that are off limits — deleting
geometry, moving a pin, widening a rule, or dropping a layer from the deck.

LVS on the same sealed and filled die: `circuits match uniquely`.


## 8. The no-regression proof, per shape

`cmp_fill_emit.json -> layers[].fill_shapes`, three independent full runs on the
sealed die:

    arm_head2 (origin/main)   metal1 113610  metal2 178450  metal3 180397  metal4 178734  metal5 180554
    arm_mine  (this branch)   metal1 113610  metal2 178450  metal3 180397  metal4 178734  metal5 180554
                              total 831745 in both, and the same 349 DRC items, item for item

And the layouts themselves, by KLayout XOR rather than by a hash (a GDS carries
the writer's timestamp, so the two files' sha256 differ and say nothing):

    LAYERS COMPARED 35   LAYERS DIFFERING 0   TOTAL XOR AREA 0.000000 um^2

Identical to the shape and to the polygon. Reading the keep-out out of the deck rather than insetting
a band places exactly the same fill on this die. The change is a change of
AUTHORITY, not of geometry — on a PDK where the three figures coincide. On the
same die with no ring, the band deletes 7.9% of the fillable core and the deck-read
keep-out deletes nothing.

## 9. What I could not settle

**The composed EDA image's PDK is missing the seal-ring PCell library.** Nothing in
this repository can fix it, and until it lands nobody can exercise the flow's
seal-ring path: the generator prints one error, exits 0 and writes nothing, and the
flow correctly reports FAIL and stops. Every arm above that carries a ring does so
because the missing directory was supplied to the container as a read-only overlay.
The ask, precisely: add
`gf180mcuD/libs.tech/klayout/tech/pymacros/sealring_cells/` — `__init__.py`,
`sealring.py`, `draw_sealring.py`, `layers.py` — to the composed image. The
shuttle operator's own precheck container ships it.

**A bridge-declared fill config gets no keep-out at all**, on either revision: the
keep-out is attached only in the derived-config path. None of the 6 PDKs in
`programs/pdk_registry.json` declares one, so the path is currently unreachable.
Named rather than fixed — a fix would be a change no input in this tree can
exercise, and this repository already has enough clauses nothing can fail.

## 10. Not run / not determined

* The shuttle operator's own precheck container was not run on these dies; every
  number above is the FLOW's own sign-off deck, which is the same PDK deck with a
  different option set. The two are not directly subtractable and no number here
  is presented as the operator's verdict.
* Extraction and STA on the filled die. Dummy metal now sits directly above and
  below live routing on every metal layer and no deck rule constrains inter-layer
  coupling.
* The `PL.8` item is the flow deck's own drawn-only poly2 density count; the
  operator's build of the same deck counts drawn + dummy and reports that layer
  passing. Two builds of one PDK's deck, not a disagreement about the layout.
* The seal ring is only producible here because the PDK in the composed EDA image
  is missing `libs.tech/klayout/tech/pymacros/sealring_cells/`, supplied for these
  runs as a read-only overlay. Until that lands in the image, the flow's seal-ring
  path cannot run for anyone.

---

## Appendix — the instruments, and the one that was validated first

    count_drc.py   counts <item><category> out of the KLayout report database.
                   Validated BEFORE use against a report whose answer was already
                   published (17988 / GR.2 17623) and matched to the item. Exits 2
                   with "this is NOT a zero" on a missing or unreadable report.
    pindist.py     min pin-port-box edge to the slot rectangle, from the routed
                   DEF's own PINS section. Exits 2 rather than printing 0 when
                   there is no UNITS line, no PINS section, or no parsable box.
    xor.py         per-layer KLayout XOR between two layouts, because a GDS
                   carries the writer's timestamp and its sha256 answers a
                   different question than "is it the same die".

Every count in this document is cross-checked against the flow's own
`reports/phase3/drc_signoff.json -> real_violation_total`, and the two agree on
every arm that produced a die. On the three arms that produced NO die, that same
field reports 0 or 3 off the ROUTER's projection — which is why "no die" is written
in the table rather than a number.
