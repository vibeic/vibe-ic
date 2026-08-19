# The slot size clause, cleared — and the four walls behind it

All sixteen stages of the shuttle operator's own precheck executed, for the first
time, on a die this flow floorplanned. This document records what was measured,
with the container's own lines, and names each wall that is left.

Everything here was measured on 2026-08-20 on 8HD-a. Nothing was hand-drawn, and no
layout was resized, moved or edited by hand at any point.

    operator precheck   ghcr.io/wafer-space/gf180mcu-precheck:latest
                        sha256:f6c0cb88efce8769ec87de5a2035ada731fd8fffb1b3e5e1968078f6dd191c2f
    operator template   github.com/wafer-space/gf180mcu-project-template @ 0de7e394
    flow image          ghcr.io/vibeic/vibeic-eda:0.3.13
    design              spm, gf180mcuD, phase 2 reused from an existing run

## 1. WHERE THE GEOMETRY CAME FROM

Not from any brief and not from this repository. `submission_template_ingest`
(step 0.5ic) read the operator's four slot configs and `submission_template_check`
re-hashed and re-derived every number from the ingested copies:

    slot_0p5x0p5   DIE_AREA [0,0,1936,2531]   CORE_AREA [442,442,1494,2089]
    slot_0p5x1     DIE_AREA [0,0,1936,5122]   CORE_AREA [442,442,1494,4680]
    slot_1x0p5     DIE_AREA [0,0,3932,2531]   CORE_AREA [442,442,3490,2089]
    slot_1x1       DIE_AREA [0,0,3932,5122]   CORE_AREA [442,442,3490,4680]

These are exactly the numbers `check_size.py` computes from its own constants, which
is the point: the flow never computes them, it reads them.

SLOT CHOSEN: `slot_0p5x0p5`, 1936 x 2531 um = 4.90 mm^2 — the smallest of the four,
24% of the area of `1x1`. All six clauses treat the four slots identically, so the
smallest is the cheapest die that can still pass. Density, DRC and routing effort all
scale with area, and this run confirms that: the density deck's rules are all
"coverage over the ENTIRE die".

## 2. WHAT THE FLOW PRODUCED

    initialize_floorplan -die_area "0 0 1936 2531" \
                          -core_area "442 442 1494 2089"

Both rectangles came out of the operator's own file via the Step 0.5ic report. The
`--die-um` flag was `auto`; the slot pinned the die. The runner said so:

    [phase3] die-um=auto and Step 0.5ic declares shuttle slot slot_0p5x0p5 —
             honoring the OPERATOR's pinned DIE_AREA 1936x2531um verbatim
             (read from librelane/slots/slot_0p5x0p5.yaml, sha256 683e070cbd11)
    [phase3] Step 0.5ic slot slot_0p5x0p5 pins CORE_AREA [442, 442, 1494, 2089] —
             using the OPERATOR's core rather than die-minus-margin

Measured on the streamed GDS with the operator's own KLayout:

    top=spm  dbu=0.001  p1=(0.0,0.0)  p2=(1936.0,2531.0)  W=1936.0  H=2531.0
    Via5 0 shapes   MetalTop 0 shapes   GUARD_RING_MK 1 shape, 141758 um^2

STATUS OF THAT GDS, stated plainly because it decides what may be published: it is a
DEBUG artefact. The run's PnR gate is FAIL (§5a), and the flow's own route verdict
says of exactly this case, "Emitted DEF/GDS are kept for debugging but are NOT
sign-off artifacts." It was streamed by the flow's own Magic stream-out from the
flow's own routed DEF. It exists to measure how far the operator's precheck gets on a
correctly-sized die. It is not in `benchmark-data/` and must not be.

## 3. THE SEAL RING

Drawn by the PDK's OWN generator, driven by step 26.5ic. The ring, measured:

    outer  0 .. 1936  /  0 .. 2531 um
    inner 16 .. 1920  / 16 .. 2515 um      a 16 um band on all four sides
    1 polygon on GUARD_RING_MK (167/5), 141758 um^2
    die bounding box unchanged — the ring is drawn INSIDE it

THE PDK IN OUR OWN IMAGE CANNOT DO THIS, and the failure is silent. `gf180mcuD` in
`vibeic-eda:0.3.13` ships `libs.tech/klayout/tech/scripts/sealring.py` but NOT the
`sealring_cells` PCell library it imports. The script prints

    Error: Couldn't load the seal ring library.

and calls `sys.exit()` with no argument — so it exits **0** and writes nothing.
`die_finishing_gen` diffs the two layouts instead of trusting that status and FAILs
with the reason named. The ring above was produced by pointing the same step at the
PDK version inside the OPERATOR's precheck container (ciel `d658698b…`), which does
ship the library. That is an environment difference. No PDK file is vendored here.

## 4. THE PRECHECK, RUN FOR REAL

    docker run --rm -v $HOME:$HOME -v <gdsdir>:/data/design:ro -v <rundir>:/data/rundir \
      ghcr.io/wafer-space/gf180mcu-precheck:latest \
      python precheck.py --input /data/design/spm.gds --dir /data/rundir \
        --top spm --slot 0p5x0p5

BEFORE — the published layout, `sha256 fb08d9ed…`, reproduced to anchor everything:

    PrecheckFlow - Stage 3 - Check Slot Size                        2/16
    [Error]: Layer 'GUARD_RING_MK' is not used.                     rc=255

AFTER — the slot-sized, sealed die, `sha256 b8ad6677…`:

    Layout size:
    layout width:  1936.0
    layout height: 2531.0
    Expected slot size:
    slot width:  1936.0
    slot height: 2531.0
    Layout dimension matches the selected slot size 0p5x0p5.
    ...
    PrecheckFlow - Stage 16 - Write the Layout                     16/16

    [ERROR]     8 KLayout density errors found. - deferred
    [ERROR]     1 KLayout antenna errors found. - deferred
    [WARNING] 252 Magic DRC errors found.
    [ERROR]  1177 KLayout DRC errors found. - deferred

Clauses 1-6 all pass. Stage 4 GenerateID passes. Nothing before density blocks.

## 5. THE FOUR WALLS THAT ARE LEFT

### 5a. PnR does not converge — and it is NOT the slot's doing

`detailed_route` reaches `[INFO DRT-0199] Number of violations = 0` in-loop, and then

    [WARNING DRT-0701] Post-route verification found 1 violation(s) that the
    routing loop did not report (0 in-loop). The published result is the verified one.

The marker, dumped with `detailed_route -output_drc`:

    violation type: NS Metal
      srcs: net:__uuf__._045_
      bbox = (1045.6700, 1939.3550) - (1045.7100, 1939.4100) on Layer Metal1

A 0.04 x 0.055 um Metal1 sliver — insufficient metal overlap at a pin, not congestion.
Three different placements (slot die, `--util 0.45`, `--spare-density 0`) each left
exactly one, at a different net each time.

THE CONTROL SETTLES THE ATTRIBUTION. The same plugin at the flow's OWN auto die
reports `detailedroute__route__drc_errors = 2`. And the run cited as clean —
`_c12_spm_gf180mcuD`, the ancestor of the published `v1.9.96` GDS — has **zero**
`DRT-0199` lines in its `openroad.log`: it was a RESUMED run, and its own DRC report
says so (`drc source: final [INFO DRT-0199] count (ABSENT …)`). There is no evidence
this design ever routed DRC-clean on this PDK with this toolchain. The route gate is
doing its job; it was previously reading a number nobody had measured.

SECOND FINDING, adjacent: the route reconciliation gate (#1080) reports
`ROUTE_DRC_METRIC_DISAGREEMENT: METRIC=1 but LOG=0` for this case. On the vibeic
OpenROAD fork the two numbers differ for a KNOWN reason that the fork prints in
DRT-0701 — the metric is the post-route VERIFIED count and the log line is the
in-loop one. The gate does not read DRT-0701, so a design with a verified-only
violation is refused as a disagreement rather than reported as "1 violation,
verified". The verdict is right; the sentence is not.

### 5b. Minimum density — the wall the empty canvas guarantees

Eight errors, one per layer, all of them the same rule shape:

    DCF.1b  PL.8  M1.4  M2.4  M3.4  M4.4  M5.4  MT.3

From the PDK's own deck: `M1.4 : Metal1 coverage over the entire die shall be >30%
(Refer to section 13.0 for Dummy Metal fill guidelines. Customer needs to ensure
enough dummy metal to satisfy Metal1 coverage)`. The die is at **1.03%** utilisation.

Our step 34 metal fill does not help and says so:

    SPARSE_DIE_FILL_SKIPPED: core_util=1.0325177110786448% < 5.0% — full-die
    decap/fill tiling bounded to avoid filling an empty fixed wrapper

That guard is right for an empty wrapper and wrong for a shuttle slot, where the
emptiness IS the design. It is also the wrong TOOL: std-cell fillers occupy rows;
these rules want DUMMY METAL on the `_Dummy` datatype-4 layers, which is a different
artefact entirely.

MEASURED REMEDY. The PDK ships its own fill scripts in the same directory as the
seal-ring generator — `fill_all.rb`, which chains `fill_comp.rb`, `fill_poly2.rb`
and `fill_metal.rb` onto COMP, Poly2 and Metal1-5. Driven the way upstream's
`KLayout.Filler` drives it (`klayout -b -zz -r <script> -rd input= -rd output=`):

    density errors   8  ->  3      (cleared: DCF.1b PL.8 M1.4 M3.4 M4.4)
    remaining               M2.4  M5.4  MT.3
    bounding box     unchanged, 1936.0 x 2531.0, still exactly the slot

So the density wall is one PDK script call from being two thirds gone. Upstream's
`chip.py` already has the shape to copy, in this exact order:

    "+Checker.KLayoutAntenna": KLayout.SealRing
    "+KLayout.SealRing":       KLayout.Filler
    "+KLayout.Filler":         KLayout.Density
    "+KLayout.Density":        Checker.KLayoutDensity

generator and checker SEPARATE, checker refuses. Step 26.5ic already sits between
routing (26) and physical verification (31) for the same reason fill must: metal
added after the evidence means the die that was signed off is not the die that ships.

### 5c. MT.3 is structurally unsatisfiable for a 5LM submission

`MT.3 : MetalTop coverage over the entire die shall be >30%`. But clause 4 of the
operator's own `check_size.py` is

    if MetalTop_region.count() > 0:
        print("[Error]: Layer 'MetalTop' is used. wafers.space uses the 5LM metal stackup.")

Satisfying MT.3 fails clause 4; satisfying clause 4 fails MT.3. The operator's
precheck runs the density deck in a configuration whose `metal_top`/`metal_level`
branch includes MetalTop while forbidding MetalTop geometry. This is a contradiction
in the operator's own setup, not in the die, and is presumably why their density
checker is `deferred` rather than fatal. It should be reported upstream to them; no
submission can clear it.

### 5d. The seal ring brings its own DRC

Same die, sealed and unsealed, through the same container (`--skip KLayout.CheckSize`
for the unsealed one, which cannot pass clause 5 by construction):

                     KLayout DRC   Magic DRC   density   antenna
    unsealed              360         248         8         4
    sealed               1177         252         8         1

The 817-error difference is almost entirely guard-ring rules: `GR.4` 794, `GR.2` 19.
The PDK's own seal-ring PCell, at this die size, violates the PDK's own deck. The
ring also FIXES three antenna violations (4 -> 1), which is what a grounded ring
around the die should do. Both halves are the PDK's behaviour, measured, not ours.

## 6. WHAT WAS NOT RUN

  * The full `programs/tests` suite. It was measured tonight to put a 32-core host
    at load 276 with no free memory. Only
    `tests/test_phase3_slot_pinned_die.py` was run (15 passed).
  * `submission_template_ingest` / `_check` were not modified; they are s05's and
    already landed. One observation for their author, not acted on here: their gate
    requires the slot to be declared by its FILE STEM (`slot_0p5x0p5`), while the
    operator's own `check_size.py --slot` vocabulary is `0p5x0p5`. A design that
    declares the operator's own spelling is refused with `SLOT_NOT_SHIPPED`.
  * The die-identification half of 26.5ic stays `NOT_DETERMINED`: the packaging
    choice is not declared for this design, and the operator's `generate_id` places
    its four cells only for a chip-on-board submission.
  * No fix was attempted for 5a, 5b, 5c or 5d. Each is named with its measurement so
    the next hand starts from the number, not from the symptom.
  * `--cob` was never passed to the precheck; every run above is the non-CoB path.
