# The seal ring is not drawn wrong. It was drawn onto a die that had already spent its band.

Research note. **Nothing here changes a layout, a gate, or a version.**
Measured values only; where a thing was not measured it says NOT DETERMINED.

Die: 1936.0 x 2531.0 um, origin (0,0), dbu 0.001, 5-metal BEOL, guard-ring marker
present. Operator precheck: rc=1, 1177 KLayout DRC.

---

## 0. The correction, stated first because it changes what to go fix

The split is right. The inference drawn from it is not.

> "813 violations are the seal ring and nothing else... it is one object, drawn wrong,
> reported 794 times."

**Measured: the ring, in isolation, has ZERO violations on every metal layer.**

```
=== GR.4 width(12um) ===
layer     ring metal ALONE     as built
metal1              0             18
metal2              0            766
metal3              0              9
metal4              0              1
metal5              0              0
TOTAL               0            794
```

Both halves score zero alone — the unsealed die has 0 GR.4, and the ring has 0 GR.4.
794 appear only in the **union**. That is not a contradiction; it is what `GR.4` is
built to do (§1). It means the defect is a **relationship**, not an object, and going
to look for the malformation in the ring will find nothing, because there isn't one.

The movable cause is at the other end: **all 41 of the die's I/O pins are placed flush
on the die boundary, inside the 16 um band the ring occupies, and the ring is drawn
directly on top of them — 41 of 41, 100% of every pin's port area.** The floorplan
reserved nothing for a seal ring. The ring then landed where the pins already were.

The count is a symptom of that. So is something worse than the count, in §3.

---

## 1. GR.4, quoted from the deck

`libs.tech/klayout/tech/drc/rule_decks/guard_ring.rb`:

```ruby
  # Rule GR.4: Minimum metal-n width (n= 1 to 6): 12
  logger.info('Executing rule GR.4')
  (1..6).each do |lvl|
    next unless ctx.metal_level_numerical >= lvl

    metal = ctx[METAL_MAP_GUARD_RING[lvl][:metal]]

    gr4_l1 = metal.not_outside(guard_ring_mk).width(12.um)
    gr4_l1.output('GR.4', "GR.4 : Minimum Metal width#{lvl}: 12")
    gr4_l1.forget
  end
```

and its neighbour, which the same evidence explains:

```ruby
  # Rule GR.2: Min GUARD_RING_MK space to prime die COMP, NWELL, Poly2,
  #            Metal 1, 2, 3, 4, 5 and metal Top: 10
    gr2_l1 = metal.separation(guard_ring_mk, 10.um)
```

As emitted into the report DB (`<categories>` in `drc.klayout.lyrdb`) — note both are
the **last** iteration of the 1..6 loop, so the id in the lyrdb does not tell you which
metal level fired:

| id | text |
|----|----|
| `GR.4` | `GR.4 : Minimum Metal width5: 12` |
| `GR.2` | `GR.2 : Min GUARD_RING_MK space to prime die Metal5: 10` |

### `not_outside` is the whole mechanism

`not_outside(guard_ring_mk)` selects every polygon that is **not entirely outside** the
marker — anything that so much as touches it — and `.width(12.um)` then measures **that
entire polygon**.

So one 0.28 um routing wire touching the marker at the die edge is measured, **along its
full length**, against a rule written for a 15 um seal-ring run. It reports a violation
at every narrow place — hundreds of microns deep into the die, far from the ring.

That is why the violation coordinates look like they are in the core. They are the same
defect, at the edge, projected inward by the rule's own semantics. Reading the
coordinates without reading `not_outside` first is how "the ring is malformed" becomes
the obvious answer, and it is the wrong one.

---

## 2. WHY does the PDK's script draw geometry that breaks the PDK's rule? — it doesn't

Taking the four candidate shapes in the brief, each against evidence:

### (a) "We invoke it wrong — missing argument, wrong dimensions, wrong units." NO.

Recorded argv:

```
python3 <PDK>/libs.tech/klayout/tech/scripts/sealring.py
  --input  <in>.gds  --output <out>.gds
  --die-width 1936.000000  --die-height 2531.000000
```

matched against the routed DEF: `DIEAREA ( 0 0 ) ( 3872000 5062000 ) ;` at
`UNITS DISTANCE MICRONS 2000` = 1936.0 x 2531.0 um. Exact. And the ring it produced,
measured: outer `[0, 0, 1936, 2531]`, inner `[16, 16, 1920, 2515]`, annulus area
141758.0 um^2 — which is the exact arithmetic annulus, 1936x2531 - 1904x2499. Nothing
is off by a factor, an offset, or a unit.

### (b) "It needs a companion layer we don't supply and silently omits it." NO.

It supplied its own, on 14 layers, including the marker and the implants:

```
comp 1 poly / 141758.0 um^2        contact  66978 polys      pad      1 poly (NEW)
pplus 1 poly / 141758.0 um^2       via1     55016 polys      guard-ring
metal1..metal5 rings               via2/3/4 64184/55016/64184  marker  1 poly (NEW)
```

It drew its own guard-ring marker and its own p-implant ring. Nothing was expected from
us that we withheld.

### (c) "It drew nothing useful; this is a fragment of the `sys.exit()` failure." NO.

That failure mode is well characterised and it writes **no output file at all**. Here
the output exists, carries a complete annulus on every BEOL layer with a full contact
and via wall (66978 contacts, 55016 + 64184 + 55016 + 64184 vias), and **scores zero
DRC violations measured in isolation**. This is a fully-formed, legal seal ring.

### (d) "Correct in isolation, illegal at this die size." HALF. Correct in isolation — yes,
measured. Illegal at this die size — no. It is illegal in this die's **content**.

### (e) The shape the list is missing, and the one the evidence selects

**The ring is correct and legal. It was drawn onto a die whose outer 16 um band was
already occupied, so it merged with what was there, and the merged object is illegal.**

The proof is arithmetic, and it is already sitting in our own gate's report file.
`die_finishing.json` logs `added_geometry` as the layer-by-layer diff (output minus
input) — i.e. only the area the ring drew that was **not already occupied**. Compare it
against the ring's actual footprint:

```
layer       ring drew   gate logged   difference   design already in band
metal1     132950.000    132937.774       12.226                   12.916
metal2     141758.000    141433.684      324.316                  324.316
metal3     132950.000    132927.776       22.224                   23.624
metal4     141758.000    141754.352        3.648                    3.648
metal5     132950.000    132950.000        0.000                    0.000
```

The difference column **is** the design geometry the ring landed on top of — exact to
three decimals on metal2, metal4 and metal5. (metal1 and metal3 differ slightly because
their ring run is the ~15 um inner annulus, so ~1 um of the band is not covered by ring
metal on those two layers.)

Our gate computed that shortfall, wrote it into its own report, called the result PASS,
and nobody read the number. §5.

---

## 3. The coordinates: not round the ring, not at the corners — where it meets the pins

Per-layer attribution inside the sealed layout, geometry assigned to its source cell
(`sealring*` / `*FILL*` / everything else = the design):

```
layer    RING total   RING inside band   FILL inside band   DESIGN inside band
metal1     132950.0        132950.000              0.000             12.916
metal2     141758.0        141758.000              0.000            324.316
metal3     132950.0        132950.000              0.000             23.624
metal4     141758.0        141758.000              0.000              3.648
metal5     132950.0        132950.000              0.000              0.000
                                                                    (um^2)
```

* **The ring occupies its band and nothing else** — `RING inside band == RING total`,
  exactly, on all five layers. It never strays into the core.
* **Metal fill is exonerated** — 0.000 um^2 inside the band, every layer. Fill respected
  the keep-out. The router did not.

`not_outside` returns **one** merged polygon per layer. The part of it outside the ring
band — the core routing dragged in by the touch — is 100% DESIGN geometry:

```
layer    leak outside band     bbox of the leak (um)
metal1         295.338 um^2    (1489.97, 1260.43) - (1920.00, 1275.25)
metal2        3234.960 um^2    ( 951.30,   16.00) - ( 986.30, 2515.00)
metal3        1031.943 um^2    (  16.00, 1263.78) - (1920.00, 1886.22)
metal4         131.776 um^2    ( 955.22, 2044.37) - ( 955.50, 2515.00)
metal5           0.000 um^2    -
```

### Those bboxes are the pin escape routes

From `routed.def`:

```
PINS 41 ;
    - clk  ... + LAYER Metal3 (-520 -280) (520 280) + PLACED ( 3871480 2530080 ) N ;
    - p    ... + LAYER Metal3 (-520 -280) (520 280) + PLACED (     520 2532320 ) N ;
    - rst  ... + LAYER Metal2 (-280 -520) (280 520) + PLACED ( 1936480     520 ) N ;
    - x[10]... + LAYER Metal2 (-280 -520) (280 520) + PLACED ( 1936480 5061480 ) N ;
```

Measured over all 41:

```
pins parsed                                              41
pins whose port box lies inside the outer 16um band      41
   by layer                          Metal2: 33   Metal3: 8
min / max distance of a port box to the die edge   0.000 / 0.000 um
```

Every pin is **flush with the die edge**. Metal2 (33 pins) and Metal3 (8 pins) are
exactly the layers carrying 766 and 9 of the GR.4 and all 19 of the GR.2. The metal2
leak band x in [951.3, 986.3] running the full die height is the `x[...]` bus escaping
to the top edge; the metal1/metal3 leaks at y ~ 1260-1275 out to x=1920 are
`clk/shift/sin/sout/tck/test` escaping right, and `p` escaping left.

For contrast, the parts of the design that were floorplanned properly stay far away:
the 419 standard-cell rows occupy x in [442.4, 1493.5], y in [442.96, 2085.4], and
FEOL — comp, nwell, poly2 — puts **0.000 um^2** inside the band, minimum distance to
the die edge 441.97 um. There was room. Nothing asked for it.

### The finding that outranks the DRC count

```
PIN PORTS GEOMETRICALLY OVERLAPPED BY SEAL-RING METAL ON THEIR OWN LAYER: 41 of 41
   clk   Metal3  port_area=0.1456  covered_by_ring=0.1456 (100%)
   p     Metal3  port_area=0.1456  covered_by_ring=0.1456 (100%)
   rst   Metal2  port_area=0.1456  covered_by_ring=0.1456 (100%)
```

**100% of every pin's port area is buried under seal-ring metal**, and the merge is
physical — `not_outside` returns a single connected polygon per layer, whose area
exceeds the ring's own by exactly the attached routing. Geometrically, all 41 I/O are
merged into the ring and hence into each other.

Whether that is a **netlist** short is NOT DETERMINED — that needs LVS/extraction, not
run (§7). But a die whose every pin is shorted to its seal ring does not work, and no
DRC waiver reaches that. **This, not the 794, is the reason this layout must not ship.**

---

## 4. The comparison, re-run here with a control

Same deck, same flags, same container, same top cell; only the input GDS differs:

```
klayout -b -zz -r <PDK>/libs.tech/klayout/tech/drc/<deck>.drc \
  -rd input=<gds> -rd topcell=<top> -rd report=<lyrdb> \
  -rd decks=all,-antenna,-density,-cup -rd variant=<variant> -rd workers=1
```

```
rule        OPERATOR   MY CONTROL   UNSEALED   delta
GR.4             794          794          0    +794
PP.2              87           87         87      +0
NP.2              83           83         83      +0
DF.13_MV          70           70         70      +0
NW.2a_LV          39           39         39      +0
NW.2b_LV          35           35         35      +0
DV.5              28           28         28      +0
GR.2              19           19          0     +19
NW.2b_MV           9            9          9      +0
DF.14_MV           9            9          9      +0
V1.2a              2            2          0      +2
V3.2a              2            2          0      +2
TOTAL           1177         1177        360    +817
```

My control reproduces the operator's 1177 exactly, rule for rule, so the A/B is
controlled at the invocation level, not merely at the artefact level.

Item-level, comparing category **plus full violation geometry**:

```
IDENTICAL (category + geometry) in both    360      <- coordinate-identical, zero drift
only in SEALED                             817      GR.4 794, GR.2 19, V1.2a 2, V3.2a 2
only in UNSEALED                             0
```

### The number is 817, not 813

`V1.2a` (2) and `V3.2a` (2) are ring-attributable too, and they are the same defect:

```
via1: space<0.26um edge pairs = 1 ; ring alone = 0 ; design alone = 0
   ep: (961.090,2527.150)-(960.949,2527.150) | (961.020,2526.900)-(961.161,2526.900)
via3: space<0.26um edge pairs = 1 ; ring alone = 0 ; design alone = 0
   ep: (955.360,2528.080)-(955.100,2528.080) | (955.230,2527.970)-(955.490,2527.970)
```

Zero in either population alone; present only in the union; located at y = 2527-2528,
inside the top 16 um band. Design vias in the ring's band, too close to the ring's via
wall. Identical mechanism to GR.4 and GR.2, different rule.

### Two caveats on the A/B, stated because they are real

1. The two inputs differ by **two** things, not one: the sealed layout carries the ring
   *and* the metal/comp/poly fill (53 cells vs 37; 3966 top instances vs 3958; the
   design itself identical — same 36 standard cells, identical nwell / nplus / dualgate
   areas). Strictly the delta is "ring + fill". The §3 attribution is what removes the
   ambiguity: fill measures **0.000 um^2** inside the band on every metal layer.
2. I did **not** measure the antenna deck. The brief reports antenna 4 -> 1; the
   `-antenna` deck was excluded from every run here, exactly as the operator's stage 14
   excluded it. That claim is unverified by me, neither confirmed nor disputed.

---

## 5. What the gate should have caught, and the predicate — described, NOT built

### What it checks today

`sealring_verify.py` refuses to trust the generator's exit status, correctly and for a
measured reason: the script's PCell library is missing in the pinned image, it prints
`Couldn't load the seal ring library.`, calls `sys.exit()` with no argument (**exit 0**)
and writes nothing. So the gate measures the output layout instead. It requires:

1. the output layout file exists;
2. the layer-by-layer diff against the input is non-empty;
3. the declared guard-ring marker layer carries geometry;
4. **ring topology** — a horizontal scan line through the die centre crosses the added
   geometry in >= 2 disjoint places, a vertical one likewise, and the centre is not
   covered;
5. it measures and reports `ring_extent.outer` and `ring_extent.inner`.

On this die all five passed, and all five were **true**: `horizontal_crossings 2,
vertical_crossings 2, centre_covered false`, marker present, outer `[0,0,1936,2531]`,
inner `[16,16,1920,2515]`.

### The gap, stated exactly

**Every predicate in that list is a question about the geometry the generator ADDED.
Not one asks what was ALREADY THERE in the band the ring is about to occupy.**

The gate proved the ring is a ring. It never asked whether the ring had anywhere legal
to be. That gap is exactly 817 violations wide — and, more to the point, 41 shorted pins
wide.

### The predicate

It needs **no DRC engine**, and should not grow one. It needs an emptiness test on a
band it already computes, over data it already holds in memory:

> Let `band` = `ring_extent.outer` minus `ring_extent.inner` — the annulus the check
> already measures and already reports.
> Let `pre` = the INPUT layout (`SEAL_IN`), which the check already reads in full and
> already indexes layer-by-layer to build the `before` map for its diff.
>
> **PRECONDITION:** for every layer L present in `pre`, `pre[L] & band` must be EMPTY.
> Report each non-empty layer by name with its intruding area. Verdict FAIL.

Why this shape:

* **No DRC engine.** One boolean region intersection per layer — cheaper than the
  region subtraction the check already does per layer for its diff.
* **No PDK literal, no foundry constant, no tuned number.** `band` is measured from the
  ring the PDK itself drew; the layer list is discovered from the input. This preserves
  the chip/PDK-agnostic property the module is careful about everywhere else.
* **It is a PRE-condition** — evaluable before the ring is drawn, so it fails fast
  instead of after a 23 MB layout exists.
* **It would have caught this one, by name.** Measured on the actual input:
  metal2 324.316, metal3 23.624, metal1 12.916, metal4 3.648, via1 0.473, via2 0.406,
  via3 0.068 um^2 inside the band — non-empty on **7 layers**.

**A corroborating variant that needs no new data whatsoever.** The gate already logs
`added_geometry` (output minus input) per layer. If it also knew the ring's own
footprint — discoverable chip-agnostically as *the cells present in the output that were
absent from the input* (`sealring`, `sealring$1`) — then `ring_footprint[L] -
added[L] > 0` means the ring was drawn over something. On this die that shortfall is
324.316 um^2 on metal2 and it is **already in the report file we shipped as PASS**.

### The half this does NOT catch, and which must not be faked

Band-emptiness catches 798 of the 817 (794 GR.4 + 4 via). It does not catch the 19
`GR.2`, which is a *separation* rule: 10 um of clearance from the marker, not merely
non-overlap. That 10 um is a number the **PDK owns** and the gate must not invent it:

* accept it as **declared input**, exactly as `SEAL_MARKER` already is (e.g.
  `SEAL_KEEPOUT_UM`);
* when declared, test the band **grown by that clearance** — here 16 + 10 = 26 um, at
  which the measured occupancy is metal2 417.001, metal3 39.155, metal1 19.816,
  metal4 6.448 um^2. Still non-empty, still FAIL;
* when **not** declared, report that half `NOT_DETERMINED`. Never PASS. A silent PASS on
  an undeclared clearance is the same class of error as trusting `sys.exit()`.

**Not implemented. Awaiting your decision.**

---

## 6. On the owner's goal of rc 0 — what this lever actually reaches

Stated plainly, because the arithmetic matters for planning:

* **Removing the ring's contact with the design removes 817**, taking 1177 -> 360. It
  does not reach rc 0.
* **The remaining 360 are pre-existing and unrelated** — `PP.2` `NP.2` `DF.13_MV`
  `DF.14_MV` `NW.2a_LV` `NW.2b_LV` `NW.2b_MV` `DV.5`, every one coordinate-identical in
  the unsealed layout. Implants, wells, diffusion taps, dualgate width: core and
  standard-cell territory (distance-to-edge p10 ~ 450 um). A separate defect with a
  separate cause. **Not investigated here.**
* rc 0 also requires the 3 density and 1 antenna deferrals, which I did not measure.

So 817 is the biggest single lever, and it is not the whole distance. Anyone planning
tonight's work should size it as 1177 -> 360, not 1177 -> 0.

### And the fix is not in the ring or in the gate

Even a perfect gate only says "no". The defect is upstream, in the floorplan, and the
flow's own artefacts show it:

* Pins are on the **die** boundary (edge distance 0.000 um) rather than a boundary inset
  for a seal ring — while the cell rows sit 442 um clear.
* The seal-ring keep-out the flow does emit, from `die_finished.def`:

  ```
  BLOCKAGES 4 ;
  # vibe-ic die-finishing: seal-ring band (placement blockage)
      - PLACEMENT RECT ( 0 0 ) ( 3872000 32000 ) ;      <- 16 um
  ```

  Three things are wrong with it, all measured:
  1. it is a **PLACEMENT** blockage — it does not stop a router, and it is routing, not
     placement, that is in the band (FEOL occupancy inside the band: 0.000 um^2);
  2. it is **16 um** — the band only, carrying no GR.2 clearance;
  3. `routed.def` contains **`BLOCKAGES` 0**. The blockage exists only in
     `die_finished.def`, which is *derived from* `routed.def` — written **after routing
     is complete**. In this run it constrained nothing. It is documentation, not a
     constraint.

The band must be reserved in the floorplan, before placement and routing, as a routing
obstruction, with the pins moved inside it. That is a change to the flow, not to the
ring and not to the gate, and it is **not proposed or implemented here**.

---

## 7. NOT RUN / NOT DETERMINED

* **Not run:** the full 16-stage precheck flow. Only the stage-14 KLayout DRC deck was
  re-run, with the operator's exact flags (`decks=all,-antenna,-density,-cup`).
* **Not run:** stage-12 magic-drc, LVS, extraction, **antenna**, density. The 3 density
  + 1 antenna deferrals are untouched and unexplained by me, and the brief's
  "antenna 4 -> 1" is unverified here.
* **Not run:** `programs/tests`, per the brief.
* **NOT DETERMINED:** whether the 41 pin/ring merges are netlist shorts. Geometric
  overlap measured (41/41, 100% of port area); electrical connectivity needs
  LVS/extraction, not run.
* **NOT DETERMINED:** the cause of the 360 pre-existing violations. Proven
  ring-independent; not otherwise investigated.
* **NOT DETERMINED:** which metal level each individual lyrdb `GR.4` item belongs to.
  The deck collapses a 1..6 loop into one category id; the per-level split
  (18/766/9/1/0) was obtained by re-deriving the rule outside the deck and sums to 794
  exactly.
* **Not done:** no layout modified, no GDS hand-edited, no violating geometry deleted,
  no rule deck relaxed, no ring regenerated, no flow re-run, no gate changed, no version
  bumped, nothing pushed.
