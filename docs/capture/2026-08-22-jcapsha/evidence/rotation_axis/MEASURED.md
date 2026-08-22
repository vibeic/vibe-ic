# `-rotation_vertical` is not inert. It is CROSSED.

Measured 2026-08-22 by `jcapsha` on 8HD-d, in
`ghcr.io/vibeic/vibeic-eda:0.3.24` (OpenROAD 26Q3-1607-g27fd905b8a,
librelane 3.1.0.dev1), against the gf180mcuD IO cell library.

## Why this measurement was taken at all

The lane that found the defect measured four SEPARATE OpenROAD processes,
one per `PAD_ROTATION_VERTICAL` value, and concluded the variable was INERT:
neither the orientation nor the extents of the vertical-side pads depended
on it at any value. That measurement is correct and reproduces here.

The same notes carried one line marked "SEPARATE OpenROAD oddity, observed
and NOT chased":

    the SOUTH pad's orientation tracked the -rotation_vertical argument even
    though -rotation_horizontal was held at R0 for every run

Those are not two observations. They are one, and the reason the first reads
as "inert" is that the sweep varied ONE of the two flags. Every run in it
held `-rotation_horizontal` at `R0`, so the flag that actually drives the
vertical rows never moved.

## The 2x2, one process per cell (`hv.tcl`)

Raw output in `HV_MEASURED_raw.txt`. The probe writes its own input, so this
directory tracks no tool output and the reproduction needs nothing but the two
`.tcl` files and the image. Row orientation and the orientation of one pad
placed into each of the four rows:

    ROTH  ROTV | IO_SOUTH  IO_NORTH | IO_WEST  IO_EAST
    -----------+--------------------+------------------
    R0    R0   | R0        MX       | MXR90    R90
    R0    R90  | R90       MYR90    | MXR90    R90
    R90   R0   | R0        MX       | MX       R180
    R90   R90  | R90       MYR90    | MX       R180

Read down the columns:

  * the HORIZONTAL rows (`IO_SOUTH`, `IO_NORTH`) change with `-rotation_vertical`
    and are unmoved by `-rotation_horizontal`;
  * the VERTICAL rows (`IO_WEST`, `IO_EAST`) change with `-rotation_horizontal`
    and are unmoved by `-rotation_vertical`.

Each flag has a real, reproducible effect. Neither is ignored. Each acts on
the axis the other one names.

## The positive control, at a SECOND flag pair (`axis.tcl`)

If the crossing were an artefact of how this probe reads orientation, a
different flag pair would not show it. `make_io_sites` takes
`-horizontal_site` / `-vertical_site` as well, so the same question can be
asked with two DISTINCT sites and no orientation reasoning at all — the row
report simply names which site landed in which row:

    IO_NORTH  site=SITE_FED_TO_VERTICAL_FLAG
    IO_SOUTH  site=SITE_FED_TO_VERTICAL_FLAG
    IO_EAST   site=SITE_FED_TO_HORIZONTAL_FLAG
    IO_WEST   site=SITE_FED_TO_HORIZONTAL_FLAG

All four rows, and all four agree. `-horizontal_site` feeds BOTH vertical
rows; `-vertical_site` feeds BOTH horizontal rows. Same crossing, same
direction, a different pair of flags, and established without measuring a
single orientation.

(An earlier reading of this control showed only the first two rows, because
the command that produced it was truncated by a line limit rather than by the
tool. The result was right and its denominator was half of what it looked
like. Re-run in full; `axis_control.txt` is the complete output.)

## What the consumer believes

`librelane/config/flow.py` declares both variables and states their meaning:

    PAD_ROTATION_HORIZONTAL  "Rotation to apply to the horizontal sites to
                              ensure pads are placed correctly."
    PAD_ROTATION_VERTICAL    "Rotation to apply to the vertical sites to
                              ensure pads are placed correctly."

and `librelane/scripts/openroad/common/pad_cfg.tcl:78-80` passes each
straight through to the matching flag. So a PDK author who sets
`PAD_ROTATION_VERTICAL` to place the east and west pads correctly rotates
the north and south rows instead.

The tool's own `help make_io_sites` prints the flag names and no axis
semantics, so nothing in the tool contradicts the consumer's reading.

## What this does and does not establish

ESTABLISHED: the flags act on the opposite axis from the one they name, in
both flag pairs, reproducibly, in separate processes, with each flag varied
independently.

NOT ESTABLISHED: which side of the swap the tool's authors intended. It may
be that `-horizontal_site` is named for the orientation a pad CELL takes
(a pad in a vertical row does lie horizontally) rather than for the axis of
the row. Under that reading the tool is self-consistent and undocumented,
and its principal consumer reads it the other way. This measurement does not
choose between those, and the fix is the same either way: the tool must
either swap the flags or state the convention where a caller reads it.

CONSEQUENCE FOR THE DEFAULT PATH: none. Both variables default to `R0`, and
`R0` on either axis is `R0`. The whole cost of the crossing is paid by the
author who sets one of them deliberately — which is exactly the case the
flow-owner ruling refuses with rc 2.
