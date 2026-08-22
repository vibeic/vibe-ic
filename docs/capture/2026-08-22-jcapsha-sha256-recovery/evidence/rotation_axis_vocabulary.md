# The `-rotation_vertical` measurement, and what it refutes

Measured 2026-08-22 on `ghcr.io/vibeic/vibeic-eda:0.3.25`
(image id `b9124fe1778a`), OpenROAD `26Q3-1655-g2b33daff56`, on this host.
Every number below is reproducible with the four `.tcl` files beside this one:

    docker run --rm -v <dir>:/w --entrypoint /bin/bash \
      ghcr.io/vibeic/vibeic-eda:0.3.25 \
      -lc 'openroad -exit -no_init /w/probe_bbox.tcl'

## The claim under test

A prior lane established, in four separate OpenROAD processes, that the
placed-pad orientation on the EAST and WEST sides is `R90` / `MXR90` for
`PAD_ROTATION_VERTICAL` = `R0` / `R90` / `R180` / `MX`, and concluded from
that constancy that **the variable is inert**.

The data is correct. The inference is not.

## 1. The argument is not dropped at any interface

    librelane/scripts/openroad/common/pad_cfg.tcl:79
        -rotation_vertical $::env(PAD_ROTATION_VERTICAL) \

    OpenROAD `make_io_sites` proc body (dumped with `info body`):
        if { [info exists keys(-rotation_vertical)] } { set rotation_ver $keys(-rotation_vertical) }
        ...
        pad::make_io_row <hor_site> <ver_site> <cor_site> \
            <offsets x4> $rotation_hor $rotation_ver $rotation_cor $index

The value reaches the row builder. Nothing discards it.

## 2. Holding one axis and sweeping the other

`-rotation_horizontal R0`, sweeping `-rotation_vertical` — the EAST/WEST rows
do not move, and the SOUTH/NORTH rows do:

    ROTV   IO_SOUTH  IO_NORTH   IO_EAST  IO_WEST
    R0     R0        MX         R90      MXR90
    R90    R90       MYR90      R90      MXR90
    R180   R180      MY         R90      MXR90
    MX     MX        R0         R90      MXR90

`-rotation_vertical R0`, sweeping `-rotation_horizontal` — the complement:

    ROTH   IO_SOUTH  IO_NORTH   IO_EAST   IO_WEST
    R0     R0        MX         R90       MXR90
    R90    R0        MX         R180      MX
    R180   R0        MX         R270      MYR90
    MX     R0        MX         MXR90     R90

## 3. The site argument routes the same way, and the geometry confirms it

One command, two DISTINCT fake sites so the site argument is distinguishable,
`-rotation_horizontal R90 -rotation_vertical R180`, die 8000 x 8000 um:

    ROW IO_SOUTH  bbox=(710000 0)       (7290000 710000)   site=SITE_V  orient=R180
    ROW IO_NORTH  bbox=(710000 7290000) (7290000 8000000)  site=SITE_V  orient=MY
    ROW IO_EAST   bbox=(7290000 710000) (8000000 7290000)  site=SITE_H  orient=MXR90
    ROW IO_WEST   bbox=(0 710000)       (710000 7290000)   site=SITE_H  orient=R90

The bounding boxes settle that the row NAMES mean what they say: `IO_SOUTH`
is at the bottom, `IO_EAST` at the right. So, measured on both the site and
the rotation argument, in one command:

    -*_horizontal  ->  the EAST and WEST rows
    -*_vertical    ->  the SOUTH and NORTH rows

That is internally consistent. It names a row by the axis PERPENDICULAR to the
row's run: `IO_EAST` extends in y and is called horizontal.

## 4. And the layer above uses the opposite convention

`librelane/scripts/openroad/common/pad_cfg.tcl:84-85`, in the same file that
passes the variable through:

    set vertical_sides   [list PAD_EAST PAD_WEST]
    set horizontal_sides [list PAD_SOUTH PAD_NORTH]

librelane names a row by the axis it RUNS ALONG. So `PAD_ROTATION_VERTICAL` —
which the file that passes it associates with `PAD_EAST` / `PAD_WEST` eleven
lines further down — is delivered by the tool to `PAD_SOUTH` / `PAD_NORTH`.

## What this refutes, and what it leaves standing

REFUTED: "`PAD_ROTATION_VERTICAL` is inert." It is a live knob. It steers the
side-pair opposite to the one its own layer's vocabulary assigns it.

WHY THE PRIOR MEASUREMENT SAW CONSTANCY: it swept ONE axis and read the sides
that the OTHER axis steers. Four processes remove the row-reuse confound they
were run to remove; they cannot remove a wiring assumption, because every one
of the four holds `PAD_ROTATION_HORIZONTAL` at the same value.

STILL STANDING: everything that lane measured about the EXTENT. The
along-the-row extent is the master's WIDTH on all four sides; upstream uses
`getWidth` in both places; the vertical-side pad orientation at
`PAD_ROTATION_HORIZONTAL`'s default is `MXR90` / `R90`, which is exactly the
row orientation in the first table's first row. The two measurements agree
where they overlap.

CONSEQUENCE FOR THE RULING: a step that refuses `rc=2 NOT DETERMINED` on a
non-default `PAD_ROTATION_VERTICAL` "because the placer ignores it" would be
refusing on a premise this measurement contradicts. The refusal may still be
the right behaviour — a knob whose effect crosses to the other side-pair is
arguably worse than an inert one — but the REASON printed with it would be
false, and a reason is the part a reader acts on.

---

## Independently corroborated by a concurrent lane, on a different image

Found after the fact, by listing the remote: a second lane
(`origin/jcapsha/sha256-capture`) reached the same conclusion the same day,
and its numbers agree with these cell for cell.

    this lane      image 0.3.25, OpenROAD 26Q3-1655-g2b33daff56
    the other lane image 0.3.24, OpenROAD 26Q3-1607-g27fd905b8a

Different image, different tool build, and a different probe DESIGN — they ran
a 2x2 with one process per cell rather than two one-at-a-time sweeps, and they
used the site arguments as a positive control that needs no orientation
reasoning at all. Their table:

    ROTH  ROTV | IO_SOUTH  IO_NORTH | IO_WEST  IO_EAST
    R0    R0   | R0        MX       | MXR90    R90
    R0    R90  | R90       MYR90    | MXR90    R90
    R90   R0   | R0        MX       | MX       R180
    R90   R90  | R90       MYR90    | MX       R180

Every cell that overlaps the two sweeps above is identical, including the
`R90`/`MX` pair on the vertical rows that only the horizontal-flag sweep
reaches. Their site control lands the same way round as the one here.

HOW INDEPENDENT THIS ACTUALLY IS, stated rather than implied: two different
images and two different probe designs is real independence of the
MEASUREMENT. It is not independence of the QUESTION — both lanes were pointed
at the same prior conclusion by the same brief, on the same host. So it
corroborates that the crossing is not a probe artefact and not a build
artefact; it does not corroborate that the crossing is the most important
thing to ask about.

AND THE SIGNAL WAS ALREADY IN THE ORIGINAL NOTES. That lane quotes a line the
first lane wrote and set aside — "SEPARATE OpenROAD oddity, observed and NOT
chased: the SOUTH pad's orientation tracked the `-rotation_vertical` argument
even though `-rotation_horizontal` was held at R0 for every run". That is this
finding, written down at the time, filed as an oddity next to the conclusion it
contradicts.
