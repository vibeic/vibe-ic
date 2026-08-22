# I ran the probe myself, and it changes what I am entitled to say

Every earlier section of this branch carried the refutation of F3's premise as
SOMEONE ELSE'S measurement, and said so. That caveat can now be withdrawn.

## The run

    image      ghcr.io/vibeic/vibeic-eda:0.3.24
    OpenROAD   26Q3-1607-g27fd905b8a
    method     four SEPARATE `docker run` processes, one per (H,V) combination,
               so no row left by an earlier pass can be reused by a later one
    script     four_sides.tcl / probe.def (this directory), gf180mcuD

    ##### H=R0  V=R0   ps0=R0   pn0=MX     pw0=MXR90  pe0=R90
    ##### H=R90 V=R0   ps0=R0   pn0=MX     pw0=MX     pe0=R180
    ##### H=R0  V=R90  ps0=R90  pn0=MYR90  pw0=MXR90  pe0=R90
    ##### H=R0  V=MX   ps0=MX   pn0=R0     pw0=MXR90  pe0=R90

**Identical, value for value, to the table published in the source report** —
and produced on a DIFFERENT OpenROAD build (26Q3-1607 here, 26Q3-1581 there).
Varying H moves WEST and EAST and leaves SOUTH and NORTH alone; varying V does
the opposite.

`-rotation_horizontal` steers the VERTICAL sides. `-rotation_vertical` steers
the HORIZONTAL sides. The parameters are named for the ROW AXIS, not the side.
`PAD_ROTATION_VERTICAL` is not inert. **Independently confirmed, by me, on my
own host, in a build neither prior lane used.**

## And the consequence I had flagged but not confirmed is now confirmed

Driving main's own producer through the test fixture and reading the DEF it
writes, against the table above at the default H=R0 V=R0:

| side | main emits | tool produces | |
|---|---|---|---|
| SOUTH | `N` | `N` | match |
| **NORTH** | **`S`** | **`FS`** | **DIFFERS** |
| WEST | `FW` | `FW` | match |
| EAST | `W` | `W` | match |
| corners | `E`,`N`,`S`,`W` | placer alternates rotation and mirror | walks a pure rotation |

`S` is a 180-degree ROTATION; `FS` is a MIRROR. Main emits **no `FS` and no
`FN` anywhere**. A mirror and a rotation give the same bounding box for these
cells, which is why every fit, abutment and BTerm check agrees either way and
nothing caught it — only a reader deriving PIN POSITIONS from the DEF sees it.

Two independent sides of the same conclusion: my OpenROAD run, and main's own
emitted artefact.

## I did NOT fix it, and that is the "check for the existing one" rule

`origin/jpadsite/pad-site` already carries the fix, verified with an A/B on one
netlist and one builder with only the programs swapped — 21 orientations
changed, positions identical:

    6c3ebe447 padring: NORTH carried a rotation where the placer produces a MIRROR
    725f9352f padring: two of four CORNERS were mirrored by the tool and rotated by us

That branch is NOT an ancestor of main (measured). Re-implementing a verified
fix here would be the near-duplicate the brief warns about, and would conflict
with the better vehicle. **What this file adds is independent confirmation that
the defect is live on main today, which is what a lander needs to prioritise
that branch.**
